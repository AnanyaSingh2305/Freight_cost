"""Fail-closed evidence rules over transparent, reviewed note annotations.

Annotations describe source text, not route-week verdicts. Unreviewed or changed
notes can be retrieved but cannot justify an increase.
"""

import hashlib
import json
from datetime import date, timedelta
from math import fsum
from pathlib import Path

from .explanations import comparison_reason, rejected_context
from .detection import meets_threshold


def note_fingerprint(note):
    payload = [note.note_id, note.published.isoformat(), note.applies_to, note.text]
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False).encode()).hexdigest()


def load_annotations(path, notes):
    document = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(document, dict) or document.get("schema_version") != 1:
        raise ValueError("Unsupported note annotation schema")
    if not isinstance(document.get("annotations"), list):
        raise ValueError("Note annotations must contain an annotations list")
    known = {note.note_id: note for note in notes}
    annotations = {}
    for item in document["annotations"]:
        required = {"note_id", "source_sha256", "evidence_quote", "effect", "summary", "interpretation"}
        if not isinstance(item, dict) or not required.issubset(item):
            raise ValueError("Each note annotation needs note_id, source_sha256, evidence_quote, effect, summary and interpretation")
        if any(not isinstance(item[key], str) or not item[key].strip() for key in required):
            raise ValueError("Required annotation fields must be nonempty strings")
        if any(item.get(key) is not None and not isinstance(item[key], str)
               for key in ("start_date", "end_date")):
            raise ValueError("Annotation dates must be ISO date strings or null")
        note_id = item["note_id"]
        if note_id in annotations:
            raise ValueError(f"Duplicate annotation: {note_id}")
        if note_id not in known:
            raise ValueError(f"Annotation refers to missing note: {note_id}")
        note = known[note_id]
        if item["source_sha256"] != note_fingerprint(note):
            raise ValueError(f"Source note changed: {note_id}; review its annotation before running")
        if not item["evidence_quote"] or item["evidence_quote"] not in note.text:
            raise ValueError(f"Evidence quote is not an exact source span: {note_id}")
        if item["effect"] not in {"increase", "no_increase"}:
            raise ValueError(f"Unsupported effect: {note_id}")
        start = date.fromisoformat(item["start_date"]) if item.get("start_date") else None
        end = date.fromisoformat(item["end_date"]) if item.get("end_date") else None
        if end and (not start or end < start):
            raise ValueError(f"Invalid evidence window: {note_id}")
        if item["effect"] == "increase" and not start:
            raise ValueError(f"Increase annotation needs a start date: {note_id}")
        maximum = item.get("maximum_increase_pct")
        if maximum is not None and (type(maximum) not in (float, int) or not 0 <= maximum <= 1000):
            raise ValueError(f"Invalid magnitude annotation: {note_id}")
        annotations[note_id] = item
    return annotations


def assess_note(row, note, annotation, config):
    if annotation is None:
        return {"eligible": False, "rejection": "unreviewed_note"}
    if note.applies_to not in {"All Routes", row["route"]}:
        return {"eligible": False, "rejection": "wrong_route"}
    if annotation["effect"] != "increase":
        return {"eligible": False, "rejection": "does_not_support_increased_cost"}
    week = date.fromisoformat(row["week_of"])
    week_end = week + timedelta(days=6)
    if note.published > week_end:
        return {"eligible": False, "rejection": "note_not_yet_published"}
    start = date.fromisoformat(annotation["start_date"])
    end = date.fromisoformat(annotation["end_date"]) if annotation.get("end_date") else None
    affected = fsum(work for day, work in row["shipment_work_by_date"].items()
                    if date.fromisoformat(day) >= max(start, note.published)
                    and (end is None or date.fromisoformat(day) <= end))
    coverage = affected / row["tonne_km"]
    result = {"eligible": False, "coverage": coverage, "rejection": None}
    if coverage == 0:
        result["rejection"] = "outside_event_window"
    elif coverage + 1e-12 < config.minimum_evidence_coverage:
        result["rejection"] = "insufficient_shipment_coverage"
    else:
        # Quantified evidence must cover the observed history-relative uplift.
        # An old persistent event no longer excuses a new, larger jump.
        own = row["vs_own_history_pct"]
        peer = row.get("vs_similar_routes_pct")
        maximum = annotation.get("maximum_increase_pct")
        history_dates = row.get("history_week_dates", [])
        # A nationwide event does not explain a route-specific peer premium,
        # because the same event also applies to its peers.
        if (note.applies_to == "All Routes" and peer is not None
                and meets_threshold(peer, config.anomaly_threshold_pct)):
            result["rejection"] = "national_event_does_not_explain_peer_premium"
        elif (end is None and history_dates
              and all(date.fromisoformat(day) >= start for day in history_dates)):
            result["rejection"] = "persistent_event_already_in_history_baseline"
        elif maximum is not None and (own is None or own <= 0 or
                                     own > maximum + config.magnitude_tolerance_pct):
            result["rejection"] = "magnitude_not_supported"
        else:
            result["eligible"] = True
    return result


def verdict(row, ranked_notes, notes, annotations, config):
    comparison = comparison_reason(row, config)
    if not row["anomaly_candidate"]:
        return {"flagged": "No", "matched_note_id": "", "verdict": "normal",
                "reason": comparison,
                "evidence_checks": []}
    checks = []
    for hit in ranked_notes:
        note_id = hit["note_id"]
        check = assess_note(row, notes[note_id], annotations.get(note_id), config)
        checks.append({**hit, **check})
    eligible = [check for check in checks if check["eligible"]]
    if eligible:
        # Route-specific evidence takes precedence over a national contributor.
        eligible.sort(key=lambda check: (notes[check["note_id"]].applies_to == "All Routes",
                                         -check["score"], check["note_id"]))
        match = eligible[0]
        note_id = match["note_id"]
        note, annotation = notes[note_id], annotations[note_id]
        window = f"{annotation['start_date']} to {annotation.get('end_date') or 'ongoing (no end specified)'}"
        reason = (comparison + f" Justified by applicable context: note {note_id} dated {note.published.isoformat()} "
                  f"describes {annotation['summary']} on {note.applies_to}; event window {window}. "
                  f"Exact evidence: \"{annotation['evidence_quote']}\" "
                  f"Applies to {match['coverage']:.1%} of this week's shipment tonne-km. "
                  "This is a supported contextual explanation, not proof of the precise causal amount.")
        return {"flagged": "No (justified)", "matched_note_id": note_id, "verdict": "justified",
                "reason": reason, "evidence_checks": checks}
    return {"flagged": "Yes", "matched_note_id": "", "verdict": "unexplained",
            "reason": (comparison + " Unexplained rise; flagged for human review. "
                       + rejected_context(row, checks, notes, annotations, config)),
            "evidence_checks": checks}
