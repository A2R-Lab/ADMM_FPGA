# Arty A7 measured-power benchmark

## Accepted implementation plan

Save this plan before implementing. Target the Arty A7-100T Rev E, USB powered.
Sequence: program, settle, idle baseline, N autonomous solves, idle baseline,
then UART download. No telemetry transmission or solver stalls during capture.

## Embedded workload

Generate an initialized BRAM ROM from a build-time CSV (up to 256 records).
Per the subsequent user instruction, provide a reproducible synthetic default,
clearly labeled in metadata, with optional replacement by recorded states.
Replay cyclically. Encode 12 state words, constraints, and trajectory command
bits using the HLS numeric configuration. Missing optional fields default to
zero. Include workload hash and length in capabilities. A changed workload
requires a new bitstream, not an HLS rebuild. Preserve solver state between
calls; reprogram for independent experiments. Support back-to-back and periodic
starts, counting deadline misses. Defaults: settle 2 s, idle 3 s, 1000 solves,
idle 3 s.

## Acquisition and build

Add BOARD=arty-power and top_uart_power to the non-project Tcl build. Instantiate
XADC directly; no GUI wizard. Use Rev E analog constraints. Calibrate in default
mode then simultaneously sequence VAUX1/9 (5 V voltage/current), VAUX2/10
(discard VAUX2; core current), internal VCCINT and temperature. Use 25 MHz ADC
clock and extended acquisition. Read 12-bit left-aligned results through DRP.
Scale external codes by 5.99/4096 V, 4/4096 A, and 2/4096 A; internal VCCINT by
3/4096 V. Average products, not products of averages. Document core voltage/current
sampling offset. Keep LEDs constant and acquisition activity consistent.

## Capture and host

Use a 2048-record BRAM trace, initially 1 ms bins. Merge adjacent bins within
phases when full, preserving weighted sums and timestamps. Flush partial bins
on phase changes. Acquisition must not backpressure the solver. Record phase,
sample count, rails, temperature, flags, solve count, busy/elapsed cycles,
latency min/max/total, final output and rolling checksum. Use versioned,
length-delimited, CRC-protected UART commands for capabilities, configuration,
start, status, and result retrieval. Watchdogs preserve incomplete captures.

Python runner programs an explicit bitstream, configures, waits, downloads,
and writes CSV, JSON and plots. Save bitstream/workload hashes and configuration.
Report both rails separately, idle drift, active energy, energy per completed
solve, and incremental energy using an interpolated idle baseline. Periodic
energy includes gaps. Do not equate core or monitored 5 V power with Vivado total
FPGA power. Instrumentation overhead and analog bandwidth limit interpretation.

## Validation

Test CSV/ROM encoding, cyclic replay, commands, XADC channel pairing/scaling,
averaging/compaction, phase transitions, watchdogs, protocol corruption and
overruns. Compare solver outputs/cycles with equivalent uninstrumented replay.
Build/route at 100 MHz and inspect timing, constraints, and resources. Hardware
acceptance: plausible rails, exactly N solves, complete traces, repeatability;
external calibration if equipment is available. Never label simulated data as
physical measurements.

## References

- https://digilent.com/reference/programmable-logic/arty-a7/reference-manual
- https://assets.testequity.com/te1/Documents/pdf/digilent/Digilent_Arty_A7_Reference_Manual.pdf
- https://raw.githubusercontent.com/Digilent/digilent-xdc/master/Arty-A7-100-Master.xdc
- https://docs.amd.com/r/en-US/ug480_7Series_XADC/Sequencer-Modes

## Implementation and validation status (2026-10-17)

### Revision: instrumentation overhead and trajectory removal

Compile trajectory support out of the power build (`ADMM_ENABLE_TRAJECTORY=0`),
retaining synthetic input ROM, 2,048 trace bins, and no external DDR3. Preserve
the previous bitstream, provenance and reports before rebuilding. Validate HLS
against C++, top-level simulation, trajectory removal, routing and DRC before
repeating two 1,000-solve hardware runs.

Extract solver, capture, ADC interface, benchmark and UART dynamic estimates,
with shared static power separate. Accept supporting logic at <=15% of total
estimated FPGA power as a practical overhead threshold. If higher, collect
simulation switching activity across idle and active operation, check annotation
coverage, and rerun power analysis. If still higher, report contributors and
possible reductions without redesigning instrumentation in this revision.
These estimates are a sanity check, not measured module power; shared-rail
hardware readings remain measurements of the instrumented design.

Implemented and tested on the user's USB-connected Arty A7-100T Rev E.
The user confirmed retaining all 2,048 trace bins after clarifying that only
on-chip BRAM is used. No external DDR3 controller or accesses were added.
Memory read enables suppress unused workload/trace reads.

The initial bitstream passes 100 MHz routed timing (+0.400 ns setup, +0.018 ns
hold) and bitstream DRC. Python and RTL tests pass, including AMD's XADC model,
real HLS output comparison to C++, and the complete benchmark top.
Three hardware experiments (two back-to-back, one 10 ms periodic) each completed
1,000 solves without acquisition errors or overruns, with identical output
checksums and 84,043-cycle solve latency. The repeated back-to-back core
incremental energies were 32.90 and 32.95 microjoules per solve.
See README.md for commands, protocol, measurement limitations and result paths.

The trajectory-free revision also passed the Python/RTL, C++/HLS and complete-top
checks. Routed timing is +0.084 ns setup and +0.014 ns hold with zero failing
endpoints; bitstream DRC has zero errors. Resource use is 25,683 LUTs, 58.5 BRAM
tiles and 82 DSPs. No trajectory-named cells remain in the routed checkpoint,
and the build manifest records `trajectory_compiled=false`.
Two new 1,000-solve hardware runs have zero faults/overruns, identical checksum
4037829182 and 84,041-cycle latency. Mean active core/BRAM power is 0.26649 W,
with 31.66 microjoules per solve above idle. Results and the matching report
comparison are in `results/power-20261017-no-trajectory-*`.

## Accepted campaign revision (2026-10-17)

Implement the campaign detailed in `POWER_CAMPAIGN.md`. The user superseded the
15% overhead target: retain instrumentation and report the explicit fixed model
`0.8 * (measured core/BRAM power + 0.032 W)`, preserving raw measurements.
VCCADC is excluded from the auxiliary allowance. Sweep all 42 timing-clean K=10
FPGA configuration pairs, including the largest designs; record capacity failures.
Freeze a source-only bundle in the mounted `a2r-main-mount` directory, corresponding
to `/home/agrillo/power_measurements` on a2r-main. Compile isolated configurations
in parallel on that server, copy verified artifacts locally, and measure the USB
Arty sequentially. Validate H20 full-sparse and staged builds and measurements
before the full sweep. Paper integration is deferred. Session persistence and
SSH-disconnection handling are the user's responsibility.

Latest user revision: skip preliminary smoke builds and remove the full-sweep
gate. Launch six builds concurrently (three threads and 16 GiB planning RAM
per worker). Collect ready bitstreams during compilation using `measure --watch`.
Per-design routed timing, provenance and numerical-pilot checks remain enabled.
