# Normalized Vivado Comparison Plan

This note captures the current decision logic for choosing the FPGA ADMM solver versions to carry forward.

## Goal

The immediate goal is not to run every historical variant through every expensive experiment. The goal is to answer:

1. Which versions actually work?
2. Which working versions are Pareto-relevant after real Vivado implementation, not only HLS estimates?
3. Which versions deserve full downstream experiments, paper figures, and possible hardware/flight validation?

## Current Working Set

Current Tier 1 evidence says:

| Version | Evidence | Current role |
| --- | --- | --- |
| `1c23f1f` flight baseline | 5 s smoke passed; HLS succeeded; full CSim timed out rather than diverged; known flight-proven version | Reliability/reference design |
| `ee338c6` memory optimization | Full generated-trajectory CSim passed with compatibility patch; HLS succeeded | Best staged-A candidate so far |
| `f2fdd4e` current fixed packing | Full generated-trajectory CSim passed; HLS succeeded | Working current baseline, likely dominated by `ee338c6` unless Vivado says otherwise |
| `78cd2c2` early staged-A | Full generated-trajectory CSim passed; HLS succeeded | Historical ablation, old 386-bit interface |
| `565281f` 1 kHz optimized | Default, 8, 10, and 12 iteration tests diverged | Failed aggressive 1 kHz attempt; paper context only unless a real numeric/architecture patch appears |

## Why HLS Alone Is Not Enough

The first HLS comparison shows a real tradeoff:

```text
1c23f1f: 187,692 cycles, 1.877 ms, BRAM 231, DSP 73,  FF 18,332, LUT 20,810
ee338c6: 136,479 cycles, 1.365 ms, BRAM 126, DSP 101, FF 36,382, LUT 52,118
```

This suggests `1c23f1f` is much lighter in general compute/fabric resources but much heavier in BRAM, while `ee338c6` saves BRAM and latency by spending more DSP/LUT/FF.

However, that is still HLS only. Final Pareto status depends on post-route timing, utilization, and power. A design that looks better in HLS can lose after Vivado due to routing, clock closure, or top-level integration.

## Trajectory Storage Caveat

The main Tier 1 rows used the same high-level trajectory:

```text
shape:       star_hold
horizon:     40
sim freq:    500 Hz
start step:  0
duration:    27.4 s
```

The archived `trajectory_refs.csv` files are byte-identical across the main full/HLS rows.

The synthesized trajectory storage is not identical, though:

```text
1c23f1f: TRAJ_Q_PACKED_COLS = 16
ee338c6: TRAJ_Q_PACKED_COLS = 3
f2fdd4e: TRAJ_Q_PACKED_COLS = 3
```

Therefore `231` versus `126` BRAM is a fair end-to-end configured-design comparison, but it is not a pure isolated measurement of only full sparse `A`/`A^T` storage versus staged-A reconstruction.

## Normalized Comparison Definition

The next comparison should have two clearly labeled views.

### View A: End-to-End Flight-Configuration Vivado

Purpose: answer which actual configured design is better for hardware.

Run Vivado synthesis and implementation with each version's intended top-level RTL and trajectory storage, but with the same board, constraints, horizon, trajectory reference, and ADMM iteration setting.

Candidates:

- `1c23f1f`
- `ee338c6` with the Vitis 2025.2 and 418-bit compatibility patch

This view is the most relevant for selecting hardware finalists, because it includes the real trajectory memory format and protocol integration cost.

### View B: Solver-Architecture Isolation

Purpose: answer whether the staged-A architecture itself is better, separate from trajectory table packing.

This requires either:

- disabling or normalizing embedded trajectory storage in both designs, or
- patching `1c23f1f` to use the same 3-column trajectory packing as `ee338c6`.

This view is useful for the paper's architectural claim. It should not replace View A for hardware selection.

## Fast Decision Strategy

The fastest useful path is:

1. Run View A first for `1c23f1f` and `ee338c6`.
2. Decide whether both are Pareto-relevant after post-route metrics.
3. Only run View B if View A leaves the BRAM story ambiguous or if the paper needs a clean isolated architectural claim.
4. Do not spend broad cluster time on `565281f`, current guard-bit sweeps, or every historical ablation before the two finalists are understood.

## Expected Pareto Outcomes

`1c23f1f` remains Pareto-relevant if it:

- closes timing at the target clock,
- uses much less LUT/FF/DSP after route,
- keeps BRAM within the board budget,
- remains the flight-proven reliability anchor.

`ee338c6` remains Pareto-relevant if it:

- closes timing at the target clock,
- preserves its BRAM and latency advantage after route,
- does not pay too much in LUT/FF/DSP or power,
- remains trajectory-correct with the compatibility patch.

Both can be Pareto-optimal at the same time: one can be the low-compute/high-BRAM design, while the other is the lower-BRAM/faster staged-A design.

## Paper Strategy

The paper can still mention the broader design space:

- `78cd2c2`: early staged-A ablation.
- `f2fdd4e`: current fixed-packing staged-A baseline.
- `565281f`: aggressive 1 kHz attempt that synthesized but failed closed-loop correctness.

The expensive implementation, hardware, and flight-style experiments should be reserved for the selected finalists unless the Vivado results reveal a new contender.

## Metrics To Collect

For each finalist Vivado run:

- commit and patch metadata,
- generated trajectory hash and trajectory storage shape,
- HLS latency/resource summary,
- post-synthesis utilization/timing/power,
- post-place utilization/timing,
- post-route utilization/timing/power/DRC,
- timing closure status at the target clock,
- whether the result is end-to-end flight configuration or solver-architecture isolation.

