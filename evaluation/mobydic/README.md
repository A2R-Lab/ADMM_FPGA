# MOBY-DIC baseline

Reproduces the quadrotor comparison using MOBY-DIC's original C++ ADMM kernel
and small-architecture transformation. The Python frontend uses AccelMPC's
model, objective and constraints without tracking augmentation.

## Reproduce

Requires Python with `requirements.txt` installed, and Vitis/Vivado 2025.2
available in the shell (source their `settings64.sh` files). Run from the
ADMM_FPGA repository root:

```sh
git submodule update --init --recursive
python -m pip install -r evaluation/mobydic/requirements.txt
python evaluation/mobydic/run.py
```

This builds H5 and H10 sequentially from scratch using 100 MHz HLS synthesis
and 100 MHz Vivado synthesis, placement and routing, then evaluates the routed
checkpoint at 60 MHz. Output goes to `output/build100_operate60/`;
use `--output PATH` for another fresh directory. Each horizon has stage logs and
reports; `summary.json` records actual outcomes. A failed horizon does not prevent
the other from running. The script exits nonzero if either build fails or misses
timing; inspect the logs to distinguish capacity failures from other errors.

Settings: small architecture, 10 ADMM iterations, rho=1000,
Artix-7 xc7a100t-csg324-1. Solver values use `ap_fixed<32,12>` and the
accumulator uses `ap_fixed<40,20,AP_RND,AP_SAT>`; coefficient widths are generated.

## Outputs

Each build retains HLS latency reports and Vivado utilization, timing and power
reports under its output directory. Power is a tool estimate, not a board
measurement. Convert HLS cycle counts to latency using the 60 MHz operating
clock, not the 100 MHz HLS target. Only timing-closed builds establish usable latency and energy.

## Upstream and license

`upstream/` pins COMPsys-UNIGE/MOBY-DIC at
`de6a0b1c4e613524c20921a24323693a39bc37d1`.
MOBY-DIC and derived adapter code are GPLv3; see COPYING and upstream notices.
AccelMPC's independent production code retains its existing license.
