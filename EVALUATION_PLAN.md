# ADMM FPGA Evaluation Plan

This document freezes the plan for evaluating the different ADMM FPGA solver versions and turning the results into a coherent RAL extension story.

The project has reached the point where more feature work should pause. The immediate goal is to make the existing versions comparable, identify the reliable flight baseline, quantify the value or cost of the A matrix memory optimization, and decide which codesign story is supported by data.

## Current Situation

The solver has several historical versions with different architectural and numerical choices:

- Full stored sparse `A` and `A^T` matrices versus staged reconstruction from per-stage dynamics.
- Unscaled versus scaled ADMM dual updates.
- Different accumulator guard-bit choices.
- Different trajectory interfaces and host protocols.
- 500 Hz flight-proven builds versus attempted 1 kHz optimized builds.
- UART-era host/test infrastructure versus newer SPI/drone protocol.

The current solver expects a 418-bit packed input. The main working tree has been patched so the current testbenches pack the full 418-bit interface. The first Slurm Tier 1 `current` job was launched before that patch and is invalid for solver conclusions, but a fixed-packing rerun has since completed successfully.

### Status Snapshot: 2026-05-15

Completed in the main working tree:

- Created Tier 1 experiment scaffold:
  - `experiments/versions.yaml`
  - `experiments/slurm/run_one_config.sh`
  - `experiments/slurm/submit_sweep.sh`
  - `experiments/slurm/collect_results.py`
- Added finalist Vivado comparison scaffold:
  - `experiments/slurm/run_vivado_config.sh`
  - `experiments/slurm/submit_vivado_finalists.sh`
  - `experiments/slurm/collect_vivado_results.py`
- Added `ARCHITECTURE_NORMALIZATION_PLAN.md` as the next-phase plan for choosing the staged-A finalist and converging to one modern branch with a solver-architecture parameter.
- Revised the sweep default so future Tier 1 submissions run a short closed-loop smoke:
  - default `ADMM_CSIM_DURATION_S=5`
  - default `ADMM_CSIM_TIMEOUT_S=1800`
  - use `ADMM_CSIM_DURATION_S=default` only for full generated-trajectory validation.
- Default cluster-side paths now work without manual exports:
  - worktrees: `<repo-parent>/worktrees`
  - results: `<repo-parent>/exp/2026-05-tier1-smoke`
  - build scratch: `<repo-parent>/exp/build/2026-05-tier1-smoke`
  - Python venv: `/home/agrillo/venv` if present.
- Patched current testbench packing in the main working tree:
  - added `pack_current_state_bits()` in `vitis_projects/ADMM/data_types.h`
  - updated `ADMM_closed_loop_tb.cpp`
  - updated `ADMM_test.cpp`
  - updated `ADMM_uart_smoke_tb.cpp`
  - dynamic constraints are explicitly zeroed in the testbenches unless intentionally set.
- Verified locally with `rg` and `git diff --check` that the current ADMM testbenches no longer use `ap_uint<386>` or `range(385, 384)`.
- Added experiment compatibility patches under `experiments/patches/`:
  - `current_418bit_testbench_packing.patch`
  - `ee338c6_vitis2025_apfixed_div.patch`
  - `ee338c6_vitis2025_and_418bit.patch`
- The combined `ee338c6` patch now fixes all three required issues for Vitis 2025.2 testing:
  - `ap_fixed / float` overload ambiguity in dynamic-constraint scaling.
  - stale 386-bit testbench packing.
  - stale `ADMM.h` declaration of `ADMM_solver(ap_uint<386>, ...)`.

Tier 1 was launched on Slurm from the pre-patch commits/worktrees. Current observed run directory:

```text
/home/agrillo/fpga/exp/2026-05-tier1-smoke
```

Current Tier 1 status:

