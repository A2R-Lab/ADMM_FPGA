# Reproduce the measured-power campaign

This workflow builds and measures the 42 timing-clean FPGA architecture/horizon
pairs selected from `evaluation/data/benchmark_summary.csv`: 10 full-sparse and
32 staged configurations, each with 10 ADMM iterations. It uses the source revision
in this checkout, fixed-point arithmetic, a 100 MHz FPGA clock, and the committed
256-state synthetic workload. Trajectory generation inside the solver is disabled;
external DDR3 is unused.

These experiments measure power on an **Arty A7-100T Rev E** using its onboard
supply monitors. They measure active core/BRAM supply power; the auxiliary/I/O
contributions used in the paper figures come from matching Vivado supply reports.
The campaign runner does not modify `evaluation/`; the paper analysis imports its
validated results as described in [benchmark methodology](benchmarking.md).

## Requirements

- An Arty A7-100T Rev E configured for USB power, with a USB connection for JTAG
  programming and UART. Connect only the board to be measured to the programming
  host; the programming helper selects the first available JTAG target/device.
- Linux and AMD Vivado/Vitis **2025.2**, with Artix-7 support and JTAG cable drivers.
  Builds use `vivado`, `v++`, `vitis-run`, GNU Make, and a C++14-capable `g++`.
  The measurement host needs Vivado and access to the board's serial device.
- Python **3.11**. The reference dependency versions are recorded in
  `scripts/requirements.txt`. Install the system compiler, Python
  development headers, and SuiteSparse/CHOLMOD development libraries before
  installing scikit-sparse.

From the repository root, set up the build environment, substituting your tool
installation paths:

```bash
source /path/to/Vivado/settings64.sh
source /path/to/Vitis/settings64.sh
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install -r scripts/requirements.txt
```

A separate measurement-only host needs `pyserial==3.5` and the Vivado environment;
Matplotlib is optional for individual trace plots. No external power sensor or
additional FPGA wiring is required by this design.

## Run the campaign

The commands below use a single machine. Keep this shell's environment active.
Choose a new campaign directory: `prepare` refuses to overwrite an existing one.

```bash
campaign_dir="$PWD/results/power-reproduction"
measurement_dir="$PWD/results/power-measurements"

python scripts/power_campaign.py prepare --campaign "$campaign_dir"
campaign_runner="$campaign_dir/source/scripts/power_campaign.py"

python "$campaign_runner" build --campaign "$campaign_dir"
python "$campaign_runner" status --campaign "$campaign_dir"

# Replace the serial device with the Arty UART on your machine.
python "$campaign_runner" measure --campaign "$campaign_dir" \
  --local "$measurement_dir" --port /dev/ttyUSB0
python "$campaign_runner" aggregate --campaign "$campaign_dir" \
  --local "$measurement_dir"
```

`prepare` freezes the source files, workload, configuration selection, and hashes.
Run the frozen campaign runner as above. Changing the design or workload requires
a new campaign; editing the frozen source causes integrity checks to fail.

`build` checks tool versions and available resources before starting. By default,
each worker is budgeted 8 threads, 32 GiB RAM, and 40 GiB scratch space, with 4 CPUs,
16 GiB RAM, and 40 GiB disk reserved for the host. Concurrency is chosen automatically
and capped at 8 workers. Use `--jobs`, `--threads`, `--memory-gib`, and `--scratch-gib`
to adapt these planning budgets to your machine; they are not enforced limits.
Completed and failed build attempts are retained, so total storage grows across the
campaign. Only artifacts that pass timing and provenance checks are measured;
larger instrumented configurations may exceed device capacity.

For a first hardware check, add `--smoke` to both `build` and `measure` to select
H20 for both architectures. Omit it to continue with the complete campaign.
`--ids full_sparse_h20_k10,staged_a_h20_k10` selects explicit configurations instead.
Re-running `build` reuses verified artifacts; add `--retry-failed` to retry failed
builds. A timing failure gets one retry with the alternative routing directive.

To build on another machine, copy the prepared campaign directory there and invoke
its frozen runner with that machine's tool/Python environment. Transfer the completed
campaign directory back to the measurement host, preserving `source/`,
`campaign.json`, `state/`, and `ready/`. A shared filesystem also works; add `--watch`
to `measure` to collect newly finished artifacts while builds continue. The runner
does not manage remote sessions or file transfers.

