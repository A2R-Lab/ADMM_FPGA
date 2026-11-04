# Reproduce the Arty solver comparison

The comparison uses an Arty A7-100T Rev E, a 100 MHz clock and ten solver
iterations. AccelMPC provides `staged_a` (default) and `full_sparse`;
the TinyMPC FPGA baseline uses the pinned upstream generator.

## Requirements

Set up Vivado/Vitis 2025.2 and the Python environment described in
[Build and program](build.md). Follow the board power and USB/JTAG requirements
in [Power measurements](power.md#requirements). Run commands from the repository
root with that environment active.

Initialize the TinyMPC generator and install its additional dependencies:

```sh
git submodule update --init --recursive evaluation/tinympc_fpga/upstream
python -m pip install -r evaluation/tinympc_fpga/requirements.txt
```

## Build and measure

Campaign preparation records an immutable source snapshot and configuration.
Choose a new campaign directory; preparation refuses to overwrite an existing one.

```sh
campaign_dir="$PWD/results/comparison"
measurement_dir="$PWD/results/comparison-meas"

python scripts/power_campaign.py prepare --comparison --campaign "$campaign_dir"
campaign_runner="$campaign_dir/source/scripts/power_campaign.py"

python "$campaign_runner" build --campaign "$campaign_dir" --smoke --jobs 2 --threads 4
python "$campaign_runner" status --campaign "$campaign_dir"

# Replace this device with the board's UART device.
python "$campaign_runner" measure --campaign "$campaign_dir" \
  --local "$measurement_dir" --port /dev/ttyUSB0 --smoke
python "$campaign_runner" aggregate --campaign "$campaign_dir" --local "$measurement_dir"
```

For this comparison, `--smoke` selects H10 and H40 for both solvers. Omit it
from both build and measure commands to run the full horizon sweep. Adjust
`--jobs` and `--threads` for available memory and CPU capacity; `--ids` selects
individual configurations. Repeating the commands resumes completed work.
Only timing-clean, hash-verified artifacts are accepted for measurement.

To reproduce the compact full-sparse mapping, prepare a separate campaign:

```sh
python scripts/power_campaign.py prepare --compact-full-sparse \
  --horizons 10,40,100 --campaign "$PWD/results/compact"
```

Use its frozen runner for the same build, measure and aggregate steps, omitting
`--smoke` to include every requested horizon. The compact patch is applied to the
snapshot, not the checkout; see [full-sparse memory mapping](full_sparse_memory.md).

## Measurement definitions

Each point uses three repetitions, bracketing idle readings and approximately
two seconds of solves per repetition (at least 1024 solves). Fixed-point pilots
require exact output bits/checksum; TinyMPC uses a floating-point tolerance and
repeat checksums.

The workload uses a zero reference and static constraints with native solver
arithmetic/state behavior: AccelMPC retains workspace between solves; TinyMPC
initializes each solve. Outputs are checked against separate references.
Ten iterations do not imply equal solution accuracy.

Publication energy combines measured core/BRAM energy with matching auxiliary/I/O
estimates; it excludes board support circuitry, host processing and communication.
Solve latency is the on-chip start-to-completion cycle count divided by the
clock frequency; no separate handshake penalty is added. EDP is energy times
that latency. See [benchmark methodology](benchmarking.md) for the complete definitions.

## Dataset and figures

[benchmarks.csv](../evaluation/data/benchmarks.csv) is the single publication
input. It retains valid measurements and explicitly identified estimates.
Bitstreams, traces and implementation reports are generated campaign outputs.

```sh
python evaluation/plot_benchmarks.py --skip-trajectory
python evaluation/summarize_results.py --benchmarks-only
```

The improved staged measurements retain the dataset identifier `staged_fused`;
the current build option is `staged_a`. Historical `staged_a` CSV rows describe
the previous implementation. The plotting scripts distinguish these rows.
See the [evaluation guide](../evaluation/README.md) for dataset details.

## Required implementation settings

Staged synthesis uses `-flatten_hierarchy none`: preserving hierarchy avoids an
observed post-synthesis functional mismatch while retaining DSP mapping.
The precise synthesis optimization responsible has not been isolated.
Do not remove this setting based solely on passing HLS simulation.

The build also registers HLS initialization files and treats missing ROM
initialization (Synth 8-4445) as an error. HLS RTL validation and the physical
board pilot check different stages of the implementation; both are required by
the H10/H40 campaign flow.
