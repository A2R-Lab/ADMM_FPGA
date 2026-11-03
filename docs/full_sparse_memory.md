# Full-sparse memory alternatives, 2026-11-03

At H40/k10, full_sparse can match staged_fused's BRAM footprint while using
67.2% fewer LUTs, 55.4% fewer registers and 46.7% fewer DSPs. The compact option
uses 26.5 BRAM tiles versus 27, at approximately 3.52 times the HLS-estimated
solve latency. This is a useful resource tradeoff when the application can
accommodate the longer solve time. Energy and EDP have not been measured.

## Routed comparison

All rows use the uninstrumented `top_spi` wrapper (`BOARD=custom`), Artix-7
`xc7a100t-csg324-1`, 100 MHz, fixed-point arithmetic, ten iterations, trajectory
disabled and horizon 40. Resources are post-route wrapper-inclusive counts.
Latency is HLS worst-case cycles divided by 100 MHz, excluding SPI transfer time;
it is not a board measurement. BRAM tiles are 36-Kbit equivalents, unlike the
18-Kbit units in HLS reports.

| Implementation | HLS cycles | Estimated ms | LUT | FF | DSP | BRAM tiles | WNS ns |
|---|---:|---:|---:|---:|---:|---:|---:|
| Original full_sparse | 148467 | 1.48467 | 9280 | 12051 | 77 | 78.5 | 0.308 |
| Shared L only | 161847 | 1.61847 | 7878 | 10139 | 82 | 70.5 | 0.269 |
| Shared L + banked transpose indices (default) | 161847 | 1.61847 | 7728 | 10165 | 82 | 37.5 | 0.877 |
| Above + compact RHS storage (optional patch) | 200907 | 2.00907 | 7628 | 9911 | 80 | 26.5 | 0.237 |
| staged_fused | 57086 | 0.57086 | 23284 | 22209 | 150 | 27 | 0.144 |

All five builds meet setup and hold constraints. The original architecture-specific
HLS settings are retained: full_sparse clock uncertainty is 2.7 ns, staged_fused
is 0 ns. The existing hierarchy settings are also retained (rebuilt for
full_sparse, none for staged_fused). Thus these compare the shipped architecture
flows under the same device, wrapper and target clock, not identical HLS directives.
The staged result is the base implementation, not the separate v6 memory campaign.

The default saves 52.2% of original full_sparse BRAM at 9.0% more cycles. The
compact option saves 66.2% at 35.3% more cycles. Simply removing the duplicate
factor was helpful but insufficient: preventing memory replication accounts for
most of the improvement. The compact point supports the comparable-memory claim;
the faster default still uses 38.9% more BRAM than staged.

## What changed

1. Generate only `L_banded` for full_sparse. Keep transpose dimension aliases for
   the public interface. A shared, non-inlined triangular-solve function reads L
   in both directions, with its allocation limited to one hardware instance.
   Backward substitution reads the corresponding lower-triangle entry at
   `row = i + bandwidth - 1 - j`, with zero padding beyond the final row.
   Both directions retain farthest-to-nearest product order. Forward substitution
   retains the intermediate `acc_t` product cast; backward substitution retains
   its wider product before accumulation. Those distinct rounding/saturation
   behaviors must not be unified.
2. Partition `AT_sparse_indexes` along its column dimension. The original H40 HLS
   mapping replicated the whole index ROM to provide parallel reads; banking
   reduces this table from 70 to 13 BRAM18K units without changing latency.
3. The optional patch binds the solver's `b_tmp` working vector to true dual-port
   BRAM. It replaces twelve replicated working-vector memories with one. This
   reduces memory ports and raises the transpose-product loop II from 1 to 7,
   explaining the extra latency. It does not change arithmetic or iteration count.

The expanded sparse operators remain explicitly stored. There is no stage-wise
operator reconstruction, Riccati solve, precision reduction or reduction
reassociation. This work removes the duplicate L transpose; it does not claim
that every transposed sparse operator is now deduplicated.

The default source retains the faster option. Apply
[`compact_rhs.patch`](../evaluation/full_sparse_memory_20261103/compact_rhs.patch)
in an isolated **full_sparse** build copy to select the memory-oriented option.
The patch is an experimental build variant, not a new architecture selector;
do not apply it to the staged comparison build.

## Validation and limits

Independent original/candidate C++ objects matched raw bits at H10 and H40:
eight forward/backward substitution cases, twelve repeated full-state ADMM
iterations, and eight repeated warm-start top-level solves. Inputs include zero,
raw fixed-point extremes, random bit patterns, nonzero q and tight/wide bounds.
The test compares complete iteration state, not only control outputs.

Both H40 finalists passed RTL co-simulation on eight baseline-generated warm-start
frames. Observed RTL latency was 161763 cycles for the default and 200823 for
compact; the table consistently uses HLS estimates for all architectures.
The generated golden vectors are retained beside `results.csv`; co-simulation
reports remain in the server experiment directory. This is C/RTL verification, not physical-board or post-route
functional verification. Trajectory-enabled behavior was not tested.

