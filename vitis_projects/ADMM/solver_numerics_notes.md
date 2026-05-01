# ADMM Fixed-Point Numerical Experiments

This note records closed-loop fixed-point HLS experiments used to debug the FPGA
controller instability.

## Baseline Test

Command run on `a2r-main`:

```bash
source /home/agrillo/amdfpga/2025.2/Vivado/settings64.sh
source /home/agrillo/amdfpga/2025.2/Vitis/settings64.sh
cd /home/agrillo/ADMM_FPGA/vitis_projects/ADMM
make cosim-closed-loop
```

The closed-loop test uses:

- `ADMM_SIM_FREQ=100`
- `ADMM_SIM_DURATION_S=2`
- `ADMM_TRAJ_START_STEP=50`
- `ADMM_CSIM_TRAJ_PATH=trajectory_cosim.csv`

## Scaled ADMM Results

The current scaled ADMM implementation stores `y` as the scaled dual variable
`u = lambda / rho`.

| ADMM form | `ACC_GUARD_BITS` | Closed-loop result | Est. clock | Solver latency | BRAM_18K | DSP | FF | LUT |
| --- | ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| scaled | 0 | `EARLY_STOP step=6 reason=control_out_of_bounds`; C/RTL co-sim matched failing behavior | `7.220 ns` | `136087` cycles | 126 | 99 | 36218 | 48656 |
| scaled | 12 | `EARLY_STOP step=-1 reason=completed`; C/RTL co-sim PASS, 200/200 transactions | `7.220 ns` | `175627` cycles | 126 | 106 | 36630 | 55374 |

Guard-bit cost in the scaled implementation:

- `+39540` cycles, about `+29%` solver latency.
- `+6718` LUT, about `+13.8%`.
- `+7` DSP.
- `+412` FF.
- No BRAM change.
- No HLS estimated clock change.

## Interpretation

Restoring the accumulator guard changes the same fixed-point closed-loop test
from an immediate control blow-up to a full C/RTL co-sim pass. This strongly
implicates accumulator precision/saturation in the solver instability.

The scaled and unscaled ADMM forms are equivalent in exact arithmetic, but not
necessarily equivalent in fixed point. They place `rho` multiplication/division,
rounding, and saturation at different points in the update.

## Unscaled ADMM Check

Run the same closed-loop test with the unscaled ADMM update:

| ADMM form | `ACC_GUARD_BITS` | Closed-loop result | Est. clock | Solver latency | BRAM_18K | DSP | FF | LUT |
| --- | ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| unscaled | 0 | `EARLY_STOP step=6 reason=control_out_of_bounds`; C/RTL co-sim matched failing behavior | `7.178 ns` | `136077` cycles | 126 | 99 | 36297 | 49238 |
| unscaled | 12 | C fixed-point closed-loop completed; RTL reached 196/200 transactions with no mismatch before manual stop | `7.220 ns` | `175617` cycles | 126 | 106 | 36709 | 55952 |

Unscaled ADMM did not fix the failure with `ACC_GUARD_BITS=0`: it failed at
the same step with the same reason as scaled ADMM. Restoring the accumulator
guard fixed the C fixed-point closed-loop for both scaled and unscaled forms.
This makes accumulator precision the primary observed factor for this test.

## Guard-Bit Sweep

The sweep was run with temporary generated HLS configs to override
`ACC_GUARD_BITS` and scaled/unscaled ADMM form during experiments. The current
checked-in Makefile intentionally does not expose these parameters; the selected
solver configuration lives in `ADMM.cpp`.

```bash
make csim-closed-loop-strict
make cosim-closed-loop
```

For parallel server runs, each job was copied into a separate `/tmp` work tree
to avoid `.Xil` and generated-project collisions.

| ADMM form | `ACC_GUARD_BITS` | Test level | Closed-loop result | Est. clock | Solver latency | BRAM_18K | DSP | FF | LUT |
| --- | ---: | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| scaled | 1 | C sim | `EARLY_STOP step=8 reason=control_step_too_large` | - | - | - | - | - | - |
| unscaled | 1 | C sim | `EARLY_STOP step=8 reason=control_step_too_large` | - | - | - | - | - | - |
| scaled | 2 | C/RTL co-sim | `EARLY_STOP step=-1 reason=completed`; PASS, 200/200 transactions | `7.288 ns` | `136477` cycles | 126 | 101 | 36089 | 51239 |
| unscaled | 2 | C/RTL co-sim | `EARLY_STOP step=-1 reason=completed`; PASS, 200/200 transactions | `7.288 ns` | `136467` cycles | 126 | 101 | 36168 | 51817 |
| scaled | 3 | C/RTL co-sim | `EARLY_STOP step=-1 reason=completed`; PASS, 200/200 transactions | `7.261 ns` | `136077` cycles | 126 | 101 | 34921 | 51163 |
| unscaled | 3 | C/RTL co-sim | `EARLY_STOP step=-1 reason=completed`; PASS, 200/200 transactions | `7.261 ns` | `136067` cycles | 126 | 101 | 35000 | 51745 |
| scaled | 6 | C sim | `EARLY_STOP step=-1 reason=completed` | - | - | - | - | - | - |
| unscaled | 6 | C sim | `EARLY_STOP step=-1 reason=completed` | - | - | - | - | - | - |

For this 200-step closed-loop trajectory test, the observed lower bound is:

- `ACC_GUARD_BITS=1` fails before co-sim is useful.
- `ACC_GUARD_BITS=2` passes full fixed-point C/RTL co-sim for both scaled and
  unscaled ADMM.

The scaled and unscaled variants behave the same numerically in this sweep.
Scaled ADMM is slightly cheaper in LUT and FF at the passing guard widths, so it
is the preferred default unless another trajectory exposes a difference.