## Active Runs

View A end-to-end native-trajectory-storage Vivado comparison was submitted on 2026-05-15:

| Version | Config | Job | Results root |
| --- | --- | --- | --- |
| `1c23f1f` | `vivado_flight_baseline_native` | `495` | `exp/2026-05-vivado-finalists-view-a` |
| `ee338c6` | `vivado_ee338c6_native` | `496` | `exp/2026-05-vivado-finalists-view-a` |

Both jobs use `BOARD=custom`, `top_spi`, `star_hold`, horizon 40, trajectory enabled, native trajectory storage for each commit, HLS IP export, Vivado synthesis, and Vivado implementation. Bitstream generation is not requested in this first pass.

## Completed View A Results

Both jobs completed successfully:

```text
495  admm_vivado_flight_baseline_native  COMPLETED  0:0  00:03:13
496  admm_vivado_ee338c6_native          COMPLETED  0:0  00:04:09
```

Summary CSV:

```text
exp/2026-05-vivado-finalists-view-a/summary/vivado_summary.csv
```

Key post-route comparison:

| Version | CSim status | HLS latency | HLS BRAM/DSP/FF/LUT | Post-route WNS | Post-route BRAM/DSP/FF/LUT | Post-route power |
| --- | --- | --- | --- | --- | --- | --- |
| `1c23f1f` | Flight-proven; 5 s smoke passed; full CSim timed out, not diverged | 187,692 cycles, 1.877 ms | 231 / 73 / 18,332 / 20,810 | 0.199 ns | 75 / 73 / 11,461 / 9,081 | 0.291 W |
| `ee338c6` | Full generated-trajectory CSim passed with compatibility patch | 136,479 cycles, 1.365 ms | 126 / 101 / 36,382 / 52,118 | 0.149 ns | 44 / 85 / 25,189 / 22,270 | 0.663 W |

Interpretation:

- Both designs close timing on the custom `top_spi` build.
- `1c23f1f` remains Pareto-relevant: much lower LUT/FF/DSP and power, better post-route slack, and flight-proven behavior, but higher BRAM and slower solver latency.
- `ee338c6` is also Pareto-relevant: lower BRAM and faster solver latency, but higher LUT/FF/DSP and power.
- Neither finalist dominates the other after Vivado. The paper can present them as two valid hardware mappings with different bottlenecks.
- The trajectory-storage caveat still applies: this View A comparison is the correct end-to-end hardware comparison, not a pure isolated `A`/`A^T` memory measurement.
- Expensive follow-up experiments should focus on these two finalist designs unless a separate View B is needed to isolate trajectory-storage effects for a specific paper claim.

## Completed Normalized Staged-A Results

After View A, the staged-A variants `ee338c6` and `f2fdd4e` were normalized to the same interface and semantics:

- 418-bit solver input,
- one-axis dynamic constraints,
- fixed-point-safe mm-to-m conversion,
- matching generated data and trajectory hashes,
- horizon 40, `star_hold`, default ADMM iterations, custom `top_spi` Vivado flow.

The 5 s CSim/HLS rerun completed successfully for both jobs `503` and `504`.

The post-route Vivado comparison completed successfully for both jobs `505` and `506`:

| Version | Vivado status | HLS latency | HLS BRAM/DSP/FF/LUT | Post-route WNS | Post-route BRAM/DSP/FF/LUT | Post-route power |
| --- | --- | --- | --- | --- | --- | --- |
| `ee338c6` normalized | pass | 136,479 cycles | 126 / 101 / 36,387 / 52,186 | 0.193 ns | 44 / 85 / 25,190 / 22,260 | 0.666 W |
| `f2fdd4e` normalized | pass | 136,479 cycles | 126 / 101 / 36,387 / 52,186 | 0.193 ns | 44 / 85 / 25,190 / 22,260 | 0.666 W |

The normalized staged-A variants are hardware-equivalent in the measured flow. Carry forward `f2fdd4e` as the staged-A base because it is the current modern code path once the fixed-point-safe conversion is applied.

## Completed Architecture-Switch Stage 2 Results

The final single-branch comparison was run from current `f2fdd4e` with `ADMM_SOLVER_ARCH=staged_a` and `ADMM_SOLVER_ARCH=full_sparse`.

Result root:

```text
exp/2026-05-arch-switch-vivado
```

Summary CSV:

```text
/tmp/arch_switch_stage2_summary.csv
```

Both jobs completed successfully:

| Architecture | Job | CSim | Vivado | HLS latency | HLS BRAM/DSP/FF/LUT | Post-route WNS | Post-route BRAM/DSP/FF/LUT | Post-route power |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `staged_a` | `507` | pass | pass | 136,479 cycles | 126 / 101 / 36,387 / 52,186 | 0.193 ns | 44 / 85 / 25,190 / 22,260 | 0.666 W |
| `full_sparse` | `509` | pass | pass | 187,589 cycles | 240 / 87 / 19,937 / 25,898 | 0.379 ns | 87.5 / 87 / 12,282 / 9,686 | 0.327 W |

Interpretation:

- `staged_a` is the faster, lower-BRAM architecture.
- `full_sparse` is the lower-LUT, lower-FF, lower-power architecture.
- Both close timing with the modern 418-bit solver interface and matching trajectory data hashes.
- The final comparison remains Pareto-style rather than winner-take-all: `staged_a` is the latency/BRAM candidate, while `full_sparse` is the fabric/power candidate.
