# Arty comparison campaigns

The two solver architectures are `staged_a` (default) and `full_sparse`.
`staged_a` now uses the optimized Q10.22 staged implementation; there is no
separate `staged_fused` build option. Floating-point staged builds retain the
numerical-reference path, rather than the Q10.22-specific mapping.

Existing frozen campaigns and benchmark CSV rows retain their original
`staged_fused` identifiers for provenance. Run those campaigns with their
frozen runner; newly prepared campaigns use `staged_a`. Historical `staged_a`
CSV rows describe the previous implementation, not the current default.

## Prepare and build

Initialize the TinyMPC generator, then freeze a campaign outside Git:

```sh
git submodule update --init --recursive evaluation/tinympc_fpga/upstream
~/venv/bin/python scripts/power_campaign.py prepare --comparison --campaign /path/to/comparison
~/venv/bin/python scripts/power_campaign.py prepare --compact-full-sparse --horizons 10,40,100 --campaign /path/to/compact
```

Run heavy tools on the build server, with its Vivado/Vitis environment sourced:

```sh
~/venv/bin/python /path/to/comparison/source/scripts/power_campaign.py build --campaign /path/to/comparison --jobs 3 --threads 4
```

Size concurrency for peak RAM, not idle utilization. `--memory-gib` is a planning
budget, not a hard limit. `--threads 0` leaves the tool defaults unrestricted
by the runner. Use `--ids` to select specific builds and `--retry-failed`
only when a failure has been addressed. Creating `STOP_NEW_BUILDS` in a campaign
defers unstarted jobs without killing active builds; remove it and rerun to resume.

## Download and measure locally

Copy the immutable `source/` snapshot, `campaign.json` and ready bundles to
local storage before using the Arty. Do not run acquisition from SSHFS. Source the
local Vivado environment and use the actual UART device:

```sh
~/venv/bin/python /path/to/comparison/source/scripts/power_campaign.py measure --campaign /path/to/comparison --local /path/to/measurements --port /dev/ttyUSB1 --watch
~/venv/bin/python /path/to/comparison/source/scripts/power_campaign.py aggregate --campaign /path/to/comparison --local /path/to/measurements
```

Measurement resumes incrementally, preserving completed valid repetitions.
`--smoke` selects H10/H40; `--ids` restricts configurations. Only
timing-clean, hash-verified ready artifacts can be programmed. Each point uses
three repetitions, bracketing idle readings and approximately two seconds of
solves per repetition (at least 1024 solves). Fixed-point pilots require exact
output bits/checksum; TinyMPC uses its float tolerance and repeat checksums.

The workload uses a zero reference and static constraints with native solver
arithmetic/state behavior: AccelMPC retains workspace between solves; TinyMPC
initializes each solve. Outputs are checked against separate references, not
against each other. Ten iterations do not imply equal solution accuracy.

The runner measures core/BRAM and monitored 5 V rails separately. Publication
energy combines measured core/BRAM energy with matching auxiliary/I/O estimates;
it excludes board support circuitry, host processing and communication.
Transaction latency includes adapter handshaking, unlike HLS solver-only cycles.
EDP is energy times transaction latency.

## Retained results

[benchmarks.csv](../evaluation/data/benchmarks.csv) is the single publication
input. Only valid completed measurements and explicitly identified estimates
belong there. Failed, incorrect and timing-failed runs are excluded.
Bitstreams, checkpoints, traces and reports remain in external campaigns.

```sh
~/venv/bin/python evaluation/import_compact_measurements.py --campaign-root /path/to/campaign_new_full_sparse
~/venv/bin/python evaluation/plot_benchmarks.py --skip-trajectory
~/venv/bin/python evaluation/summarize_results.py --benchmarks-only
```

See [benchmark methodology](benchmarking.md) for resource scopes, estimate
markers and the legacy data retained for other analyses.

## Hardware correctness fixes

TinyMPC synthesis stayed in the HLS directory after creating floating-point IP.
The benchmark's repository-relative workload ROM path then failed to resolve;
Vivado warned and continued, producing zero outputs on the board. Synthesis now
restores the repository working directory, registers HLS initialization files,
and treats missing ROM initialization (Synth 8-4445) as an error. Corrected TinyMPC builds passed the Arty pilot and three power repetitions at both H10 and H40.

AccelMPC's wrong first board output reproduced exactly in post-synthesis
simulation, including a standalone solver netlist. The same HLS RTL produced
correct results with DSP mapping disabled, or with hierarchy preserved while
retaining DSPs. Disabling BRAM mapping did not fix it; isolated multiplier tests
passed. This implicates a synthesis optimization interaction, but does not yet
identify a minimal vendor bug or a particular faulty optimization.

For staged_a, synth.tcl now uses `-flatten_hierarchy none`; other solvers
retain `rebuilt`. Solver math, precision, HLS pipeline schedule and cycle counts
are unchanged. Preserving hierarchy can affect area, routing and power, so the
corrected physical builds must be measured. Corrected staged builds contain this workaround and the ROM fix. H10 and H40 close routed timing at
100 MHz. Both H10 and H40 have passed their eight-solve Arty pilots and all three
power repetitions. Do not use v2/v3 results as valid performance
measurements.

The eight-transaction publication test checks HLS RTL, not the synthesized
netlist. The board pilot checks fixed-point output/checksum exactly and TinyMPC
outputs with the documented float tolerance. These scopes are distinct.
