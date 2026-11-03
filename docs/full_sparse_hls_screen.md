# Full sparse HLS scheduling screen

This is the initial directive-only screen. The later storage experiments are
recorded in [Full sparse memory tradeoffs](full_sparse_memory.md).

## Result

Three H40/k10 HLS candidates were screened against the unchanged source at
`a93bfc8` (`exploration/full-sparse-hls`). None reduced latency enough to justify
routing or a horizon sweep. No directive-only solver change was retained from this initial screen. The result is
limited to the Artix-7 100T, 100 MHz, fixed-point, trajectory-disabled,
`arty-power` wrapper configuration.

| Configuration | HLS cycles (estimated) | Latency at 100 MHz | HLS LUT / FF / DSP / BRAM18K (estimated) | Routed timing and resources | Energy / EDP |
|---|---:|---:|---:|---|---|
| Baseline | 148,467 | 1.48467 ms | 24,103 / 18,848 / 77 / 224 | 100 MHz met; WNS 0.143 ns. `top_uart_power`: 14,687 LUT, 15,252 FF, 79 DSP, 101.5 BRAM tiles | Not measured; no EDP |
| Explicit update `PIPELINE II=1` | 148,467 | 1.48467 ms | Same as baseline | Not routed | Not measured; no EDP |
| Bind sparse products to DSP, latency 3 | 148,477 | 1.48477 ms | 24,051 / 19,030 / 91 / 224 | Not routed | Not measured; no EDP |
| Cyclic `x` banking, factor 8 | 148,466 | 1.48466 ms | 25,037 / 19,183 / 77 / 238 | Not routed | Not measured; no EDP |

HLS estimates showed 7.220 ns estimated delay (138.50 MHz estimated Fmax) for
the baseline, while the routed `arty-power` design had 0.143 ns setup slack
against a 10 ns requirement (9.326 ns data-path delay). The routed critical path was in the backward
substitution loop and was 95.5% routing delay. The full power wrapper estimated
286 BRAM18Ks before implementation, above the device's 270; Vivado mapped some
memory to LUT RAM. The final routed design used 101.5 BRAM tiles. These wrapper
resources should not be compared directly with publication solver/SPI counts.

The update loop achieved II=5 (732 rows, 3,678 cycles) because of resource
limits. Forward and backward substitutions each achieved II=8 (652 rows) with
memory-dependence constraints. The explicit II=1 directive did not change HLS
scheduling or resources. DSP binding increased DSPs by 14 with no latency gain.
Factor-8 banking saved one cycle over the baseline, less than 0.001%, while
adding 14 BRAM18Ks and 934 LUTs. Neither candidate is a meaningful win.

The TinyMPC reference (`/home/agrillo/moailImpl/tinympc_ip_gen/hls_generator.py`
and `/home/agrillo/moailImpl/2025-ICFPT_MPCOperatorFusion.pdf`, Sections III–IV)
uses static scheduling, loop pipelining, unrolled fixed-size dimensions, and
compile-time fusion/pruning. Full_sparse already fuses each constraint's sparse
product, projection, dual update, and RHS contribution in one row loop. The
screen did not find a scheduling-only change that improved its bottleneck.

No bit-exact RTL comparison or board measurement was run: no candidate advanced
past HLS screening. Vivado's vectorless 0.316 W power estimate had low
confidence, so it is not used to claim energy or EDP.

## Reproduction

Run on a2r-main from an isolated copy, with the Vitis/Vivado 2025.2 and Python
environments from `FULL_SPARSE_HANDOFF.md`:

```sh
export ADMM_SOLVER_ARCH=full_sparse
export ADMM_HORIZON_LENGTH=40 ADMM_ITERATIONS=10 ADMM_ENABLE_TRAJECTORY=0
python scripts/trajectory_generator.py
python scripts/header_generator.py
rg -n 'ADMM_ITERATIONS|ADMM_ENABLE_TRAJECTORY|ADMM_SOLVER_ARCH_NAME' \
  vitis_projects/ADMM/admm_runtime_config.h
make BOARD=arty-power hls
make BOARD=arty-power vivado
```

Baseline reports and candidate builds remain outside Git in
`/home/agrillo/moailImpl/full-sparse-hls-runs/`. Baseline report locations:

- HLS summary: `baseline-h40/vitis_projects/ADMM/ADMM/hls/syn/report/csynth.rpt`
- HLS detail: `baseline-h40/vitis_projects/ADMM/ADMM/hls/syn/report/ADMM_solver_csynth.rpt`
- Routed timing: `baseline-h40/build/reports/post_route_timing.rpt`
- Routed utilization: `baseline-h40/build/reports/post_route_utilization.rpt`
- Low-confidence power estimate: `baseline-h40/build/reports/post_route_power.rpt`
