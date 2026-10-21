# Evaluation results

These tables and previews are generated from the bundled benchmark/flight inputs
and the numerical analysis described below. Full-resolution exports are generated
in `output/`; only selected PNG previews are kept in `previews/`.

## Solver benchmarks

The [benchmark CSV](data/benchmark_summary.csv) contains the historical measurements,
implementation estimates and failed points. The table uses the same row selection
as `plot_benchmarks.py`: timing-clean implementations, lowest latency then lowest
power, with the figure's explicit readability exclusions. The default comparison
uses 10 iterations; the common-horizon resource comparison is H40.

FPGA latency is HLS cycles at 100 MHz, excluding communication. FPGA energy uses
Vivado post-route power estimates; TinyMPC energy uses the stored MCU timings
and a 287.1 mW active-power estimate. EDP is energy times solve delay. See
[benchmark definitions and reproduction](../docs/benchmarking.md) for the power
boundaries, 100 µs feasibility-table reserve, and historical source limitations.
The maximum-horizon results describe capacity, not 1 kHz operation.

<!-- BEGIN GENERATED BENCHMARKS -->

| H40 / 10 iterations | Solve (ms) | Energy (mJ) | EDP (mJ·ms) |
| --- | --- | --- | --- |
| Staged FPGA | 1.365 | 0.932 | 1.273 |
| Full-sparse FPGA | 1.485 | 0.494 | 0.734 |
| TinyMPC | 20.899 | 6.000 | 125.396 |

| H40 FPGA resources | LUTs | FFs | BRAM tiles | DSPs |
| --- | --- | --- | --- | --- |
| Staged FPGA | 22127 | 26540 | 36 | 80 |
| Full-sparse FPGA | 9280 | 12051 | 78.5 | 77 |

| Largest recorded timing-clean horizon | Horizon | Variables | Constraints | Solve (ms) |
| --- | --- | --- | --- | --- |
| Full-sparse FPGA | 90 | 1452 | 1632 | 3.295 |
| Staged FPGA | 1350 | 21612 | 24312 | 44.859 |

<!-- END GENERATED BENCHMARKS -->

![Solve latency and energy versus horizon](previews/benchmark_latency_energy.png)

![Energy-delay product comparison](previews/benchmark_edp_bars.png)

## NumericFPGA latency is HLS cycles at 100 MHz, excluding communication. FPGA energy uses
Vivado post-route power estimates; TinyMPC energy uses the stored MCU timings
and a 287.1 mW active-power estimate. EDP is energy times solve delay. See
[benchmark definitions and reproduction](../docs/benchmarking.md) for the power
boundaries, 100 µs feasibility-table reserve, and historical source limitations.
The maximum-horizon results describe capacity, not 1 kHz operation.
al accuracy

The current H27/k9 analysis uses the actual C++ solver and persistent warm starts.
Independent fixed, float and OSQP closed-loop trajectories use a generated
figure-eight and nonlinear plant. The command-error comparison instead replays
identical fixed-rollout inputs through float and OSQP, avoiding trajectory
feedback differences. These are reconstructed simulations, separate from flights.

<!-- BEGIN GENERATED NUMERICS -->

```text
H27 / 9 iterations / figure-eight / persistent warm start

First-command error, p95 (normalized motor units; 257 identical-input samples):
  fixed–float: 4.73499e-05
  fixed–OSQP: 0.00450374
  float–OSQP: 0.00447495

Controller   Tracking RMSE (m)   Max XY-bound violation (m)
  fixed      0.05672986          0
  float      0.05672938          0
  osqp       0.05663985          0
```

<!-- END GENERATED NUMERICS -->

![Fixed and floating-point residuals by iteration](previews/numerical_convergence.png)

## Recorded flights

The figure-eight overlay uses the original March inputs and the plot script's
fixed alignment and row windows. It is a trajectory visualization, not a new
synchronized tracking-error measurement.

![Recorded figure-eight trajectories](previews/figure8_trajectory_overlay.png)

The following metrics quantify **position-constraint violation**, not tracking
error. Star values use the larger of the x/y violations per sample. Dynamic 
values use the complete TAKE1 recording and last transmitted x bounds.
RMS includes zero violations; percentages are sample-weighted with repeated
motion-capture frames retained. These values do not measure obstacle clearance.
See [flight methodology and limitations](../docs/flight-analysis.md).

<!-- BEGIN GENERATED FLIGHTS -->

| Recording | Samples | Max violation (cm) | RMS violation (cm) | Outside (%) |
| --- | --- | --- | --- | --- |
| dynamic_take1 | 6639 | 4.5048 | 0.3386 | 3.449 |
| star_185211 | 3752 | 3.1325 | 0.5070 | 11.354 |
| star_185342 | 3830 | 3.8894 | 0.5690 | 12.167 |

<!-- END GENERATED FLIGHTS -->

![Dynamic obstacle bounds and recorded position](previews/dynamic_take1_bounds.png)

## Regenerate

Run from the repository root in a Python 3.10–3.12 environment:

```bash
python -m pip install numpy==1.26.4 matplotlib==3.10.1
python evaluation/plot_benchmarks.py
python evaluation/flight_metrics.py
python evaluation/make_top_side_frame_table.py
```

These commands use only bundled CSVs and panel images; no FPGA is required.
The first produces latency/energy, EDP, H40 radar, figure-eight overlay and the
iteration-budget table. The flight script writes text/CSV metrics and trajectory/
bounds figures. The panel script composes the paper's video-frame figure from
tracked PNGs. Original videos are needed only for its optional `--extract-panels`.

Numerical simulation also needs the [build dependencies](../docs/build.md), a
C++14 compiler, AMD's Vitis headers, and OSQP:

```bash
python -m pip install osqp==0.6.7.post3
HLS_INCLUDE=/path/to/Vitis/include OPENBLAS_NUM_THREADS=1 \
  python evaluation/numerical_accuracy.py --simulate
```

Subsequent `python evaluation/numerical_accuracy.py` calls reuse the local
`output/numerical.npz`; use `--simulate` after changing solver or model settings.
The simulation writes a text report and convergence plot.

After regenerating all analyses, refresh the tables and selected previews with:

```bash
python evaluation/summarize_results.py
```

This last command updates this page and `previews/` for review. It does not run
hardware builds or physical experiments. Keep numerical inputs and plotting
styles in the source scripts; exported figures should be regenerated.

## New power measurements

The [Arty power campaign](../docs/power.md) measures core/BRAM and 5 V supply rails.
The [Arty power measurements CSV](data/arty_power_measurements.csv) contains the
campaign summary for 42 planned configurations: 23 measured with three valid
repetitions each and 19 marked pending.