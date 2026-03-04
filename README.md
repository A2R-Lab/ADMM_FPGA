# ADMM FPGA

FPGA implementation of an ADMM (Alternating Direction Method of Multipliers) solver for Model Predictive Control (MPC) on a quadrotor. The solver runs on an Artix-7 FPGA and communicates with an external controller via SPI.

## Overview

This project implements a real-time convex optimization solver using ADMM, targeting the Crazyflie quadrotor control problem. The FPGA receives the current state via SPI, computes optimal control inputs, and returns the results.

**Key Features:**
- Fixed-point arithmetic (32-bit, Q10.22 format)
- Configurable iteration count
- SPI slave interface for communication
- 100 MHz system clock
- ~50 Hz control loop capability

## Hardware

- **FPGA:** Xilinx Artix-7 XC7A100T-CSG324
- **Clock:** 100 MHz
- **Interface:** SPI slave (directly from crazyflie)

## Project Structure

```
ADMM_FPGA/
├── Makefile                    # Top-level build system
├── README.md
├── scripts/
│   ├── header_generator.py     # Generates ADMM matrices as C headers
│   ├── crazyloihimodel.py      # Quadrotor dynamics model
│   ├── synth.tcl               # Vivado synthesis script
│   ├── impl.tcl                # Vivado implementation script
│   ├── bitstream.tcl           # Bitstream generation script
│   ├── program.tcl             # JTAG programming script
│   └── program_flash.tcl       # SPI flash programming script
├── vitis_projects/
│   └── ADMM/
│       ├── ADMM.cpp            # HLS ADMM solver implementation
│       ├── ADMM.h              # Solver header
│       ├── ADMM_test.cpp       # HLS testbench
│       ├── data_types.h        # Fixed-point type definitions
│       ├── hls_config.cfg      # Vitis HLS configuration
│       └── Makefile            # HLS build makefile
├── vivado_project/
│   └── vivado_project.srcs/
│       ├── sources_1/new/
│       │   ├── top_spi.v       # Top-level module (SPI interface)
│       │   ├── spi_slave.v     # SPI slave implementation
│       │   └── spi_slave_word.v# Word-based SPI interface
│       └── constrs_1/new/
│           └── constraints.xdc # Pin assignments and timing
└── build/                      # Build outputs (generated)
    ├── top_spi.bit             # FPGA bitstream
    ├── top_spi.bin             # SPI flash image
    ├── reports/                # Utilization and timing reports
    └── logs/                   # Build logs
```

## Prerequisites

### Required Tools

| Tool | Version | Purpose |
|------|---------|---------|
| Vivado | 2024.x or 2025.x | FPGA synthesis and implementation |
| Vitis HLS | 2024.x or 2025.x | High-Level Synthesis |
| Python | 3.8+ | Header generation |
| NumPy | - | Matrix computations |

### Environment Setup

```bash
# Source Vivado/Vitis environment (adjust path as needed)
source /opt/Xilinx/Vivado/2025.2/settings64.sh

# Install Python dependencies
pip install numpy
```

## Building

### Quick Start

```bash
# Full build: headers → HLS → Vivado → bitstream
make
```

### Build Targets

| Target | Description |
|--------|-------------|
| `make` or `make all` | Full build from scratch |
| `make headers` | Generate `data.h` from Python |
| `make hls` | Build HLS IP only |
| `make vivado` | Vivado synthesis + implementation |
| `make bit` | Generate bitstream (requires impl) |
| `make program` | Program FPGA via JTAG |
| `make flash` | Write to SPI flash |
| `make clean` | Clean Vivado build artifacts |
| `make clean-hls` | Clean HLS build artifacts |
| `make clean-all` | Clean everything |
| `make report` | Show utilization and timing |
| `make help` | Show all targets |

### Incremental Builds

The Makefile tracks dependencies automatically:

- Changing `ADMM.cpp` → rebuilds HLS, then Vivado
- Changing `top_spi.v` → rebuilds Vivado only (skips HLS)
- Changing `header_generator.py` → rebuilds everything

### Build Outputs

After a successful build:

```
build/
├── top_spi.bit          # Bitstream for JTAG programming
├── top_spi.bin          # Binary for SPI flash
├── post_synth.dcp       # Synthesis checkpoint
├── post_route.dcp       # Routed checkpoint
├── reports/
│   ├── post_synth_utilization.rpt
│   ├── post_route_utilization.rpt
│   ├── post_route_timing.rpt
│   └── post_route_power.rpt
└── logs/
    ├── synth.log
    ├── impl.log
    └── bitstream.log
```