| Candidate | Job | Status | CSim result | HLS synthesis |
| --- | --- | --- | --- | --- |
| Flight baseline `1c23f1f` | `286` | Failed by timeout | Reached late closed-loop CSim before 7200 s timeout; no divergence conclusion | Succeeded |
| Flight baseline long rerun `1c23f1f` | `298` | Canceled by user decision | CSim-only rerun was stopped because full 13700-step CSim is too slow for Tier 1 | Not requested |
| Flight baseline smoke rerun `1c23f1f` | `299` | Completed | 5 s CSim passed, `EARLY_STOP step=-1 reason=completed` | Not requested |
| Early staged-A `78cd2c2` | `287` | Completed | `EARLY_STOP step=-1 reason=completed` | Succeeded |
| Early staged-A smoke rerun `78cd2c2` | `300` | Completed | 5 s CSim passed, `EARLY_STOP step=-1 reason=completed` | Not requested |
| A memory optimization `ee338c6` | `288` | Failed setup | Vitis 2025.2 compile failure before meaningful CSim | Compile failure |
| A memory optimization compatibility rerun `ee338c6` | `297` | Completed | Full generated-trajectory CSim passed, `EARLY_STOP step=-1 reason=completed` | Succeeded |
| A memory optimization smoke rerun `ee338c6` | `309` | Completed | 5 s CSim passed, `EARLY_STOP step=-1 reason=completed` | Not requested |
| 1 kHz optimized `565281f` | `289` | Failed numerically | `EARLY_STOP step=1221 reason=attitude_or_rate_diverged` | Succeeded |
| 1 kHz optimized smoke rerun `565281f` | `307` | Failed numerically | 5 s CSim failed, `EARLY_STOP step=1221 reason=attitude_or_rate_diverged` | Not requested |
| 1 kHz optimized iter-8 probe `565281f` | `310` | Failed numerically | 5 s CSim failed, `EARLY_STOP step=1179 reason=attitude_or_rate_diverged` | Succeeded |
| 1 kHz optimized iter-10 probe `565281f` | `311` | Failed numerically | 5 s CSim failed, `EARLY_STOP step=1153 reason=attitude_or_rate_diverged` | Succeeded |
| 1 kHz optimized iter-12 probe `565281f` | `301` | Failed numerically | 5 s CSim failed, `EARLY_STOP step=1135 reason=attitude_or_rate_diverged` | Succeeded |
| Current stale `f2fdd4e` | `290` | Failed, invalid | `EARLY_STOP step=1153 reason=attitude_or_rate_diverged`; worktree used old 386-bit packing | Succeeded |
| Current fixed-packing rerun `f2fdd4e` | `294` | Completed | `EARLY_STOP step=-1 reason=completed` | Succeeded |
| Current fixed-packing smoke rerun `f2fdd4e` | `308` | Completed | 5 s CSim passed, `EARLY_STOP step=-1 reason=completed` | Not requested |

Fast decision view:

| Version | Works? | Best current role | HLS latency | Key resources |
| --- | --- | --- | --- | --- |
| `ee338c6` A memory optimization | Yes: full generated-trajectory CSim plus HLS in job `297`; 5 s smoke in job `309` | Best current staged-A FPGA candidate | 136,479 cycles, 1.365 ms | BRAM 126, DSP 101, FF 36,382, LUT 52,118 |
| `f2fdd4e` current fixed packing | Yes: full generated-trajectory CSim plus HLS in job `294`; 5 s smoke in job `308` | Working current baseline, but slightly worse than `ee338c6` on HLS resources | 136,484 cycles, 1.365 ms | BRAM 126, DSP 121, FF 37,268, LUT 52,648 |
| `78cd2c2` early staged-A | Yes: full generated-trajectory CSim plus HLS in job `287`; 5 s smoke in job `300` | Historical staged-A ablation; not the clean production pick because it uses the old 386-bit interface | 136,077 cycles, 1.361 ms | BRAM 126, DSP 99, FF 36,297, LUT 49,238 |
| `1c23f1f` flight baseline | Flight-proven and 5 s smoke-passing; full Tier 1 CSim job `286` timed out rather than diverged | Safest known flight reference, not the fastest/largest-memory winner | 187,692 cycles, 1.877 ms | BRAM 231, DSP 73, FF 18,332, LUT 20,810 |
| `565281f` 1 kHz optimized | No: default, 8, 10, and 12 iteration runs all diverged | Failing 1 kHz architecture candidate; keep only as an ablation unless a real numeric/architecture patch appears | 106,724 cycles at 6 iterations, but invalid because CSim fails | BRAM 112, DSP 190, FF 57,676, LUT 63,317 |

Current practical answer: if only one working staged-A version should move forward quickly, use `ee338c6` with the Vitis 2025.2 and 418-bit compatibility patch. Keep `1c23f1f` as the flight-proven reliability reference. Do not spend time on guard-bit sweeps for `ee338c6` or `f2fdd4e` based on the existing data; both pass the relevant closed-loop tests. Do not spend time increasing only the ADMM iteration count for `565281f`; that experiment has already failed.

