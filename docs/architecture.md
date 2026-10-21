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
| Model and settings | [parameters.py](../scripts/parameters.py), [crazyloihimodel.py](../scripts/crazyloihimodel.py) | Horizon, costs, bounds, dynamics and trajectory settings |
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
