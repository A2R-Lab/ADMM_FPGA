# FPGA/TinyMPC Plotting Workflow

This file is a quick runbook to reproduce benchmark data and plots.

## 1) Run FPGA benchmark sweep (real measured data)

From repo root:

```bash
python3 scripts/benchmark_fpga_horizons.py \
  --port /dev/ttyUSB1 \
  --board arty \
  --admm-iters 10 \
  --samples 1 \
  --horizons 10,20,30,40,50,60,70,80 \
  --budget-us 2000 \
  --continue-on-error
```

Outputs:
- `plots/fpga_res.csv` (BENCH_CSV, total solve time semantics)
- `plots/fpga_raw_cycles.csv` (raw cycles + total_us + per_iter_us)


## 2) Project measured FPGA rows to multiple iteration counts

The benchmark above measures one configured `admm-iters` value (default `10`).
This step projects those timings to additional iter counts (linear scaling).

```bash
python3 scripts/project_fpga_iters.py \
  plots/fpga_res.csv \
  plots/fpga_res_projected_iters.csv \
  --base-iter 10 \
  --target-iters 1,2,5,10,15,20,25,30 \
  --budget-us 2000
```

Output:
- `plots/fpga_res_projected_iters.csv`


## 3A) Compare 3 sources (TinyMPC + FPGA float + FPGA fixed)

```bash
python3 plots/plot_compare_sources.py \
  --tinympc plots/res.csv \
  --fpga-float plots/fpga_res_projected_iters.csv \
  --fpga-fixed plots/fpga_res_projected_iters.csv \
  -o plots/compare_three_sources
```

Outputs in `plots/compare_three_sources/`:
- `01_compare_avg_vs_iter_per_h.png`
- `02_compare_norm_vs_iter_per_h.png`
- `03_speedup_vs_tinympc_per_h.png`
- `04_k_step_iter_vs_h.png`
- `summary.txt`

Note:
- Replace `--fpga-float` and `--fpga-fixed` with different files once you have both datasets.


## 3B) Plot one source with the existing plotter (`plot_bench.py`)

FPGA projected:

```bash
python3 plots/plot_bench.py \
  plots/fpga_res_projected_iters.csv \
  -o plots/fpga_projected_plots
```

TinyMPC:

```bash
python3 plots/plot_bench.py \
  plots/res.csv \
  -o plots/bench_plots
```


## Common checks

List serial ports:

```bash
ls /dev/ttyUSB* /dev/ttyACM* 2>/dev/null
```

Digilent dual-port boards usually use `/dev/ttyUSB1` for UART data.
