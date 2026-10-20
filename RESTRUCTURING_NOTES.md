# Repository restructuring record

Recorded 2026-10-20. This document records the restructuring already performed in
this session so it can be reviewed, undone separately from the power-measurement
work, and reconsidered after other branches are merged. It is documentation only:
no rollback, branch creation, staging, or commit is authorized by this document.
Retain this document when undoing the restructuring.

## Intended sequence

1. Document the restructuring (this document).
2. When separately authorized, undo the restructuring completely while preserving
   the power-measurement changes that existed before it.
3. Isolate, manually review, validate, and merge the power-measurement work.
4. Merge the user's other pending work.
5. Revisit a smaller restructuring plan against the resulting merged repository;
   agree on the exact moves before implementing them.

The current implementation is not a reviewed restructuring to merge. It was applied
after misinterpreting the user's instruction to continue planning as implementation
authorization. No commit was created during this work.

## Baseline and preservation boundary

The checked-out commit is `b3edd31d80be06a4a64d94cfedde083d93f1680c`.
The working tree was already dirty before any restructuring. **The rollback target
is that pre-restructuring working tree, not a clean checkout of this commit.**

Initially modified tracked files:

- `.gitignore`: simulator artifacts and the local `a2r-main-mount/` exclusion.
- `Makefile`: the `arty-power` board, trajectory disabling, SystemVerilog sources,
  generated-header dependencies, power workload generation, bitstream manifest,
  and related build dependencies.
- `README.md`: a 276-line power-measurement section appended to the existing overview.
- `scripts/synth.tcl`: power RTL, include directories, constraints, and clock checking.
- `scripts/impl.tcl`: hierarchical utilization reporting.
- `scripts/bitstream.tcl`: power-build clock/timing checks before bitstream generation.

Initially untracked power work to preserve:

- `POWER_MEASUREMENT_PLAN.md`, `POWER_MEASUREMENT_HANDOFF.md`, `POWER_CAMPAIGN.md`.
- The twelve power-related scripts identified as untracked in the move table below.
- `experiments/power/synthetic_states.csv`.
- `tests/power/`: Python tests, RTL testbenches, C++ reference, and XADC stimulus.
- Under `vivado_project/vivado_project.srcs/sources_1/new/`:
  `power_benchmark.sv`, `power_capture.sv`, `power_uart.sv`, `power_xadc.v`, and
  `top_uart_power.sv`.
- `vivado_project/vivado_project.srcs/constrs_1/new/constraints_arty_power.xdc`.

The local `a2r-main-fpga/` workspace also appeared untracked before restructuring;
it is not a source directory to inspect, move, delete, or stage during this work.
Both it and `a2r-main-mount/` must be excluded from recursive searches/copies because
of the SSHFS mounts. Do not use an unrestricted untracked-file inventory to assess
this checkout.

There was no complete pre-edit snapshot of all untracked files. Git's `HEAD` cannot
recover the original power additions. A later rollback must reverse the recorded
restructuring edits in those files, preserving the implementation. Do not use a
blanket reset, clean, or restore on the mixed working tree.

## Implemented layout and exact moves

The implemented layout groups support scripts into `scripts/build/`, `model/`,
`benchmark/`, `hardware/`, and `power/`. Power shell test runners were moved into
`tests/power/`. The HLS and Vivado project directories and `paper_figures/` stayed
in place. All 51 moves are listed here; paths are relative to the repository root.
“Untracked power” means the source file already existed before restructuring, not
that the restructuring created its implementation.

