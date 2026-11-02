# TinyMPC FPGA baseline

Adapts the model-specific fused HLS generator in the sibling `tinympc_ip_gen`
checkout (upstream commit `bd1a6bd2348d2659652d0ae315f9eea8fea40c95`) to the
same quadrotor dynamics, input units, state/input bounds and dimensions used
by the MOBY-DIC comparison. H5/H10 use 6/11 state points, respectively.

The upstream steady-state Riccati coefficients, Pinf terminal term, rho
additions and reference weighting are preserved. This is a comparison of
similarly sized constrained MPC solvers, not identical quadratic programs.
No stage-dependent Riccati coefficients are introduced. Native float32 and
rho=1 are retained; MOBY-DIC uses fixed point and rho=1000.

## Preparation and validation

From the ADMM_FPGA root, with NumPy, SciPy, OSQP and autograd installed:

```sh
python evaluation/tinympc_fpga/prepare.py --horizon 5 --output /tmp/tiny-input/h5
python evaluation/tinympc_fpga/prepare.py --horizon 10 --output /tmp/tiny-input/h10
```

Use `--upstream PATH` if the generator is not in the sibling directory.
Each preparation compiles generated C++ with g++, checks all four test cases
against independently initialized Python reference solvers, and records
`numerical.json`. OSQP results use the AccelMPC objective and are diagnostic,
not assertions of equivalent solutions. In particular, the objective difference
is not an optimality gap for TinyMPC, and projected outputs can have dynamics
residuals after a fixed iteration budget.

The adapter explicitly supplies the configured solver to all function generators,
fixing upstream's silent reconstruction of its default model. It emits per-stage
bounds to leave x0 unconstrained and uses infinity for unbounded components.
It avoids the upstream testbench's retained Python workspace and its success
exit code on failed validation.

## FPGA builds

Copy the prepared `h5` and `h10` directories to a build machine. Source Vitis
and Vivado 2025.2, then run:

```sh
python evaluation/tinympc_fpga/build.py --input /path/to/input --output /path/to/fresh-output
```

The two builds run sequentially. They target Artix-7 `xc7a100t-csg324-1`, with
100 MHz HLS, implementation and routed timing/power evaluation. MOBY-DIC
needed a 60 MHz fallback; that fallback is not applied to TinyMPC. `summary.json` records each outcome.
Outputs retain HLS reports and routed utilization/timing/power reports.

The top-level interface is a local array memory instead of the upstream AXI DDR
interface. The fixed 10-iteration solve includes initialization and input/output
copies, but excludes external communication and the Ultra96 processor subsystem.
Termination checking is removed for deterministic work and to avoid upstream's
modulo-by-zero behavior when a zero check interval is supplied. The solver
arithmetic, loop scheduling pragmas and matrix-expression generation are retained.

Latency must use HLS cycles divided by the operating clock and is usable only
when routed timing closes. Power and energy are tool estimates, not board
measurements. Floating-point operator IP must be included in Vivado implementation.

Generated files record source hashes. Keep the upstream checkout and its notices
alongside the adapter; the upstream README currently contains a license placeholder.

## Primal versus projected trajectory validation

`validation/h5.json` and `validation/h10.json` retain the four-case, 10-iteration
checks. A separate host-only diagnostic source captures primal x/u before output
projection; the synthesized source is unchanged. Both primal and projected C++
trajectories are checked against fresh Python reference runs. The Python observer
captures primal values before upstream `solve()` overwrites x/u with slack outputs.

Across these cases, primal dynamics residuals are at most 3.06e-6, consistent with
float32 arithmetic. Projected dynamics residuals reach 2.014. State consensus is
zero in these cases: the discrepancy arises from input clipping, with input
consensus residuals reaching 6.358 in the deliberately aggressive input-active
case. Projected bound violations are at most 3.10e-9. These observations validate
the distinction between dynamics-feasible primal trajectories and bound-feasible
projected outputs; they do not establish convergence after ten iterations.

## Horizon sweep

After validating H5/H10, generate larger instances without constructing dense
OSQP matrices:

```sh
python evaluation/tinympc_fpga/prepare.py --generate-only \
  --model-report evaluation/tinympc_fpga/validation/h5.json \
  --horizon 80 --output /path/to/input/h80
python evaluation/tinympc_fpga/build.py --input /path/to/input \
  --output /path/to/fresh-output --horizons 20 40 80 160 320 640 1280
```

Run synthesis and implementation on the build server. The runner uses four
Vivado threads; independent output directories support separate workers.
Archive completed outcomes through the SSHFS mount with `collect.py --run PATH
--output PATH`. Export one or more archived campaigns with `summarize.py`, using
repeated `--run` arguments and `--output evaluation/data/tinympc_fpga_comparison.csv`.
The exporter checks the actual 100 MHz routed reports, including for the initial
campaign whose historical directory name includes `operate60`. Usable latency
and energy are withheld from builds that do not close timing. Failed builds
retain synthesis resource counts where available.

## All-metric comparison

After exporting completed campaigns, run:

```sh
python evaluation/tinympc_fpga/compare.py
```

