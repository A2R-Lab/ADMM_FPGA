# Late-May flight metrics

Compute the physical-flight constraint metrics with:

```bash
python3 paper_figures/flight_metrics.py
```

This prints the numbers and writes `flight_metrics.txt`, `flight_metrics.csv`,
and PDF/PNG figures under `paper_figures/output/`. It reads only bundled data:
no server, mounted home directory, historical Git checkout, or FPGA tools are
needed. Paths are resolved relative to the script, so the command also works
from another directory.

Use a Python environment with compatible NumPy and Matplotlib installations.
For a fresh Python 3.10–3.12 environment:

```bash
python3 -m venv /tmp/accelmpc-flight-env
/tmp/accelmpc-flight-env/bin/python -m pip install -r paper_figures/requirements-flight.txt
/tmp/accelmpc-flight-env/bin/python paper_figures/flight_metrics.py
```

The pinned versions were checked with Python 3.11.2. Mixing a system Matplotlib
built for NumPy 1 with a user-installed NumPy 2 causes an import error; the
isolated environment avoids that conflict.

Optional arguments:

```bash
python3 paper_figures/flight_metrics.py --experiment star
python3 paper_figures/flight_metrics.py --experiment dynamic --output-dir /tmp/flight-metrics
```

Subset runs write `flight_metrics_star.{txt,csv}` or
`flight_metrics_dynamic.{txt,csv}`, preserving an existing complete report.
Generated outputs are ignored by Git.

## Inputs and experiment selection

The single configuration is
[`data/flight_metrics/experiments.json`](data/flight_metrics/experiments.json).
It records original CSV filenames and SHA-256 hashes, experiment attribution,
interval rules, coordinate conventions, source revisions and reconstruction
parameters. The script checks the hashes before computing any numbers.

| Experiment | May 22 recording | Evaluation |
|---|---|---|
| Dynamic obstacles, paper-panel take | TAKE1, 15:35:39 | Full log |
| Constrained-star candidates | 18:52:11; 18:53:42 | Unique `start_traj` through following `reset_traj`, inclusive |

Original files are bundled unchanged under `data/flight_metrics/`. TAKE1 reuses
the existing CSV under `data/top_side_frame_table/` so the panel figure and this
analysis share one input without duplicating it.

The source bridge repository's May 25 commit identifies May 22 as the filmed
dynamic-obstacle and constrained-star session. The star candidates have explicit
start/reset intervals, stable altitude, and similar repeated motion after
subtracting their logged origins. Their association with the named star source
is **inferred**. The exact flashed image and correspondence to the paper video
are not verified. The video creation timestamp alone does not identify a run.
Other trial recordings remain in the original bridge repository.

TAKE1 is the author-selected dynamic-obstacle demonstration and is already used
for the paper's obstacle panels. Its metrics describe this single recording.
Other takes are outside this deliverable and remain in the original source
repository. TAKE1 has no stop/landing event establishing a flight-only interval;
the default evaluates its complete log. A future narrower interval must use the manifest's
`explicit` mode with `start_s`, `end_s` and independent `evidence` (for example,
a documented video synchronization). Full-log results should remain available
as separate manifest entries. Never choose cutoffs to reduce error.

Figure 7's March figure-eight recordings and the existing benchmark plotting
script are unchanged. This workflow does not recompute or rank those flights.
Fixed/float simulations elsewhere in the repository are separate experiments.

## What the numbers mean

**Position tracking error** is the distance between measured and reference
positions at the same physical time.

**Position-constraint violation** is the distance outside an allowed interval:

```text
violation = max(lower_bound - position, position - upper_bound, 0)
```

For example, x = 0.43 m with an upper bound of 0.40 m gives a 3 cm violation,
irrespective of the commanded reference.

For each evaluated axis, the report gives maximum violation, RMS violation over
all evaluated samples (including zeros), and outside-sample count/percentage.
For star runs, `xy_any` uses `max(x_violation, y_violation)` per sample; it counts
a sample once when either axis is outside. This is the largest axis violation,
not Euclidean distance to the box or tracking RMSE.

