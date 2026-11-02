# Staged-fused / TinyMPC Arty campaign

The initial v2/v3 bitstreams failed physical-board correctness checks and are
quarantined. Passing HLS RTL simulation and routed timing did not establish
post-synthesis functional correctness. Use corrected campaigns described below.

Select `ADMM_SOLVER_ARCH=staged_fused` for the Q10.22 implementation. Existing
`staged_a` and `full_sparse` paths and the default are preserved. The fused path
uses the previously validated split_far3 mapping, sharing coefficient generation
and the solver source. It uses zero HLS clock uncertainty; actual full-design
100 MHz timing must still pass before a bitstream is accepted.

Initialize the existing TinyMPC upstream submodule before preparing a comparison:

```sh
git submodule update --init --recursive evaluation/tinympc_fpga/upstream
python scripts/power_campaign.py prepare --comparison --campaign /path/to/campaign
python /path/to/campaign/source/scripts/power_campaign.py build --campaign /path/to/campaign --jobs 3 --threads 4
```

The full comparison contains 70 points: both solvers at 35 horizons, with H40 and
H10 first, all at 100 MHz and ten iterations. Capacity/timing failures remain
explicit. Measurement uses the existing synthetic workload, zero reference,
static constraints, and native solver arithmetic/state behavior: AccelMPC retains
workspace between solves; TinyMPC initializes each solve. TinyMPC command words
are native float input deviations; AccelMPC returns absolute fixed-point commands.
They are checked against separate references, not against each other.

On the Arty host, source Vivado and activate ~/venv, then run the frozen runner:

```sh
python /path/to/campaign/source/scripts/power_campaign.py measure --campaign /path/to/campaign --local /path/to/measurements --port /dev/ttyUSB1 --watch
python /path/to/campaign/source/scripts/power_campaign.py aggregate --campaign /path/to/campaign --local /path/to/measurements
```

Use the actual Arty UART device. `--smoke` selects the four H10/H40 designs.
Only timing-clean, hash-verified ready artifacts can be programmed. Each uses
three repetitions and bracketing idle measurements. H10/H40 publication also
requires eight real-RTL transactions through the benchmark scheduler.
Float pilot outputs use numerical tolerance; repeat-run checksums must match.
Fixed-point pilots require exact output bits and checksum.

Energy is measured separately for core/BRAM and monitored 5 V rails. These are
not total FPGA power estimates. EDP is calculated per repetition as energy times
transaction latency. UART/programming time is excluded. Adapter handshake time
is included in measured transaction latency; keep HLS cycle counts separate.

The active server campaign is under
`/home/agrillo/moailImpl/arty-comparison-20261102/`, exposed through SSHFS.
All hand-written files are written through that mount; heavy tools run via SSH
with ~/venv and AMD 2025.2. Bitstreams, checkpoints, raw traces, and work directories
remain outside Git; campaign manifests bind them to the source and workload.

After aggregation, regenerate measured-only plots with:

```sh
python scripts/plot_arty_comparison.py --summary /path/to/summary.csv --output /path/to/measured-plots
```

Missing or failed points remain in provenance and are never replaced with estimates.

## Hardware failures and fixes (2026-11-02)

TinyMPC synthesis stayed in the HLS directory after creating floating-point IP.
The benchmark's repository-relative workload ROM path then failed to resolve;
Vivado warned and continued, producing zero outputs on the board. Synthesis now
restores the repository working directory, registers HLS initialization files,
and treats missing ROM initialization (Synth 8-4445) as an error. Campaign-v4
(`02d4a7cd581d4f176b9bf4a9b00519830ac4f3dc08c27cb65d4be329219f1871`)
passed the Arty pilot and three power repetitions at both H10 and H40.

AccelMPC's wrong first board output reproduced exactly in post-synthesis
simulation, including a standalone solver netlist. The same HLS RTL produced
correct results with DSP mapping disabled, or with hierarchy preserved while
retaining DSPs. Disabling BRAM mapping did not fix it; isolated multiplier tests
passed. This implicates a synthesis optimization interaction, but does not yet
identify a minimal vendor bug or a particular faulty optimization.

For staged_fused, synth.tcl now uses `-flatten_hierarchy none`; other solvers
retain `rebuilt`. Solver math, precision, HLS pipeline schedule and cycle counts
are unchanged. Preserving hierarchy can affect area, routing and power, so the
corrected physical builds must be measured. Campaign-v5
(`d5eb1b1cc0c06dd168f02b7938d719b0cacbbc2a7a8356cce87651b68b1ad005`)
contains this workaround and the ROM fix. H10 and H40 close routed timing at
100 MHz. H10 has passed its Arty pilot and all three power repetitions; H40
has passed its eight-solve Arty pilot; power repetitions are in progress. Do not use v2/v3 results as valid performance
measurements.

The eight-transaction publication test checks HLS RTL, not the synthesized
netlist. The board pilot checks fixed-point output/checksum exactly and TinyMPC
outputs with the documented float tolerance. These scopes are distinct.

Copy the immutable source snapshot, campaign.json, and ready bundles to local
storage before running the Arty tools. Do not execute acquisition from SSHFS.
Campaign and artifact hashes are checked by the local runner. Keep v4 TinyMPC
and v5 AccelMPC provenance separate when comparing their measurements.

Create `STOP_NEW_BUILDS` in a campaign to defer unstarted jobs while active builds
finish; remove it and rerun `build` to resume.

The full v5 sweep was restarted after both corrected AccelMPC board pilots
passed and the first H40 power repetition was valid. It uses three workers,
four tool threads per worker, and preserves already-published ready bundles.
