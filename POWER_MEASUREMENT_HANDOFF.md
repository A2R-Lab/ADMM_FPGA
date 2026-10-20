# Arty power measurement findings and handoff

## Objective and current decisions

Replace FPGA benchmark power estimates with measurements for full-sparse and
staged solvers. Compile on a2r-main, program the local USB-connected Arty A7-100T
Rev E, and collect UART-controlled idle/solve/idle experiments. Paper integration
is deferred. The server's existing dirty repository must remain untouched.
The SSHFS mount `a2r-main-mount` maps to
`agrillo@a2r-main:/home/agrillo/power_measurements`.

The user decided the campaign correction is:

- Corrected power = 0.8 × (measured core/BRAM power + 0.032 W).
- Corrected energy/solve = 0.8 × (integrated core/BRAM energy + 0.032 W × active-window duration) / completed solves.
- Exclude the estimated 38 mW VCCADC contribution, based on the intended custom-board power arrangement.
- Keep raw readings and label corrections as measurement-based estimates.
- The 32 mW and 20% are fixed assumptions, not measured corrections per design.
- Keep 2,048 trace bins and embedded synthetic inputs. No external DDR3 accesses.
- Skip designs that cannot fit or meet timing; no instrumentation redesign now.

## Implemented measurement architecture

`BOARD=arty-power` selects `top_uart_power`. XADC is instantiated directly,
without requiring a Vivado wizard. UART is 921600 baud, 8N1, framed with CRC16.
The host configures the experiment, starts it, remains silent during acquisition,
and downloads records after FPGA completion. Programming uses volatile JTAG,
not flash programming. The board serial used was 210319BE047B; UART was ttyUSB1.

The ADC calibrates in its default mode, then samples simultaneous pairs 1/9 and
2/10 plus internal VCCINT and temperature. A sequence is approximately 464
100 MHz clocks, or 215,517 snapshots/s. Initial sequences are discarded.
Nominal conversion factors are Vcore=3c/4096, Icore=2c/4096,
V5=5.99c/4096, I5=4c/4096. No external calibration has been performed.

The trace contains per-bin timestamps, durations, sample counts, voltage/current
sums, sums of instantaneous voltage-current products, temperature and flags.
The FPGA accumulates sums; host software performs averaging and energy analysis.
The 2,048 × 512-bit on-chip buffer is split into 512 idle-before, 1,024 active,
and 512 idle-after records. Starting at 1 ms bins, phase-local compaction merges
adjacent bins and doubles their duration when necessary. A small queue prevents
capture from stalling the solver. Workload and trace reads have enables.

The workload is 256 plausible synthetic states embedded as 418-bit ROM records:
12 Q10.22 state words, constraints, and trajectory command bits. It is not flight
telemetry. Fixed latency does not imply input-independent switching power.
Warm solver state is retained between solves. Back-to-back and fixed-period
schedules are supported, with watchdog, overrun and capture-error reporting.
A run is single-use until reprogramming.

## Power boundaries

The monitored core supply covers FPGA VCCINT and VCCBRAM. It includes static and
dynamic power for solver logic, BRAM, clocking and instrumentation on these rails.
It does not isolate solver power. Other FPGA supplies include VCCAUX, VCCO and
VCCADC. The current model estimates about 32 mW auxiliary and 38 mW ADC power;
I/O estimates depend on supplied activity and report rounding.

The monitored 5 V supply also feeds board circuits and regulators. DDR3L remains
physically powered despite being unused; Ethernet, clocks, flash, interface and
analog circuits and LEDs also consume power. Their low-power/reset states have
not been comprehensively audited. Supply-conversion losses are included. This
reading must not be called FPGA-chip power, nor assumed identical to all USB
input consumption without checking the full supply paths.

Idle subtraction removes much constant board/instrumentation consumption, but
also measures changes in controller/workload activity and regulator losses.
Absolute energy and idle-subtracted energy are different metrics.

## Initial hardware validation: trajectory support compiled in

Configuration: staged_a, horizon 27, nine ADMM iterations, 100 MHz, fixed point.
Trajectory commands were zero, so trajectory playback never started, but support
was compiled in. Bitstream SHA256:
`1b536faa7665faa53e61c856b8d1e2824158b8951242e7c11efa2d1eaa2b7769`.

Three runs of 1,000 solves completed with flags=0, overruns=0,
checksum=4037829182, and constant latency=84,043 cycles (840.43 us).

