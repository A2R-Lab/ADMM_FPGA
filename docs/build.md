# Build and program

Run commands from the repository root. The build flow uses Linux, AMD Vivado
and Vitis **2025.2** with Artix-7 support, GNU Make, a C++14 compiler, and Python
**3.11**. Install the JTAG cable drivers for programming.

## Environment

Install SuiteSparse/CHOLMOD and Python development headers before installing
the Python dependencies. On Debian/Ubuntu the system packages are
`build-essential`, `python3-dev`, `python3-venv` and `libsuitesparse-dev`.

```bash
source /path/to/Vivado/settings64.sh
source /path/to/Vitis/settings64.sh
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install -r scripts/requirements.txt
```

## Build

| `BOARD` | Interface and purpose | Top module |
|---|---|---|
| `custom` (default) | Crazyflie deck, SPI | `top_spi` |
| `arty` | Arty A7, UART solver testing | `top_uart` |
| `arty-power` | Arty A7-100T Rev E, power measurements | `top_uart_power` |

```bash
make BOARD=custom
```

The Makefile generates headers and trajectory data, exports the HLS solver,
runs Vivado synthesis and implementation, and writes `build/top_spi.bit`.
Reports are in `build/reports/`. The command-line build uses Vivado's non-project
flow; opening the checked-in GUI project is not required.

Solver settings are defined in [parameters.py](../scripts/parameters.py).
The defaults are staged-A, horizon 27, nine ADMM iterations, fixed point and
an enabled trajectory generator. Set overrides as **environment variables**:

```bash
export ADMM_SOLVER_ARCH=full_sparse ADMM_HORIZON_LENGTH=40 ADMM_ITERATIONS=10
python scripts/trajectory_generator.py
python scripts/header_generator.py
make BOARD=custom
```

Make does not track environment changes: rerun both generators when changing
settings. Check for unintended `ADMM_*` overrides in the shell.
Use separate worker directories for concurrent configurations; the benchmark
runners manage these. A single checkout shares generated headers and HLS outputs.

## Simulate and program

```bash
make sim-csim                    # Solver C simulation
make sim-cosim                   # C/RTL co-simulation
make hls_closed_loop_sim         # Closed-loop simulation and plots
make BOARD=custom program        # Load the existing bitstream over JTAG
```

C simulation regenerates `test_data.h` using a double-precision ADMM reference
at the selected iteration count. It compares four controls for one cold-start
input; this checks implementation agreement, not convergence to the QP optimum.
The C/RTL target synthesizes the matching configuration before comparison.

`program` selects the first available JTAG target/device; connect the intended
board only. It loads volatile FPGA configuration. `make BOARD=custom flash`
writes persistent SPI flash. Neither programming target builds a new bitstream.

For an explicit artifact, use
`make program-file BITSTREAM_FILE=/path/to/design.bit`. For server builds,
`make sync REMOTE=user@host:/path/to/ADMM_FPGA` retrieves `build/` before local
programming. Run `make help` for the remaining targets.

For power acquisition, use the [campaign guide](power.md), which binds each
measurement to its bitstream and workload.