BRAM comparison caveat: jobs `286`, `287`, `294`, and `297` used the same high-level trajectory configuration (`star_hold`, horizon 40, 500 Hz, start step 0, duration 27.4 s), and their archived `trajectory_refs.csv` files are byte-identical. However, the synthesized trajectory storage layout is not byte-identical across historical commits. For example, `1c23f1f` archives `TRAJ_Q_PACKED_COLS=16`, while `ee338c6`/`f2fdd4e` use `TRAJ_Q_PACKED_COLS=3`. Therefore the `231` versus `126` BRAM comparison is a fair end-to-end configured-design comparison, but not a pure isolated measurement of only full sparse `A`/`A^T` storage versus staged-A reconstruction.

Important interpretation:

- The fixed `current` result is now meaningful and passes Tier 1 closed-loop CSim with HLS synthesis. The original `current` failure was caused by the stale 386-bit testbench packing, not by solver behavior.
- The `early_staged_a` result passes Tier 1 and is a valid comparison point, even though it uses the historical 386-bit interface.
- The `565281f` result is a valid Tier 1 smoke failure for that commit: it synthesized, but closed-loop CSim diverged at step 1221. Its HLS latency is the fastest observed so far, but it is not yet a correctness candidate.
- Iteration-count probes for `565281f` show that 8, 10, and 12 iterations still fail the 5 s smoke, and the failure happens earlier as iterations increase. This argues against "only too few ADMM iterations" as the root cause.
- The original `ee338c6` failures were setup/toolchain compatibility failures, not numerical results. Jobs `309` and `297` prove the compatibility-patched `ee338c6` passes both the 5 s smoke and the full generated-trajectory CSim, with HLS synthesis also succeeding.
- The original flight baseline job is also not a solver failure. It timed out near the end of closed-loop CSim. Job `298` was canceled because full 13700-step CSim is too expensive for the default tier; job `299` is the short 5 s baseline smoke replacement.
- Intermediate jobs `291`, `292`, `295`, `296`, canceled `298`, and canceled oversized submissions `302`-`306` should be treated as setup/debug runs, not candidate benchmark rows.

Relevant current files:

- `vitis_projects/ADMM/ADMM.cpp`: current solver, staged dynamics, guard-bit setting, 418-bit unpacking.
- `vitis_projects/ADMM/data_types.h`: shared current testbench packer `pack_current_state_bits()` using 418-bit layout.
- `vitis_projects/ADMM/ADMM_closed_loop_tb.cpp`: patched to use 418-bit packing in the main working tree.
- `vitis_projects/ADMM/ADMM_test.cpp`: patched to use 418-bit packing in the main working tree.
- `vitis_projects/ADMM/ADMM_uart_smoke_tb.cpp`: patched to use 418-bit packing in the main working tree, though UART remains legacy relative to SPI hardware.
- `vivado_project/vivado_project.srcs/sources_1/new/top_spi.v`: current SPI path using the widened input.
- `vivado_project/vivado_project.srcs/sources_1/new/top_uart.v`: old UART path, not currently aligned with the 418-bit solver interface.
- `vitis_projects/ADMM/solver_numerics_notes.md`: previous accumulator guard-bit experiments.
- `RESEARCH_HISTORY.md`: existing research narrative and notes.
- `TinyFPGATrajopt__ICRA___FOR_2026_.pdf`: current paper draft to extend.
- `NORMALIZED_VIVADO_COMPARISON.md`: focused finalist/Pareto comparison rationale and active Vivado job tracking.
- `ARCHITECTURE_NORMALIZATION_PLAN.md`: next-phase plan for first choosing between normalized `ee338c6` and `f2fdd4e`, then carrying forward only selected staged-A and full-sparse architectures in one modern branch.

## Version Inventory

These commits should be treated as named experimental candidates.

