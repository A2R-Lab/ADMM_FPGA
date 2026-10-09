# ADMM_FPGA

This repository contains the FPGA implementation of an ADMM (Alternating Direction Method of Multipliers) solver developed for real-time linear Model Predictive Control (MPC) on the Crazyflie quadrotor platform.

The project targets an AMD Xilinx Artix-7 100T FPGA and includes the HLS solver, the FPGA integration files, and support scripts used to build and program the design.

## Design Flow

The development flow for this project is managed through the provided Makefiles:

1. Python scripts generate the matrices and headers used by the solver.
2. The ADMM solver is synthesized with Vitis HLS.
3. The generated IP is integrated in the full FPGA design and built in Vivado.
4. An Arduino-based SPI test can be used for standalone communication checks.
5. The final deployment target is the Crazyflie platform, using the companion firmware in the `crazyflie_fpga_firmware` component.

## Repository Contents

- `vitis_projects/ADMM/`: Vitis HLS project containing the ADMM solver implementation and testbench
- `vivado_project/`: Vivado project with the top-level FPGA design, SPI/UART modules, constraints, and generated IP
- `scripts/`: build, programming, simulation, and data/header generation scripts
- `experiments/`: configuration sweeps and the Slurm batch scripts used to run them on a cluster
- `Makefile`: top-level build flow for HLS, Vivado, bitstream generation, and programming

## Related Components

- FPGA deck hardware: `Crazyflie_FPGA_Deck`
- Crazyflie firmware: `crazyflie_fpga_firmware`