## Measurement and acceptance

For each design, the runner first programs the FPGA and checks an eight-solve pilot
against a C++ reference checksum and final output. It then performs three independent
repetitions, reprogramming before each:

1. Settle for 5 seconds.
2. Measure idle power for 3 seconds.
3. Run back-to-back solves for approximately 2 seconds, rounded up to a multiple of
   256 and at least 1,024 solves.
4. Measure idle power for another 3 seconds, then download the trace.

UART is quiet during acquisition. Programming is volatile; SPI flash is not written.
Complete sample coverage, zero fault flags/overruns, constant solve latency, and
consistent numerical outputs are required. Invalid captures are retained and retried
once. A serial/JTAG connection error stops collection so the connection can be fixed.
Re-running `measure` resumes validated captures; always pass the same `--local`
directory to `measure` and `aggregate`.

## Results and interpretation

`aggregate` prints the output directory and writes `summary.csv`
under `<measurement_dir>/summaries/<campaign-id>/`. Each row includes architecture,
horizon, status, resource use, artifact hashes, valid repetition count, and the
mean/sample standard deviation/minimum/maximum of the measured quantities.

| Summary field prefix | Meaning |
|---|---|
| `raw_core_w` | Active core/BRAM rail power, in watts |
| `raw_core_energy_uj` | Active core/BRAM energy per completed solve, in microjoules |
| `incremental_core_energy_uj` | Energy per solve after subtracting the interpolated idle baseline |
| `five_w` | Active monitored 5 V supply power, in watts |
| `latency_us` | Solver latency, in microseconds |
| `temperature_drift_c` | Change between the two idle-window temperatures |

Look for `status=measured` and `valid_repetitions=3`. A finished command does not imply
all configurations passed. Pending, build-failed, and incomplete measurements remain
explicit rows; consult the corresponding logs to diagnose them.

Raw `trace.csv`, `metadata.json`, pilot results, and acquisition logs are retained
under `<measurement_dir>/measurements/<campaign-id>/<configuration-id>/`. Build
reports and bitstream manifests are in `<campaign_dir>/ready/<configuration-id>/`;
failed build logs are retained under `<campaign_dir>/work/`. Archive both directories
with the exported summaries: generated results are not committed to Git.

The October 2026 campaign summary is committed as
[`evaluation/data/arty_power_measurements.csv`](../evaluation/data/arty_power_measurements.csv).
It contains core/BRAM measurements for all planned configurations, with failed-build rows
retained.

Core/BRAM and monitored 5 V power have different boundaries. The 5 V reading includes
other board loads and conversion losses. Both include the measurement instrumentation.
Core voltage and current are sampled at slightly different times; traces are intended
for batch averages. The 2,048-record trace buffer progressively merges bins while
preserving sums and durations, so longer runs have coarser time resolution. Scaling
uses nominal board values without external calibration. Repetition spread measures
repeatability, not absolute measurement accuracy.

## Code and validation

Only `scripts/power_campaign.py` is needed as a user-facing campaign command.
The implementation has three helpers called automatically:

| Helper | Why it is needed |
|---|---|
| `scripts/power_benchmark.py` | Programs one design, acquires UART traces, and calculates rail statistics |
| `scripts/power_workload.py` | Converts the committed workload into the FPGA's initialized ROM |
| `scripts/power_build_manifest.py` | Binds the bitstream to its workload and solver configuration with hashes |

To check the host code without FPGA hardware:

```bash
python -m unittest discover -s tests -v
```

For RTL development, load the Vivado/Vitis environment and build the matching power
configuration before running the simulation checks. These are separate from physical
measurement validation:

```bash
make BOARD=arty-power
bash tests/test_power.sh
bash tests/test_power_hls.sh
```

The first script tests capture, scheduling, UART, and the XADC simulation model.
The second compares real HLS RTL outputs against C++ and exercises the complete top.

## Paper energy figures

Both post-route estimates and measurements are available; the benchmark estimates
are more conservative at the measured configurations. Measured points use active
core/BRAM power plus matching estimated auxiliary/I/O supply power, excluding 
VCCADC as on the custom board VCCADC is tied to ground. The latency/energy plot
uses asterisked post-route estimates where instrumented builds failed. See the
[definitions and regeneration procedure](benchmarking.md#energy-and-timing-definitions).
