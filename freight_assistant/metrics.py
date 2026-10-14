"""Calendar-week metrics with no current-week or future-week leakage."""

from collections import defaultdict
from datetime import date, timedelta
from math import fsum, isfinite


def monday(day):
    return day - timedelta(days=day.weekday())


def percent_change(current, baseline):
    # A percentage against a zero baseline is mathematically undefined.
    return None if baseline is None or baseline <= 0 else 100.0 * (current / baseline - 1.0)


def weekly_metrics(shipments):
    groups = defaultdict(list)
    for shipment in shipments:
        groups[(shipment.origin, shipment.destination, shipment.route_type,
                monday(shipment.shipment_date))].append(shipment)
    rows = []
    for (origin, destination, route_type, week), members in sorted(groups.items()):
        total_work = fsum(s.tonne_km for s in members)
        total_cost = fsum(s.cost for s in members)
        rate = total_cost / total_work
        if not all(isfinite(v) for v in (total_work, total_cost, rate)):
            raise ValueError("Nonfinite aggregate; input magnitudes are too large")
        rows.append({
            "route": f"{origin}-{destination}", "origin": origin, "destination": destination,
            "route_type": route_type, "week_of": week.isoformat(),
            "cost_per_tonne_km": rate, "freight_cost_inr": total_cost,
            "tonne_km": total_work, "shipment_count": len(members),
            "shipment_work_by_date": {
                day.isoformat(): fsum(s.tonne_km for s in members if s.shipment_date == day)
                for day in sorted({s.shipment_date for s in members})
            },
        })
    by_route, peers = defaultdict(list), defaultdict(list)
    for row in rows:
        by_route[(row["origin"], row["destination"], row["route_type"])].append(row)
        peers[(row["route_type"], row["week_of"])].append(row)
    for route_rows in by_route.values():
        route_rows.sort(key=lambda r: r["week_of"])
        for i, row in enumerate(route_rows):
            week = date.fromisoformat(row["week_of"])
            cutoff = (week - timedelta(weeks=8)).isoformat()
            prior = [r["cost_per_tonne_km"] for r in route_rows[:i]
                     if cutoff <= r["week_of"] < row["week_of"]]
            own = fsum(prior) / len(prior) if prior else None
            others = [r["cost_per_tonne_km"] for r in peers[(row["route_type"], row["week_of"])]
                      if (r["origin"], r["destination"]) != (row["origin"], row["destination"])]
            peer = fsum(others) / len(others) if others else None
            previous = route_rows[i - 1]["cost_per_tonne_km"] if i else None
            row.update(history_average=own, history_weeks=len(prior), peer_average=peer,
                       history_week_dates=[r["week_of"] for r in route_rows[:i]
                                           if cutoff <= r["week_of"] < row["week_of"]],
                       peer_count=len(others), previous_observed_rate=previous,
                       vs_own_history_pct=percent_change(row["cost_per_tonne_km"], own),
                       vs_similar_routes_pct=percent_change(row["cost_per_tonne_km"], peer),
                       vs_previous_observed_pct=percent_change(row["cost_per_tonne_km"], previous))
    return sorted(rows, key=lambda r: (r["route"], r["week_of"]))