| Run | Core active W | 5 V active W | Core incremental uJ/solve | 5 V incremental uJ/solve |
|---|---:|---:|---:|---:|
| Back-to-back first | 0.264710 | 1.095389 | 32.903 | 34.926 |
| Back-to-back repeat | 0.265587 | 1.096212 | 32.951 | 34.599 |
| 10 ms period | 0.230100 | 1.057412 | 36.627 | 32.115 |

Back-to-back means: core absolute energy 222.841 uJ/solve; monitored 5 V absolute
energy 920.955 uJ/solve. Settling was 2 s, idle windows 3 s each. The periodic
active interval includes gaps; its small power increment is more sensitive to
baseline drift. The first active window had 181,129 ADC snapshots in 841 bins.

Original routed timing: setup +0.400 ns, hold +0.018 ns, no failing endpoints.
Resources: 25,725 LUTs, 62.5 BRAM tiles, 82 DSPs. Bitstream DRC had zero errors.
Results: `results/power-20261017-first`, `-repeat`, `-periodic`.
Original bitstream/manifest/reports are archived under
`results/power-20261017-before-no-trajectory`.

## Trajectory-free revision and hardware validation

The power Make target now forces ADMM_ENABLE_TRAJECTORY=0 and regenerates
trajectory-enabled headers before reusing HLS artifacts. The manifest explicitly
records trajectory_compiled=false and excludes unused trajectory source hashes.
Trajectory-named logic is absent from generated HLS RTL and the routed netlist.
Embedded synthetic state inputs remain.

Resources: 25,683 LUTs, 58.5 BRAM tiles, 82 DSPs. Removing trajectory support saved
four BRAM tiles. Timing: setup +0.084 ns, hold +0.014 ns; no failing endpoints.
Bitstream DRC had zero errors. The same output checksum was obtained in both new
1,000-solve runs, with zero faults/overruns and latency 84,041 cycles (840.41 us).

| Run | Core active W | 5 V active W | Core incremental uJ/solve | 5 V incremental uJ/solve |
|---|---:|---:|---:|---:|
| First | 0.266327 | 1.093272 | 31.620 | 33.233 |
| Repeat | 0.266658 | 1.096797 | 31.702 | 33.240 |

Means: core active 0.266492 W, absolute 223.965 uJ/solve, incremental
31.661 uJ/solve; 5 V active 1.095034 W, absolute 920.289 uJ/solve, incremental
33.236 uJ/solve. These results do not establish a reduction in absolute power
from trajectory removal: baseline and operating conditions also varied.
Results: `results/power-20261017-no-trajectory-first`, `-repeat`, `-comparison`.
The comparison directory archives the matching bitstream, manifest, routed
power/resource/timing reports, comparison JSON and hardware validation JSON.

## Validation already completed

- Python workload encoding, range checks, CRC, scaling and energy calculations.
- RTL capture compaction, weighted sums, phase boundaries and complete coverage.
- Scheduler, UART framing and AMD UNISIM XADC model tests.
- Five warm-started real HLS solves compared bit-for-bit with C++.
- Complete top-level real HLS/XADC simulation, quiet UART and trace readout.
- Real board experiments described above, with nominal analog scaling.

Scripts: `scripts/test_power.sh` and `scripts/test_power_hls.sh`.
Functional tests do not establish absolute sensor accuracy or per-module power.

## Vivado comparisons and instrumentation findings

Initial vectorless report: total FPGA 447 mW; VCCINT+VCCBRAM 364 mW.
Initial measured core mean 265.15 mW was 27.16% below that supply-matched estimate.
Trajectory-free vectorless report: total 445 mW; core+BRAM 361 mW. Its measured
mean 266.49 mW was 26.18% below the supply-matched estimate. These comparisons
must not compare 5 V board power directly with FPGA-only estimates.

| Estimate | Capture mW | ADC interface mW | Benchmark mW | UART mW | All support mW | Total FPGA mW | Support fraction |
|---|---:|---:|---:|---:|---:|---:|---:|
| Original vectorless | 118 | 3 | 13 | 5 | 139 | 447 | 31.1% |
| Trajectory-free vectorless | 111 | 3 | 14 | 5 | 133 | 445 | 29.9% |
| Active RTL-SAIF | 93 | 3 | 11 | 6 | 113 | 447 | 25.3% |
| Active SAIF with checked read enable | 67 | 3 | 11 | 6 | 87 | 421 | 20.7% |

Hierarchical entries are dynamic estimates. Shared static and unassigned top-level
power are not attributed to modules. The final refined model estimates solver
hierarchical dynamic power at 242 mW; this is not directly measured solver power.
Capture+ADC interface alone is 70/421=16.6%; all supporting logic is 20.7%.

