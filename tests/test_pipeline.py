import csv
import io
import unittest

from freight_assistant.pipeline import ROOT, analyze
from freight_assistant.questions import answer_question
from freight_assistant.reporting import csv_text
from freight_assistant.validation import OUTPUT_COLUMNS


class PipelineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rows, cls.audit, cls.cost = analyze(mode="lexical")

    def test_full_dataset_coverage(self):
        self.assertEqual(len(self.rows), 728)
        self.assertEqual(sum(row["shipment_count"] for row in self.rows), 2940)

    def test_csv_contract_and_quoting(self):
        text = csv_text(self.rows)
        reader = csv.DictReader(io.StringIO(text))
        self.assertEqual(tuple(reader.fieldnames), OUTPUT_COLUMNS)
        rows = list(reader)
        self.assertEqual(len(rows), 728)
        self.assertTrue(all(None not in row and None not in row.values() for row in rows))

    def test_sample_numeric_examples_and_verdicts(self):
        # Values supplied in the example contract are independent external checks.
        with (ROOT / "data/sample_output_format_v2.csv").open(newline="", encoding="utf-8-sig") as stream:
            examples = list(csv.DictReader(stream))
        export = {(row["route"], row["week_of"]): row for row in csv.DictReader(io.StringIO(csv_text(self.rows)))}
        for example in examples:
            actual = export[example["route"], example["week_of"]]
            for field in ("cost_per_tonne_km", "vs_own_history", "vs_similar_routes", "flagged", "matched_note_id"):
                with self.subTest(route=example["route"], field=field):
                    self.assertEqual(actual[field], example[field])

    def test_justified_rows_are_route_and_date_grounded(self):
        notes = {note["note_id"]: note for note in self.audit["notes"]}
        for row in self.rows:
            if row["verdict"] == "justified":
                note = notes[row["matched_note_id"]]
                annotation = self.audit["annotations"][note["note_id"]]
                self.assertIn(note["applies_to"], ["All Routes", row["route"]])
                self.assertIn(annotation["evidence_quote"], note["note"])
                self.assertIn(annotation["evidence_quote"], row["reason"])
                self.assertEqual(annotation["effect"], "increase")
                affected_days = [day for day in row["shipment_work_by_date"]
                                 if day >= annotation["start_date"]
                                 and (not annotation["end_date"] or day <= annotation["end_date"])]
                self.assertTrue(affected_days)
            else:
                self.assertEqual(row["matched_note_id"], "")

    def test_repeat_same_inputs(self):
        repeated, _, _ = analyze(mode="lexical")
        self.assertEqual(csv_text(self.rows), csv_text(repeated))

    def test_honest_no_generative_usage(self):
        self.assertEqual(self.cost["generative_llm_calls"], 0)
        self.assertEqual(self.cost["rough_api_cost_usd"], 0)
        self.assertEqual(self.audit["retriever"]["mode"], "lexical")
        self.assertLessEqual(self.cost["retrieval_and_evidence_seconds"], self.cost["runtime_seconds"])

    def test_question_is_grounded_and_date_filtered(self):
        answer = answer_question("Why did Chennai-Bangalore get pricier in March 2025?", self.rows)
        self.assertIn("N001", answer)
        self.assertIn("2025-03-10", answer)
        self.assertNotIn("N002", answer)

    def test_unknown_question_requests_supported_scope(self):
        self.assertIn("Include exactly one route", answer_question("Why did costs rise?", self.rows))


if __name__ == "__main__":
    unittest.main()
