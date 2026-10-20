# Recorded-flight metrics

```bash
python paper_figures/flight_metrics.py
```

Run from the repository root with the [plotting dependencies](requirements-flight.txt).
The script prints results and writes `flight_metrics.txt`, `flight_metrics.csv`
and PDF/PNG plots under `output/`. `--experiment star` or `--experiment dynamic`
selects a subset; `--output-dir /path/to/output` changes the destination. Subsets
use distinct report filenames. See the [results page](README.md) for previews.

## Recordings and provenance

The [experiment configuration](data/flight_metrics/experiments.json) records
source filenames and hashes, evaluation intervals, coordinate conventions and
reconstruction parameters. Input hashes are checked before analysis.

| Recording | Evaluation | Attribution |
|---|---|---|
| TAKE1, May 22 at 15:35:39 | Complete log | Author-selected dynamic-obstacle demonstration used for the paper panels |
| May 22 at 18:52:11 | Unique `start_traj` through following `reset_traj`, inclusive | Candidate constrained-star run |
| May 22 at 18:53:42 | Same start/reset rule | Candidate constrained-star run |

TAKE1 shares its CSV with the panel-figure inputs under `data/top_side_frame_table/`.
The other logs and reconstructed star geometry are under `data/flight_metrics/`.
The star-source association is inferred from source `b82e18d`, session records
and trajectory behavior; the exact flashed image and video correspondence are
not verified. Other trial recordings are not bundled.

TAKE1 has no independently established flight-only interval, so the default
includes the whole log, including any termination/handling. A narrower interval
requires independently supported start/end times in the configuration's explicit
interval mode. The original March figure-eight inputs are a separate dataset.

## What is measured

Position-constraint violation in metres is:

```text
max(lower_bound - position, position - upper_bound, 0)
```

This differs from position tracking error, which needs the time-matched reference.
For each axis the report gives maximum violation, RMS including zero violations,
and outside-sample count/percentage. Star `xy_any` uses the maximum x/y violation
per sample, not Euclidean distance to the box.

Metrics are sample-weighted without smoothing, resampling or outlier removal.
Repeated motion-capture frames remain. Percentages do not measure continuous-time
violation duration. Reports include exclusions, sample support, repeated frames,
timestamp gaps and source hashes. Invalid required samples are counted/excluded;
reversed timestamps, inverted bounds and hash mismatches fail explicitly.

## Star bounds and reference

Position is `mocap_xyz - target_xyz`; the constant target defines the assumed
controller origin, not the changing onboard reference. Source `b82e18d` uses
`star_hold`, 2 m amplitude per axis and inner ratio 0.25. The generator shifts
configured ±1 m bounds by `2 × 0.25 × cos(pi/4)`, giving approximately
**[-1.353553, +0.646447] m** on each relative axis. Metrics are conditional on
this inferred source/frame association.

`constraint_active=0` means the bridge is not transmitting dynamic bounds;
it does not disable compiled static constraints. The reconstructed star CSV
contains one geometric cycle, excluding the 28-sample entry prefix. Its time
column is nominal cycle time, not log elapsed time. No fitted spatial or temporal
alignment is used. Exact onboard tables and playback phase remain unverified.

## Dynamic bounds and timing

Use mocap world x and the latest preceding `set_constraints` transmission's
signed integer bounds divided by 1000, held until the next transmission. Equal
timestamps follow CSV row order. Floating bounds on sample rows may not have
been sent; they appear only as diagnostic curves.

A transmitted `(0,0)` pair requests compiled defaults, not a zero-width box.
Those defaults are not matched to these recordings: such samples are excluded
as `static_defaults_not_identified`. Samples before the first transmission are
also reported. Bounds reflect logged transmission, not acknowledged controller
application. Poses are asynchronously cached; fields on a row need not have
been acquired simultaneously.

The bridge's `elapsed_s` and `monotonic_s` both derive from `time.time()`;
`mocap_stamp_s` uses the ROS header clock. Their difference does not establish
sensor latency. The 0.20 m inset is relative to obstacle markers; obstacle
geometry is insufficient to compute physical clearance.

## Tracking error and checks

Tracking RMSE, p95 and maximum are unavailable for these logs because matching
onboard reference tables and playback timing are unverified. The analyzer can
use a same-frame reference marked `verified_log_elapsed`, with zero-order hold
and full interval coverage. Reconstructed geometry alone is insufficient.

```bash
python -m unittest discover -s paper_figures -p test_flight_metrics.py -v
```

Tests cover units, frame translation, event order, interval selection, zero-bound
sentinels, missing data and repeated frames. An independent CSV/math calculation
checks every constraint metric on the bundled recordings. These checks validate
computation; they do not resolve historical attribution.
