"""Validate saved dashboard results and fingerprint their actual input files."""

from collections import Counter
from dataclasses import asdict
import hashlib
import json
import math
from pathlib import Path

from .detection import Config
from .reporting import csv_text, file_hash
from .evidence import load_annotations
from .validation import load_notes

INPUT_NAMES = ("shipment_records.csv", "context_notes.csv", "sample_output_format_v2.csv", "note_annotations.json")


def analysis_revision(root):
    root = Path(root)
    paths = sorted((root / "freight_assistant").glob("*.py"))
    paths += [root / "data" / name for name in INPUT_NAMES] + [root / "config.json"]
    return tuple((path.relative_to(root).as_posix(), file_hash(path)) for path in paths)


def load_saved(root, revision):
    root = Path(root)
    audit_path, cost_path = root / "results/audit.json", root / "results/token_cost_log.json"
    if not audit_path.exists() or not cost_path.exists():
        return None
    try:
        audit = json.loads(audit_path.read_text(encoding="utf-8"))
        cost = json.loads(cost_path.read_text(encoding="utf-8"))
        if not isinstance(audit, dict) or not isinstance(cost, dict) or audit.get("schema_version") != 1:
            raise ValueError("Unsupported saved analysis format")
        sources = {name.replace("\\", "/"): digest for name, digest in audit["source_sha256"].items()}
        current = dict(revision)
        if any(current.get(name) != digest for name, digest in sources.items()):
            return None
        expected_sources = {name for name in current if name.startswith("freight_assistant/")}
        if set(sources) != expected_sources:
            return None
        if any(audit["input_sha256"].get(name) != current.get("data/" + name) for name in INPUT_NAMES):
            return None
        settings = audit["configuration"]
        if not isinstance(settings, dict) or set(settings) != set(asdict(Config())):
            raise ValueError("Incomplete saved configuration")
        Config(**settings)
        if audit["retriever"]["mode"] not in {"semantic", "lexical"}:
            raise ValueError("Unknown saved retrieval mode")
        rows = audit["rows"]
        required = {"route", "route_type", "week_of", "cost_per_tonne_km", "history_average", "peer_average",
                    "vs_own_history_pct", "vs_similar_routes_pct", "history_weeks", "peer_count", "reason",
                    "matched_note_id", "verdict", "anomaly_candidate"}
        if not isinstance(rows, list) or not rows or any(not isinstance(row, dict) or not required <= row.keys() for row in rows):
            raise ValueError("Incomplete saved route-week rows")
        if hashlib.sha256(csv_text(rows).encode("utf-8")).hexdigest() != audit["output_sha256"]:
            raise ValueError("Saved rows do not match their exported CSV hash")
        summary = audit["summary"]
        if (summary["route_week_count"] != len(rows)
                or summary["route_count"] != len({row["route"] for row in rows})
                or summary["verdict_counts"] != dict(Counter(row["verdict"] for row in rows))):
            raise ValueError("Saved summary does not match the route-week rows")
        if not isinstance(summary["threshold_sensitivity_candidate_counts"], dict) or not isinstance(audit["notes"], list):
            raise ValueError("Incomplete saved diagnostics")
        notes = load_notes(root / "data/context_notes.csv")
        expected_notes = [{"note_id": note.note_id, "date": note.published.isoformat(),
                           "applies_to": note.applies_to, "note": note.text} for note in notes]
        if (audit["notes"] != expected_notes
                or audit["annotations"] != load_annotations(root / "data/note_annotations.json", notes)):
            raise ValueError("Saved evidence does not match the reviewed source notes")
        if type(summary["shipment_count"]) is not int:
            raise ValueError("Invalid saved shipment count")
        for key in ("rough_api_cost_usd", "total_input_tokens", "runtime_seconds"):
            if type(cost[key]) not in (int, float) or not math.isfinite(cost[key]) or cost[key] < 0:
                raise ValueError("Invalid saved runtime/cost log")
        return {"rows": rows, "audit": audit, "cost": cost, "revision": revision}
    except (KeyError, TypeError, AttributeError, OverflowError) as exc:
        raise ValueError("Saved analysis is incomplete; regenerate it with Run analysis") from exc
