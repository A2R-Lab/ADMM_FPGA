# ADMM_FPGA

This repository contains the FPGA implementation of an ADMM (Alternating Direction Method of Multipliers) solver developed for real-time linear Model Predictive Control (MPC) on the Crazyflie quadrotor platform.

The project targets an AMD Xilinx Artix-7 100T FPGA and includes the HLS solver, the FPGA integration files, and support scripts used to build and program the design.

## Project Information

This work was developed within the master's thesis:

*Hardware-Algorithm Co-Design for Real-Time Linear Model Predictive Control. FPGA Implementation and Deployment on a Resource-Constrained Quadrotor*

Author: Andrea Grillo  
Period: 2025-2026

## Design Flow

The development flow for this project is managed through the provided Makefiles:

1. Python scripts generate the matrices and headers used by the solver.
2. The ADMM solver is synthesized with Vitis HLS.
3. The generated IP is integrated in the full FPGA design and built in Vivado.
4. An Arduino-based SPI test can be used for standalone communication checks.
5. The final deployment target is the Crazyflie platform, using the companion firmware available here: [crazyflie_fpga_firmware](https://github.com/A2R-Lab/crazyflie_fpga_firmware).

## Repository Contents

- `vitis_projects/ADMM/`: Vitis HLS project containing the ADMM solver implementation and testbench
- `vivado_project/`: Vivado project with the top-level FPGA design, SPI/UART modules, constraints, and generated IP
- `scripts/`: build, programming, simulation, and data/header generation scripts
- `arduino_spi_test/`: simple Arduino sketch used for SPI communication tests
- `Makefile`: top-level build flow for HLS, Vivado, bitstream generation, and programming

## Related Repositories

- FPGA deck hardware repository: [Crazyflie_FPGA_Deck](https://github.com/A2R-Lab/Crazyflie_FPGA_Deck)
- Crazyflie firmware repository: [crazyflie_fpga_firmware](https://github.com/A2R-Lab/crazyflie_fpga_firmware)