| Name | Commit | Role | Notes |
| --- | --- | --- | --- |
| Flight baseline | `1c23f1fb276b193294ac106037873362d5740f6e` | Known working star trajectory version | Full stored sparse `A` and `A^T`, high accumulator guard width, used for filmed star trajectory. This is the reliability anchor. |
| Early staged-A ablation | `78cd2c219871d31f3e50b2676a7a11372d2737d0` | Early memory-optimized version | Staged dynamics representation. Likely numerically fragile because guard bits were too low. Useful as an ablation, not likely a final candidate. |
| A memory optimization | `ee338c643eec3b10c02e64e3ffc29437312c48d4` | Main staged-A candidate | Staged `A`, scaled ADMM, dynamic constraints, widened interface, low guard-bit setting. Important for the memory optimization story. |
| 1 kHz optimized candidate | `565281f` | Resource-sharing and timing-closure candidate | Not in the original short list, but important. Contains 6-iteration, 8 ns clock, allocation limits, shared resource architecture, and loop unrolling aimed at 1 kHz. |
| Current | `f2fdd4e81fb770805409799127642cd99ff34783` | Current working tree baseline | Staged `A`, dynamic constraints, 10 iterations, 10 ns clock. Needs testbench/interface repair before conclusions. |

Optional historical ablations:

| Commit or Branch | Reason to Include |
| --- | --- |
| `514ff0c` / `traj_mem_opt` | Trajectory-memory optimization without all later changes. |
| `c7ad61e` | Early staged-A refactor. |
| `float_benchmark` | Only include if the RAL story needs a fixed-point versus floating-point FPGA comparison. |
| `differentiated_width` | Likely unstable, but useful only if explaining why aggressive bit-width specialization was abandoned. |

## Interface Status

The 418-bit current simulation harness issue has been patched in the main working tree and verified by reruns. Do not use the original `current_f2fdd4e_290` result for numerical conclusions because that job used stale 386-bit testbench packing.

Current solver packing should be:

```text
state bits:        [383:0]
constraints word:  [415:384]
trajectory cmd:    [417:416]
total width:       418 bits
```

Required repairs and status:

- Update closed-loop testbench packer from `ap_uint<386>` to `ap_uint<418>`: done in main working tree.
- Update basic ADMM test packer from `ap_uint<386>` to `ap_uint<418>`: done in main working tree.
- Update UART smoke test packer or mark it obsolete for current SPI-based builds: packer updated; UART remains legacy.
- Ensure start trajectory and reset trajectory commands are placed in bits `[417:416]`: done through shared pack helper.
- Ensure dynamic constraints are either explicitly zero or intentionally set in bits `[415:384]`: explicitly zeroed in current testbenches.
- Re-run current closed-loop star trajectory simulation after this fix: done. Job `294` completed full generated-trajectory CSim and HLS synthesis. Job `308` completed the 5 s smoke.

Conclusion: the original current star failure was the stale packing mismatch, not evidence of insufficient guard bits.

## Benchmark Goals

The benchmark should answer these questions:

1. Does the staged-A representation actually save enough memory or routing pressure to justify its complexity?
2. Does staged-A hurt latency, DSP use, timing closure, or numerical robustness?
3. Which accumulator guard width is required for the star trajectory and for broader trajectory robustness?
4. Which design reaches reliable 500 Hz flight?
5. Which design, if any, reaches reliable 1 kHz onboard control?
6. Which version is best for the RAL paper story: full sparse matrices, staged dynamics, or a hybrid narrative?

## Metrics To Collect

For every build:

- Git commit hash.
- Dirty tree status.
- Branch name.
- Header-generation command and environment.
- Horizon length.
- ADMM iteration count.
- Clock target.
- Board target.
- Solver interface width.
- Accumulator guard bits.
- Rho settings.
- Whether trajectory memory is enabled.
- Whether dynamic constraints are enabled.
- Whether the design uses full sparse `A` and `A^T` or staged dynamics.

HLS metrics:

- Estimated clock period.
- Latency in cycles.
- Latency in microseconds.
- Initiation interval.
- DSP count.
- LUT count.
- FF count.
- BRAM count.
- URAM count if applicable.

Post-route metrics:

- WNS.
- TNS.
- Worst hold slack.
- Achieved timing at target clock.
- LUT.
- LUTRAM.
- FF.
- DSP.
- BRAM.
- Routing congestion indicators if available.
- Total on-chip power.
- Dynamic power.
- Static power.

Closed-loop metrics:

- Pass or fail.
- Failure step.
- Failure reason.
- Max state error.
- RMS position error.
- Final position error.
- Max control.
- Control saturation count.
- Constraint violation count.
- Trajectory completion status.
- Number of simulation steps.
- Runtime of simulation.

Drone metrics:

