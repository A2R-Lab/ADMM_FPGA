# Architecture Normalization Plan

This note defines the next FPGA solver cleanup step after the Tier 1 and finalist Vivado comparisons.

## Goal

Choose the best staged-A implementation first, then carry forward only two final architectures in one modern repo state:

- `staged_a`: the best measured staged-A implementation.
- `full_sparse`: the old `1c23f1f` full sparse `A`/`A^T` flight-baseline architecture, forward-ported to the same modern interface.

The choice between current `f2fdd4e` and `ee338c6` must be data-driven. Do not choose current just because it already has the desired one-axis dynamic constraints or modern 418-bit interface. If `ee338c6` is better, port the desired one-axis dynamic-constraint behavior and interface to it.

## Staged-A Selection

Normalize `ee338c6` and `f2fdd4e` before deciding which staged-A code path survives.

Both normalized staged-A variants should use:

- 418-bit packed input:
  - state bits `[383:0]`
  - constraints word `[415:384]`
  - trajectory command `[417:416]`
- the same one-axis dynamic-constraint semantics,
- the same fixed-point-safe mm-to-m conversion style,
- the same generated problem data,
- the same trajectory configuration and trajectory reference hash,
- the same horizon, ADMM iteration count, board target, and Vivado flow.

Validation for both variants:

- 5 s closed-loop CSim smoke,
- full generated-trajectory CSim,
- HLS synthesis,
- Vivado synthesis and implementation.

Selection rule:

- If one normalized staged-A variant is strictly better or Pareto-superior after correctness, HLS, and post-route comparison, choose it.
- If both pass and neither dominates, choose the one with the better practical hardware tradeoff for drone validation.
- Interface convenience is not a tie-breaker. Desired interface and one-axis constraints should be ported to the winner.

Current evidence before this normalization:

| Version | Correctness | HLS latency | HLS BRAM/DSP/FF/LUT |
| --- | --- | --- | --- |
| `ee338c6` | Full generated-trajectory CSim passed in job `297`; 5 s smoke passed in job `309` | 136,479 cycles, 1.365 ms | 126 / 101 / 36,382 / 52,118 |
| `f2fdd4e` | Fixed-packing full generated-trajectory CSim passed in job `294`; 5 s smoke passed in job `308` | 136,484 cycles, 1.365 ms | 126 / 121 / 37,268 / 52,648 |

This evidence currently favors `ee338c6`, but the final choice should be made after normalizing the one-axis dynamic constraints and implementation flow.

## Stage 1 Run Notes

Normalized staged-A patches were prepared for both `ee338c6` and `f2fdd4e`:

- `experiments/patches/ee338c6_normalized_staged_a.patch`
- `experiments/patches/f2fdd4e_normalized_staged_a.patch`

The first normalized smoke/HLS submission, jobs `497` and `498`, applied both patches and completed HLS synthesis, but CSim failed at compile setup before simulation. A later diagnostic showed direct CSim Makefile invocation needed the normal Vivado/Vitis toolchain environment and `make` on the compute nodes.

Future Slurm runners now default to sourcing:

```bash
source /home/agrillo/amdfpga/2025.2/Vivado/settings64.sh
source /home/agrillo/amdfpga/2025.2/Vitis/settings64.sh
```

through `experiments/slurm/setup_xilinx_2025_2.sh` when those files exist. Future smoke/HLS and Vivado submitters default to 8 CPUs per task unless overridden by `ADMM_SLURM_CPUS_PER_TASK`.

Rerun jobs `503` and `504` were submitted under `exp/2026-05-normalized-staged-a-smoke-rerun` with explicit toolchain setup. Local logs showed both jobs past CSim compilation and executing the 5 s closed-loop simulation.

The smoke rerun completed successfully for both normalized variants:

- `normalized_ee338c6_ee338c6_503`: CSim pass, HLS pass, 418-bit input, 136,479 cycles, BRAM/DSP/FF/LUT = 126/101/36,387/52,186.
- `normalized_f2fdd4e_f2fdd4e_504`: CSim pass, HLS pass, 418-bit input, 136,479 cycles, BRAM/DSP/FF/LUT = 126/101/36,387/52,186.

Because normalized HLS is identical, the next discriminator was post-route Vivado. Jobs `505` and `506` were submitted under `exp/2026-05-normalized-staged-a-vivado-20t` with `ADMM_SLURM_CPUS_PER_TASK=20`, `VIVADO_MAX_THREADS=20`, and `ADMM_RUN_CSIM=0`.

The normalized Vivado comparison also completed successfully for both variants:

| Version | Vivado status | HLS latency | HLS BRAM/DSP/FF/LUT | Post-route WNS | Post-route BRAM/DSP/FF/LUT | Post-route power |
| --- | --- | --- | --- | --- | --- | --- |
| `ee338c6` normalized | pass | 136,479 cycles | 126 / 101 / 36,387 / 52,186 | 0.193 ns | 44 / 85 / 25,190 / 22,260 | 0.666 W |
| `f2fdd4e` normalized | pass | 136,479 cycles | 126 / 101 / 36,387 / 52,186 | 0.193 ns | 44 / 85 / 25,190 / 22,260 | 0.666 W |

The generated trajectory/data hashes also match between jobs `505` and `506`, so the normalized staged-A candidates are hardware-equivalent for the measured flow.

