# Design and interfaces

The controller uses a 12-state, four-input quadrotor model. Python constructs
the MPC problem and its cached factorization; the HLS solver performs a fixed
number of ADMM iterations for each incoming state. The FPGA returns four motor
commands. See the [paper](https://arxiv.org/abs/2609.09380) for the formulation.

## Follow the implementation

For the equations, offline factorization and a step-by-step runtime explanation,
read [How one FPGA solve works](solver-walkthrough.md).

| Stage | Source | Role |
|---|---|---|
| Model and settings | [parameters.py](../scripts/parameters.py), [crazyflie_model.py](../scripts/crazyflie_model.py) | Horizon, costs, bounds, dynamics and trajectory settings |
| Offline generation | [header_generator.py](../scripts/header_generator.py), [trajectory_generator.py](../scripts/trajectory_generator.py) | Cached matrices, runtime configuration and reference tables |
| Solver | [ADMM.cpp](../vitis_projects/ADMM/ADMM.cpp) | ADMM updates, triangular solves and trajectory control |
| Numerical/packet types | [data_types.h](../vitis_projects/ADMM/data_types.h) | Fixed-point representation and bit packing |
| Board integration | [RTL sources](../vivado_project/vivado_project.srcs/sources_1/new/), [constraints](../vivado_project/vivado_project.srcs/constrs_1/new/) | SPI/UART, clocks, pins and power instrumentation |

`ADMM_SOLVER_ARCH=full_sparse` uses stored sparse matrices for the dynamics
operations. `staged_a` exploits repeated stage structure to reduce storage and
support longer horizons. Both use the same external solver interface.

The interleaved vector `[x0,u0,x1,u1,...,xH]` contains `16H+12` variables and
`18H+12` constraint rows. Both architectures retain horizon-dependent Cholesky
bands and work vectors. Staged-A stores the repeated dynamics coefficients and
applies them stage by stage instead of storing the expanded sparse operator.
Actual loop initiation intervals and resource use come from HLS/implementation
reports; source unrolling does not establish achieved throughput.

Primal, dual and cached right-hand-side arrays persist between solves without
a horizon shift. The solver executes exactly the configured iteration count.
Trajectory reset changes playback state; it does not clear the solver's static
warm-start arrays. A core reset clears that state.

## Model and timing

The current model uses mass 0.048 kg, four normalized motor commands, diagonal
Q/R costs from `parameters.py`, and terminal cost equal to Q. The attitude
coordinates come from the quaternion ratio `q_vector/q_scalar`, not general
Euler angles. Motor commands are relative to hover inside the QP; hover is
added to the output. Static XY bounds can be shifted by the trajectory generator,
so inspect generated bounds when changing reference shapes.

Model discretization defaults to 50 Hz (20 ms), independently of the solver
invocation rate. Reference playback advances every 20 calls by default; at
1 kHz this also gives 20 ms. Dynamic constraints change bounds on one fixed
axis (default x). Changing the constraint normals or topology requires matrix
regeneration and refactorization.

### State, model, and cost specification

State order is `[px, py, pz, rx, ry, rz, vx, vy, vz, wx, wy, wz]`:
world-frame position (m), attitude coordinates `r = q_vector/q_scalar`,
world-frame velocity (m/s), and body angular velocity (rad/s). The four inputs
are normalized motor commands relative to the hover command. The generated
linear model is about zero position/velocity, identity attitude, and hover.
`crazyflie_model.py` differentiates the RK4 discrete dynamics and transforms the
quaternion perturbation to the 12-state coordinates. The generator then applies
the configured linear-drag correction to the velocity diagonal of `A`.

The following are the current generator defaults, not a claim that every
recorded benchmark or flight used these settings. Environment overrides and
matrix overrides take precedence.

| Setting | Default | Definition/source |
|---|---|---|
| Mass | 0.048 kg | `CrazyFlieModel.mass`; model parameter, not measured airframe mass |
| Inertia diagonal | `(2.3951e-5, 2.3951e-5, 3.2347e-5)` kg m² | `CrazyFlieModel.J` |
| Gravity / motor arm coefficient | 9.81 m/s² / 0.0353 m | `g`, `el` |
| Thrust / torque coefficients | `kt = 2.90e-6 * 65535`, `km = kt * 0.002078` | Per normalized motor command |
| Model step | 0.02 s | `ADMM_MODEL_FREQ=50` |
| Drag coefficients, XY / Z | 0.12 / 0.12 | Velocity diagonal correction `-drag/(mass * MODEL_FREQ)` |
| Diagonal Q | `(40,40,158,0.4,0.4,40,3.5,3.5,4,0.2,0.2,25)` | State order above; `ADMM_Q_DIAG` |
| Diagonal R | `(1,1,1,1)` | `ADMM_R_DIAG`, multiplied by `ADMM_R_SCALE` (default 1) |
| Absolute motor bounds | `[0,1]` | `ADMM_U_ABS_MIN/MAX`; subtract hover for QP bounds |
| Nominal XY bounds | `[-1,1]` m | `ADMM_XY_MIN/MAX`; trajectory-dependent offsets apply |
| Equality / inequality penalties | 128 / 32 | `ADMM_RHO_EQ_PARAM`, `ADMM_RHO_INEQ_PARAM` |
| Horizon / iterations | 27 / 9 | `ADMM_HORIZON_LENGTH`, `ADMM_ITERATIONS` |

The hover command is `mass * g / (4 * kt)` for each motor. The objective uses
`1/2 wᵀ P w + qᵀ w`, with `P = blockdiag(Q,R,...,Q)` and reference-dependent
linear terms. Initial state and dynamics are equality constraints; the generated
inequalities bound motor commands and predicted X/Y positions.

## Solver boundary

`ADMM_solver` accepts 418 bits and returns 128 bits:

| Input bits | Value |
|---|---|
| 383:0 | Twelve 32-bit state values, state 0 in the lowest word |
| 415:384 | Packed dynamic constraint bounds |
| 417:416 | Two trajectory command bits |

The output contains four 32-bit motor-command values. The default numeric type
is `ap_fixed<32,10,AP_RND,AP_SAT>`: 22 fractional bits, rounding and saturation.
Accumulators use `ap_fixed<40,18,AP_RND,AP_SAT>`, adding eight integer guard bits
while retaining the same fractional precision.
The float configuration changes the word interpretation to IEEE float32.
Transport framing is implemented by the board top level; the 418-bit solver
input is not itself a byte-stream protocol specification.

Use [uart_solver_smoke_test.py](../scripts/uart_solver_smoke_test.py) for the
current UART framing and the [companion firmware](https://github.com/A2R-Lab/crazyflie_fpga_firmware)
for deployment over SPI. Firmware, generated solver settings and the bitstream
must agree on packing and numerical format.

For SPI, the input is a 32-bit header (low byte `0xAA`, bit 8 start, bit 9 reset),
twelve state words and one constraint word. The constraint word holds signed
16-bit minimum/maximum bounds in millimetres, low/high half respectively; a zero
word requests compiled defaults. The response is `0xFFFFFFFF` followed by four
command words. `io2` signals readiness. Keep chip select asserted through receive,
compute and response. Words shift MSB first, with receive on rising SCK and
transmit on falling SCK; confirm byte packing in the host firmware.


## SPI transaction and sensing timing

The companion firmware's `src/fpga_controller.c`
implements a pipelined exchange in `controllerOutOfTree`:

1. At each scheduled 1 kHz callback, decode any received obstacle command and
   prepare the current state packet.
2. Poll `io2`, then clock out the previous solve's ready word (`0xFFFFFFFF`)
   and four motor commands.
3. Deassert chip select, wait 1 us, reassert it, and send the next 56-byte
   request. The FPGA solves this request while chip select remains asserted.
4. Return the previously received commands to the flight stack. The new
   request's result is read on the following callback.

Initialization sends a dummy request to prime this exchange. In steady state, 
the result consumed at callback `n` corresponds to the request sent at 
callback `n-1`.

The firmware selects `SPI_BAUDRATE_12MHZ`. The minimum steady-state payload is
56 request bytes plus 4 ready bytes and 16 result bytes: 608 clocked bits.
At a 12 MHz wire clock this takes about 50.7 us, excluding software/DMA setup,
ready polling, extra synchronization bytes, and the 1 us chip-select gap.
Empirical measures estimate that the whole communication procedure takes 100 us.

The experiments use a 120 Hz motion-capture stream (nominal frame interval
8.33 ms) and a 1 kHz MPC invocation rate. Each FPGA request uses the latest
onboard state estimation; it does not wait for a new motion-capture frame.
The firmware retains the latest received world-frame obstacle bounds until
another constraint command arrives, converts them to the controller's relative
position frame, and includes them in each request. There is no obstacle-motion
extrapolation or age-based expiry in this controller. The `(0,0)` command
selects compiled defaults. Bounds and state are held fixed throughout a solve.