| Original path | Current path | Original status |
|---|---|---|
| `MAX_HORIZON_BENCHMARK.md` | `docs/benchmarking/max-horizon.md` | Tracked |
| `POWER_CAMPAIGN.md` | `docs/power/campaign.md` | Untracked power |
| `POWER_MEASUREMENT_HANDOFF.md` | `docs/power/history.md` | Untracked power |
| `POWER_MEASUREMENT_PLAN.md` | `docs/power/design.md` | Untracked power |
| `benchmark_precision.py` | `scripts/benchmark/benchmark_precision.py` | Tracked |
| `scripts/aggregate_benchmark_summaries.py` | `scripts/benchmark/aggregate_benchmark_summaries.py` | Tracked |
| `scripts/aggregate_max_horizon_results.py` | `scripts/benchmark/aggregate_max_horizon_results.py` | Tracked |
| `scripts/benchmark_fpga_horizons.py` | `scripts/benchmark/benchmark_fpga_horizons.py` | Tracked |
| `scripts/bitstream.tcl` | `scripts/build/bitstream.tcl` | Tracked |
| `scripts/build_bitstreams_parallel.py` | `scripts/benchmark/build_bitstreams_parallel.py` | Tracked |
| `scripts/check_power_saif.py` | `scripts/power/check_power_saif.py` | Untracked power |
| `scripts/compare_power.py` | `scripts/power/compare_power.py` | Untracked power |
| `scripts/compare_trajectories.py` | `scripts/benchmark/compare_trajectories.py` | Tracked |
| `scripts/crazyloihimodel.py` | `scripts/model/crazyloihimodel.py` | Tracked |
| `scripts/header_generator.py` | `scripts/model/header_generator.py` | Tracked |
| `scripts/hw_in_loop_simulation.py` | `scripts/hardware/hw_in_loop_simulation.py` | Tracked |
| `scripts/hw_in_loop_simulation_float.py` | `scripts/hardware/hw_in_loop_simulation_float.py` | Tracked |
| `scripts/impl.tcl` | `scripts/build/impl.tcl` | Tracked |
| `scripts/parameters.py` | `scripts/model/parameters.py` | Tracked |
| `scripts/power_activity.tcl` | `scripts/power/power_activity.tcl` | Untracked power |
| `scripts/power_activity_report.tcl` | `scripts/power/power_activity_report.tcl` | Untracked power |
| `scripts/power_benchmark.py` | `scripts/power/power_benchmark.py` | Untracked power |
| `scripts/power_build_manifest.py` | `scripts/power/power_build_manifest.py` | Untracked power |
| `scripts/power_campaign.py` | `scripts/power/power_campaign.py` | Untracked power |
| `scripts/power_workload.py` | `scripts/power/power_workload.py` | Untracked power |
| `scripts/profile_power.sh` | `scripts/power/profile_power.sh` | Untracked power |
| `scripts/program.tcl` | `scripts/build/program.tcl` | Tracked |
| `scripts/program_file.tcl` | `scripts/build/program_file.tcl` | Tracked |
| `scripts/program_flash.tcl` | `scripts/build/program_flash.tcl` | Tracked |
| `scripts/project_fpga_iters.py` | `scripts/benchmark/project_fpga_iters.py` | Tracked |
| `scripts/publish_solver_scalability.py` | `scripts/benchmark/publish_solver_scalability.py` | Tracked |
| `scripts/run_hls_closed_loop_once.py` | `scripts/benchmark/run_hls_closed_loop_once.py` | Tracked |
| `scripts/run_max_horizon_parallel.py` | `scripts/benchmark/run_max_horizon_parallel.py` | Tracked |
| `scripts/run_max_horizon_point.py` | `scripts/benchmark/run_max_horizon_point.py` | Tracked |
| `scripts/run_prebuilt_bitstreams.py` | `scripts/benchmark/run_prebuilt_bitstreams.py` | Tracked |
| `scripts/summarize_power_overhead.py` | `scripts/power/summarize_power_overhead.py` | Untracked power |
| `scripts/sweep_hls_csim_full_grid.py` | `scripts/benchmark/sweep_hls_csim_full_grid.py` | Tracked |
| `scripts/sweep_hls_csim_qr_freq.py` | `scripts/benchmark/sweep_hls_csim_qr_freq.py` | Tracked |
| `scripts/sweep_horizon_trajectory_gap.py` | `scripts/benchmark/sweep_horizon_trajectory_gap.py` | Tracked |
| `scripts/sweep_hw_controller_grid.py` | `scripts/benchmark/sweep_hw_controller_grid.py` | Tracked |
| `scripts/sweep_motor_lag_tuning.py` | `scripts/benchmark/sweep_motor_lag_tuning.py` | Tracked |
| `scripts/sweep_qr_tuning.py` | `scripts/benchmark/sweep_qr_tuning.py` | Tracked |
| `scripts/sweep_resource_utilization.py` | `scripts/benchmark/sweep_resource_utilization.py` | Tracked |
| `scripts/sweep_resource_utilization_parallel.py` | `scripts/benchmark/sweep_resource_utilization_parallel.py` | Tracked |
| `scripts/synth.tcl` | `scripts/build/synth.tcl` | Tracked |
| `scripts/test_power.sh` | `tests/power/test_power.sh` | Untracked power |
| `scripts/test_power_hls.sh` | `tests/power/test_power_hls.sh` | Untracked power |
| `scripts/trajectory_generator.py` | `scripts/model/trajectory_generator.py` | Tracked |
| `scripts/uartCommTester.py` | `scripts/hardware/uartCommTester.py` | Tracked |
| `scripts/uartCommTester2.py` | `scripts/hardware/uartCommTester2.py` | Tracked |
| `scripts/uart_solver_smoke_test.py` | `scripts/hardware/uart_solver_smoke_test.py` | Tracked |

