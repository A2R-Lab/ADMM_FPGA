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

## Interpret and reproduce historical results

The committed benchmark CSV preserves source revisions, working-tree status,
implementation variants and timing failures. Several FPGA runs used modified
working trees: the base commit alone cannot recreate those exact builds.
TinyMPC rows do not record a matching source revision. A fresh build tests the
current implementation; regenerating the figures reproduces the stored analysis.

| Experiment | Configuration evidence |
|---|---|
| Solver comparison | Bundled CSV; default plots compare 10 iterations, radar at H40 |
| Maximum horizon | Bundled CSV; capacity experiment, separate from 1 kHz flight operation |
| Constrained star | Historical source `b82e18d`, H27/k9 staged-A; flight association and timing limits are in the [flight guide](flight-analysis.md) |
| Dynamic obstacle demos | Historical sources `82c068a` (H40/k9) and `a0c021d` (H25/k9), full-sparse; exact flashed-image/log correspondence is not established |

Inspect historical settings with `git show <revision>:scripts/parameters.py`.
Current defaults should not be substituted for the named experiment settings.
Matching firmware, PCB and TinyMPC revisions and acquisition settings are needed
to repeat the complete physical comparison; companion repositories are linked
from the root README.

## Energy and timing definitions

FPGA solve latency is HLS cycle count divided by the configured clock (100 MHz
in the stored benchmark), subject to route timing closure. It excludes SPI and
host processing. FPGA power is Vivado's total on-chip post-route estimate;
`scripts/impl.tcl` does not load measured switching activity. Board regulators,
support components and host energy are outside that estimate.

TinyMPC energy uses the stored MCU latency and the plotting default
`0.087 A × 3.3 V = 0.2871 W`. This is an active-power estimate, not a direct
MPC rail measurement. Energy is `P × t`; energy-delay product is `P × t²`.
The plots compare computation-window energy under these different estimation
methods. The separate [Arty campaign](power.md) reports measured rails and
explicitly labelled corrections.

The feasibility table reserves 100 µs for FPGA communication within a 1 ms
control period. A larger feasible horizon does not imply operation at 1 kHz.