- Bitstream name and hash.
- Firmware commit.
- Host/drone protocol version.
- Battery voltage range.
- Control loop frequency.
- SPI transaction time.
- Solver valid/ready timing.
- Dropped command count.
- Flight result: pass, degraded, or fail.
- Tracking logs.
- Video/log reference if available.

## Benchmark Matrix

Start with a controlled matrix that separates architecture, numerics, and final flight validation.

### Tier 1: Correctness Smoke

Purpose: make sure each candidate can run its own closed-loop simulation before spending cluster time.

Candidates:

- `1c23f1f`
- `78cd2c2`
- `ee338c6`
- `565281f`
- `f2fdd4e`

Configuration:

- Horizon: 40.
- Iterations: version default.
- Clock: version default.
- Trajectory: star.
- Simulation length: short smoke, currently 5 simulated seconds at 500 Hz by default.
- Full generated-trajectory CSim is not the Tier 1 default. Use it only for finalist validation or when a specific baseline pass/fail question justifies the runtime.

Output:

- Pass/fail.
- Failure reason.
- First failing step.
- Basic tracking metrics.

### Tier 2: Guard-Bit Sweep

Purpose: isolate numerical robustness from architecture.

Candidates:

- `ee338c6`
- `565281f`
- `f2fdd4e`

Guard bits:

- `2`
- `3`
- `4`
- `6`
- `8`
- `12`

Configuration:

- Horizon: 40.
- Star trajectory.
- Iterations: version default, plus 6 and 10 where relevant.

Output:

- Minimum guard width that passes closed-loop star simulation.
- Resource and latency cost of each additional guard width.
- Whether the current star issue is purely accumulator width or also an interface/protocol issue.

### Tier 3: Architecture Sweep

Purpose: compare full sparse storage against staged dynamics.

Candidates:

- Full sparse baseline: `1c23f1f`.
- Staged-A candidate: `ee338c6`.
- 1 kHz staged-A candidate: `565281f`.
- Current staged-A candidate: `f2fdd4e`.

Horizons:

- `20`
- `40`
- `60`
- `80`

Iterations:

- `6`
- `10`
- Maximum feasible per horizon if useful.

Trajectory:

- Disabled for pure resource/latency comparison.
- Enabled for final correctness builds.

Output:

- Memory use versus horizon.
- Latency versus horizon.
- Timing closure versus horizon.
- Resource scaling versus horizon.
- Whether staged-A changes the bottleneck from memory to compute/routing.

### Tier 4: Pareto Finalists

Purpose: pick only the meaningful designs for hardware and drone testing.

Expected finalists:

- Flight-proven full sparse 500 Hz build.
- Best staged-A 500 Hz build.
- Best staged-A 1 kHz or near-1 kHz build.
- Current build after guard/interface fixes, if it beats or clarifies one of the above.

Output:

- Final Pareto table for the paper.
- Bitstreams ready for drone tests.
- Clear explanation of why non-finalist variants were dropped.

## Slurm Execution Plan

Each Slurm job should use an isolated git worktree and isolated build directory.

Per job:

1. Create worktree for the target commit.
2. Record git metadata:
   - commit hash
   - branch or detached state
   - `git status --short`
   - patch if dirty
3. Generate trajectory data.
4. Generate solver headers.
5. Run HLS C simulation.
6. Run HLS synthesis.
7. Run C/RTL co-simulation if selected for that tier.
8. Run Vivado implementation.
9. Generate bitstream if the build passes timing.
10. Archive all reports and generated files.

Each job should archive:

- `data.h`
- HLS synthesis report.
- HLS CSim log.
- C/RTL co-sim log if run.
- Vivado utilization report.
- Vivado timing report.
- Vivado power report.
- Bitstream if generated.
- Generated trajectory CSV or binary.
- Build stdout/stderr.
- Job metadata JSON.

Avoid sharing these across jobs:

- `.Xil`
- HLS project directories.
- Vivado project directories.
- Generated `data.h`
- Intermediate build products.

## Suggested Results Directory

Use a structure like:

```text
experiments/
  versions.yaml
  slurm/
    submit_sweep.sh
    run_one_config.sh
  results/
    2026-05-rAL-sweep/
      manifest.csv
      raw/
        <commit>_<config_id>/
      summary/
        hls_summary.csv
        implementation_summary.csv
        closed_loop_summary.csv
        drone_summary.csv
      plots/
```

The exact script names can change, but every generated result should be traceable to a commit and config.

## Drone Testing Plan