## Edits beyond file moves

### Build, model, and benchmark paths

- Updated the top-level Makefile's script dependencies and commands to the new
  workflow directories, including running generators from `scripts/model/`.
  These changes are interleaved with the earlier power-build additions.
- Increased repository-root discovery by one directory level in moved Python,
  Tcl, and shell scripts. The model generators use `SCRIPT_DIR.parent.parent`.
- Updated direct CLI paths and `Path` expressions across benchmark runners,
  including worker-local generation and the precision runner's worktree command.
- Added the sibling model directory to Python's import search path in both HIL
  scripts, `run_hls_closed_loop_once.py`, and `sweep_horizon_trajectory_gap.py`.
- Changed the HLS QR/frequency sweep's minimal worker layout to `scripts/model/`
  so the copied generators discover the correct worker repository root.
- Added a directory-existence fallback in `experiments/slurm/run_one_config.sh`
  and `run_vivado_config.sh`, supporting both historical flat script layouts and
  the new `scripts/model/` layout. Historical patch files were not rewritten.
- Updated two diagnostic strings in `vitis_projects/ADMM/ADMM.cpp` to reference
  `scripts/model/header_generator.py`; no solver arithmetic was changed.

### Power campaign and tests

- Replaced the power campaign's flat source-snapshot directory with an explicit
  list of the five script groups. Added `.sh` files to the power-test snapshot
  suffixes and changed its documentation paths to the relocated power documents.
- Added `scripts/benchmark/` to the campaign runner's import search path because
  its build implementation imports benchmark helpers.
- Updated power acquisition/programming and runner-provenance paths.
- Added compatibility for existing manifests containing the original flat paths:
  `campaign_data()` accepts either runner path for its existing runner-change
  exception, and `measure()` chooses frozen runner/acquisition/programming paths
  from the manifest. Existing frozen campaign contents were not edited.
- Updated imports/paths in `tests/power/test_power.py`, `test_campaign.py`, and
  `test_campaign_build_flow.py`.
- Extended the existing transport-failure test to exercise both flat and grouped
  manifest paths and check the selected acquisition command. Extended the snapshot
  test to require the moved generator, synthesis Tcl, and benchmark helper.
- Adjusted both moved shell test runners' repository-root traversal and workload
  generator paths. Updated the power profiling script and Tcl references as well.

Undoing the restructuring must remove its compatibility/path/test changes while
retaining the original power acquisition, build, validation, and campaign logic.
The original power documents were relocated and had script references updated;
they must be moved back, not deleted as newly created documentation.

### Copy exclusions and Git ignore rules

- Added the two known remote workspaces, `results`, `xsim.dir`, `.aws`, `.codex`,
  and `.agents` to the copy exclusions in `run_max_horizon_parallel.py`,
  `build_bitstreams_parallel.py`, and `sweep_resource_utilization_parallel.py`.
- Added `/a2r-main-fpga/` to `.gitignore`.
- Changed `.gitignore`'s `build/` to `/build/` because the original pattern also
  ignored the newly created `scripts/build/` source directory.
- Changed the old `scripts/admm_results.txt*` and `scripts/clockInfo.txt` exclusions
  to their `scripts/hardware/` equivalents.
- The simulator and `/a2r-main-mount/` ignore entries predated restructuring and
  belong to the preserved power work.

### Documentation and figure generation

- Replaced the root README with a paper-oriented overview and workflow map.
- Extracted its detailed power section into the newly created `docs/power/README.md`.
  This file contains pre-existing power documentation and must not simply be
  deleted during rollback. Its heading, links, introductory setup text, script
  paths, and installation-path example were edited during extraction.
