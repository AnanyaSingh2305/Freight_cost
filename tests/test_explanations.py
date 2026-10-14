"""Check that explanations distinguish observed patterns without inventing causes."""

from dataclasses import replace
import unittest

from freight_assistant.detection import Config, is_candidate
from freight_assistant.evidence import load_annotations, verdict
from freight_assistant.explanations import comparison_reason
from freight_assistant.pipeline import ROOT
from freight_assistant.validation import load_notes


class ExplanationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.notes = {n.note_id: n for n in load_notes(ROOT / "data/context_notes.csv")}
        cls.annotations = load_annotations(ROOT / "data/note_annotations.json", cls.notes.values())

    def row(self, **changes):
        row = {"route": "Mumbai-Pune", "week_of": "2025-09-15",
               "cost_per_tonne_km": 4.0, "history_average": 3.8, "history_weeks": 8,
               "peer_average": 3.2, "peer_count": 2, "previous_observed_rate": 3.9,
               "vs_own_history_pct": 5.26315789, "vs_similar_routes_pct": 25.0,
               "vs_previous_observed_pct": 2.56410256, "tonne_km": 100,
               "shipment_work_by_date": {"2025-09-15": 100}}
        row.update(changes)
        row["anomaly_candidate"] = is_candidate(row, Config())
        return row

    def test_peer_only_rise_names_correct_trigger_and_actual_values(self):
        reason = comparison_reason(self.row(), Config())
        self.assertIn("INR 4.00/tonne-km", reason)
        self.assertIn("+5.3% vs history (INR 3.80/tonne-km; 8 prior weeks)", reason)
        self.assertIn("+25.0% vs same-type peers", reason)
        self.assertIn("met against peers.", reason)
        self.assertNotIn("met against history", reason)

    def test_elevated_but_falling_is_not_called_below_threshold(self):
        row = self.row(vs_own_history_pct=-3, vs_previous_observed_pct=-2)
        reason = comparison_reason(row, Config())
        self.assertFalse(row["anomaly_candidate"])
        self.assertIn("a rise above 0%", reason)
        self.assertNotIn("below the 15% threshold", reason)

    def test_initial_week_does_not_invent_history(self):
        row = self.row(history_average=None, history_weeks=0, vs_own_history_pct=None,
                       previous_observed_rate=None, vs_previous_observed_pct=None)
        reason = comparison_reason(row, Config())
        self.assertIn("Comparison with history unavailable", reason)
        self.assertIn("a rise above 0%", reason)

    def test_live_threshold_is_used(self):
        row = self.row(vs_own_history_pct=8, vs_similar_routes_pct=10)
        config = replace(Config(), anomaly_threshold_pct=7)
        row["anomaly_candidate"] = is_candidate(row, config)
        reason = comparison_reason(row, config)
        self.assertIn("Threshold 7% met against history and peers.", reason)

    def test_zero_baseline_not_reported_as_missing(self):
        row = self.row(history_average=0, vs_own_history_pct=None)
        reason = comparison_reason(row, Config())
        self.assertIn("Above a zero history baseline", reason)
        self.assertNotIn("Comparison with history unavailable", reason)

    def test_expired_event_explains_rejection_without_assigning_cause(self):
        row = self.row(route="Chennai-Bangalore", week_of="2025-03-10",
                       shipment_work_by_date={"2025-03-10": 100}, vs_own_history_pct=22)
        ranks = [{"note_id": key, "score": 0.5} for key in self.notes]
        result = verdict(row, ranks, self.notes, self.annotations, Config())
        self.assertEqual(result["flagged"], "Yes")
        self.assertEqual(result["matched_note_id"], "")
        self.assertIn("2025-02-24 to 2025-03-08", result["reason"])
        self.assertIn("covers none", result["reason"])
        self.assertNotIn("Justified", result["reason"])
        self.assertNotIn("N003", result["reason"])  # Future fuel event is not evidence for March.

    def test_national_note_cannot_become_a_route_specific_cause(self):
        ranks = [{"note_id": key, "score": 0.5} for key in self.notes]
        result = verdict(self.row(), ranks, self.notes, self.annotations, Config())
        self.assertIn("N003 describes a nationwide increase affecting peers too", result["reason"])
        self.assertIn("Unexplained rise", result["reason"])
        self.assertEqual(result["matched_note_id"], "")


if __name__ == "__main__":
    unittest.main()