Metrics are sample-weighted, using the recorded rows with no smoothing,
resampling or outlier removal. Repeated mocap frames remain and are counted.
Percentages are neither independent-frame statistics nor continuous-time
violation durations. Maximum values are maxima of the retained samples.

### Star coordinates and static bounds

Primary position is `mocap_xyz - target_xyz`, in metres. The target must be
constant during the selected run. It supplies the assumed world-to-controller
origin; the CSV's constant target is not the time-varying onboard reference.

The identified source `b82e18d` uses `star_hold`, outer amplitude 2 m on each
axis and inner ratio 0.25. Its header generator subtracts
`2 * 0.25 * cos(pi/4)` from the configured ±1 m bounds. Thus the static box is
approximately **[-1.353553, +0.646447] m on each relative axis**.
The output labels this source-bound/frame association as inferred.

`constraint_active=0` in these logs means that the bridge is not transmitting
dynamic bounds. It does not disable the FPGA's compiled static box.

`star_reference_reconstructed.csv` contains one geometric cycle regenerated
from the historical source function with the parameters and hashes recorded in
the manifest. Its `t_s` is nominal cycle time, not log elapsed time. The source's
28-sample entry prefix is not included in this geometric overlay. No fitted
translation, rotation, phase, or time scale is used.

### Dynamic bounds and timing

The bridge maps drone and obstacle coordinates into the same frame. Use mocap
world x and the latest preceding `event=command, command=set_constraints` row's
signed integer bounds divided by 1000. Hold those bounds until the next
transmission. Equal timestamps follow CSV row order.

Sample rows contain newly calculated bounds that may not have been transmitted.
Their floating `box_min_x/box_max_x` values appear only as dotted diagnostic
curves. The logger stores asynchronously cached poses; matching fields on one
row does not prove simultaneous acquisition.

**A transmitted `(0, 0)` pair is a protocol sentinel requesting compiled static
defaults. It does not impose x = 0.** This behavior is present in the named
dynamic-demo source `a0c021d`. Those defaults are not matched to these logs, so
samples during this state are excluded from the dynamic-bound calculation,
counted as `static_defaults_not_identified`, and shaded grey in the figures.
The script also reports samples preceding the first transmission.

The bridge uses `time.time()` for `elapsed_s` and the misleadingly named
`monotonic_s`; `mocap_stamp_s` comes from the ROS pose header. The analysis checks
timestamp ordering and reports gaps and duplicates. It does not infer sensor
latency from differences between unverified clock domains.

These are **transmitted bounds**, not confirmed controller application times.
TAKE1's 0.20 m inset is measured from obstacle markers; without obstacle
dimensions and marker-to-surface geometry it does not establish physical
clearance. This workflow makes no clearance calculation.

## Figures, missing information and validation

- `star_*_trajectory.{pdf,png}`: recorded XY, inferred static box, reconstructed
  reference geometry and highlighted outside samples.
- `star_*_bounds.{pdf,png}`: x/y versus elapsed time and static bounds.
- `dynamic_take*_bounds.{pdf,png}`: mocap x, transmitted bounds, floating
  diagnostic bounds, and violation versus time.

Plots and metrics use the same evaluated arrays. The report includes sample
support, every exclusion count, repeated frames, gaps, origin, attribution and
source hashes. Invalid mocap/required fields are counted and excluded; reversed
timestamps, inverted bounds and hash mismatches fail instead of silently
repairing the recording.

Tracking RMSE/95th percentile/maximum remain unavailable for these inputs:
their exact onboard reference tables and playback timing are not verified.
The script can evaluate a same-frame reference explicitly marked
`verified_log_elapsed`, using its time-stamped positions with zero-order hold
and full coverage. Do not mark a reconstructed geometric cycle as synchronized.

Run the checks with:

```bash
python3 -m unittest discover -s paper_figures -p test_flight_metrics.py -v
```

The checks cover translation, units, event order, start/reset selection, zero
bound sentinels, missing data, repeated frames and unavailable metadata. An
independent `csv`/`math` calculation checks every reported constraint metric
across all three bundled recordings. Repeat runs must produce identical text/CSV numbers.
These checks validate the computation; remaining historical attribution is
recorded explicitly above and in the manifest.