- The old power README installation example used
  `/media/andrea/48a1bd03-3653-4c55-8d37-cd7d804e2212/amdfpga/2025.2/` for the
  Vivado/Vitis settings scripts and `~/venv/bin/activate`. The extracted guide
  replaced that example with a reference to the new build guide.
- Created `docs/build.md`, `docs/benchmarking/README.md`, and
  `paper_figures/README.md`. The benchmarking guide also documents that parallel
  precision workers use committed `HEAD` and discusses frozen campaign paths.
- Moved the maximum-horizon guide and the three pre-existing power documents as
  listed in the table; updated their command examples to the new script paths.
- Changed `paper_figures/plot_benchmarks.py` default data/output paths from working-
  directory-relative paths to paths based on its own location. This allows commands
  from the repository root. Figure selections, styles, and numerical inputs were
  not changed.
- Ran both figure generators, producing ignored files in `paper_figures/output/`.
  These generated outputs are not source edits. No curated figure data was changed.

The tracked Vivado incremental checkpoint and GUI project, HLS project layout,
power RTL/constraints, workload CSV, historical experiment patches, and video
assets were not reorganized. Existing generated build/measurement artifacts and
SSHFS workspace contents were not deliberately changed.

## Validation actually performed and unresolved issues

Completed before work was stopped:

- All 15 Python power tests passed, including the updated legacy/current manifest
  transport test. The campaign build test uses mocks; it is not an FPGA build.
- Make dry runs succeeded for `custom`, `arty`, and `arty-power` in the working tree
  and in a newly prepared temporary campaign snapshot.
- The new temporary snapshot passed manifest/source integrity checking.
- 27 CLI `--help` entry points succeeded from outside the repository.
- Both paper figure generators ran successfully. A Git diff confirmed the tracked
  curated inputs under `paper_figures/data/` were unchanged; generated outputs were
  confirmed ignored.
- Python parsing and shell syntax checks passed at an intermediate stage, and
  `git diff --check` passed. This is not a final all-files validation: moved,
  untracked files are not fully covered by `git diff --check`.

Limitations and remaining problems:

1. **Worker-copy bug:** all three general repository-copy runners still have a
   bare `"build"` entry in `shutil.ignore_patterns`. That pattern applies at every
   directory level and will omit the new `scripts/build/` directory. The later
   `.gitignore` correction does not fix Python's copy filters. The power snapshot's
   explicit allowlist avoids this bug, so its successful dry run did not exercise
   the affected copy paths. A future restructuring must address and test this.
2. A final formatting edit accidentally removed the `ignore_names =
   shutil.ignore_patterns(` assignment in `build_bitstreams_parallel.py`, causing
   an `IndentationError`. That block was subsequently restored, but the final
   syntax/CLI checks were not rerun before the user stopped implementation.
3. The final `/build/` Git-ignore correction and copy-block repair were made after
   earlier successful validations. Do not describe the final tree as fully checked.
4. No full HLS/Vivado build, RTL/HLS simulation suite, FPGA programming, or physical
   measurement was run for the restructuring. Vivado simulation commands were not
   available on the shell's PATH during inspection.
5. Parallel precision runs create worktrees from committed `HEAD`; the current
   uncommitted moves are not automatically present in those worktrees.

## Guidance for a later, separately authorized rollback

Preserve this record and capture the current local source state before editing.
Use explicit local file/directory lists and exclude both SSHFS paths. Temporary
session files `/tmp/admm_path_mapping.json`, `/tmp/admm-moves.diff`,
`/tmp/reorganize_admm.py`, and `/tmp/admm_docs.py` may still provide implementation
history, but they are not backups and must not be rerun. The move-aware diff compares
tracked files against `HEAD`, so it also contains pre-existing power changes.

Reverse the move table together with the dependent path/import changes. Reassemble
the old root README from its original overview and the preserved power section,
undoing only the restructuring edits to that section. Remove only the documentation
created for restructuring after its needed content has been preserved. Keep this
record for the later planning phase.

Handle the six initially modified tracked files and all initially untracked power
files as mixed-content files. For tracked files that were clean beforehand, `HEAD`
is a useful reference after checking for any subsequent user edits. Do not apply
that rule to the six modified files or use it to discard untracked power additions.

Review the resulting power-only diff against the baseline and validate it separately.
Do not attempt to replay this large restructuring patch after other branches merge;
prepare a new, narrower plan from the merged tree, with pure moves, required path
updates, and editorial documentation changes easy to review separately.
