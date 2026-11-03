# Optimize full_sparse HLS without changing its mapping or mathematics

## Task and success criteria

The user requested a separate agent session to explore whether `full_sparse` can
benefit from better FPGA operation scheduling, as `staged_fused` did. This is an
experiment, not an assumption that full_sparse will win. Implement and screen a
few high-impact changes; avoid immediately rebuilding the full horizon campaign.

Preserve the full_sparse mapping: explicitly stored expanded sparse constraint
operators, the banded-Cholesky primal step, fixed-point formats, coefficients,
penalties, projection, iteration count, warm-start behavior and public interface.
Do not turn it into stage-wise operator reconstruction or a Riccati solver.
Preserve bit-exact outputs, including rounding, saturation and accumulation order.
Do not change arithmetic precision or reassociate reductions to manufacture speedups.

The useful outcome is lower latency/energy/EDP while retaining a credible lower
logic/DSP footprint than fused staged. Report tradeoffs rather than optimizing
latency alone. A negative result or a small gain that does not justify a sweep is
also useful. FPGA resource counts do not establish ASIC area.

## Standalone server repository and isolation

- Branch: `exploration/full-sparse-hls`.
- Base: `implementation/staged-fused-arty`, commit `a93bfc8`. This contains the
  fused implementation, hardware fixes and measurement tooling to learn from.
- Local SSHFS view (not the recommended Git working directory): `/home/andrea/aa/maoilImpl/a2r-main-mount/full-sparse-hls-worktree`.
- Standalone repository on server: `/home/agrillo/moailImpl/full-sparse-hls-worktree`.
- Main publication checkout: `/home/andrea/aa/maoilImpl/ADMM_FPGA`, branch
  `comparison/tinympc-fpga`; latest local publication commit at handoff `7850eff`.
  Its most recent push was interrupted: do not assume remote has that commit.
  The publication CSV is staged on this server at the snapshot path below.
- Main paper: `/home/andrea/aa/maoilImpl/paper`. Do not edit it in this experiment.
- Existing fused worktree: `../arty-comparison-20261102/git-integration`.

This is now a standalone clone with its own `.git` directory on a2r-main, NOT
an SSHFS-linked Git worktree. The user explicitly prefers running a Codex session
directly on a2r-main for this experiment. Run Git and edit files directly there;
no local-machine Git metadata is required. `origin` is
`git@github.com:A2R-Lab/ADMM_FPGA.git`.

The failed initial linked checkout is preserved at
`/home/agrillo/moailImpl/full-sparse-hls-worktree.incomplete-backup`; it is not an
active repository. Do not use it for builds. The useful handoff has been copied
into this standalone repository. Do not alter other campaigns or worktrees.

Create separate build copies per configuration under
`/home/agrillo/moailImpl/full-sparse-hls-runs`; never share generated headers or
HLS outputs between concurrent jobs. Read applicable AGENTS.md files if present.

## Machines and tools

Use `~/venv` both locally and remotely, not system Python or a new environment.
All HLS, FPGA builds, heavy simulation and expensive C++ reference compilation run
on **a2r-main**. The user wants useful concurrency, but RAM can spike sharply:
inspect running jobs and memory first; do not launch eight large jobs blindly.
Never stop other campaigns/processes or alter their thread settings.

When running Codex directly on a2r-main, source the three environments below
and execute commands directly; SSH is only needed when launching from the laptop.
Server launch prefix:

```sh
ssh -o BatchMode=yes -o ConnectTimeout=10 a2r-main '
  source /home/agrillo/venv/bin/activate
  source /home/agrillo/amdfpga/2025.2/Vivado/settings64.sh
  source /home/agrillo/amdfpga/2025.2/Vitis/settings64.sh
  # cd to an isolated server build copy, then run the chosen command
'
```