The profile uses five real HLS synthetic solves between 2 ms idle windows,
excluding startup/UART readout. The actual ADC model receives representative
voltages with deterministic +/-2-code variation; this is not a recorded analog
waveform. It does not exercise buffer compaction. Direct SAIF matching was 4%
before solving, 17% during solving, 16% afterward. Vivado reports medium overall
confidence, but substantial propagated/default activity remains.

A concrete modeling error was found: the routed capture RAM read-enable net
`capture/ram_q0` was assigned 50% probability, although the profile makes no
trace reads. `scripts/check_power_saif.py` proves read_enable and state bits 1/2
remain zero for the complete profile, excluding compaction states 2..6. The
report script validates all 29 physical ENBWREN pins share that net, then maps
its activity to zero. This changes analysis only, not the FPGA implementation.
The corrected report reduces modeled trace-BRAM power from 82 to 56 mW.
The other memory port has enable probability one in the model and its physical
enable traces to reset-related logic; it is a candidate for a later enable audit.

Final refinement completed successfully at 2026-10-17 09:59:38 local time:
`build/power/activity_reports/active_read_checked_power.rpt`.
Its log also warns about excessive inferred reset assertion. This warning and
unknown inactive RAM outputs require caution: 20.7% is a rough estimate, not
an accurate measured decomposition or a proven bound for other configurations.

Scripts: profile_power.sh, power_activity.tcl, power_activity_report.tcl,
check_power_saif.py, summarize_power_overhead.py. Raw SAIF files are roughly
166–169 MB each under build/power; annotation files are also large. Reports and
read-enable proof JSON are under build/power/activity_reports. Some earlier
summary JSON files contain the uncorrected 25.3% estimate; consult the final
read-checked report for 20.7%. No further hardware change followed that analysis.

## Existing paper data and campaign implications

The historical paper uses estimated total FPGA power and ten iterations; the
bring-up measurements used H27/K9 and have no exact paper match. Nearby staged
points: H20/K10 estimates 0.671 W and 468.875 uJ/solve; H30/K10 estimates 0.690 W
and 710.541 uJ/solve. TinyMPC power is itself estimated at 87 mA × 3.3 V = 0.2871 W.
These measurements do not establish an updated FPGA/MCU energy-saving ratio.

There are 42 previously timing-clean FPGA architecture/horizon pairs, including
hidden plotting points: 32 staged and 10 full-sparse. Historical CSV rows also
include failures and implementation retries across different commits. Largest
staged designs used 130 of 135 BRAM tiles before adding the current logger;
instrumented versions may not fit. Record such failures without labeling them
solver-only scalability limits. Paper data and figures are not to be edited now.

## Planned follow-up: campaign implementation

Prepare an immutable source/configuration bundle in the mounted server directory,
with isolated per-point build directories and bounded parallelism. Do not copy
stale generated HLS/Vivado products into workers. Run full-sparse and staged
smoke builds before the entire 42-point campaign. Freeze numerical parameters,
K10, fixed point, 100 MHz, trajectory disabled, and the synthetic workload.

For each build publish hashes, bitstream, configuration, timing/resources,
reports and an eight-solve C++ reference. Reject timing failures. Measure one
local board at a time: eight-solve pilot, then three fresh-programming repetitions,
five seconds settling, 3 s idle before/after, at least 1,024 solves rounded to
whole 256-record cycles and approximately 2 s active time. Check numerical
reference, flags, counts, repeat checksums, time coverage and provenance. Retry
failed acquisition once and retain both attempts. Export CSV/JSON summaries with
raw readings and the user-decided correction. No paper integration and no runner
SSH-detachment/session-management logic; the user handles disconnection.

## Tool environment and preservation

Local setup:

```bash
source /media/andrea/48a1bd03-3653-4c55-8d37-cd7d804e2212/amdfpga/2025.2/Vivado/settings64.sh
source /media/andrea/48a1bd03-3653-4c55-8d37-cd7d804e2212/amdfpga/2025.2/Vitis/settings64.sh
source ~/venv/bin/activate
```

Generated build/results folders are git-ignored. Archive them separately; source
changes were not committed during the session. Board was left programmed with
the trajectory-free build after its final completed run. Hardware access and
Vivado simulator local IPC required execution outside the filesystem sandbox.

References: Digilent Arty A7 reference manual (power supplies and monitoring),
Arty A7 E.2 schematic, and AMD UG480 XADC documentation. The manufacturer's
manual was also available from the TestEquity PDF mirror cited in the README.

## Campaign measurements and UART recovery (2026-10-17, evening)

