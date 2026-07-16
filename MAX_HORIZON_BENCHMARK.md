# Maximum-Horizon Benchmark

This flow is direct/local execution only. It does not use Slurm.

## One-time Environment

```bash
source ~/venv/bin/activate
python -c "from sksparse.cholmod import cholesky"
source experiments/slurm/setup_xilinx_2025_2.sh
```

The setup script name is historical; it only loads the Xilinx/Vitis environment.

## Run One Point

From `ADMM_FPGA/`:

```bash
python scripts/run_max_horizon_point.py \
  --arch staged_a \
  --horizon 320 \
  --iters 10 \
  --board custom \
  --out-dir ../exp/2026-07-max-horizon-direct
```

For SSH sessions, prefer detached execution so the build survives a disconnect:

```bash
python scripts/run_max_horizon_point.py \
  --arch staged_a \
  --horizon 320 \
  --iters 10 \
  --board custom \
  --out-dir ../exp/2026-07-max-horizon-direct \
  --detach
```

Detached mode writes:

- `<out-dir>/<slug>/runner.pid`
- `<out-dir>/<slug>/detached_runner.log`
- normal point logs under `<out-dir>/<slug>/command_logs/`

Foreground mode prints a heartbeat every 60 seconds. Use `--heartbeat-s 0` to
disable it.

The runner sets:

- `ADMM_SOLVER_ARCH`
- `ADMM_HORIZON_LENGTH`
- `ADMM_ITERATIONS`
- `ADMM_ENABLE_TRAJECTORY=0`

It removes generated headers before running `make BOARD=custom bit`, then archives
reports, logs, generated headers, bitstream outputs, hashes, and one CSV row.

Benchmark-point failures are expected while searching for the maximum horizon.
The runner therefore exits `0` after successfully archiving a failed point. Use
`--strict-exit-code` only if you intentionally want the shell to receive the
underlying failing build code.

## Suggested Sequence

Staged-A:

```text
40, 160, 320, 640, 960, 1280, 1536, 1792, 2048
```

After the first staged-A fail, refine between the last pass and first fail in
32-horizon steps.

Full sparse:

```text
80, 90, 100
```

Stop full-sparse after the first LUTRAM/DRC/resource overuse failure unless
`H=100` unexpectedly passes.

## Aggregate And Plot

```bash
python scripts/aggregate_max_horizon_results.py \
  --run-dir ../exp/2026-07-max-horizon-direct
```

Outputs:

- `summary.csv`
- `common_horizon_comparison.csv`
- `max_horizon_by_arch.csv`
- `plots/latency_vs_horizon.png`
- `plots/energy_vs_horizon.png`
- `plots/power_vs_horizon.png`
- `plots/wns_vs_horizon.png`
- `plots/resources_vs_horizon.png`
- `plots/solver_radar.png` when both solvers have passing points
- `plots/solver_cost_radar_h<H>.png` for each horizon where both solvers have
  timing-clean points. This is a lower-is-better cost radar using latency,
  energy, energy-delay product, power, resource utilization, and optional
  scalability when max-horizon rows are included.
- `plots/solver_comparison_h<H>_bars.png` with the same lower-is-better
  cost metrics as grouped bars.

## Parallel Comparison Runs

The parallel runner uses one worker per horizon and tries implementation
variants sequentially for that horizon. It stops a horizon after the first
timing-clean variant unless `--run-all-seeds` is specified.

By default each invocation creates a unique worker root under `/tmp` and removes
it after the run. Only pass `--work-root` when debugging or intentionally
preserving worker repos; explicitly provided work roots are lock-protected and
cannot be reused by concurrent runs.

Use a separate output directory for `full_sparse` max-horizon exploration:

```bash
python scripts/run_max_horizon_parallel.py \
  --arch full_sparse \
  --horizons 80,90,100,110,120,130,140,150 \
  --seeds 0,1,2,3,4,5,6,7,8,9 \
  --workers 6 \
  --threads-per-worker 3 \
  --board custom \
  --iters 10 \
  --out-dir ../exp/2026-07-full-sparse-max-variants
```

For an apples-to-apples radar, put both architectures in one common-horizon
directory:

```bash
python scripts/run_max_horizon_parallel.py \
  --arch staged_a \
  --horizons 80,100 \
  --seeds 0,1,2,3 \
  --workers 2 \
  --threads-per-worker 3 \
  --board custom \
  --iters 10 \
  --out-dir ../exp/2026-07-common-horizon-radar

python scripts/run_max_horizon_parallel.py \
  --arch full_sparse \
  --horizons 80,100 \
  --seeds 0,1,2,3 \
  --workers 2 \
  --threads-per-worker 3 \
  --board custom \
  --iters 10 \
  --out-dir ../exp/2026-07-common-horizon-radar

python scripts/aggregate_max_horizon_results.py \
  --run-dir ../exp/2026-07-common-horizon-radar
```

## Manual Scalability Input

The aggregator never searches other run directories for scalability data. To
add the optional scalability axis, create `<run-dir>/max_horizon_manual.csv`:

```csv
arch,max_timing_clean_horizon
full_sparse,90
staged_a,1350
```

If this file is absent, scalability fields and axes are omitted.

## Publish Results To Git

Raw experiment directories under `../exp` are working data, not the permanent
record. Publish only compact, plot-ready data and final figures:

```bash
python scripts/publish_solver_scalability.py \
  --run-dir ../exp/2026-07-solver-scalability \
  --manual-scalability ../exp/2026-07-solver-scalability/scalability_manual.csv \
  --output results/2026-07-solver-scalability
```

Each tracked campaign contains canonical CSVs, a manifest, a README, and final
figures. Bitstreams, reports, logs, generated headers, and worker repositories
remain outside Git. Figures can be regenerated without raw artifacts:

```bash
python scripts/publish_solver_scalability.py \
  --output results/2026-07-solver-scalability \
  --regenerate-only
```
