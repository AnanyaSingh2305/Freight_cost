"""Explicit, configurable anomaly policy; no thresholds inferred from sample output."""

from dataclasses import asdict, dataclass
import math


@dataclass(frozen=True)
class Config:
    anomaly_threshold_pct: float = 15.0
    minimum_rise_pct: float = 0.0
    minimum_evidence_coverage: float = 0.75
    magnitude_tolerance_pct: float = 2.0

    def __post_init__(self):
        values = asdict(self)
        if not all(isinstance(v, (int, float)) and math.isfinite(v) for v in values.values()):
            raise ValueError("Configuration values must be finite numbers")
        if self.anomaly_threshold_pct <= 0 or self.minimum_rise_pct < 0:
            raise ValueError("Anomaly threshold must be positive; minimum rise nonnegative")
        if not 0 < self.minimum_evidence_coverage <= 1 or self.magnitude_tolerance_pct < 0:
            raise ValueError("Invalid evidence coverage or magnitude tolerance")


def is_candidate(row, config):
    own, peer, previous = (row[k] for k in
                          ("vs_own_history_pct", "vs_similar_routes_pct", "vs_previous_observed_pct"))
    high = any(v is not None and v >= config.anomaly_threshold_pct for v in (own, peer))
    rising = any(v is not None and v > config.minimum_rise_pct + 1e-9 for v in (own, previous))
    # An increase from zero is real even though its percentage is undefined.
    if row.get("cost_per_tonne_km", 0) > 0:
        zero_history = row.get("history_average") == 0
        high = high or zero_history or row.get("peer_average") == 0
        rising = rising or zero_history or row.get("previous_observed_rate") == 0
    return high and rising
