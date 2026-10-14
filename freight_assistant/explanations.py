"""Deterministic explanations of measured comparisons, never invented causes."""

from datetime import date, timedelta


def comparison_reason(row, config):
    parts = [f"{row['route']}, week of {row['week_of']}."]
    rate = row.get("cost_per_tonne_km")
    if rate is not None:
        parts.append(f"Cost INR {rate:.2f}/tonne-km.")
    for label, percent_key, baseline_key, count_key, count_label in (
        ("history", "vs_own_history_pct", "history_average", "history_weeks", "prior weeks"),
        ("same-type peers", "vs_similar_routes_pct", "peer_average", "peer_count", "other routes"),
    ):
        percent, baseline = row.get(percent_key), row.get(baseline_key)
        detail = []
        if baseline is not None:
            detail.append(f"INR {baseline:.2f}/tonne-km")
        if row.get(count_key) is not None:
            label_for_count = count_label[:-1] if row[count_key] == 1 else count_label
            detail.append(f"{row[count_key]} {label_for_count}")
        suffix = f" ({'; '.join(detail)})" if detail else ""
        if percent is not None:
            parts.append(f"{percent:+.1f}% vs {label}{suffix}.")
        elif baseline == 0 and rate is not None and rate > 0:
            parts.append(f"Above a zero {label} baseline{suffix}; percentage undefined.")
        else:
            parts.append(f"Comparison with {label} unavailable{suffix}.")
    high = []
    for label, percent_key, baseline_key in (
        ("history", "vs_own_history_pct", "history_average"),
        ("peers", "vs_similar_routes_pct", "peer_average"),
    ):
        value = row.get(percent_key)
        if value is not None and value >= config.anomaly_threshold_pct:
            high.append(label)
        elif row.get(baseline_key) == 0 and rate is not None and rate > 0:
            high.append(f"zero {label} baseline")
    if high:
        parts.append(f"Threshold {config.anomaly_threshold_pct:g}% met against {' and '.join(high)}.")
        previous = row.get("vs_previous_observed_pct")
        if previous is not None:
            parts.append(f"{previous:+.1f}% vs the previous observed week.")
        if not row["anomaly_candidate"]:
            parts.append(f"Not flagged: a rise above {config.minimum_rise_pct:g}% versus history or the previous observed week is not established.")
    elif all(row.get(key) is None for key in ("vs_own_history_pct", "vs_similar_routes_pct")):
        parts.append("Not flagged: insufficient comparison data to establish an unusual rise.")
    else:
        parts.append(f"Not flagged: available comparisons are below the {config.anomaly_threshold_pct:g}% threshold.")
    return " ".join(parts)


def rejected_context(row, checks, notes, annotations, config):
    """Show relevant failures in plain English; retain all raw checks in the audit."""
    week_end = date.fromisoformat(row["week_of"]) + timedelta(days=6)
    relevant = [check for check in checks
                if notes[check["note_id"]].applies_to in {row["route"], "All Routes"}
                and notes[check["note_id"]].published <= week_end
                and annotations.get(check["note_id"], {}).get("effect") == "increase"]
    # Prefer route-specific and recent events, independent of retrieval ordering.
    relevant.sort(key=lambda c: (notes[c["note_id"]].applies_to == "All Routes",
                                 -notes[c["note_id"]].published.toordinal(), c["note_id"]))
    messages = []
    for check in relevant:
        note_id = check["note_id"]
        annotation = annotations[note_id]
        rejection = check.get("rejection")
        if rejection == "outside_event_window":
            text = (f"Note {note_id}'s event window ({annotation['start_date']} to "
                    f"{annotation.get('end_date') or 'ongoing'}) covers none of this week's shipment work.")
        elif rejection == "insufficient_shipment_coverage":
            text = (f"Note {note_id} covers only {check['coverage']:.1%} of shipment tonne-km; "
                    f"at least {config.minimum_evidence_coverage:.0%} is required.")
        elif rejection == "national_event_does_not_explain_peer_premium":
            text = (f"Note {note_id} describes a nationwide increase affecting peers too; "
                    "it does not explain this route's premium over peers.")
        elif rejection == "persistent_event_already_in_history_baseline":
            text = f"Note {note_id}'s ongoing event is already included in every history week; it does not establish a new rise."
        elif rejection == "magnitude_not_supported":
            text = (f"Note {note_id} supports up to {annotation['maximum_increase_pct']:g}% "
                    f"(plus {config.magnitude_tolerance_pct:g} percentage points tolerance); "
                    "the history comparison does not meet this magnitude check.")
        else:
            continue
        messages.append(text)
        if len(messages) == 2:
            break
    return " ".join(messages) or "No available note supports an increase for this route and these shipment dates."