`comparison/metrics.csv` combines the TinyMPC results with matching-horizon,
10-iteration AccelMPC rows from `benchmark_summary.csv` and the MOBY-DIC rows.
`comparison/comparison.png` and `.pdf` plot latency, estimated energy, EDP,
LUTs, BRAM and LUT–latency product. All energy values in this comparison use post-route power estimates;
board measurements from the main evaluation are not mixed into this plot.
MOBY-DIC retains its verified 60 MHz operating point; the other solvers use
100 MHz. `largest_demonstrated.json` reports the largest recorded timing-clean
horizon for each architecture, not a proof that all larger horizons fail.
When multiple AccelMPC records share a horizon, the first published successful
record is retained and its campaign is recorded in the combined CSV.

## Completed sweep and supported conclusions

All points use ten iterations. TinyMPC closes routed timing at 100 MHz for H5,
H10, H20, H40, H80, H160, H320, H640 and H1023. H1024 and H1280 fail placement
capacity DRC: they require 19,907 and 27,052 LUT-as-memory cells, respectively,
against 19,000 available. H1023 is the largest demonstrated passing point;
this is a measured implementation boundary, not a proof about every possible
mapping or tool setting.

The published AccelMPC dataset contains timing-clean staged H1350 and
full-sparse H90 at ten iterations. Staged therefore demonstrates a 32.0% longer
horizon than this TinyMPC port (1350 versus 1023). This is a capacity result,
not an equal-deadline performance result.

At H5/H10/H20/H40, AccelMPC full-sparse uses 59.8–71.0% fewer LUTs than TinyMPC.
It uses 77 DSPs versus 136 (43.4% fewer). Full-sparse has approximately 5.0%
lower estimated energy at H10 and 5.3% lower at H20, but TinyMPC has lower energy
at H5 and H40. These small energy differences are tool estimates, not measured
board-power advantages.

The LUT–latency product (LUT count multiplied by solve latency) measures a
logic/time tradeoff without assigning weights to different resource types.
Full-sparse has 43.2%, 39.8%, 25.8% and 22.6% lower LUT–latency product at
H5/H10/H20/H40, respectively. This does not include BRAM/DSP costs and does not
predict the number of controllers that can be replicated on the device.

TinyMPC wins latency and EDP at every common tested horizon. At H80 it also
uses fewer LUTs and less estimated energy than full-sparse. Thus the data support
short-horizon resource efficiency for full-sparse and larger demonstrated
capacity for staged; they do not support universal AccelMPC superiority.

EDP is energy times latency, or power times latency squared. The combined CSV
includes EDP in µJ·µs and LUT–latency product in LUT·µs, as well as raw latency,
power, energy, LUT, FF, BRAM and DSP counts. The figures include these combined
metrics alongside the underlying quantities; no weighted overall score is used.

## Solution-quality scope

`comparison/quality.json` retains an eight-point diagnostic: the existing four
cold-start cases at H5/H10 and ten iterations. `quality.py` uses unchanged copies
of AccelMPC's sources and its benchmark interface, generated in a temporary
directory. Reproduce with `python evaluation/tinympc_fpga/quality.py
--hls-include /path/to/Vitis/include`.

The host build uses `-O2 -ftrivial-auto-var-init=zero`: without deterministic
zeroing of automatic storage, the ap_fixed host benchmark failed the zero-input
sanity check. This compiler setting is explicitly recorded; the diagnostic is
not validation of RTL numerical quality. No production solver files are modified.

In these diagnostics, AccelMPC has smaller dynamics residuals than TinyMPC's
returned projected trajectory on the nonzero cases. TinyMPC's internal primal
trajectory, however, satisfies dynamics to float32 precision and has smaller
first-command errors against the common OSQP reference on these cases. Both
returned trajectories satisfy the tested bounds to numerical precision.
The OSQP reference uses AccelMPC's objective, while TinyMPC retains different
terminal and rho/reference weighting. These mixed outcomes do not establish
closed-loop superiority or equal-quality energy/latency. Do not use a projected
trajectory residual alone to claim that AccelMPC solves the problem better.

## Relationship to the paper

The baseline is the paper's sparse-aware fused TinyMPC generator adapted to
AccelMPC's quadrotor model and Artix-7 device, not a reproduction of its published
Ultra96 experiment. The checkout implements the forward/backward passes,
constant expressions and sparse pruning from Section IV; the programmable vector
processor from Section III is not present in this checkout.

The paper's Figure 13 reports per-iteration timing, whereas our fixed-budget
latency includes ten iterations, initialization and local input/output copies.
Its Table IV reports measured static and incremental dynamic power. Our results
use total post-route estimated power. The paper's 54.10% reduction for Q-N30
is the dynamic-power reduction (122 to 56 mW); static plus dynamic changes from
719 to 472 mW. Its 25.96% tracking-error improvement changes horizon and control
rate, and is not an equal-horizon solution-accuracy claim. These published results
are context only and are not mixed into our comparison CSV.

`comparison/capacity.png` and `.pdf` show the largest demonstrated horizons,
including AccelMPC horizons outside the common-horizon performance plots.

## Extended closed-loop quality evaluation

