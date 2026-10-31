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
All latency coordinates in the bubble plot, the feasibility table and
resource/scalability results use these synthesized implementations. They are separate from the Arty measurement campaign.

Both post-route power estimates and [Arty measurements](power.md) are provided.
At all 24 configurations with measurements, the post-route benchmark estimates
are higher than the measurement-based values, giving a more conservative power
comparison. The latency/energy and EDP figures use measured active
core/BRAM rail power plus the auxiliary and I/O supply estimates
from each configuration's matching post-route report. At the report's printed
precision these contributions are 32.4 mW VCCAUX and 13.2 mW VCCO33 for all 24
measured configurations. VCCADC is excluded as it is tied to ground in the custom 
PCB. The EDP comparison requires measured core/BRAM power. The latency/energy plot
uses post-route estimates for configurations without measurements, marked by an
asterisk. Each such bubble uses the matching synthesis-derived latency.

The monitored core rail includes measurement instrumentation. Vivado estimates
that this instrumentation accounts for approximately 30% of total power consumption. 
We retain this overhead in the reported measurements, giving a conservative assessment
of solver power rather than introducing uncertainty by subtracting an estimated
contribution. The added estimates use total supply current (including static current).
Regulators, external board support circuitry, host processing and SPI-transfer energy
remain outside the metric. The measurements are from the Arty, not the custom flight
deck; trajectory generation is disabled.

FPGA energy uses the campaign's mean active core energy plus auxiliary/I/O power
times that configuration's measured solve latency. EDP multiplies this combined
energy by the same latency. Synthesis-derived latency is never substituted into these
energy calculations. TinyMPC uses the stored MCU latency and the nominal active
power `0.087 A × 3.3 V = 0.2871 W`. TinyMPC keeps the MCU active within FreeRTOS without
voluntarily yielding or blocking during the solve, occupying time during which it
would otherwise be idle. We attribute the active MCU energy consumed throughout
this directly measured execution interval to MPC. Energy
consumed during the rest of the autopilot cycle is excluded. For both platforms,
`E = P × t` and `EDP = E × t` exclude communication.

The 18 unmeasured campaign configurations have failed instrumented builds;
none are awaiting measurement in this dataset. Staged H250 and
full-sparse H90 failed routed timing; the other failures occurred during HLS,
implementation or capacity checks. The measurement instrumentation increases
FPGA resource usage and can make timing closure more difficult, limiting the
horizons supported by the instrumented build relative to the solver alone.
The bubble plot uses asterisked estimates for unmeasured configurations. The 
feasibility table separately reserves 100 µs for FPGA communication within 
a 1 ms period. A larger supported horizon does not imply operation at 1 kHz.

Regenerate the figures from the bundled CSVs:

```bash
python evaluation/plot_benchmarks.py
python evaluation/summarize_results.py --benchmarks-only
```

`evaluation/data/arty_power_measurements.csv` stores measured core/BRAM values
and the missing supply estimates in `estimated_aux_w` and `estimated_io_w`.
The estimates were taken from the matching post-route supply reports using
voltage times total current. Failed configurations keep these fields empty.
The existing plotter adds these contributions when calculating energy and EDP;
no separate preprocessing step or combined CSV is needed.

The architecture radar uses measured solve latency and measured core/BRAM energy
plus estimated auxiliary/I/O energy, on the same basis as the EDP comparison.
BRAM and LUT utilization and maximum demonstrated horizons come from the
implementation results in `benchmark_summary.csv`. The “Logic” axis is LUT utilization
as a percentage of the device's LUT capacity. At H40 this is 34.9% for staged and
14.6% for full_sparse. Missing measured latency or energy causes radar generation
to fail rather than silently use power estimates.
