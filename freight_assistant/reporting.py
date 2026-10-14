import csv
import hashlib
import io
import json
from pathlib import Path

from .validation import OUTPUT_COLUMNS


def file_hash(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_json(path, value):
    Path(path).write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n",
                          encoding="utf-8")


def comparison(value, suffix):
    return f"{value:+.1f}% {suffix}" if value is not None else f"N/A ({suffix}; baseline unavailable)"


def csv_text(rows):
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=OUTPUT_COLUMNS, lineterminator="\n")
    writer.writeheader()
    for row in rows:
        writer.writerow({
            "route": row["route"], "week_of": row["week_of"],
            "cost_per_tonne_km": f"{row['cost_per_tonne_km']:.2f}",
            "vs_own_history": comparison(row["vs_own_history_pct"], "vs this route's past average"),
            "vs_similar_routes": comparison(row["vs_similar_routes_pct"], "vs similar-length routes this week"),
            "flagged": row["flagged"], "matched_note_id": row["matched_note_id"], "reason": row["reason"],
        })
    return stream.getvalue()