Do not fly every synthesized variant. Use simulation and implementation reports to reduce the set first.

### Stage 1: No-Prop Hardware Smoke

For each finalist bitstream:

- Program FPGA.
- Verify SPI protocol width.
- Send zero-state or known-state packet.
- Verify solver start/done behavior.
- Verify command output is finite.
- Verify start/reset trajectory commands are recognized.
- Log solver response time.

### Stage 2: Bench or Handheld Test

For each finalist that passes no-prop smoke:

- Run the full control stack without free flight.
- Verify command stream timing.
- Verify no dropped solver outputs.
- Verify trajectory reset behavior.
- Verify constraint word behavior if enabled.

### Stage 3: Flight Test

Fly only the final Pareto candidates:

- Full sparse flight baseline.
- Best staged-A 500 Hz candidate.
- Best 1 kHz candidate if timing and bench tests are solid.

Use the same star trajectory, logging format, and start/reset protocol where possible.

## Paper Story Options

The final story should be selected after the benchmark data is available.

### Story A: Staged A Wins

Use this if staged dynamics clearly reduce memory or routing pressure while still meeting timing and flight requirements.

Claim:

The MPC problem structure should be exposed to the FPGA. Instead of storing the full horizon-expanded constraint matrices, the solver stores compact per-stage dynamics and reconstructs the required products in hardware. This trades memory for structured compute and allows the implementation to scale better with horizon length.

Supporting evidence needed:

- Lower BRAM or LUTRAM use.
- Better scaling with horizon.
- Timing closure at useful horizons.
- Closed-loop and flight success.
- Guard-bit analysis showing robustness is preserved.

### Story B: Full Sparse Storage Is Better Enough

Use this if the full `A` and `A^T` storage fits comfortably and staged-A increases complexity, latency, or numerical risk.

Claim:

For this class of small aerial MPC problems, the full sparse matrices fit on the target FPGA. The more important codesign choices are banded factor storage, fixed-point arithmetic, accumulator sizing, ADMM scaling, and HLS resource scheduling. The staged-A attempt is an instructive ablation showing that minimizing memory is not automatically the best FPGA design.

Supporting evidence needed:

- Full sparse version has acceptable memory use.
- Full sparse version is simpler and more robust.
- Staged-A does not improve timing or energy enough.
- Flight-proven baseline remains competitive.

### Story C: Two-Level Codesign

Use this if both versions are useful in different regimes.

Claim:

The solver has two valid FPGA mappings. For moderate horizons, precomputed sparse matrices are simple and robust. For longer horizons or tighter memory budgets, staged dynamics improve memory scaling. The final design space is selected by jointly considering horizon length, iteration count, accumulator width, and timing closure.

Supporting evidence needed:

- Crossover point in horizon/resource scaling.
- Different Pareto-optimal designs for different horizons or frequencies.
- Clear explanation of when staged-A becomes worthwhile.

## Likely RAL Extension

The strongest likely RAL extension is not just "we made it faster." It should be:

1. Start from the ICRA flight-proven 500 Hz FPGA MPC result.
2. Show that naive optimization hits FPGA-specific limits: timing, routing, accumulator precision, and protocol complexity.
3. Compare alternative hardware mappings of the same ADMM algorithm:
   - full sparse matrices
   - staged dynamics
   - shared-resource 1 kHz architecture
4. Quantify the tradeoff between memory, latency, power, timing closure, and robustness.
5. Validate the selected design on the Crazyflie with the star trajectory.

The RAL contribution can then be framed as a codesign methodology for embedded FPGA MPC on micro aerial robots, not only as a one-off implementation.

## Immediate Next Actions

1. Treat `ee338c6` as the best current working staged-A FPGA candidate from Tier 1:
   - job `297` passed full generated-trajectory CSim and HLS synthesis.
   - job `309` passed the 5 s CSim smoke.
   - it has essentially the same HLS latency as current `f2fdd4e`, but uses fewer DSP/FF/LUT resources.
2. Keep `1c23f1f` as the flight-proven safety/reference design:
   - job `299` passed the 5 s smoke.
   - job `286` provides HLS metrics but full generated-trajectory CSim timed out, so do not classify it as a numerical failure.
