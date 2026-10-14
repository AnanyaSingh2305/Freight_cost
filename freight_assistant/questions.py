"""Limited, deterministic question answering over computed results.

Supports route names, month names and optional four-digit years. It does not
claim arbitrary conversational understanding.
"""

import calendar
from datetime import date, timedelta
import re


def normalize(value):
    return " ".join(re.findall(r"[a-z0-9]+", value.lower()))


def answer_question(question, rows):
    text = normalize(question)
    routes = sorted({row["route"] for row in rows})
    matches = [route for route in routes if normalize(route) in text]
    if len(matches) != 1:
        return "Include exactly one route, for example: Why did Chennai-Bangalore get pricier in March 2025?"
    route = matches[0]
    months = [i for i in range(1, 13) if calendar.month_name[i].lower() in text.split()
              or calendar.month_abbr[i].lower() in text.split()]
    years = [int(value) for value in re.findall(r"\b(?:19|20)\d{2}\b", question)]
    if len(set(months)) > 1 or len(set(years)) > 1:
        return "Use one month and one optional year per question."
    selected = []
    for row in rows:
        if row["route"] != route:
            continue
        week = date.fromisoformat(row["week_of"])
        days = [week + timedelta(days=i) for i in range(7)]
        if any((not months or day.month == months[0]) and (not years or day.year == years[0]) for day in days):
            selected.append(row)
    if not selected:
        return f"No computed route-weeks match {route} and the requested period."
    anomalies = [row for row in selected if row["anomaly_candidate"]]
    scope = f"{route}: {len(selected)} matching route-weeks ({selected[0]['week_of']} through {selected[-1]['week_of']})."
    if months and not years:
        scope += " No year supplied; includes all available years."
    if not anomalies:
        return scope + " No unusual rising cost was detected under the configured threshold."
    lines = [scope, f"Found {len(anomalies)} unusual route-weeks:"]
    for row in anomalies:
        own = row["vs_own_history_pct"]
        change = "history unavailable" if own is None else f"{own:+.1f}% versus history"
        lines.append(f"- Week {row['week_of']}: INR {row['cost_per_tonne_km']:.2f}/tonne-km, {change}. {row['reason']}")
    return "\n\n".join(lines)