## Programming the FPGA

### Via JTAG (Volatile)

```bash
make program
```

The design is lost on power cycle.

### Via SPI Flash (Persistent)

```bash
make flash
```

The FPGA will boot from flash on power-up. Power cycle the board after programming.

## SPI Protocol

### Communication Format

- **Word size:** 32 bits
- **Mode:** SPI Mode 0 (CPOL=0, CPHA=0)
- **Byte order:** MSB first

### Transaction Sequence

1. **Master sends header:** `0x0000AA` (1 word)
2. **Master sends state:** 12 words (current quadrotor state)
3. **FPGA computes:** MISO held low during computation
4. **FPGA sends header:** `0xFFFFFF` (ready signal)
5. **FPGA sends results:** 4 words (control inputs)

`start_traj` is encoded in the header word:
- Base header: `0x000000AA` (regulator mode)
- Start trajectory: set header bit `0x00000100` (example: `0x000001AA`)

### LED Indicators

| LED1 | LED2 | State |
|------|------|-------|
| OFF | OFF | Idle |
| OFF | ON | Receiving data |
| ON | OFF | Computing |
| ON | ON | Transmitting results |

## HLS Development

### Running C Simulation

```bash
cd vitis_projects/ADMM
make csim
```

### Running Co-Simulation

```bash
cd vitis_projects/ADMM
make cosim
```

### Viewing HLS Reports

```bash
cd vitis_projects/ADMM
make report
```

## Customization

### Changing ADMM Parameters

Edit `scripts/header_generator.py`:

```python
N = 20              # Horizon length
rho = 256           # ADMM penalty parameter
timer_period = 0.02 # Control frequency (50 Hz)
```

Then rebuild:

```bash
make clean-all
make
```

### Encoding Trajectory In FPGA

Trajectory generation and packing are split into two deterministic steps:
- `scripts/trajectory_generator.py` writes `vitis_projects/ADMM/trajectory_refs.csv`
- `scripts/trajectory_generator.py` also writes `vitis_projects/ADMM/traj_data.h`
- `scripts/header_generator.py` only generates solver/model header data (`vitis_projects/ADMM/data.h`)

Generated arrays:
- `traj_q_packed[TRAJ_LENGTH + HORIZON_LENGTH][STATE_SIZE + INPUT_SIZE]`

`traj_q_packed` is preweighted offline (`-Q*x_ref`, `-R*u_ref`) and packed as stage blocks.
At runtime, `start_traj` (header bit `0x00000100`) latches trajectory mode and the solver only shifts a pointer into `traj_q_packed`.

### Changing Fixed-Point Format

Edit `vitis_projects/ADMM/data_types.h`:

```cpp
typedef ap_fixed<32, 10, AP_RND, AP_SAT> fp_t;
//              │   │
//              │   └── Integer bits (including sign)
//              └────── Total bits
```

### Trajectory Start Command

In `vivado_project/vivado_project.srcs/sources_1/new/top_spi.v`:

```verilog
// Header bit mask:
localparam START_TRAJ_MASK = 32'h00000100;
```

Set this bit in the header word to latch trajectory mode start.

## Troubleshooting

### Build Fails at HLS Stage

- Ensure `data.h` exists: `make headers`
- Check HLS logs: `vitis_projects/ADMM/ADMM/vitis_hls.log`

### Timing Not Met

- Check `build/reports/post_route_timing.rpt`
- Consider reducing clock frequency or adding pipeline stages

### FPGA Not Responding

1. Check LED indicators
2. Verify SPI wiring and clock polarity
3. Ensure CS is pulled low during transaction
4. Check that header byte `0xAA` is sent first

### Flash Programming Fails

- Verify the flash part in `scripts/program_flash.tcl`
- Common parts: `s25fl128sxxxxxx0`, `n25q128-3.3v-spi-x1_x2_x4`

## License

MIT License

## References

- [OSQP: Operator Splitting Solver for Quadratic Programs](https://osqp.org/)
- [Crazyflie 2.1 Documentation](https://www.bitcraze.io/documentation/)
- [Xilinx Vitis HLS User Guide](https://docs.xilinx.com/r/en-US/ug1399-vitis-hls)
