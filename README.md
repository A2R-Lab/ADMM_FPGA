# ADMM_FPGA

This repository contains the FPGA implementation of an ADMM (Alternating Direction Method of Multipliers) solver developed for real-time linear Model Predictive Control (MPC) on the Crazyflie quadrotor platform.

The project targets an AMD Xilinx Artix-7 100T FPGA and includes the HLS solver, the FPGA integration files, and support scripts used to build and program the design.

## Project Information

This work was developed within the master's thesis:

*Hardware-Algorithm Co-Design for Real-Time Linear Model Predictive Control. FPGA Implementation and Deployment on a Resource-Constrained Quadrotor*

Author: Andrea Grillo  
Period: 2025-2026

## Design Flow

The development flow for this project is managed through the provided Makefiles:

1. Python scripts generate the matrices and headers used by the solver.
2. The ADMM solver is synthesized with Vitis HLS.
3. The generated IP is integrated in the full FPGA design and built in Vivado.
4. An Arduino-based SPI test can be used for standalone communication checks.
5. The final deployment target is the Crazyflie platform, using the companion firmware available here: [crazyflie_fpga_firmware](https://github.com/A2R-Lab/crazyflie_fpga_firmware).

## Repository Contents

- `vitis_projects/ADMM/`: Vitis HLS project containing the ADMM solver implementation and testbench
- `vivado_project/`: Vivado project with the top-level FPGA design, SPI/UART modules, constraints, and generated IP
- `scripts/`: build, programming, simulation, and data/header generation scripts
- `paper_figures/`: paper figure scripts and committed input data in `data/`; generated figures in `output/` are ignored
- `arduino_spi_test/`: simple Arduino sketch used for SPI communication tests
- `Makefile`: top-level build flow for HLS, Vivado, bitstream generation, and programming

## Related Repositories

- FPGA deck hardware repository: [Crazyflie_FPGA_Deck](https://github.com/A2R-Lab/Crazyflie_FPGA_Deck)
- Crazyflie firmware repository: [crazyflie_fpga_firmware](https://github.com/A2R-Lab/crazyflie_fpga_firmware)

## Arty A7 measured power

The `arty-power` build embeds a reproducible synthetic state sequence and measures
both the FPGA core rail and the board's monitored 5 V supply using the onboard
XADC. It targets the **Arty A7-100T Rev E**. The accepted design is recorded in
[POWER_MEASUREMENT_PLAN.md](POWER_MEASUREMENT_PLAN.md).

```bash
source /media/andrea/48a1bd03-3653-4c55-8d37-cd7d804e2212/amdfpga/2025.2/Vivado/settings64.sh
source /media/andrea/48a1bd03-3653-4c55-8d37-cd7d804e2212/amdfpga/2025.2/Vitis/settings64.sh
source ~/venv/bin/activate
make BOARD=arty-power
python scripts/power_benchmark.py --port /dev/ttyUSB1 --solves 1000
```

The runner programs `build/top_uart_power.bit`, waits for XADC calibration, and
checks the bitstream hash and embedded workload against `build/top_uart_power.json`.
This sidecar freezes the workload, solver constants, and generated-source hashes
at build time; keep it with the bitstream when copying to another machine. It then
runs **2 s settling → 3 s idle → N solves → 3 s idle**, downloads the trace, and
writes `trace.csv`, `metadata.json`, and `power.png` under `results/power-*`.
External DDR3 is unused; no DDR controller is instantiated. Workload ROM reads
are enabled only when fetching a new input; trace BRAM reads are enabled only
for compaction or downloading. UART is silent during settling and acquisition. The FPGA sends a completion
notification only after the capture buffer has drained. Download time is outside
the measured interval. LED states are held constant.

For controller-rate operation, add `--period-ms 10`. Omit it for back-to-back
solves. Other options include `--settle-s`, `--idle-before-s`, `--idle-after-s`,
`--watchdog-s`, `--output`, and `--no-plot`. The per-solve watchdog defaults to
10 s; the complete experiment has a 600 s watchdog. Idle windows are limited to
30 s each. Deadline overruns count scheduled slots missed while the solver was
busy; solves never overlap. Program again for each independent experiment:
HLS persistent arrays are not necessarily cleared by the pushbutton reset.
`--already-programmed` is intended for a freshly programmed board only.

### Workload

The default file is `experiments/power/synthetic_states.csv`: 256 synthetic,
bounded state vectors, with zero constraints and trajectory commands. It is a
bring-up/benchmark workload, **not recorded flight data**. The metadata labels
it synthetic. Fixed iteration counts do not imply input-independent power:
different values change digital switching activity.

To embed another workload:

```bash
make BOARD=arty-power POWER_WORKLOAD=/absolute/path/to/states.csv
```

The CSV must contain 1–256 rows and these columns, in solver units (positions in
metres, angles in radians, linear/angular velocities in metres/s and radians/s):

```text
x,y,z,roll,pitch,yaw,vx,vy,vz,wx,wy,wz
```

Optional `constraints` and `traj_cmd` columns are integer values (decimal or
`0x` hexadecimal), defaulting to zero. Constraints use the solver's existing
packed signed 16-bit millimetre bounds. `traj_cmd` is 0–3 and is replayed exactly,
including when the workload wraps. Bit 0 starts the internal trajectory; bit 1
resets its index. The ROM encodes the current fixed Q10.22 or IEEE float32 build
format, and preserves HLS warm-start state between calls. Extra CSV columns are
ignored. Inputs are not uploaded at runtime. A changed CSV rebuilds the FPGA
integration/bitstream, not the solver HLS IP.

### Measurement interpretation

XADC calibration runs in default mode before switching to simultaneous sampling.
The ADC clock is 25 MHz, with extended external-input acquisition. Each sequence
includes VAUX1/9 (5 V voltage/current simultaneously), VAUX2/10 (core current on
10; channel 2 discarded), internal VCCINT voltage, and temperature. Results are
read through the DRP after EOS. The 5 V power average is the mean of simultaneous
voltage–current products. Core power pairs core current with core voltage from
the same sequence; these are separated by a few microseconds, not simultaneous.
Timestamps mark collection on the 100 MHz FPGA clock, including DRP readout
latency. Sampling is continuous; conversion-to-phase-boundary alignment has
sequence-scale uncertainty. The data is intended for batch averages, not
instantaneous per-solve transients.

Trace storage has 2,048 records: 512 for idle-before, 1,024 for active, and 512
for idle-after. Each phase begins with 1 ms bins. When its allocation fills,
adjacent bins are merged and the future bin width doubles. Integer sums and
sample counts are preserved, so partial bins and unequal sample counts remain
correctly weighted. This yields a complete but progressively coarser trace;
a long experiment does not retain 1 ms resolution everywhere. The host computes
energy from each bin's mean power and actual duration. Empty bins, ADC saturation,
FIFO errors, timeouts, and incomplete solve counts invalidate the summary.

The reports distinguish:

- Core-rail power (the board's core/BRAM supply current times internal VCCINT).
- Monitored 5 V supply power, including downstream board loads and conversion losses.
- Active-phase energy per solve, including scheduled gaps in periodic mode.
- Incremental energy per solve, subtracting an idle baseline linearly interpolated
  between the two idle-window averages. Negative increments are retained.

Both idle windows, temperature change, and missed deadlines are reported. XADC,
logging, and replay logic consume power; baseline subtraction removes some fixed
overhead, not all measurement influence. The nominal board scaling is used
without an external current calibration. These quantities are not identical to
Vivado's total FPGA power estimate. Check plausible rail readings and repeatability
on the physical board before treating results as validated measurements.

### Protocol and validation

The dedicated benchmark UART protocol uses 921600 baud, 8N1. Frames are
`A5 5A | version:u8=1 | opcode:u8 | length:u16 | payload | crc:u16`, little-endian.
CRC is CRC16-CCITT (polynomial `0x1021`, initial `0xffff`, no reflection/xorout),
over version through payload. Maximum request payload is 32 bytes. Responses
use `opcode | 0x80`; four-byte command status is zero for success, one for reject.
Corrupt/oversized/incomplete requests are discarded; incomplete frames expire
in 100 ms. The legacy solve protocol belongs to `BOARD=arty`, not this build.

| Opcode | Request | Response |
|---|---|---|
| 1 | Empty | Clock Hz, workload count, float flag, record size (four uint32), then workload SHA256 as a little-endian 256-bit integer |
| 2 | Six uint32: solves, period, settling, idle-before, idle-after, solve-watchdog; times in clock cycles | Status |
| 3 | Empty | Status; acknowledged before settling starts; one experiment per programming |
| 4 | Empty | 104-byte status decoded by `decode_status()` in the runner |
| 5 | Physical trace index:uint32 | One 64-byte record; valid ranges begin at 0, 512, 1536 |
| 0x86 | Unsolicited after capture | Four-byte experiment error mask |

Experiment error bits: 0 solver timeout, 1 acquisition fault, 2 capture overflow,
3 overall timeout, 4 missing solver output at completion. Status includes phase
record counts, completed solves, overruns, output checksum/final output, timing
statistics, and latest ADC values. Record bit offsets are documented in
`power_capture.sv` and decoded in the runner; raw record bytes are retained as
hex in the CSV. Record flag bit 0 indicates saturation, bit 1 an empty source bin.
Only query/download after completion: no UART polling during measurement.

With the tool environment above, run:

```bash
bash scripts/test_power.sh
bash scripts/test_power_hls.sh
```

The first runs Python tests and RTL tests for capture compaction, scheduling,
UART framing, and AMD's actual XADC simulation model. The second compares five
warm-started real HLS RTL solves bit-for-bit with C++ reference outputs. Test
workloads live in a separate generated directory and do not replace the build's
embedded workload. Simulation verifies logic; real rail accuracy and energy
results still require the physical board.

### Hardware validation — 2026-10-17

Validated on the connected Arty A7-100T Rev E (Digilent serial `210319BE047B`),
USB powered, with the default synthetic workload, horizon 27 and 9 ADMM
iterations. External DDR3 was unused. Routing met 100 MHz timing (setup slack
+0.400 ns, hold slack +0.018 ns); bitstream DRC had no errors. Resource use was
25,725 LUTs, 62.5 BRAM tiles, and 82 DSPs, including the solver and instrumentation.

| Run (1,000 solves each) | Core idle / active W | 5 V idle / active W | Incremental core µJ/solve | Incremental 5 V µJ/solve |
|---|---|---|---|---|
| Back-to-back, first | 0.22584 / 0.26471 | 1.05494 / 1.09539 | 32.90 | 34.93 |
| Back-to-back, repeat | 0.22670 / 0.26559 | 1.05608 / 1.09621 | 32.95 | 34.60 |
| 10 ms period | 0.22677 / 0.23010 | 1.05545 / 1.05741 | 36.63 | 32.11 |

Idle values in this table are the initial baseline; incremental energy uses both
baselines. All three runs reported zero acquisition faults and zero overruns,
84,043 cycles per solve (0.84043 ms), and output checksum `4037829182`.
The first active window contained 181,129 ADC snapshots, retained in 841 bins.
The lower duty-cycle run has a much smaller mean power increment, so baseline
drift has a larger relative effect on its incremental-energy estimate. Values
use nominal onboard scaling and have not been externally calibrated.

Raw traces, provenance JSON, and plots are in:

- `results/power-20261017-first/`
- `results/power-20261017-repeat/`
- `results/power-20261017-periodic/`

These generated result directories are git-ignored; archive them separately if
needed. Python tests, capture/scheduler/UART/XADC RTL tests, five-solve C++/RTL
comparison, and full top-level integration simulation also passed.

### Comparison with Vivado and paper data

The two back-to-back runs above average **0.26515 W** on the monitored
core/BRAM supply (range 0.26471–0.26559 W). The matching routed build estimates
VCCINT at 0.355 W and VCCBRAM at 0.009 W: **0.364 W combined**. The measurement
is **27.16% below that estimate**. Vivado marks this report low confidence and
has no simulation activity file; its generic thermal settings also differ from
the physical board. The repeat range is not a calibrated accuracy bound.

| Source | Configuration | Power W | Absolute energy µJ/solve |
|---|---|---:|---:|
| Hardware, core + BRAM | staged_a H27, K9 | 0.26515 | 222.84 |
| Hardware, monitored 5 V | staged_a H27, K9 | 1.09580 | 920.95 |
| Current Vivado, total on-chip | staged_a H27, K9 | 0.447 | 375.67 |
| Paper Vivado, total on-chip | staged_a H20, K10 | 0.671 | 468.87 |
| Paper Vivado, total on-chip | staged_a H30, K10 | 0.690 | 710.54 |

Current Vivado energy here uses the measured 840.43 µs solve latency. Hardware
energy integrates the entire back-to-back active window, including the one-cycle
inter-solve gap. Paper entries use their original reported latency and energy.
The paper rows are selected with the same `best_rows(..., 10)` function used by
`paper_figures/plot_benchmarks.py`; no H27 row exists in the paper input.

These power boundaries differ: core/BRAM excludes other FPGA supplies, while
the monitored 5 V includes board loads and conversion losses. Both measurements
include the running instrumentation. Neither directly measures total FPGA power.
The core idle-subtracted result is 32.93 µJ/solve, a separate metric that must
not replace the paper's absolute energy. The paper also estimates TinyMPC power
at 87 mA × 3.3 V = 0.2871 W rather than measuring it. Consequently these runs do
not validate or revise the paper's FPGA/MCU energy-saving ratio. That requires
matching configurations and workloads and a consistent power boundary.

Reproduce the comparison and export every selected paper row:

```bash
source ~/venv/bin/activate
python scripts/compare_power.py \
  results/power-20261017-first/metadata.json \
  results/power-20261017-repeat/metadata.json \
  --output results/power-20261017-comparison
```

The generated `comparison.json` records input hashes, measurements, estimates,
and limitations; `paper_selected.csv` preserves the paper selections. Use a
Vivado report from the measured build (`--report`); the default report is
`build/reports/post_route_power.rpt` and will change on a subsequent build.
The existing paper inputs and figures are unchanged.

### Trajectory-free power build and overhead estimation

`make BOARD=arty-power` now forces `ADMM_ENABLE_TRAJECTORY=0` and regenerates
trajectory-enabled headers before HLS reuse. The input-state ROM remains; it
feeds the solver and is separate from the disabled reference trajectory. The
bitstream manifest records `trajectory_compiled` explicitly. No external DDR3
is used and the 2,048-bin logger is retained.

The initial measurements and comparisons above describe the earlier build.
Its bitstream, manifest and reports are archived in
`results/power-20261017-before-no-trajectory/`.

To refine vectorless overhead estimates after building and running the tests:

```bash
# Source the Vivado/Vitis environments and ~/venv first.
bash scripts/test_power_hls.sh
bash scripts/profile_power.sh
python scripts/summarize_power_overhead.py \
  build/reports/post_route_power.rpt \
  build/power/activity_reports/idle_before_power.rpt \
  build/power/activity_reports/active_power.rpt \
  build/power/activity_reports/idle_after_power.rpt \
  --output results/power-no-trajectory-overhead.json
```

The profile records separate RTL SAIF files for 2 ms idle, five back-to-back
synthetic solves, and 2 ms idle after solving, excluding startup and UART
readout. The actual XADC simulation model receives representative voltages with
deterministic +/-2 ADC-code variation. This is a simulated stimulus, not a
measured analog waveform. The short profile does not exercise trace compaction.
Each SAIF is applied independently to the matching routed checkpoint; annotation
and switching reports accompany each power report. RTL activity does not capture
all gate glitches or map every optimized net, so these remain approximate
estimates. Check annotation coverage and memory enables before interpreting them.

The overhead summary separates capture plus ADC-interface dynamic power from
all supporting logic (also benchmark and UART). Shared static and unassigned
top-level power are not attributed to the solver or instrumentation. The 15%
threshold is a practical criterion for deciding whether to investigate further,
not a metrology guarantee. Hardware measurements remain instrumented rail power.

### Remote measured-power campaign

See [POWER_CAMPAIGN.md](POWER_CAMPAIGN.md) for the 42-point full-sparse/staged
campaign, isolated parallel builds on `a2r-main`, local Arty measurement commands,
and the agreed `0.8 × (core/BRAM power + 32 mW)` correction. Raw readings remain
available separately. The local SSHFS destination is `a2r-main-mount`; paper
integration is deferred. Previous findings and measurement limits are recorded
in [POWER_MEASUREMENT_HANDOFF.md](POWER_MEASUREMENT_HANDOFF.md).