3. Keep the canonical Tier 1 rows and setup/debug rows separate:
   - canonical full/HLS rows: `286` HLS-only baseline metrics, `287`, `289`, `294`, `297`.
   - canonical 5 s smoke rows: `299`, `300`, `307`, `308`, `309`, plus `301`/`310`/`311` as `565281f` iteration probes.
   - debug/setup only: `288`, `291`, `292`, `295`, `296`, canceled `298`, canceled oversized `302`-`306`, and stale `290`.
4. Do not start broad guard-bit sweeps for current or `ee338c6` based on the present data; both pass closed-loop CSim when tested with the correct interface.
5. Treat `565281f` as a numerically failing 1 kHz architecture candidate for now: default, 8, 10, and 12 iterations all fail the 5 s smoke.
6. Fastest useful next experiment: move only the viable finalists into implementation/resource validation, starting with `ee338c6` and the flight baseline reference. Include `f2fdd4e` only if a direct current-vs-`ee338c6` comparison is needed for the paper.

Active finalist Vivado comparison:

- Results root: `exp/2026-05-vivado-finalists-view-a`.
- Job `495`: `1c23f1f`, `vivado_flight_baseline_native`, end-to-end native trajectory storage, `BOARD=custom`, Vivado synthesis plus implementation. Completed successfully.
- Job `496`: `ee338c6`, `vivado_ee338c6_native`, compatibility patch, end-to-end native trajectory storage, `BOARD=custom`, Vivado synthesis plus implementation. Completed successfully.
- This is View A from `NORMALIZED_VIVADO_COMPARISON.md`: same board/constraints/high-level trajectory, but each commit keeps its native trajectory storage layout. Use it for hardware finalist/Pareto selection. Run a separate View B only if an isolated trajectory-storage-normalized architectural claim is needed.
- Post-route interpretation: both finalists are Pareto-relevant. `1c23f1f` uses lower LUT/FF/DSP and power with higher BRAM and latency; `ee338c6` uses lower BRAM and latency with higher LUT/FF/DSP and power.

## Decision Gates

Use these gates to avoid spending drone time on weak candidates.

### Gate 1: Simulation

A candidate must pass closed-loop star simulation with finite controls and no constraint violations.

### Gate 2: HLS

A candidate must have a plausible HLS latency for the target control rate.

For 500 Hz:

- Solver plus communication must fit below 2 ms.

For 1 kHz:

- Solver plus communication must fit below 1 ms.
- Leave margin for SPI, estimator/controller overhead, and timing jitter.

### Gate 3: Implementation

A candidate must pass post-route timing with positive WNS at the target clock.

### Gate 4: Bench Hardware

A candidate must pass no-prop SPI smoke and bench timing before flight.

### Gate 5: Flight

A candidate should only be flown if it has passed the previous gates and contributes to the paper comparison.

## Open Questions

- Does the current fixed-packing staged-A design offer any advantage over `ee338c6`, or should `ee338c6` replace it as the main staged-A candidate?
- Does staged-A reduce BRAM/LUTRAM enough to matter on the target FPGA?
- Does staged-A increase logic/routing enough to offset the memory benefit?
- Is the 1 kHz build reliable enough for flight, or only for synthesis/bench demonstration?
- Should the final paper emphasize 500 Hz robustness, 1 kHz feasibility, or the full design-space exploration?
- Which host protocol should be considered canonical for the final paper and artifacts: SPI only, or SPI plus legacy UART support?

## Working Assumptions

- The filmed star trajectory version is the ground-truth flight baseline.
- The current SPI path is the intended hardware path for the drone.
- UART scripts are legacy unless updated to the widened current protocol.
- Slurm should be used for synthesis and implementation sweeps, not for drone-in-the-loop tests.
- Drone testing should be reserved for finalists after simulation and implementation reports are available.

## Handoff To Next Session

The current working copy is an SSHFS-mounted view of the project that lives on the Slurm cluster. The next session should be started from a mounted upper-level directory, not from only the `ADMM_FPGA` repository directory. This is so the agent can see the main repo, sibling worktree directories, experiment outputs, Slurm logs, and archived reports in one workspace.

Current cluster-side layout:

```text
/home/agrillo/fpga/
  ADMM_FPGA/
  worktrees/
  exp/
```

Current local SSHFS mount:

```text
/home/andrea/projects/fpga/
  ADMM_FPGA/
  worktrees/
  exp/
```

The exact names can change, but the next session should keep these roles separate:

- Main repository: source of scripts, manifests, and documentation.
- Worktree root: isolated checkouts for historical commits.
- Experiment root: Slurm outputs, reports, bitstreams, logs, and summary CSVs.

