# Benchmarks and reproduction

Start with the [results page](../evaluation/README.md) to inspect the bundled
measurements and regenerate figures without hardware. Use the [build environment](build.md)
for new FPGA experiments. Run commands below from the repository root.

## Choose a workflow

| Question | Entry point | Requirements |
|---|---|---|
| Latency, power estimates and resources versus horizon | `scripts/run_max_horizon_point.py` or `scripts/run_max_horizon_parallel.py` | Vitis/Vivado, Python build dependencies |
| Summarize those implementation runs | `scripts/aggregate_max_horizon_results.py` | Recorded implementation outputs, NumPy/Matplotlib |
| Measure Arty supply power | [Power campaign](power.md) | Arty A7-100T Rev E, Vivado and serial access |
| Closed-loop behavior in simulation | `make hls_closed_loop_sim` | Vitis HLS and Python build dependencies |
| Fixed/float/OSQP numerical accuracy | `evaluation/numerical_accuracy.py` | Vitis headers, C++ compiler, build dependencies and OSQP |
| UART solver communication | `scripts/uart_solver_smoke_test.py` | Programmed Arty board and pyserial |

The retained tuning and resource sweeps in `scripts/sweep_*.py` are exploratory
workflows. Their `--help` describes each grid; they are not prerequisites for
regenerating the published figures.

## Implement one point or a sweep

```bash
python scripts/run_max_horizon_point.py \
  --arch staged_a --horizon 320 --iters 10 --board custom \
  --out-dir results/horizon-sweep

python scripts/run_max_horizon_parallel.py \
  --arch full_sparse --horizons 20,40,80,90,100 \
  --seeds 0,1,2,3 --workers 2 --threads-per-worker 3 \
  --board custom --iters 10 --out-dir results/horizon-sweep

python scripts/aggregate_max_horizon_results.py --run-dir results/horizon-sweep
```

Both architectures can share an output directory for common-horizon comparisons.
The runners disable trajectory generation and record reports, generated headers,
bitstreams and one result row per point. The aggregator writes `summary.csv`,
`common_horizon_comparison.csv`, `max_horizon_by_arch.csv` and plots.

The single-point runner archives failed builds and normally exits zero even for
an infeasible point. Pass `--strict-exit-code` when a shell failure is required.
Check timing and resource use in the reports, not just command completion.
`--detach` runs a single point in the background; its PID and log are in the
point directory.

Parallel workers use isolated copies under a unique temporary directory. An
explicit `--work-root` retains workers for debugging and cannot be shared by
concurrent runs. Each horizon stops at the first timing-clean implementation
variant unless `--run-all-seeds` is requested. Choose worker counts to match
available RAM and disk as well as CPUs.

For an optional scalability axis, supply `max_horizon_manual.csv` in the run
directory with columns `arch,max_timing_clean_horizon`. Values must come from
verified runs; the aggregator does not search other campaigns automatically.

For a compact export from existing runs, use `scripts/publish_solver_scalability.py`
with repeated `--run-dir`, a `--manual-scalability` CSV and an `--output` directory.
It writes canonical CSVs, figures and a short source/settings record. Its
`--regenerate-only` option redraws figures from the exported CSVs.

## Energy and timing definitions

The single publication input is `evaluation/data/benchmarks.csv`. It contains
completed, timing-clean results only. Measured configurations use measured solve
latency; uninstrumented configurations use HLS cycles divided by their operating
clock, subject to route timing closure. Communication and host processing are excluded.

Both AccelMPC and **TinyMPC FPGA (Wu et al.) use Arty measurements** wherever
available. All 29 TinyMPC FPGA publication points, H5 through H1023, are measured.
Fused measurements also extend through H1023. For both FPGA solvers, energy is
measured active core/BRAM energy plus matching post-route auxiliary/I/O supply
power multiplied by measured latency. EDP uses that same latency. Auxiliary/I/O
power is supply voltage times total current, including static current; VCCADC is
excluded because it is tied to ground on the custom PCB. Instrumentation remains
included in measured core power; no estimated instrumentation power is subtracted.
Regulators, board support circuitry, host processing and SPI energy are excluded.
Measurements are from the Arty, not the flight deck, with trajectory generation disabled.

`energy_source=board_core_plus_estimated_aux_io` identifies these measurements;
`post_route_estimate` identifies uninstrumented estimates, marked with an asterisk.
TinyMPC FPGA measured bars are neither asterisked nor hatched. TinyMPC MCU latency
is measured in FreeRTOS and its energy uses nominal active power,
`0.087 A × 3.3 V = 0.2871 W`. MCU points have no asterisk; this nominal-power
assumption is stated in the captions. Energy outside the solve is excluded.

The CSV retains every valid point. Only the latency/energy display is thinned at
large horizons to avoid overlapping bubbles; comparisons and statistics still use
all rows. EDP bars cover H10 through H80, with dashed arrows and boxed ratios
showing the EDP reduction from the MCU and Wu FPGA baselines to fused AccelMPC.
The separate feasibility table reserves 100 microseconds for FPGA communication
within a 1 ms period. Large demonstrated horizons do not imply 1 kHz operation.

Regenerate without FPGA tools:

```bash
~/venv/bin/python evaluation/plot_benchmarks.py --skip-trajectory
~/venv/bin/python evaluation/summarize_results.py --benchmarks-only
```

The H40 radar reports measured latency and energy for staged and compact full_sparse.
Numbers on its spokes show actual values; radial positions normalize each cost to
the worst design, with the BRAM radius additionally scaled by 0.8 for readability
(the same factor for both mappings). Scalability uses inverse largest demonstrated horizon. Resources
come from the consolidated CSV's `solver_*` fields and use matching uninstrumented
SPI wrappers for both mappings. Measured energy includes the instrumented builds.
Full_sparse currently uses H400 as its largest demonstrated horizon, which is not an exact capacity limit. Missing
measurements or matched resource fields at the radar horizon cause generation
to fail. Historical campaign
CSVs and Vivado reports are not additional inputs to publication plotting.
