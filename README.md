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
- **Interface:** SPI slave (custom PCB) or UART (Arty A7)

## Project Structure

```
ADMM_FPGA/
├── Makefile                    # Top-level build system
├── README.md
├── scripts/
│   ├── header_generator.py     # Generates ADMM matrices as C headers
│   ├── ddr_fetch_overhead.py   # DDR traffic/latency estimator
│   ├── crazyloihimodel.py      # Quadrotor dynamics model
│   ├── synth.tcl               # Vivado synthesis script
│   ├── impl.tcl                # Vivado implementation script
│   ├── bitstream.tcl           # Bitstream generation script
│   ├── create_arty_ddr_bd.tcl  # DDR block-design bootstrap (MIG + AXI + HLS IP)
│   ├── program.tcl             # JTAG programming script
│   └── program_flash.tcl       # SPI flash programming script
├── vitis_projects/
│   └── ADMM/
│       ├── ADMM.cpp            # HLS ADMM solver implementation
│       ├── ADMM_ddr.cpp        # DDR-backed HLS ADMM solver
│       ├── ADMM.h              # Solver header
│       ├── ADMM_ddr.h          # DDR solver header
│       ├── ADMM_test.cpp       # HLS testbench
│       ├── ADMM_ddr_test.cpp   # DDR solver testbench
│       ├── matrix_loader.cpp   # Flash->DDR preload kernel
│       ├── matrix_loader.h     # Loader kernel header
│       ├── data_types.h        # Fixed-point type definitions
│       ├── hls_config.cfg      # Vitis HLS configuration
│       ├── hls_config_ddr.cfg  # DDR solver HLS config
│       ├── hls_config_loader.cfg # Loader HLS config
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

### Board Selection

Builds can target either the **custom PCB** (SPI) or the **Arty A7** (UART):

```bash
# Custom PCB: top_spi, constraints.xdc (default)
make BOARD=custom

# Arty A7: top (UART), constraints_arty_a7.xdc
make BOARD=arty
```

If `BOARD` is omitted, `BOARD=custom` is used. The bitstream is named after the top module (`top_spi.bit` or `top.bit`).

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
| `make matrix-blob` | Generate packed `build/matrices.bin` + layout headers |
| `make hls` | Build HLS IP only |
| `make hls-ddr` | Build DDR-backed solver HLS IP (`ADMM_solver_ddr`) |
| `make hls-loader` | Build matrix loader HLS IP (`matrix_loader`) |
| `make estimate-ddr` | Estimate DDR fetch overhead from generated layout/constants |
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

When `build/matrices.bin` exists, flash images now include both:
- bitstream at `0x00000000`
- matrix payload at `0x00600000`

This enables hardware boot preload flows (QSPI -> DDR) without host matrix upload.

## SPI Protocol

### Communication Format

- **Word size:** 24 bits
- **Mode:** SPI Mode 0 (CPOL=0, CPHA=0)
- **Byte order:** MSB first

### Transaction Sequence

1. **Master sends header:** `0x0000AA` (1 word)
2. **Master sends state:** 12 words (current quadrotor state)
3. **FPGA computes:** MISO held low during computation
4. **FPGA sends header:** `0xFFFFFF` (ready signal)
5. **FPGA sends results:** 4 words (control inputs)

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

### DDR Solver / Loader HLS Flow

```bash
# Generate data.h + DDR matrix blob artifacts
make headers

# Build/export DDR-based solver kernel
make hls-ddr

# Build/export matrix preload kernel (QSPI->DDR copy path)
make hls-loader

# Optional C simulations
make sim-ddr
make sim-loader

# Estimate external-memory overhead from generated dimensions
make estimate-ddr
```

Vivado DDR block-design bootstrap script:

```bash
vivado -mode batch -source scripts/create_arty_ddr_bd.tcl
```

This script expects a board-specific MIG config file at `scripts/mig_arty_a7.prj`.
An example placeholder is provided at `scripts/mig_arty_a7.prj.example`.

### Generating `scripts/mig_arty_a7.prj` (Arty A7)

If Digilent board files are installed locally, copy the reference file directly:

```bash
cp /home/agrillo/amdfpga/vivado-boards/new/board_files/arty-a7-100/E.0/1.1/mig.prj \
   scripts/mig_arty_a7.prj
```

Then run the full DDR BD bootstrap:

```bash
source ~/venv/bin/activate
make headers
make hls-ddr
make hls-loader
vivado -mode batch -source scripts/create_arty_ddr_bd.tcl
```

Generated block design:
- `build/ddr_bd/ddr_bd.srcs/sources_1/bd/admm_ddr_system/admm_ddr_system.bd`

If you must generate `mig.prj` manually in Vivado:
1. Create/configure a `mig_7series` IP for Arty A7 DDR3.
2. In MIG customization, export/save the MIG project file (`.prj`).
3. Place it at `scripts/mig_arty_a7.prj`.

### Additional Hardware Integration Needed

- Add Arty A7 board constraints (XDC) for:
  - DDR3 interface pins from MIG (`DDR3` interface)
  - MIG clocks/resets (`ddr_ref_clk`, `ddr_sys_rst`)
  - QSPI pins (`ext_spi_clk` + `SPI_0` I/O)
  - Runtime control/status pins for `matrix_loader` and `ADMM_solver_ddr`
- Create top-level control logic/FSM:
  - wait `init_calib_complete`
  - assert loader `ap_start` once with `flash_blob`, `ddr_blob`, `word_count`
  - wait loader `ap_done`
  - run solver on each runtime command
- Flash layout:
  - bitstream at `0x00000000`
  - matrix blob at `0x00600000` (`build/matrices.bin`)

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

Additional generated DDR artifacts:
- `vitis_projects/ADMM/solver_constants.h`
- `vitis_projects/ADMM/matrix_layout.h`
- `vitis_projects/ADMM/matrix_blob_sim.h`
- `build/matrices.bin`

### Changing Fixed-Point Format

Edit `vitis_projects/ADMM/data_types.h`:

```cpp
typedef ap_fixed<32, 10, AP_RND, AP_SAT> fp_t;
//              │   │
//              │   └── Integer bits (including sign)
//              └────── Total bits
```

### Changing Iteration Count and Hover Thrust

Iteration count and hover thrust are generated into `data.h` by `scripts/header_generator.py`:

- **ADMM_ITERS:** number of ADMM iterations (e.g. `50`)
- **U_HOVER:** hover thrust added to the four command outputs

Edit `header_generator.py` (e.g. set `ADMM_ITERS = 50`, and `U_HOVER` comes from `ug[0]`), then run `make headers` and rebuild.

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
