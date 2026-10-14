"""Small labeled evidence evaluation, deliberately separate from anomaly accuracy."""

import argparse
import io
import json
from pathlib import Path
import unittest

from .detection import Config
from .evidence import load_annotations, verdict
from .pipeline import ROOT
from .reporting import write_json
from .retrieval import NoteRetriever, query_for
from .validation import load_notes


def evaluate(mode="semantic", offline=False):
    notes = load_notes(ROOT / "data/context_notes.csv")
    annotations = load_annotations(ROOT / "data/note_annotations.json", notes)
    cases = json.loads((ROOT / "evaluation/cases.json").read_text())
    rows = []
    for case in cases:
        work = case.get("work", {case["week"]: 100})
        rows.append({"route": case["route"], "week_of": case["week"],
                     "vs_own_history_pct": case["own"], "vs_similar_routes_pct": case.get("peer"),
                     "history_week_dates": case.get("history", []), "tonne_km": sum(work.values()),
                     "shipment_work_by_date": work, "anomaly_candidate": True})
    retriever = NoteRetriever(notes, mode, ROOT / ".cache/models", offline)
    rankings = retriever.rank_many([query_for(row) for row in rows])
    outputs, true_positive, false_positive, false_negative, hits = [], 0, 0, 0, 0
    for case, row, ranking in zip(cases, rows, rankings):
        result = verdict(row, ranking, {n.note_id: n for n in notes}, annotations, Config())
        expected, actual = case["expected_note"], result["matched_note_id"] or None
        true_positive += bool(actual and actual == expected)
        false_positive += bool(actual and actual != expected)
        false_negative += bool(expected and actual != expected)
        top3 = [hit["note_id"] for hit in ranking[:3]]
        hits += bool(expected and expected in top3)
        outputs.append({"case": case["name"], "expected_note": expected, "actual_note": actual,
                        "passed": expected == actual, "retrieval_top_3": top3})
    positives = sum(bool(case["expected_note"]) for case in cases)
    log = io.StringIO()
    suite = unittest.TestLoader().discover(str(ROOT / "tests"))
    test_result = unittest.TextTestRunner(stream=log, verbosity=2).run(suite)
    report = {
        "scope": "20 manually reviewed evidence-suitability cases plus independent numerical/contract tests; not a hidden-test anomaly accuracy estimate",
        "retriever": mode, "case_count": len(cases), "positive_cases": positives,
        "case_accuracy": sum(item["passed"] for item in outputs) / len(cases),
        "justified_precision": true_positive / (true_positive + false_positive) if true_positive + false_positive else None,
        "supported_evidence_recall": true_positive / positives,
        "retrieval_recall_at_3_before_guards": hits / positives,
        "unsupported_justifications": false_positive, "missed_supported_cases": false_negative,
        "unit_tests_run": test_result.testsRun, "unit_tests_passed": test_result.wasSuccessful(),
        "all_labeled_cases_passed": all(item["passed"] for item in outputs),
        "cases": outputs, "unit_test_log": log.getvalue(),
        "limitations": "Small development-time cases informed the guards; not an independent held-out dataset. Recall@3 is descriptive: all notes are checked after retrieval in this small corpus.",
    }
    return report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--retriever", choices=["semantic", "lexical"], default="semantic")
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("--output", type=Path, default=ROOT / "results/evaluation.json")
    args = parser.parse_args()
    report = evaluate(args.retriever, args.offline)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    write_json(args.output, report)
    print(json.dumps({k: v for k, v in report.items() if k not in {"cases", "unit_test_log"}}, indent=2))
    return 0 if report["unit_tests_passed"] and report["all_labeled_cases_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
