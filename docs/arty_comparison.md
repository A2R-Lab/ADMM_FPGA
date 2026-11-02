# Staged-fused / TinyMPC Arty campaign

This is an implementation checkpoint. The integrated staged_fused kernel passes
an eight-solve H10 bit-exact host comparison against staged_a. Power host tests
pass. Instrumented synthesis, routed timing, RTL adapter validation, and physical
measurements are pending; no new board-performance claim is made here.

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

The initial live build uses `campaign-v2` with source manifest
`bfb7a13aabc5e8d854b422a4e78acae59025b88771a21c767edf01c34015e78a`.
Its runner is immutable; later code fixes require a new campaign.

After aggregation, regenerate measured-only plots with:

```sh
python scripts/plot_arty_comparison.py --summary /path/to/summary.csv --output /path/to/measured-plots
```

Missing or failed points remain in provenance and are never replaced with estimates.
