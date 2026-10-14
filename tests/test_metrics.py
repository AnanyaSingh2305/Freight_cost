import csv
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

from freight_assistant.detection import Config, is_candidate
from freight_assistant.metrics import monday, weekly_metrics
from freight_assistant.validation import SHIPMENT_COLUMNS, Shipment, ValidationError, load_shipments


def shipment(i, day, rate, origin="A", destination="B", kind="Short", quantity=1, distance=1):
    return Shipment(str(i), origin, destination, kind, quantity, distance,
                    rate * quantity * distance, day)


class MetricsTests(unittest.TestCase):
    def test_monday_and_sunday_share_week(self):
        self.assertEqual(monday(date(2025, 1, 5)), date(2024, 12, 30))
        self.assertEqual(monday(date(2025, 1, 6)), date(2025, 1, 6))

    def test_weighted_weekly_rate(self):
        rows = weekly_metrics([shipment(1, date(2025, 1, 6), 2, quantity=10, distance=10),
                               shipment(2, date(2025, 1, 12), 4, quantity=20, distance=20)])
        self.assertEqual(len(rows), 1)
        self.assertAlmostEqual(rows[0]["cost_per_tonne_km"], 1800 / 500)

    def test_trailing_eight_weeks_and_current_exclusion(self):
        start = date(2025, 1, 6)
        rows = weekly_metrics([shipment(i, start + timedelta(weeks=i), i + 1) for i in range(10)])
        self.assertEqual(rows[0]["history_weeks"], 0)
        self.assertIsNone(rows[0]["history_average"])
        self.assertEqual(rows[2]["history_average"], 1.5)
        self.assertEqual(rows[-1]["history_weeks"], 8)
        self.assertEqual(rows[-1]["history_average"], 5.5)  # rates 2 through 9

    def test_calendar_gap_does_not_pull_older_week(self):
        rows = weekly_metrics([shipment(1, date(2025, 1, 6), 100),
                               shipment(2, date(2025, 3, 10), 2),
                               shipment(3, date(2025, 3, 17), 4)])
        self.assertEqual(rows[-1]["history_average"], 2)
        self.assertEqual(rows[-1]["history_weeks"], 1)

    def test_peers_exclude_self_and_other_types(self):
        day = date(2025, 1, 6)
        rows = weekly_metrics([shipment(1, day, 2), shipment(2, day, 4, origin="C"),
                               shipment(3, day, 8, origin="D"),
                               shipment(4, day, 100, origin="E", kind="Long")])
        self.assertEqual(rows[0]["peer_average"], 6)
        self.assertEqual(rows[0]["peer_count"], 2)
        self.assertIsNone(rows[-1]["peer_average"])

    def test_future_append_cannot_change_past(self):
        base = [shipment(1, date(2025, 1, 6), 2), shipment(2, date(2025, 1, 13), 3)]
        self.assertEqual(weekly_metrics(base), weekly_metrics(base +
                         [shipment(3, date(2025, 2, 3), 1000)])[:2])

    def test_direction_is_preserved(self):
        rows = weekly_metrics([shipment(1, date(2025, 1, 6), 2),
                               shipment(2, date(2025, 1, 6), 4, origin="B", destination="A")])
        self.assertEqual([r["route"] for r in rows], ["A-B", "B-A"])

    def test_zero_cost_baseline_is_unavailable(self):
        rows = weekly_metrics([shipment(1, date(2025, 1, 6), 0),
                               shipment(2, date(2025, 1, 13), 2)])
        self.assertIsNone(rows[-1]["vs_own_history_pct"])

    def test_static_high_peer_cost_is_not_a_rise(self):
        row = dict(vs_own_history_pct=0, vs_similar_routes_pct=50, vs_previous_observed_pct=0)
        self.assertFalse(is_candidate(row, Config()))
        row["vs_own_history_pct"] = 16
        self.assertTrue(is_candidate(row, Config()))

    def test_config_rejects_bad_threshold(self):
        with self.assertRaises(ValueError):
            Config(anomaly_threshold_pct=float("nan"))

    def test_positive_cost_after_zero_baseline_is_flagged(self):
        rows = weekly_metrics([shipment(1, date(2025, 1, 6), 0),
                               shipment(2, date(2025, 1, 13), 2)])
        self.assertIsNone(rows[-1]["vs_own_history_pct"])
        self.assertTrue(is_candidate(rows[-1], Config()))


class ValidationTests(unittest.TestCase):
    def write_input(self, directory, overrides=None, duplicate=False):
        row = dict(zip(SHIPMENT_COLUMNS, ["1", "A", "B", "Short", "Steel", "1", "10", "20",
                                          "2025-01-06", "Transporter"]))
        row.update(overrides or {})
        path = Path(directory) / "input.csv"
        with path.open("w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=SHIPMENT_COLUMNS)
            writer.writeheader()
            writer.writerow(row)
            if duplicate:
                writer.writerow(row)
        return path

    def test_invalid_rows_are_rejected(self):
        for overrides in ({"quantity_tonnes": "0"}, {"distance_km": "-1"},
                          {"freight_cost_inr": "nan"}, {"shipment_date": "2025-02-30"},
                          {"route_type": "Unknown"}, {"origin": ""}):
            with self.subTest(overrides=overrides), tempfile.TemporaryDirectory() as tmp:
                with self.assertRaises(ValidationError):
                    load_shipments(self.write_input(tmp, overrides))

    def test_duplicate_id_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValidationError):
                load_shipments(self.write_input(tmp, duplicate=True))


if __name__ == "__main__":
    unittest.main()
