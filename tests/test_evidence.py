import json
import tempfile
import unittest
from dataclasses import replace
from datetime import date
from pathlib import Path

from freight_assistant.detection import Config
from freight_assistant.evidence import assess_note, load_annotations, verdict
from freight_assistant.pipeline import ROOT
from freight_assistant.retrieval import NoteRetriever, query_for
from freight_assistant.validation import load_notes


def example(route="Chennai-Bangalore", week="2025-02-24", own=25, work=None):
    return {"route": route, "week_of": week, "vs_own_history_pct": own,
            "tonne_km": sum((work or {week: 100}).values()),
            "shipment_work_by_date": work or {week: 100}, "anomaly_candidate": True}


class EvidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.notes = load_notes(ROOT / "data/context_notes.csv")
        cls.by_id = {n.note_id: n for n in cls.notes}
        cls.annotations = load_annotations(ROOT / "data/note_annotations.json", cls.notes)
        cls.config = Config()

    def check_note(self, row, note_id):
        return assess_note(row, self.by_id[note_id], self.annotations[note_id], self.config)

    def test_flood_valid_window(self):
        self.assertTrue(self.check_note(example(), "N001")["eligible"])

    def test_wrong_route_rejected(self):
        self.assertEqual(self.check_note(example(route="Delhi-Jaipur"), "N001")["rejection"], "wrong_route")

    def test_flood_expired(self):
        self.assertFalse(self.check_note(example(week="2025-03-10"), "N001")["eligible"])

    def test_future_flood_rejected(self):
        self.assertFalse(self.check_note(example(week="2025-02-17"), "N001")["eligible"])

    def test_recovery_is_not_cost_increase(self):
        self.assertEqual(self.check_note(example(week="2025-03-17"), "N009")["rejection"],
                         "does_not_support_increased_cost")

    def test_all_routes_distractor_rejected(self):
        self.assertFalse(self.check_note(example(week="2024-03-11"), "N004")["eligible"])

    def test_fuel_cannot_explain_large_rise(self):
        self.assertEqual(self.check_note(example(week="2025-05-05", own=35), "N003")["rejection"],
                         "magnitude_not_supported")
        self.assertTrue(self.check_note(example(week="2025-05-05", own=6), "N003")["eligible"])

    def test_partial_week_uses_shipment_work(self):
        row = example(week="2025-03-03", work={"2025-03-08": 10, "2025-03-09": 90})
        result = self.check_note(row, "N001")
        self.assertEqual(result["coverage"], 0.1)
        self.assertFalse(result["eligible"])
        row = example(week="2025-03-03", work={"2025-03-08": 90, "2025-03-09": 10})
        self.assertTrue(self.check_note(row, "N001")["eligible"])

    def test_national_event_does_not_excuse_peer_premium(self):
        row = example(week="2025-05-05", own=6)
        row["vs_similar_routes_pct"] = 25
        self.assertEqual(self.check_note(row, "N003")["rejection"],
                         "national_event_does_not_explain_peer_premium")

    def test_persistent_event_already_in_history(self):
        row = example(week="2025-10-06", own=6)
        row["history_week_dates"] = ["2025-08-11", "2025-08-18"]
        self.assertEqual(self.check_note(row, "N003")["rejection"],
                         "persistent_event_already_in_history_baseline")

    def test_unknown_annotation_fails_closed(self):
        self.assertFalse(assess_note(example(), self.by_id["N001"], None, self.config)["eligible"])

    def test_mutated_source_requires_review(self):
        changed = [replace(note, text="Different source text") if note.note_id == "N001" else note
                   for note in self.notes]
        with self.assertRaisesRegex(ValueError, "Source note changed"):
            load_annotations(ROOT / "data/note_annotations.json", changed)

    def test_fabricated_quote_rejected(self):
        payload = json.loads((ROOT / "data/note_annotations.json").read_text())
        payload["annotations"][0]["evidence_quote"] = "The price doubled"
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "annotations.json"
            path.write_text(json.dumps(payload))
            with self.assertRaisesRegex(ValueError, "not an exact source span"):
                load_annotations(path, self.notes)

    def test_final_verdict_has_grounded_id(self):
        row = example()
        ranks = NoteRetriever(self.notes, "lexical").rank_many([query_for(row)])[0]
        result = verdict(row, ranks, self.by_id, self.annotations, self.config)
        self.assertEqual(result["matched_note_id"], "N001")
        self.assertIn(self.annotations["N001"]["evidence_quote"], result["reason"])

    def test_unexplained_id_is_blank(self):
        row = example(route="Delhi-Jaipur")
        ranks = NoteRetriever(self.notes, "lexical").rank_many([query_for(row)])[0]
        result = verdict(row, ranks, self.by_id, self.annotations, self.config)
        self.assertEqual(result["flagged"], "Yes")
        self.assertEqual(result["matched_note_id"], "")


if __name__ == "__main__":
    unittest.main()
