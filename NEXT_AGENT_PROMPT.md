# Next Agent Prompt

We are continuing work on an FPGA ADMM solver project for Crazyflie onboard linear MPC.

Start from the upper-level mounted directory, not only from inside `ADMM_FPGA/`:

```text
/home/andrea/projects/fpga/
  ADMM_FPGA/
  worktrees/
  exp/
  SLURM_ADMIN_PLAN.md
```

Cluster-side paths mirror this under:

```text
/home/agrillo/fpga/
  ADMM_FPGA/
  worktrees/
  exp/
```

## First Read

Read this file first and follow it as the next-phase source of truth:

```text
ADMM_FPGA/ARCHITECTURE_NORMALIZATION_PLAN.md
```

The current direction is:

1. Normalize and compare `ee338c6` against current `f2fdd4e`.
2. Choose the better staged-A implementation by measured data, not by interface convenience.
3. If `ee338c6` wins, port the desired one-axis dynamic constraints and modern 418-bit interface to it.
4. Then converge to one modern branch with `scripts/parameters.py` selecting:
   - `ADMM_SOLVER_ARCH=staged_a`
   - `ADMM_SOLVER_ARCH=full_sparse`
5. Forward-port the old flight-proven `1c23f1f` full sparse `A`/`A^T` architecture into the same modern interface as `full_sparse`.

Use these as supporting context only:

```text
ADMM_FPGA/EVALUATION_PLAN.md
ADMM_FPGA/NORMALIZED_VIVADO_COMPARISON.md
```

`EVALUATION_PLAN.md` contains historical Tier 1 results and candidate evidence. `NORMALIZED_VIVADO_COMPARISON.md` contains the completed Vivado comparison showing `1c23f1f` and `ee338c6` are both Pareto-relevant in the end-to-end native-trajectory view.

## Current Interface Target

The modern solver interface is a 418-bit packed input:

```text
state bits:        [383:0]
constraints word:  [415:384]
trajectory cmd:    [417:416]
```

Keep this interface for normalized staged-A and future `full_sparse`.

## Key Existing Evidence

- `ee338c6` works with compatibility patching:
  - full generated-trajectory CSim + HLS passed in job `297`;
  - 5 s smoke passed in job `309`;
  - HLS: 136,479 cycles, BRAM 126, DSP 101, FF 36,382, LUT 52,118.
- Current `f2fdd4e` works after fixed packing:
  - full generated-trajectory CSim + HLS passed in job `294`;
  - 5 s smoke passed in job `308`;
  - HLS: 136,484 cycles, BRAM 126, DSP 121, FF 37,268, LUT 52,648.
- `1c23f1f` is the flight-proven full-sparse reference:
  - 5 s smoke passed in job `299`;
  - HLS passed in job `286`;
  - full Tier 1 CSim timed out, not diverged.
- Stale current job `290` is invalid because it used old 386-bit testbench packing.
- `565281f` remains a failed 1 kHz candidate; do not chase it by only increasing ADMM iterations.

## Operating Rules

- Use `ssh a2r-main` only for Slurm commands/status/submission.
- Do not inspect logs through SSH; logs and results are mounted locally under `exp/`.
- Do not stop running jobs unless explicitly asked.
- Do not delete untracked project files.
- Keep `SLURM_ADMIN_PLAN.md` separate from FPGA evaluation notes unless Slurm status directly affects benchmark execution.
- Prefer 5 s CSim smoke jobs for broad sweeps. Reserve full generated-trajectory CSim for finalists or specific pass/fail questions.

## Important Files To Preserve

```text
ADMM_FPGA/ARCHITECTURE_NORMALIZATION_PLAN.md
ADMM_FPGA/EVALUATION_PLAN.md
ADMM_FPGA/NORMALIZED_VIVADO_COMPARISON.md
ADMM_FPGA/RESEARCH_HISTORY.md
ADMM_FPGA/TinyFPGATrajopt__ICRA___FOR_2026_.pdf
ADMM_FPGA/NEXT_AGENT_PROMPT.md
SLURM_ADMIN_PLAN.md
```
