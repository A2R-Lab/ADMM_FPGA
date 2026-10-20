"""Regression checks for flight coordinates, event timing and bundled metrics.

Run: python3 -m unittest discover -s evaluation -p test_flight_metrics.py
"""
import csv
import hashlib
import json
import math
from pathlib import Path
import tempfile
import unittest

import numpy as np

import flight_metrics as fm


FIELDS = [
    "elapsed_s", "event", "command", "mocap_valid", "constraint_active",
    "mocap_x", "mocap_y", "mocap_z", "mocap_stamp_s",
    "target_x", "target_y", "target_z", "dynamic_x_min_mm", "dynamic_x_max_mm",
    "box_min_x", "box_max_x",
]


def row(t, **kwargs):
    values = dict(zip(FIELDS, [""] * len(FIELDS)))
    values.update(elapsed_s=t, event="sample", command="", mocap_valid="1",
                  constraint_active="1", mocap_x=0, mocap_y=0, mocap_z=0,
                  mocap_stamp_s=1000 + t, target_x=0, target_y=0, target_z=0,
                  dynamic_x_min_mm=-1000, dynamic_x_max_mm=1000,
                  box_min_x=-1, box_max_x=1)
    values.update(kwargs)
    return values


class FlightMetricsTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.data = Path(self.directory.name)
        self.spec = dict(
            id="test", experiment="dynamic", file="flight.csv",
            interval={"mode": "full_log"},
        )

    def write(self, rows):
        path = self.data / self.spec["file"]
        with path.open("w", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=FIELDS)
            writer.writeheader()
            writer.writerows(rows)
        self.spec["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()

    def analyze(self, rows):
        self.write(rows)
        return fm.analyze(self.spec, self.data)

    def test_transmissions_not_newly_calculated_sample_bounds(self):
        r = self.analyze([
            row(0),  # no transmitted bounds yet
            row(1, event="command", command="set_constraints",
                dynamic_x_min_mm=-100, dynamic_x_max_mm=100),
            # The newly calculated sample bound is wider; it has not been sent.
            row(1, mocap_x=.15),
            row(2, mocap_x=.15),
            row(3, event="command", command="set_constraints"),
            row(3, mocap_x=.15),
        ])
        self.assertEqual(r["excluded"]["before_first_transmission"], 1)
        self.assertEqual(r["metrics"]["x"]["outside_samples"], 2)
        self.assertAlmostEqual(r["metrics"]["x"]["max_violation_cm"], 5)
        self.assertAlmostEqual(r["metrics"]["x"]["rms_violation_cm"], math.sqrt(50 / 3))
        np.testing.assert_allclose(r["upper"][:, 0], [.1, .1, 1])

    def test_equal_timestamp_uses_recorded_event_order(self):
        r = self.analyze([
            row(0, event="command", command="set_constraints"),
            row(1, mocap_x=.5),
            row(1, event="command", command="set_constraints", dynamic_x_max_mm=100),
            row(2, mocap_x=.5),
        ])
        np.testing.assert_allclose(r["violations"][:, 0], [0, .4])

    def test_star_origin_bounds_and_start_reset(self):
        self.spec.update(experiment="star", origin="logged_target_xyz",
                         interval={"mode": "start_to_reset"},
                         static_bounds={"x": [-1, 1], "y": [-1, 1]})
        r = self.analyze([
            row(0, mocap_x=999),
            row(1, event="command", command="start_traj"),
            row(1, mocap_x=11.03, mocap_y=18.96, target_x=10, target_y=20,
                constraint_active="0"),
            row(2, mocap_x=10, mocap_y=20, target_x=10, target_y=20,
                constraint_active="0"),
            row(2, event="command", command="reset_traj"),
            row(3, mocap_x=999),
        ])
        self.assertEqual(r["excluded"]["outside_interval"], 2)
        self.assertAlmostEqual(r["metrics"]["x"]["max_violation_cm"], 3)
        self.assertAlmostEqual(r["metrics"]["y"]["max_violation_cm"], 4)
        self.assertEqual(r["metrics"]["xy_any"]["outside_samples"], 1)
        self.assertAlmostEqual(r["metrics"]["xy_any"]["rms_violation_cm"], math.sqrt(8))
        self.assertEqual(r["evaluated_interval"], [1., 2.])

    def test_invalid_repeated_and_missing_samples(self):
        r = self.analyze([
            row(0, event="command", command="set_constraints"),
            row(.1, mocap_stamp_s=100),
            row(.2, mocap_valid="0"),
            row(.3, mocap_x="nan"),
            row(.4, constraint_active="0"),
            row(.5, mocap_stamp_s=100),
        ])
        self.assertEqual(r["repeated_mocap_samples"], 1)
        self.assertEqual(r["metrics"]["x"]["samples"], 2)
        self.assertEqual(r["excluded"]["invalid_mocap"], 1)
        self.assertEqual(r["excluded"]["missing_or_nonfinite"], 1)
        self.assertEqual(r["excluded"]["inactive_constraints"], 1)
        self.assertAlmostEqual(r["max_log_gap_s"], .4)

    def test_no_transmissions_returns_unavailable(self):
        r = self.analyze([row(0), row(1)])
        self.assertEqual(r["status"], "unavailable")
        self.assertEqual(r["excluded"]["before_first_transmission"], 2)

    def test_zero_pair_requests_static_defaults_not_zero_width_box(self):
        r = self.analyze([
            row(0, event="command", command="set_constraints",
                dynamic_x_min_mm=0, dynamic_x_max_mm=0),
            row(.1, mocap_x=.9),
            row(1, event="command", command="set_constraints"),
            row(1.1, mocap_x=.9),
            row(1.2, mocap_x=.9),
        ])
        self.assertEqual(r["excluded"]["static_defaults_not_identified"], 1)
        self.assertEqual(r["metrics"]["x"]["samples"], 2)
        self.assertEqual(r["metrics"]["x"]["max_violation_cm"], 0)

    def test_missing_star_bounds_returns_unavailable(self):
        self.spec["experiment"] = "star"
        r = self.analyze([row(0), row(1)])
        self.assertEqual(r["status"], "unavailable")
        self.assertIn("bounds", r["reason"])

    def test_invalid_source_or_bounds_fail(self):
        self.write([row(0), row(1)])
        self.spec["sha256"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "hash mismatch"):
            fm.analyze(self.spec, self.data)
        with self.assertRaisesRegex(ValueError, "integer bounds"):
            self.analyze([row(0, event="command", command="set_constraints",
                              dynamic_x_min_mm=1000, dynamic_x_max_mm=-1000), row(1)])
        with self.assertRaisesRegex(ValueError, "Reversed"):
            self.analyze([row(1), row(0)])

    def test_explicit_interval_needs_evidence(self):
        self.spec["interval"] = {"mode": "explicit", "start_s": 0, "end_s": 1}
        with self.assertRaisesRegex(ValueError, "evidence"):
            self.analyze([row(0), row(1)])

    def test_verified_tracking_uses_held_reference(self):
        ref = self.data / "ref.csv"
        ref.write_text("t_s,x_m,y_m,z_m\n0,0,0,0\n1,1,0,0\n2,0,0,0\n")
        self.spec["reference"] = dict(file="ref.csv", sha256=hashlib.sha256(ref.read_bytes()).hexdigest(),
                                      timing="verified_log_elapsed", frame="world")
        r = self.analyze([row(0, event="command", command="set_constraints"),
                          row(.5), row(1, mocap_x=1)])
        self.assertEqual(r["tracking"]["rmse_cm"], 0)
        self.spec["reference"]["timing"] = "unverified"
        r = fm.analyze(self.spec, self.data)
        self.assertIsNone(r["tracking"])

    def test_ambiguous_start_or_missing_reset_fail(self):
        self.spec.update(experiment="star", origin="logged_target_xyz",
                         interval={"mode": "start_to_reset"},
                         static_bounds={"x": [-1, 1], "y": [-1, 1]})
        with self.assertRaisesRegex(ValueError, "one start"):
            self.analyze([row(0, event="command", command="start_traj"),
                          row(1, event="command", command="start_traj"),
                          row(2, event="command", command="reset_traj")])
        with self.assertRaisesRegex(ValueError, "reset_traj"):
            self.analyze([row(0, event="command", command="start_traj"), row(1)])

    def test_verified_reference_requires_frame_and_full_coverage(self):
        ref = self.data / "ref.csv"
        ref.write_text("t_s,x_m,y_m,z_m\n0,0,0,0\n1,1,0,0\n")
        self.spec["reference"] = dict(file="ref.csv", sha256=hashlib.sha256(ref.read_bytes()).hexdigest(),
                                      timing="verified_log_elapsed", frame="world")
        self.write([row(0, event="command", command="set_constraints"),
                    row(.5), row(1.5)])
        with self.assertRaisesRegex(ValueError, "cover"):
            fm.analyze(self.spec, self.data)
        self.spec["reference"]["frame"] = "relative_to_logged_target"
        with self.assertRaisesRegex(ValueError, "frame"):
            fm.analyze(self.spec, self.data)

    def test_nonfinite_static_bound_fails(self):
        self.spec.update(experiment="star", origin="logged_target_xyz",
                         static_bounds={"x": [-1, float("nan")], "y": [-1, 1]})
        with self.assertRaisesRegex(ValueError, "Nonfinite"):
            self.analyze([row(0), row(1)])


class BundledDataTests(unittest.TestCase):
    def test_independent_csv_math_calculation(self):
        """Recalculate all bundled logs without the analyzer's selection or math helpers."""
        manifest = json.loads(fm.MANIFEST.read_text())
        for spec in manifest["experiments"]:
            with self.subTest(recording=spec["id"]):
                with (fm.DATA / spec["file"]).open(newline="") as stream:
                    rows = list(csv.DictReader(stream))
                a, b = -math.inf, math.inf
                if spec["experiment"] == "star":
                    a = float(next(r["elapsed_s"] for r in rows if r["event"] == "command" and r["command"] == "start_traj"))
                    b = float(next(r["elapsed_s"] for r in rows if r["event"] == "command" and r["command"] == "reset_traj"))
                last = None
                values = {"x": []} if spec["experiment"] == "dynamic" else {"x": [], "y": [], "xy_any": []}
                for row_ in rows:
                    if row_["event"] == "command" and row_["command"] == "set_constraints":
                        last = [int(row_["dynamic_x_min_mm"]) / 1000, int(row_["dynamic_x_max_mm"]) / 1000]
                    if row_["event"] != "sample" or row_["mocap_valid"] != "1" or not a <= float(row_["elapsed_s"]) <= b:
                        continue
                    if spec["experiment"] == "dynamic" and (last is None or row_["constraint_active"] != "1"):
                        continue
                    if spec["experiment"] == "dynamic" and last == [0., 0.]:
                        continue
                    pair = []
                    for axis in ("x" if spec["experiment"] == "dynamic" else "xy"):
                        pos = float(row_["mocap_" + axis])
                        if spec["experiment"] == "star":
                            pos -= float(row_["target_" + axis])
                            lo, hi = spec["static_bounds"][axis]
                        else:
                            lo, hi = last
                        v = lo - pos if pos < lo else pos - hi if pos > hi else 0.
                        pair.append(v)
                        values[axis].append(v)
                    if len(pair) == 2:
                        values["xy_any"].append(max(pair))
                computed = fm.analyze(spec)
                for axis, vals in values.items():
                    metrics = computed["metrics"][axis]
                    self.assertEqual(metrics["samples"], len(vals))
                    self.assertEqual(metrics["outside_samples"], sum(v > 0 for v in vals))
                    self.assertAlmostEqual(metrics["max_violation_cm"], 100 * max(vals), places=10)
                    self.assertAlmostEqual(metrics["rms_violation_cm"], 100 * math.sqrt(math.fsum(v * v for v in vals) / len(vals)), places=10)
                self.assertIsNone(computed["tracking"])


if __name__ == "__main__":
    unittest.main()
