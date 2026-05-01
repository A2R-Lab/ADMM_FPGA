# Makefile for Vitis HLS project

PROJECT = ADMM
CONFIG = hls_config.cfg
WORK_DIR = $(PROJECT)

# Source files for dependency tracking
SOURCES = ADMM.cpp ADMM.h data_types.h data.h

.PHONY: all clean build csim cosim export help ip

# Default target
all: build export

# Help target
help:
	@echo "Available targets:"
	@echo "  csim    - Run C simulation"
	@echo "  csim-rho - Run rho/accumulator C simulation testbench"
	@echo "  csim-uart-smoke - Run one-shot ADMM_solver smoke testbench"
	@echo "  csim-closed-loop - Run fixed-point closed-loop C simulation"
	@echo "  csim-closed-loop-strict - Run fixed-point closed-loop C simulation and fail on early stop"
	@echo "  build-uart-smoke - Run HLS synthesis for one-shot ADMM_solver smoke testbench"
	@echo "  cosim-uart-smoke - Run one-shot ADMM_solver RTL co-simulation smoke testbench"
	@echo "  build-closed-loop - Run HLS synthesis for closed-loop testbench"
	@echo "  cosim-closed-loop - Run fixed-point closed-loop RTL co-simulation"
	@echo "  build   - Run C synthesis"
	@echo "  cosim   - Run C/RTL co-simulation"
	@echo "  export  - Package/export RTL"
	@echo "  ip      - Alias for build + export"
	@echo "  clean   - Remove build directory"
	@echo "  test    - Run full flow"

# C Simulation
csim:
	vitis-run --mode hls --csim --config ./$(CONFIG) --work_dir $(WORK_DIR)

csim-rho:
	vitis-run --mode hls --csim --config ./hls_rho_tb_config.cfg --work_dir ADMM_rho_tb

csim-uart-smoke:
	vitis-run --mode hls --csim --config ./hls_uart_smoke_config.cfg --work_dir ADMM_uart_smoke

csim-closed-loop:
	ADMM_SIM_FREQ=100 ADMM_SIM_DURATION_S=2 ADMM_TRAJ_START_STEP=50 ADMM_CSIM_TRAJ_PATH=trajectory_csim.csv vitis-run --mode hls --csim --config ./hls_eval_config.cfg --work_dir ADMM_closed_loop

csim-closed-loop-strict:
	ADMM_FAIL_ON_EARLY_STOP=1 ADMM_SIM_FREQ=100 ADMM_SIM_DURATION_S=2 ADMM_TRAJ_START_STEP=50 ADMM_CSIM_TRAJ_PATH=trajectory_csim.csv vitis-run --mode hls --csim --config ./hls_eval_config.cfg --work_dir ADMM_closed_loop

build-uart-smoke:
	v++ -c --mode hls --config ./hls_uart_smoke_config.cfg --work_dir ADMM_uart_smoke

cosim-uart-smoke: build-uart-smoke
	vitis-run --mode hls --cosim --config ./hls_uart_smoke_config.cfg --work_dir ADMM_uart_smoke

build-closed-loop:
	v++ -c --mode hls --config ./hls_eval_config.cfg --work_dir ADMM_closed_loop

cosim-closed-loop: build-closed-loop
	ADMM_SIM_FREQ=100 ADMM_SIM_DURATION_S=2 ADMM_TRAJ_START_STEP=50 ADMM_CSIM_TRAJ_PATH=trajectory_cosim.csv vitis-run --mode hls --cosim --config ./hls_eval_config.cfg --work_dir ADMM_closed_loop

# C Synthesis - use v++ instead
build:
	v++ -c --mode hls --config ./$(CONFIG) --work_dir $(WORK_DIR)

# C/RTL Co-simulation
cosim:
	vitis-run --mode hls --cosim --config ./$(CONFIG) --work_dir $(WORK_DIR)

# Package/Export RTL
export:
	vitis-run --mode hls --package --config ./$(CONFIG) --work_dir $(WORK_DIR)

# Convenience target for full IP generation
ip: build export

# Clean
clean:
	rm -rf $(WORK_DIR) .Xil *.log *.jou

# Full test flow
test: clean csim build cosim
	@echo "Full test flow completed!"

# Show reports
report:
	@echo "=== Synthesis Report ==="
	@find $(WORK_DIR) -name "*csynth.rpt" -exec cat {} \; | grep -A 20 "Performance"
	@echo ""
	@echo "=== Cosim Report ==="
	@find $(WORK_DIR) -name "*cosim.rpt" -exec cat {} \;
