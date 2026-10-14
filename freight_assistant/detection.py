"""Explicit, configurable anomaly policy; no thresholds inferred from sample output."""

from dataclasses import asdict, dataclass
import math
import json
from pathlib import Path


@dataclass(frozen=True)
class Config:
    anomaly_threshold_pct: float = 15.0
    minimum_rise_pct: float = 0.0
    minimum_evidence_coverage: float = 0.75
    magnitude_tolerance_pct: float = 2.0

    def __post_init__(self):
        values = asdict(self)
        try:
            finite = all(type(v) in (int, float) and math.isfinite(v) for v in values.values())
        except OverflowError:
            finite = False
        if not finite:
            raise ValueError("Configuration values must be finite numbers")
        if self.anomaly_threshold_pct <= 0 or self.minimum_rise_pct < 0:
            raise ValueError("Anomaly threshold must be positive; minimum rise nonnegative")
        if not 0 < self.minimum_evidence_coverage <= 1 or self.magnitude_tolerance_pct < 0:
            raise ValueError("Invalid evidence coverage or magnitude tolerance")


def load_config(path):
    document = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise ValueError("Configuration must be a JSON object")
    unknown = set(document) - set(asdict(Config()))
    if unknown:
        raise ValueError("Unknown configuration fields: " + ", ".join(sorted(unknown)))
    return Config(**document)


def meets_threshold(value, threshold):
    # Decimal rates can land just below the boundary in binary floating point.
    return value is not None and value + 1e-9 >= threshold


def is_candidate(row, config):
    own, peer, previous = (row[k] for k in
                          ("vs_own_history_pct", "vs_similar_routes_pct", "vs_previous_observed_pct"))
    high = any(meets_threshold(v, config.anomaly_threshold_pct) for v in (own, peer))
    rising = any(v is not None and v > config.minimum_rise_pct + 1e-9 for v in (own, previous))
    # An increase from zero is real even though its percentage is undefined.
    if row.get("cost_per_tonne_km", 0) > 0:
        zero_history = row.get("history_average") == 0
        high = high or zero_history or row.get("peer_average") == 0
        rising = rising or zero_history or row.get("previous_observed_rate") == 0
    return high and rising
