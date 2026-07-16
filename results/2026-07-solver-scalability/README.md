# Solver Pareto And Scalability Results

## Question

This campaign measures the tradeoff between two FPGA mappings of the same
structured ADMM problem:

- `full_sparse` stores the horizon-expanded sparse operators directly.
- `staged_a` stores stage-level dynamics and reconstructs products using a
  reused compute datapath.

The intended result is a Pareto comparison, not a claim that one architecture
is universally superior. Horizon is retained as configuration context, while
optimization variables and constraints are the primary problem-size measures.

## Configuration

- Target: custom Artix-7 `xc7a100tcsg324-1` board
- Configured clock: 100 MHz
- ADMM iterations per solve: 10
- Trajectory output: disabled
- Low sweep: H=10 through H=90 in steps of 10, baseline implementation, seed 0
- Low-sweep source revision: `a834011a71c66a82cf59a8c8e1230a803f19ec73`
- Every one of the 18 low-sweep points produced a bitstream and met timing.

The low sweeps were launched separately so their manifests and raw artifacts
did not race:

```bash
python scripts/run_max_horizon_parallel.py \
  --arch full_sparse \
  --horizons 10,20,30,40,50,60,70,80,90 \
  --seeds 0 --workers 9 --threads-per-worker 5 \
  --board custom --iters 10 \
  --out-dir ../exp/2026-07-solver-scalability

python scripts/run_max_horizon_parallel.py \
  --arch staged_a \
  --horizons 10,20,30,40,50,60,70,80,90 \
  --seeds 0 --workers 9 --threads-per-worker 10 \
  --board custom --iters 10 \
  --out-dir ../exp/2026-07-solver-scalability-staged-a
```

## Findings

At shared problem sizes, `staged_a` is consistently faster. At H=40 (652
variables and 732 constraints), it solves in 1.365 ms versus 1.485 ms for
`full_sparse`.

Before its on-chip memory representation saturates, `full_sparse` occupies the
low-power and low-energy side of the frontier. At H=40 it uses 0.333 W and
0.494 mJ/solve versus 0.683 W and 0.932 mJ/solve for `staged_a`. It also uses
substantially less aggregate LUT+FF compute at these moderate sizes.

That advantage reverses near the storage limit. At H=90, `full_sparse` reaches
91.6% LUTRAM and its power rises to 0.732 W, while `staged_a` uses 2.2% LUTRAM
and 0.707 W. Energy is then 2.412 mJ/solve for `full_sparse` versus 2.139
mJ/solve for `staged_a`. This H=90 point demonstrates the failure regime: BRAM
pressure spills the sparse representation into LUTRAM, erasing the power and
energy advantage. It is a boundary datapoint, not a recommended operating
point. All ten tested H=100 full-sparse implementation variants failed to
produce a bitstream, so H=90 remains its demonstrated implementation maximum.

The staged architecture scales to H=1350: 21,612 optimization variables,
24,312 constraints, 44.859 ms per 10-iteration solve, and 22.29 solves/s. This
point is timing-clean at WNS=+0.023 ns. The limiting resources are BRAM (96.3%)
and physical compute/packing rather than DSP count. H=1400 did not close timing
across the tested variants; its best completed WNS was -0.172 ns. H=1450 did
not produce a successful result before the campaign cutoff and is classified
as unsuccessful. H=1350 is therefore the demonstrated timing-clean maximum.

The codesign conclusion is therefore conditional:

- choose `full_sparse` for problems that fit its efficient memory regime when
  power, energy, and compute footprint dominate;
- choose `staged_a` when problem-size scaling and stable memory structure are
  more important, accepting greater compute and energy at moderate sizes.

Larger horizons represent larger horizon-expanded structured QPs. They are a
proxy for optimization workload, not proof that arbitrary larger dynamical
systems have identical scaling.

## Tracked Data

- `data/low_horizon_comparison.csv`: all 18 fresh shared-size results with
  timing, latency, power, energy, and routed resource metrics.
- `data/staged_scalability.csv`: 13 explicitly curated timing-clean staged
  points from H=40 to H=1350.
- `manifest.json`: source revisions, raw locations, configuration, and hashes
  for every tracked data and figure file.

The high-horizon rows predate the clean tooling commit. Their metadata records
base revision `b82e18d` and the dirty worktree, whose relevant generator,
implementation, and benchmark-script changes were subsequently committed in
`a834011`. This exception is preserved rather than represented as clean-commit
provenance. The deliberately canceled H=1200 run is excluded; only timing-clean
high-scale points are published.

## Regenerate Figures

Figures depend only on the tracked canonical CSVs:

```bash
source ~/venv/bin/activate
python scripts/publish_solver_scalability.py \
  --output results/2026-07-solver-scalability \
  --regenerate-only
```

To republish from raw data and the explicitly curated manual scalability CSV:

```bash
python scripts/publish_solver_scalability.py \
  --run-dir ../exp/2026-07-solver-scalability \
  --run-dir ../exp/2026-07-solver-scalability-staged-a \
  --manual-scalability ../exp/2026-07-solver-scalability/scalability_manual.csv \
  --output results/2026-07-solver-scalability
```