Target Artix-7 100T, fixed k=10, trajectory disabled, 100 MHz preferred.
Make does not reliably notice environment-only parameter changes: explicitly
regenerate headers after switching architecture/horizon/iterations and check the
resulting generated config. See `docs/build.md`, `scripts/parameters.py`,
`scripts/header_generator.py`, `Makefile` and existing runner --help options.
Typical overrides include `ADMM_SOLVER_ARCH=full_sparse`,
`ADMM_HORIZON_LENGTH=40`, `ADMM_ITERATIONS=10`; verify the exact trajectory override
in the code rather than guessing its name.

## Start small: greedy search

1. Inspect `vitis_projects/ADMM/ADMM.cpp`, especially the full_sparse operator
   products, substitutions, projection/dual/RHS updates, HLS directives and data
   types. Compare with the STAGED_FUSED conditional code. Inspect actual HLS
   latency/II/critical recurrence and memory-port evidence before proposing fixes.
2. Establish an unchanged full_sparse baseline at H40/k10, using the same flow,
   wrapper, clock and trajectory setting as candidate builds. Reuse valid existing
   baseline evidence when truly comparable. Record baseline source/configuration.
3. Try a small number of changes independently. Candidate ideas (not promises):
   - pipeline independent streaming updates;
   - forward values directly between sparse-product consumption and updates,
     avoiding unnecessary full-vector writes/reads without reconstructing operators;
   - explicitly schedule/register long-latency multiplies away from recurrences;
   - improve memory access scheduling/port use and modest partitioning/unrolling;
   - preserve intermediate casts and ordered accumulations while doing so.
   Avoid broad LUTRAM conversion: the user specifically dislikes trading large
   amounts of logic/energy for memory without a demonstrated benefit.
4. Use HLS first to reject obvious losers. A lower cycle count is not a confirmed
   improvement until routed timing closes. Check promising candidates at H10 and
   H40; test a near-capacity H80/H90 only after a real win. Do not sweep all horizons.
5. For finalists, obtain comparable uninstrumented resource reports for full_sparse
   and fused. Current publication reports use different wrappers (see below), so
   raw ratios are not an apples-to-apples solver-area comparison.
6. Before hardware measurement, do a concise bit-exact comparison with unchanged
   full_sparse on representative inputs, bounds and repeated warm-start solves.
   Cover relevant saturation/rounding cases. Use an RTL check on the finalist;
   C/HLS simulation alone was insufficient in the earlier campaign. Do not spend
   days on exhaustive simulation of every rejected candidate.
7. Only if the improvement is meaningful, build instrumented H10/H40 finalists
   and measure locally on Arty. Do not duplicate an entire campaign preemptively.

No numerical threshold is a hard user requirement. As a practical screen, a
roughly 10% latency/EDP gain or substantial resource saving is worth examining;
a smaller gain may matter if cheap and robust. Explain the decision using the
Pareto tradeoff and engineering cost, not just a single percentage.

## Known hardware lessons: do not regress these

Earlier aggressive fused builds passed some simulation checks but produced wrong
hardware outputs. The retained fixes include power-test ROM initialization and
preserved synthesis hierarchy (`ea49a3c`). Inspect that commit and the actual Tcl.
Do not describe this as a proven generic Vivado DSP bug. Do not casually remove
hierarchy preservation, change reset/ROM handling or transplant a pragma without
checking the generated implementation. HLS estimated timing is not routed timing.

The newer memory-mapping campaign's source is separate from the base worktree:
`../arty-comparison-20261102/campaign-v6-memory/source`. It applies distributed-ROM
mapping to coefficient ROMs and block-RAM mapping to large working arrays. Inspect
it if relevant; this is a mapping change, not mathematical compression. Treat
measured results from each actual bitstream as authoritative.

## Existing evidence and comparison scope

Publication CSV (all valid points; do not change it in this experiment):
`/home/andrea/aa/maoilImpl/ADMM_FPGA/evaluation/data/benchmarks.csv`.
A snapshot is also staged at
`../arty-comparison-20261102/paper-integration/benchmarks.csv` (111 valid points).
The parent branch's older evaluation files do NOT contain all current results.