Stage 1 selection: carry forward current `f2fdd4e` as `staged_a`, with the measured fixed-point-safe mm-to-m conversion retained. This is not because the interface was already convenient; after normalization, the two staged-A candidates produce the same HLS and Vivado metrics, and `f2fdd4e` is the current modern code path to integrate with the architecture switch.

Vivado Slurm note: request 20 CPUs when useful, but keep memory at `59000M` rather than `60G`/`64G` so jobs can run on nodes advertised to Slurm as `60000M`.

## Single-Branch Architecture Switch

After choosing the staged-A finalist, create one modern branch with a solver architecture parameter in `scripts/parameters.py`.

Required parameter:

```text
ADMM_SOLVER_ARCH=staged_a
ADMM_SOLVER_ARCH=full_sparse
```

Expected generated config:

```c
#define ADMM_SOLVER_ARCH_STAGED_A 1
#define ADMM_SOLVER_ARCH_FULL_SPARSE 0
```

or equivalent compile-time defines that make the selected architecture unambiguous in generated metadata and HLS builds.

The public HLS/top-level interface should remain identical for both architectures:

```cpp
void ADMM_solver(
    ap_uint<418> current_in_bits,
    ap_uint<128> &command_out_bits
);
```

Both architectures must share:

- current-state packing and unpacking,
- one-axis dynamic constraints,
- trajectory start/reset command semantics,
- command output packing,
- closed-loop testbench entry points,
- SPI/top-level integration path,
- result metadata fields.

The solver-core implementation can differ behind compile-time selection:

- `staged_a` uses staged dynamics storage and staged `A`/`A^T` reconstruction.
- `full_sparse` preserves the old `1c23f1f` full sparse `A` and `A^T` solver architecture.

## Header Generation

Extend `scripts/header_generator.py` so generated data matches `ADMM_SOLVER_ARCH`.

For `staged_a`, continue emitting:

- `A_stage_row_counts`,
- `A_stage_row_cols`,
- `A_stage_row_vals`,
- `A_stage_col_counts`,
- `A_stage_col_rows`,
- `A_stage_col_vals`,
- `B_stage`.

For `full_sparse`, emit the full sparse storage needed by the old baseline architecture:

- `A_sparse_data`,
- `A_sparse_indexes`,
- `AT_sparse_data`,
- `AT_sparse_indexes`.

The generated headers must record enough constants for both C++ and RTL metadata to identify the architecture, horizon, trajectory status, and solver input width.

## Validation Plan

Stage 1: choose staged-A finalist.

- Build normalized `ee338c6`.
- Build normalized `f2fdd4e`.
- Compare CSim, HLS, post-route utilization, timing, and power.
- Select the better staged-A implementation by measured data.

Stage 2: validate the single-branch architecture switch.

- Build with `ADMM_SOLVER_ARCH=staged_a`.
- Build with `ADMM_SOLVER_ARCH=full_sparse`.
- For each architecture, run:
  - 5 s closed-loop CSim smoke,
  - full generated-trajectory CSim where practical,
  - HLS synthesis,
  - Vivado synthesis and implementation.

Stage 3: final two-candidate comparison.

- Compare only the selected `staged_a` architecture and the forward-ported `full_sparse` baseline.
- Treat these as the paper and drone candidates.
- Generate bitstreams and start drone validation only after both pass the normalized Vivado flow.

## Stage 2 Results

The single-branch architecture switch was validated from current `f2fdd4e` with:

- `experiments/patches/f2fdd4e_arch_switch_stage2.patch`
- result root `exp/2026-05-arch-switch-vivado`
- summary CSV `/tmp/arch_switch_stage2_summary.csv`
- jobs `507` (`staged_a`) and `509` (`full_sparse`)
- `ADMM_SLURM_CPUS_PER_TASK=20`, `VIVADO_MAX_THREADS=20`, `ADMM_SLURM_MEM=59000M`

Both architectures completed 5 s closed-loop CSim, HLS export, Vivado synthesis, placement, and routing with return code 0.

| Architecture | CSim | HLS latency | HLS BRAM/DSP/FF/LUT | Post-route WNS | Post-route BRAM/DSP/FF/LUT | Post-route power |
| --- | --- | --- | --- | --- | --- | --- |
| `staged_a` | pass | 136,479 cycles | 126 / 101 / 36,387 / 52,186 | 0.193 ns | 44 / 85 / 25,190 / 22,260 | 0.666 W |
| `full_sparse` | pass | 187,589 cycles | 240 / 87 / 19,937 / 25,898 | 0.379 ns | 87.5 / 87 / 12,282 / 9,686 | 0.327 W |

Stage 2 interpretation:

- The modern 418-bit interface, trajectory commands, one-axis dynamic constraints, generated metadata, and `ADMM_SOLVER_ARCH` switch work for both architectures.
- `staged_a` is faster and uses about half the post-route BRAM, but spends more LUT/FF and roughly double the power.
- `full_sparse` is slower and BRAM-heavy, but remains much smaller in LUT/FF and lower power.
- Neither architecture dominates the other; carry both into Stage 3 as the final paper/drone comparison candidates.

## Assumptions

- One-axis dynamic constraints are required for the final drone-capable implementation.
- `1c23f1f` should remain the architectural source for `full_sparse`, but its old host/protocol state should not be preserved in the final branch.
- `565281f` remains excluded unless a new architecture or numeric fix is proposed.
- Historical commits remain provenance; the final work should converge toward one modern branch with an explicit architecture parameter.
