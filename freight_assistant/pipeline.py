"""One execution path shared by the CLI, evaluations, and dashboard."""

from collections import Counter
from dataclasses import asdict
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
import platform
from time import perf_counter

from .detection import Config, is_candidate
from .evidence import load_annotations, verdict
from .metrics import weekly_metrics
from .reporting import csv_text, file_hash, write_json
from .retrieval import NoteRetriever, query_for
from .validation import load_notes, load_shipments, validate_output_contract

ROOT = Path(__file__).resolve().parents[1]


def versions():
    result = {"python": platform.python_version(), "platform": platform.platform()}
    for package in ("pandas", "numpy", "streamlit", "onnxruntime", "tokenizers"):
        try:
            result[package] = version(package)
        except PackageNotFoundError:
            result[package] = "not installed"
    return result


def analyze(data_dir=None, config=None, mode="semantic", cache_dir=None, offline=False):
    start = perf_counter()
    data_dir, config = Path(data_dir or ROOT / "data"), config or Config()
    cache_dir = Path(cache_dir or ROOT / ".cache" / "models")
    input_files = [data_dir / name for name in (
        "shipment_records.csv", "context_notes.csv", "sample_output_format_v2.csv", "note_annotations.json")]
    validate_output_contract(input_files[2])
    shipments, notes = load_shipments(input_files[0]), load_notes(input_files[1])
    annotations = load_annotations(input_files[3], notes)
    rows = weekly_metrics(shipments)
    for row in rows:
        row["anomaly_candidate"] = is_candidate(row, config)
    candidates = [row for row in rows if row["anomaly_candidate"]]
    retrieval_start = perf_counter()
    retriever = NoteRetriever(notes, mode=mode, cache_dir=cache_dir, offline=offline)
    rankings = iter(retriever.rank_many([query_for(row) for row in candidates]))
    note_map = {note.note_id: note for note in notes}
    for row in rows:
        row.update(verdict(row, next(rankings) if row["anomaly_candidate"] else [],
                           note_map, annotations, config))
    retrieval_seconds = perf_counter() - retrieval_start
    summary = {
        "shipment_count": len(shipments), "route_count": len({s.route for s in shipments}),
        "route_week_count": len(rows), "anomaly_candidates": len(candidates),
        "verdict_counts": dict(sorted(Counter(row["verdict"] for row in rows).items())),
        "threshold_sensitivity_candidate_counts": {
            str(threshold): sum(is_candidate(row, Config(**{**asdict(config), "anomaly_threshold_pct": threshold}))
                                for row in rows) for threshold in (10.0, 15.0, 20.0)
        },
    }
    audit = {
        "schema_version": 1, "configuration": asdict(config),
        "input_sha256": {path.name: file_hash(path) for path in input_files},
        "source_sha256": {str(path.relative_to(ROOT)): file_hash(path)
                          for path in sorted((ROOT / "freight_assistant").glob("*.py"))},
        "environment": versions(), "summary": summary,
        "retriever": {key: value for key, value in retriever.stats.items()
                      if key not in {"embedding_input_tokens", "embedding_inference_batches",
                                     "document_embedding_cache_hit"}},
        "notes": [{"note_id": n.note_id, "date": n.published.isoformat(),
                   "applies_to": n.applies_to, "note": n.text} for n in notes],
        "annotations": annotations, "rows": rows,
    }
    elapsed = perf_counter() - start
    cost = {
        "scope": "one full shipment-file analysis; dependency/model download excluded",
        "model": retriever.stats["embedding_model"], "retrieval": retriever.stats,
        "generative_llm_calls": 0, "generative_input_tokens": 0, "generative_output_tokens": 0,
        "total_input_tokens": retriever.stats["embedding_input_tokens"], "total_output_tokens": 0,
        "token_count_definition": "Total input includes actual local encoder tokens. The encoder outputs vectors, not text tokens. Generative input/output are separately zero.",
        "rough_api_cost_usd": 0.0,
        "pricing_basis": "Local open-source encoder and deterministic templates; no billed generative API used.",
        "runtime_seconds": round(elapsed, 4),
        "retrieval_and_evidence_seconds": round(retrieval_seconds, 4),
        "local_compute_note": "CPU time, memory, electricity and initial model download are not zero-cost resources.",
        "randomness": "FP32 CPU inference, sequential ONNX execution, one thread; no sampling, dropout or generation.",
    }
    return rows, audit, cost


def save_analysis(out_dir, rows, audit, cost):
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    output = out_dir / "analysis_output.csv"
    output.write_text(csv_text(rows), encoding="utf-8", newline="")
    audit["output_sha256"] = file_hash(output)
    write_json(out_dir / "audit.json", audit)
    write_json(out_dir / "summary.json", audit["summary"])
    write_json(out_dir / "token_cost_log.json", cost)
    return output