Campaign `5de81c77ed43099e278dc36bd4333d7be9fb1324d31a6e790e8c44cc2bb76fca`
is in `a2r-main-mount/arty-power-20261017-six`. The user changed the server runner
to disable resource-limit rejection and its runner-source hash rejection. Local
acquisition accepts this authorized controller change and records server/local
runner hashes under `results/power-campaign/provenance/<campaign-id>/runner.json`.
Other FPGA/acquisition sources and downloaded artifact hashes remain checked.
The server source was not overwritten.

Initial completed measurements (three valid repetitions each, K=10):

| Architecture | H | Core/BRAM mW | Corrected mW | Corrected µJ/solve | Latency µs |
|---|---:|---:|---:|---:|---:|
| full_sparse | 10 | 212.4018 | 195.5215 | 77.7882 | 397.84 |
| full_sparse | 20 | 220.4205 | 201.9364 | 153.4414 | 759.84 |

Correction is the agreed `0.8 * (core/BRAM + 32 mW)` model. H10 uses 5,120 solves
per repetition; H20 uses 2,816. Both eight-solve numerical pilots matched C++.
These corrected values remain model-adjusted measurements, not directly measured
solver-only power. The historical paper H10 row estimated 267 mW at 398.67 µs;
current source and instrumentation differ from that historical build.

After H20's first repetition, opening `/dev/ttyUSB1` returned OS error 5 (I/O
error), although JTAG programming still succeeded. A separate serial-open test
also failed; kernel logs were unavailable to the user account. The queue was
stopped during copying H30, before programming it. No cause beyond the UART/USB
failure was established. The user physically disconnected and reconnected the
board; serial open then succeeded, and H20 repetitions two and three passed.
The failed attempts are retained under H20's
`serial-failure-20261017-220943` directory. The valid pilot and first repetition
were retained and resumed. Subsequent acquisition uses the stable USB serial ID
`usb-Digilent_Digilent_USB_Device_210319BE047B-if01-port0`.

The next queue contains full_sparse H30/H40/H50/H60 and staged_a H20. Its live
log is `results/power-campaign/current-measurements.log`. A started queue is not
evidence of completed measurements: consult each `complete.json` and the latest
summary. Raw captures live under `results/power-campaign/measurements/<campaign-id>`.

### Recurring UART failure and recovery test

The subsequent full_sparse H30/H40/H50/H60 pilot attempts failed while opening
the serial port with OS error 5, before data acquisition. These were transport
failures, not demonstrated numerical or FPGA-design failures. The queue was
stopped; H10/H20's completed data remain valid. The prior physical reconnect
provided only temporary recovery.

Kernel logs read with sudo showed Arty USB resets at the fault times (including
22:07:11 and 22:15:36), along with resets of the webcam on the same USB bus.
The Arty device `/sys/bus/usb/devices/1-2` had `power/control=auto`, a 2,000 ms
autosuspend delay, and runtime state `suspended`. Setting that device's control
to `on` made it active but did not clear the stale UART error. Unbinding and
rebinding only FTDI interface `1-2:1.1` restored serial opening. The UART then
became ttyUSB0; the stable by-id path still identifies interface 1 correctly.
No persistent system-wide USB policy was changed. This device-specific setting
may need repeating after a physical reconnect. Autosuspend is a suspected
contributor, not yet a conclusively isolated root cause.

The local campaign runner now stops the entire queue on a serial exception or
actual missing-JTAG-target error, preserving the failing attempt and writing
`results/power-campaign/connection_failure.json`. Echoed Tcl error statements
are not mistaken for failures. Fifteen host tests pass, including a regression
that asserts one transport failure cannot trigger a retry or another design.
H30's failed attempts were archived under `serial-failure-20261017-222155`;
a fresh pilot and first repetition passed after the driver recovery. Full
three-repetition acceptance and the remaining configurations require checking
subsequent `complete.json` records; this entry is not a claim they finished.

## Historical estimate audit (2026-10-18)

See `results/power-comparison-20261018/estimate-audit/EXPLANATION.md`. All 15
matched staged configurations have identical historical/current generated data
and runtime-header hashes, including trajectory disabled in both. Therefore
trajectory removal does not explain their lower current Vivado estimates.
H20 total estimate falls 671 to 445 mW, driven by solver dynamic estimate falling
559 to 203 mW despite similar solver resources. Current logs all warn about
excessive inferred reset activity. Changed wrapper/control activity propagation
is strongly implicated; its quantitative contribution is not isolated without
a controlled activity-annotated power rerun. Do not interpret this as proven
hardware power improvement. The comparison report was corrected accordingly.