`comparison/closed_loop/` contains the raw per-run JSON, aggregate CSV, source
hashes and tracking-error plot for 150 simulated trajectories: H10/H40, five
scenarios, five initial-condition seeds, and three solver modes. The modes are
AccelMPC cold-start, AccelMPC retained x/b/y state, and the TinyMPC FPGA port's
native cold-start behavior. All use ten iterations, a matched linear plant at
50 Hz, 250 control steps (5 s), identical reference previews and seeded velocity
disturbances, and identical actuator clipping. AccelMPC's retained-state bridge
calls its unchanged `ADMM_iteration` with persistent workspace, reset between
trajectories. No production solver source is modified.

Reproduction (Python dependencies from requirements.txt; also matplotlib for plots):

```sh
python evaluation/tinympc_fpga/prepare_closed_loop.py --output /path/to/experiment
# On the build server, in /path/to/experiment:
HLS_INCLUDE=/path/to/Vitis/include bash /path/to/evaluation/tinympc_fpga/build_closed_loop.sh
python closed_loop.py --input . --output results --solvers accel tiny
python closed_loop.py --input . --output results_warm --solvers accel_warm
# Copy results/results.json and results_warm/results.json to
# comparison/closed_loop/cold.json and warm.json, respectively, then:
python evaluation/tinympc_fpga/summarize_quality.py
```

Remote trajectory arrays and compiled artifacts are retained at
`/home/agrillo/maolinComp/tiny-quality-loop/` on a2r-main. Per-step arrays have
columns time, state[12], reference[12], raw control[4], applied control[4].
The reported cost integrates the common Q/R stage loss along each actual
simulated trajectory; it is not either solver's internal finite-horizon objective.
As with the earlier host diagnostic, AccelMPC compilation explicitly initializes
automatic storage to zero to avoid the observed ap_fixed host initialization
issue. These are host simulation results, not RTL or physical-flight validation.
The plant is linear and the test set is limited; no claim is made about robust
performance across nonlinear plants, all references or all parameter tunings.

The evidence does not support general AccelMPC solution-quality superiority.
Retained-state AccelMPC has about 4.9% lower position RMSE on H40 circle tracking
(9.29 versus 9.77 cm), but TinyMPC has lower mean RMSE in the other nine
horizon/scenario combinations and lower common stage cost in all ten.
The H40 boundary test reaches a 0.307 m XY-bound violation for retained-state
AccelMPC, versus zero for TinyMPC. All 150 runs completed. These findings should
remain visible alongside the resource/scalability advantages.

## Completed EDP horizon grid

The `fill_a` (H30/H60) and `fill_b` (H50/H70) campaigns complete the 10-step
horizon grid from H10 through H80. All four additional points close timing at
100 MHz. They are included in the canonical CSV and the paper's latency–energy
and EDP plots; there are no missing TinyMPC FPGA EDP bars on that grid.

## Fresh checkout setup

The FPGA generator is a separate, pinned checkout next to ADMM_FPGA:

```sh
# From the directory containing ADMM_FPGA:
git clone https://github.com/KevinLikesDrinkingCoffee/tinympc_ip_gen.git
git -C tinympc_ip_gen checkout bd1a6bd2348d2659652d0ae315f9eea8fea40c95
cd ADMM_FPGA
python -m pip install -r evaluation/tinympc_fpga/requirements.txt
```

The optional AccelMPC host-quality experiments also require scikit-sparse and
its system SuiteSparse dependency; install `requirements-quality.txt` for those.
The HLS/Vivado benchmark uses AMD 2025.2. Large builds should run on a2r-main;
copy prepared directories through its SSHFS mount and invoke build commands by
SSH. Read logs and collect reports through the mount.

## Paper constrained star with the nonlinear plant

`prepare_star.py` recreates the existing paper experiment: H27, nine iterations,
1 kHz control updates, 25.6 s, 12-point `star_hold` reference with outer amplitude
2 m and the translated XY box [-1.3535533905932737, 0.6464466094067263] m.
It asserts that the generated path matches the retained paper reference and
that the reference actually leaves the feasible XY region (about 50.7% of its
samples). Both solvers use the unchanged nonlinear quaternion/RK4 quadrotor
plant from `ADMM_closed_loop_tb.cpp`, including motor lag, parameter mismatch,
drag and rotor imbalance. No production solver or plant source is edited.

```sh
python evaluation/tinympc_fpga/prepare_star.py --output /path/to/star-experiment
# Copy the experiment to a2r-main through the mount, then run there:
HLS_INCLUDE=/home/agrillo/amdfpga/2025.2/Vitis/include \
TASK_PYTHON=/home/agrillo/venv/bin/python \
bash /path/to/evaluation/tinympc_fpga/run_star_remote.sh /path/to/star-experiment
```

The runner retains independent solver logs and trajectory arrays. JSON results
include completion/early-stop status, raw-reference and clipped-reference RMSE,
maximum XY violation, violation duration fraction, and proximity to the XY
bounds. Reference infeasibility is checked independently of plant behavior.
These are ideal fixed-rate host simulations; they do not model solve overruns
or communication and are not physical-flight measurements.