Important: SSHFS is useful for editing and inspecting files, but HLS/Vivado builds should run on the Slurm cluster's native filesystem inside Slurm jobs. Do not run large HLS/Vivado builds through the SSHFS client path if avoidable.

### Current Files To Preserve

The current session added:

- `EVALUATION_PLAN.md`
- `experiments/versions.yaml`
- `experiments/slurm/run_one_config.sh`
- `experiments/slurm/submit_sweep.sh`
- `experiments/slurm/collect_results.py`
- `experiments/patches/`

There were already untracked project artifacts visible in the repo:

- `RESEARCH_HISTORY.md`
- `TinyFPGATrajopt__ICRA___FOR_2026_.pdf`

Do not delete or overwrite these. Treat them as project context for the next session.

### What The Next Session Should Do First

Start from the upper-level mounted directory and inspect:

```bash
pwd
ls
git -C ADMM_FPGA status --short --branch
git -C ADMM_FPGA log --oneline --decorate -n 20
```

If the next session is running on the local SSHFS mount, inspect logs/results locally. Use SSH only for Slurm commands such as `squeue`, `sacct`, `sbatch`, and `scancel`.

### Next Session Task List

The next session should continue with these concrete tasks:

1. Start from the cleaned Tier 1 interpretation:
   - `ee338c6` works and is the best current staged-A candidate.
   - `f2fdd4e` works but is slightly worse than `ee338c6` in HLS resources.
   - `78cd2c2` works but is a historical 386-bit-interface ablation.
   - `1c23f1f` is the flight-proven safety/reference design, with a passing 5 s smoke and HLS metrics; its full Tier 1 CSim timed out rather than diverged.
   - `565281f` fails numerically even when the ADMM iteration count is increased.
2. Keep setup/debug rows out of scientific tables:
   - debug/setup only: `288`, `291`, `292`, `295`, `296`, canceled `298`, canceled oversized `302`-`306`, and stale `290`.
3. Do not run guard-bit sweeps for `ee338c6` or `f2fdd4e` based on current evidence.
4. Fastest useful next experiment: run implementation/resource validation only for likely finalists, starting with `ee338c6` and `1c23f1f`. Add `f2fdd4e` only if the paper needs an explicit current-vs-memory-optimization comparison.
5. Treat `565281f` as a failing 1 kHz architecture candidate unless a later architectural/numeric patch is proposed; increasing ADMM iterations to 8, 10, or 12 did not rescue the 5 s smoke.

### Critical Context For Next Session

The current solver interface expects 418 bits:

```text
state bits:        [383:0]
constraints word:  [415:384]
trajectory cmd:    [417:416]
```

The current main-worktree testbenches now use the 418-bit packing helper, and the fixed current rerun passes. Historical commits may still have 386-bit declarations or packers, so compatibility patches must be explicit when testing widened-interface commits.

The main candidate commits are:

```text
f2fdd4e81fb770805409799127642cd99ff34783  current
ee338c643eec3b10c02e64e3ffc29437312c48d4  A_mem_optimization
78cd2c219871d31f3e50b2676a7a11372d2737d0  early staged-A candidate
1c23f1fb276b193294ac106037873362d5740f6e  filmed star trajectory, known working
565281f                                      1 kHz optimized candidate worth including
```

The first scientific decision is not whether to keep the memory optimization. The first decision is whether each version is being tested with the correct interface and trajectory protocol. After that, the benchmark should decide whether staged-A is a real improvement, a useful ablation, or the wrong tradeoff for this FPGA.

Current best interpretation after the first Tier 1 runs:

- The main `ee338c6` memory-optimization candidate passes full generated-trajectory CSim and HLS synthesis with the compatibility patch. It is the strongest immediate staged-A candidate because it matches current latency while using fewer DSP/FF/LUT resources.
- Current fixed-packing staged-A passes Tier 1, but is slightly worse than `ee338c6` in HLS resources.
- Early staged-A also passes Tier 1 and is a valid ablation row.
- The flight baseline passes the 5 s smoke and has HLS metrics from job `286`, but its full generated-trajectory CSim timed out. Reserve full baseline validation for finalists.
- The 1 kHz optimized candidate is faster in HLS but fails CSim. Iteration probes at 8, 10, and 12 iterations still fail the 5 s smoke, so the failure is not simply the default 6-iteration budget.