At H40/k10 the current publication resource counts are:

| Design | LUTs | Registers | DSPs | BRAM tiles | Wrapper |
|---|---:|---:|---:|---:|---|
| full_sparse | 9280 | 12051 | 77 | 78.5 | solver/SPI |
| staged_fused | 27412 | 25371 | 152 | 58 | instrumented |

These suggest a resource tradeoff but cannot support precise solver-only ratios.
A reduced logic footprint is a reason to investigate full_sparse, not proof that
it will use a smaller FPGA or ASIC (memory and timing also matter).

At H40/k10 fused is measured at 569.63 us and 186.46 uJ; Wu FPGA at 769.00 us and
270.96 uJ. These energies include measured core/BRAM plus estimated auxiliary/I/O.
All 29 TinyMPC FPGA publication points use Arty measurements, NOT total post-route
power estimates. Fused measurements extend through H1023. Uninstrumented fused
has a timing-clean H1800 build; that is not a measured energy point or an exact
maximum capacity claim. Full_sparse's previous demonstrated limit is H90.

Published energy accounting must stay consistent: mean measured core/BRAM energy
plus matching auxiliary/I/O supply power times measured solve latency; EDP is
that energy times that same latency. Keep raw rail results too. Vivado power is
only a screening estimate: prior designs had much larger estimated differences
than their measured differences. Do not claim a measured EDP gain from estimates.

## Arty workflow (only after screening)

The board is connected to the LOCAL machine, not a2r-main. Coordinate with any
active measurement session; use the existing locks and never steal the device.
Stable port:
`/dev/serial/by-id/usb-Digilent_Digilent_USB_Device_210319BE047B-if01-port0`.

Local tool settings:

```sh
source /home/andrea/venv/bin/activate
source /media/andrea/48a1bd03-3653-4c55-8d37-cd7d804e2212/amdfpga/2025.2/Vivado/settings64.sh
source /media/andrea/48a1bd03-3653-4c55-8d37-cd7d804e2212/amdfpga/2025.2/Vitis/settings64.sh
```

Existing script: `scripts/power_campaign.py`. Established campaigns and bundles:
`../arty-comparison-20261102/campaign-v5` and `campaign-v6-memory`.
Local runner example:
`/home/andrea/aa/maoilImpl/arty-local-20261102/measure-ready-v6.sh`.
Read it for the environment, not as a way to measure new candidates under an old
campaign ID. Make a separate experiment campaign/output identity.

Copy new bitstreams AND scripts locally before running on the board; do not run
hardware measurement from SSHFS. Verify bundle hashes. Existing measurements use
an 8-solve validation pilot and three valid repeated batches targeting two seconds,
with at least 1024 solves. Keep those settings for comparability. The campaign
supports incremental results; do not rerun already completed old points.

## Deliverables and boundaries

- Commit isolated changes on this branch and give reproducible commands.
- A short baseline/candidate table: clock, cycles, routed timing, latency, LUTs,
  registers, DSPs, BRAM, and energy/EDP with explicit estimated/measured labels.
- Summarize the correctness checks and any resource/energy regressions.
- Recommend whether a larger sweep is warranted. Do not launch it just because
  spare CPU exists, and do not pursue an ASIC flow in this task.
- Keep bulky builds, bitstreams, reports and failed candidates outside Git.
  Keep only useful source, instructions and compact valid result summaries.
- Do not rewrite publication claims or the flight narrative. The paper is being
  simplified separately to full_sparse versus the improved staged implementation;
  the original staged_a is not intended as a third headline method.
- Provide regular concise updates and continue authorized work autonomously.

Start by inspecting the code and existing evidence, then propose/implement the
first narrowly scoped experiment. No FPGA jobs were launched by the handoff author.
