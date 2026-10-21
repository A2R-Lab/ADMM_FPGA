# Flight-analysis methodology

See the [evaluation README](../evaluation/README.md) for results, plots, dependencies
and reproduction commands.

## Recordings and provenance

`evaluation/data/flight_metrics/` contains `constrained_star_flight.csv`
and `star_reference.csv`. Evaluation uses start_traj through reset_traj.

The dynamic-obstacle recording shares its CSV with the paper panel inputs under
`evaluation/data/top_side_frame_table/`. Its constraint metrics use the complete
log, including any termination/handling.

## What is measured

Position-constraint violation in metres is:

```text
max(lower_bound - position, position - upper_bound, 0)
```

This differs from position tracking error, which compares flight position with
the reference trajectory at the corresponding playback phase.
For each axis the report gives maximum violation, RMS including zero violations,
and outside-sample count/percentage. Star `xy_any` uses the maximum x/y violation
per sample, not Euclidean distance to the box.

Metrics are sample-weighted without smoothing, resampling or outlier removal.
Repeated motion-capture frames remain. Percentages do not measure continuous-time
violation duration. Reports include exclusions, sample support, repeated frames,
timestamp gaps. Invalid required samples are counted/excluded;
reversed timestamps and inverted bounds fail explicitly.

## Star bounds and reference

Position is `mocap_xyz - target_xyz`; the constant target defines the assumed
controller origin, not the changing onboard reference. Source `b82e18d` uses
`star_hold`, 2 m amplitude per axis and inner ratio 0.25. The generator shifts
configured ±1 m bounds by `2 × 0.25 × cos(pi/4)`, giving approximately
**[-1.353553, +0.646447] m** on each relative axis.

`constraint_active=0` means the bridge is not transmitting dynamic bounds;
it does not disable compiled static constraints. The star CSV contains one
geometric cycle, excluding the 28-sample entry prefix. Its time column is nominal
cycle time, not log elapsed time.

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

## STAR tracking error

The STAR recording is compared with the recorded trajectory.
Reference samples use a 20 ms hold.

The reported tracking metrics use a fixed phase of 24.343 s over the 25 s
reference cycle (equivalently -0.657 s), as specified by `STAR_PHASE_OFFSET_S`
in `evaluation/flight_metrics.py`, to align reference playback with the flight
recording. The offset affects reference lookup and selection of samples whose
reference lies inside the bounds, not measured positions or bound violations.

Tracking RMSE, p95 and maximum are scored only at flight samples whose 
reference point lies inside the source's static XY box. The report gives the
scored flight-sample coverage and the fraction of reference points that are
feasible. This avoids counting demanded positions outside the QP's position
bounds as trackable targets.

Generate text and CSV without plotting dependencies with
`python3 evaluation/flight_metrics.py --no-plots`.
