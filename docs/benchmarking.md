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

Synthesis-derived FPGA solve latency is HLS cycle count divided by 100 MHz,
subject to route timing closure. It excludes SPI and host processing.
Latency coordinates use the on-chip start-to-completion cycle count divided by
100 MHz where measured, and synthesis-derived latency otherwise.

Both post-route power estimates and [Arty measurements](power.md) are provided.
AccelMPC and TinyMPC FPGA (Wu et al.) use measured values where available;
all 29 Wu FPGA points, H5 through H1023, are measured.
The latency/energy and EDP figures use measured active
core/BRAM rail power plus the auxiliary and I/O supply estimates
from each configuration's matching post-route report. At the report's printed
precision these contributions are 32.4 mW VCCAUX and 13.2 mW VCCO33 for all 68
current measured configurations. VCCADC is excluded as it is tied to ground in the custom
PCB. FPGA EDP uses measured core/BRAM power, except for the
MOBY-DIC baseline and the asterisked staged H1800 estimate in the paper figure. The latency/energy plot
uses post-route estimates for unmeasured AccelMPC configurations, marked by an
asterisk. Each such bubble uses the matching synthesis-derived latency.

The monitored core rail includes measurement instrumentation. Vivado estimates
that this instrumentation and other non-solver dynamic power account for
approximately 30% of total power consumption in staged H40 (28.5%; 46.9% for
compact full_sparse and 25.7% for Wu FPGA at H40).
We retain this overhead in the reported measurements, giving a conservative assessment
of solver power rather than introducing uncertainty by subtracting an estimated
contribution. The added estimates use total supply current (including static current).
Regulators, external board support circuitry, host processing and SPI-transfer energy
remain outside the metric. The measurements are from the Arty, not the custom flight
deck; trajectory generation is disabled.

Measured FPGA energy uses the campaign's mean active core energy plus auxiliary/I/O power
times that configuration's measured solve latency. EDP multiplies this combined
energy by the same latency. Synthesis-derived latency is never substituted into these
energy calculations. TinyMPC MCU uses the stored MCU latency and the nominal active
power `0.087 A × 3.3 V = 0.2871 W`. TinyMPC keeps the MCU active within FreeRTOS without
voluntarily yielding or blocking during the solve, occupying time during which it
would otherwise be idle. We attribute the active MCU energy consumed throughout
this directly measured execution interval to MPC. Energy
consumed during the rest of the autopilot cycle is excluded. For both platforms,
`E = P × t` and `EDP = E × t` exclude communication.

The measurement instrumentation increases
FPGA resource usage and can make timing closure more difficult, limiting the
horizons supported by the instrumented build relative to the solver alone.
The bubble plot uses asterisked estimates for unmeasured AccelMPC configurations.
The feasibility table separately reserves 100 µs for FPGA communication within
a 1 ms period. A larger supported horizon does not imply operation at 1 kHz.

Regenerate the figures from the consolidated `evaluation/data/benchmarks.csv`:

```bash
python evaluation/paper_figures.py
python evaluation/plot_benchmarks.py --skip-trajectory
python evaluation/summarize_results.py --benchmarks-only
```

`evaluation/data/benchmarks.csv` stores measured core/BRAM energy in
`raw_core_energy_uj` and the missing supply estimates in `estimated_aux_io_w`.
The estimates were taken from the matching post-route supply reports using
voltage times total current. The combined energy is already stored in the CSV;
no separate preprocessing step is needed. MCU points use nominal power and
have no asterisk.

The architecture radar uses measured solve latency and measured core/BRAM energy
plus estimated auxiliary/I/O energy, on the same basis as the EDP comparison.
BRAM and LUT utilization use uninstrumented solver builds in the
consolidated CSV's `solver_*` fields. Maximum demonstrated horizons are H400 for
full_sparse and H1800 for staged, not proven capacity limits. The “Logic” axis is LUT utilization
as a percentage of the device's LUT capacity. At H40 this is 36.7% for staged and
12.0% for full_sparse and 36.5% for Wu FPGA. Missing measured latency, energy or resource fields
causes radar generation to fail rather than silently use power estimates.

The paper radar labels show actual values; radial positions normalize costs to
the worst of the three designs, with the same radial offset for every axis.
The 1 kHz horizon axis uses the inverse largest integer horizon estimated from
a linear latency fit to meet the 0.9 ms solve budget: H64 for staged, H17 for
full_sparse and H46 for Wu FPGA. Fits use measured points through H400; the
sweep displays a subset of horizons for readability. These fitted limits are not separate hardware
measurements. PNG previews are tracked; PDF exports remain in ignored
`evaluation/output/paper_figures/` for copying into the paper repository.
`plot_benchmarks.py` also regenerates the earlier layouts and manuscript numbers.