H10 synthesis provides a second size check, not routed evidence:

| full_sparse layout | HLS cycles | HLS BRAM18K |
|---|---:|---:|
| Original | 39867 | 105 |
| Shared L | 43647 | 86 |
| Shared L + index banks | 43647 | 85 |
| Compact RHS as well | 53907 | 63 |

Index banking has a much larger benefit at H40; do not extrapolate a fixed
percentage saving to every horizon. No capacity sweep, power instrumentation,
energy measurement or ASIC inference is included. A subsequent board experiment
should compare the compact point with staged if the longer solve time fits the
application; a broad horizon sweep is not yet necessary.

## Reproduction and provenance

Baseline source is commit `0f17551`. Each configuration has its own build copy in
`/home/agrillo/moailImpl/full-sparse-hls-runs`. Compact HLS/routed metrics and solver source hashes are in
[`results.csv`](../evaluation/full_sparse_memory_20261103/results.csv).
Full build/report provenance remains in the server experiment directory.
Bulky build products remain outside Git. The current ADMM.cpp matches the
banked-index run exactly; applying the compact patch reproduces the compact
run's ADMM.cpp exactly.

In a fresh isolated copy of the desired source revision (apply the optional patch
before building):

```sh
source /home/agrillo/venv/bin/activate
source /home/agrillo/amdfpga/2025.2/Vivado/settings64.sh
source /home/agrillo/amdfpga/2025.2/Vitis/settings64.sh
export ADMM_SOLVER_ARCH=full_sparse
export ADMM_HORIZON_LENGTH=40
export ADMM_ITERATIONS=10
export ADMM_ENABLE_TRAJECTORY=0
(cd scripts && python trajectory_generator.py && python header_generator.py)
make BOARD=custom vivado
```

For the staged comparison use unchanged baseline source and set
`ADMM_SOLVER_ARCH=staged_fused`. Regenerate headers explicitly after any
configuration change; Make does not track environment-only changes reliably.
`BOARD=arty` was not used: its UART wrapper has a solver input-width mismatch in
this checkout, whereas the SPI wrapper preserves the full interface.

To compare original and candidate C++ implementations and emit RTL vectors:

```sh
python scripts/check_full_sparse_shared_l.py \
  --baseline /path/to/baseline-build-copy \
  --candidate /path/to/candidate-build-copy \
  --output /tmp/shared-l-check \
  --hls-include /home/agrillo/amdfpga/2025.2/Vitis/include
```

After synthesis, in the candidate's `vitis_projects/ADMM`, copy the generated
`rtl_tb.cpp` as `shared_l_rtl_tb.cpp` and `vectors.h` as `vectors.h`. Copy
`hls_config.cfg` to `hls_shared_l_rtl.cfg`, replacing the `ADMM_test.cpp` testbench
entry with `shared_l_rtl_tb.cpp`, then run:

```sh
vitis-run --mode hls --cosim --config hls_shared_l_rtl.cfg --work_dir ADMM
```

This reuses synthesis and verifies the RTL against baseline outputs; it is not
necessary to repeat it when merely reading or packaging the existing results.

## Integration into the publication checkout

Imported from server commit `b99f78d` together with its staged_fused build-flow
dependencies. The default full_sparse source now uses shared factor storage and
banked indices; compact RHS remains an optional patch. Existing publication
`evaluation/data/benchmarks.csv` full_sparse measurements describe the original
implementation and have **not** been replaced or relabeled. Neither new variant
has measured energy, a validated maximum horizon, or flight validation yet.

The experiment radar is deliberately separate from publication figures:

```sh
~/venv/bin/python evaluation/plot_compact_full_sparse_radar.py
```

It reads only the compact results CSV and writes `evaluation/output/full_sparse_memory_radar.*`.
Its energy/EDP values are post-route estimates and must not replace board measurements.

## Preparing compact measurement campaigns

The campaign runner can apply the compact RHS binding to its immutable source
snapshot without changing the production checkout:

```sh
~/venv/bin/python scripts/power_campaign.py prepare \
  --campaign /path/to/new-campaign --compact-full-sparse --horizons 10,40
```

Omit `--horizons` to use the historical full_sparse sweep. The manifest records
the patched solver hash; H10/H40 compact builds run the same RTL-check stage as
the staged/TinyMPC pilot points. `--comparison` and `--compact-full-sparse` are
mutually exclusive. Run builds on a2r-main and copy completed bundles locally for
Arty acquisition, following `docs/arty_comparison.md`.

The build/preflight option `--threads 0` removes the campaign-imposed tool thread
cap. It does not disable memory/disk admission checks or the concurrent-job limit.
It does not guarantee a specific tool CPU utilization.

This runner is imported unchanged from the server campaign. Its preparation
check reproduces the compact solver hash used by the measured campaign. Full
integration synthesis and board regression remain separate validation steps.
