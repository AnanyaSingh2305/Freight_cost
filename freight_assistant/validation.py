"""Strict CSV ingestion: errors retain the source file and row number."""

import csv
import math
from dataclasses import dataclass
from datetime import date
from pathlib import Path

SHIPMENT_COLUMNS = (
    "shipment_id", "origin", "destination", "route_type", "material",
    "quantity_tonnes", "distance_km", "freight_cost_inr", "shipment_date", "transporter",
)
NOTE_COLUMNS = ("note_id", "date", "applies_to", "note")
OUTPUT_COLUMNS = (
    "route", "week_of", "cost_per_tonne_km", "vs_own_history",
    "vs_similar_routes", "flagged", "matched_note_id", "reason",
)


class ValidationError(ValueError):
    """A supplied input violates the documented contract."""


@dataclass(frozen=True)
class Shipment:
    shipment_id: str
    origin: str
    destination: str
    route_type: str
    quantity: float
    distance: float
    cost: float
    shipment_date: date

    @property
    def route(self):
        return f"{self.origin}-{self.destination}"

    @property
    def tonne_km(self):
        return self.quantity * self.distance


@dataclass(frozen=True)
class Note:
    note_id: str
    published: date
    applies_to: str
    text: str


def parse_date(value):
    parsed = date.fromisoformat(value)
    if parsed.isoformat() != value:
        raise ValueError("expected YYYY-MM-DD")
    return parsed


def read_rows(path, required):
    path = Path(path)
    with path.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        headers = reader.fieldnames or []
        if len(headers) != len(set(headers)) or not set(required).issubset(headers):
            raise ValidationError(f"{path.name}: missing or duplicate columns; required: {required}")
        rows = []
        for line, row in enumerate(reader, start=2):
            if None in row or any(row.get(k) is None or not row[k].strip() for k in required):
                raise ValidationError(f"{path.name}:{line}: blank field or malformed row")
            rows.append({k: v.strip() for k, v in row.items()})
    if not rows:
        raise ValidationError(f"{path.name}: no data rows")
    return rows


def load_shipments(path):
    result, seen, route_types, route_labels = [], set(), {}, {}
    for line, row in enumerate(read_rows(path, SHIPMENT_COLUMNS), start=2):
        try:
            key = (row["origin"], row["destination"])
            route = "-".join(key)
            if row["shipment_id"] in seen:
                raise ValueError("duplicate shipment_id")
            if row["route_type"] not in {"Short", "Medium", "Long"}:
                raise ValueError("route_type must be Short, Medium, or Long")
            if key in route_types and route_types[key] != row["route_type"]:
                raise ValueError("one directed route has conflicting route types")
            if route in route_labels and route_labels[route] != key:
                raise ValueError("ambiguous hyphenated route label")
            q, d, c = (float(row[k]) for k in ("quantity_tonnes", "distance_km", "freight_cost_inr"))
            if not all(math.isfinite(v) for v in (q, d, c)) or q <= 0 or d <= 0 or c < 0:
                raise ValueError("quantity/distance must be positive; cost nonnegative; all must be finite")
            if not math.isfinite(q * d) or q * d == 0:
                raise ValueError("tonne-km overflows or underflows")
            result.append(Shipment(row["shipment_id"], *key, row["route_type"], q, d, c,
                                   parse_date(row["shipment_date"])))
            seen.add(row["shipment_id"])
            route_types[key], route_labels[route] = row["route_type"], key
        except (ValueError, OverflowError) as exc:
            raise ValidationError(f"{Path(path).name}:{line}: {exc}") from exc
    return sorted(result, key=lambda s: (s.route, s.shipment_date, s.shipment_id))


def load_notes(path):
    result, seen = [], set()
    for line, row in enumerate(read_rows(path, NOTE_COLUMNS), start=2):
        try:
            if row["note_id"] in seen:
                raise ValueError("duplicate note_id")
            result.append(Note(row["note_id"], parse_date(row["date"]), row["applies_to"], row["note"]))
            seen.add(row["note_id"])
        except ValueError as exc:
            raise ValidationError(f"{Path(path).name}:{line}: {exc}") from exc
    return sorted(result, key=lambda n: n.note_id)


def validate_output_contract(path):
    with Path(path).open(encoding="utf-8-sig", newline="") as stream:
        if tuple(next(csv.reader(stream), [])) != OUTPUT_COLUMNS:
            raise ValidationError("The supplied sample header does not match the supported output contract")
