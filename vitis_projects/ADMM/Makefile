# Makefile for Vitis HLS project

PROJECT = ADMM
CONFIG = hls_config.cfg
WORK_DIR = $(PROJECT)
CONFIG_DDR = hls_config_ddr.cfg
WORK_DIR_DDR = ADMM_ddr
CONFIG_LOADER = hls_config_loader.cfg
WORK_DIR_LOADER = matrix_loader

# Source files for dependency tracking
SOURCES = ADMM.cpp ADMM.h ADMM_ddr.cpp ADMM_ddr.h matrix_loader.cpp matrix_loader.h data_types.h data.h solver_constants.h matrix_layout.h matrix_blob_sim.h

.PHONY: all clean build csim cosim export help ip \
	build-ddr csim-ddr cosim-ddr export-ddr ip-ddr \
	build-loader csim-loader cosim-loader export-loader ip-loader

# Default target
all: build export

# Help target
help:
	@echo "Available targets:"
	@echo "  csim    - Run C simulation"
	@echo "  build   - Run C synthesis"
	@echo "  cosim   - Run C/RTL co-simulation"
	@echo "  export  - Package/export RTL"
	@echo "  ip      - Alias for build + export"
	@echo "  csim-ddr    - Run C simulation for ADMM_solver_ddr"
	@echo "  build-ddr   - Run C synthesis for ADMM_solver_ddr"
	@echo "  cosim-ddr   - Run C/RTL co-sim for ADMM_solver_ddr"
	@echo "  export-ddr  - Package/export ADMM_solver_ddr RTL"
	@echo "  ip-ddr      - Alias for DDR solver build + export"
	@echo "  csim-loader   - Run C simulation for matrix_loader"
	@echo "  build-loader  - Run C synthesis for matrix_loader"
	@echo "  cosim-loader  - Run C/RTL co-sim for matrix_loader"
	@echo "  export-loader - Package/export matrix_loader RTL"
	@echo "  ip-loader     - Alias for matrix_loader build + export"
	@echo "  clean   - Remove build directory"
	@echo "  test    - Run full flow"

# C Simulation
csim:
	vitis-run --mode hls --csim --config ./$(CONFIG) --work_dir $(WORK_DIR)

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

# DDR solver targets
csim-ddr:
	vitis-run --mode hls --csim --config ./$(CONFIG_DDR) --work_dir $(WORK_DIR_DDR)

build-ddr:
	v++ -c --mode hls --config ./$(CONFIG_DDR) --work_dir $(WORK_DIR_DDR)

cosim-ddr:
	vitis-run --mode hls --cosim --config ./$(CONFIG_DDR) --work_dir $(WORK_DIR_DDR)

export-ddr:
	vitis-run --mode hls --package --config ./$(CONFIG_DDR) --work_dir $(WORK_DIR_DDR)

ip-ddr: build-ddr export-ddr

# Loader targets
csim-loader:
	vitis-run --mode hls --csim --config ./$(CONFIG_LOADER) --work_dir $(WORK_DIR_LOADER)

build-loader:
	v++ -c --mode hls --config ./$(CONFIG_LOADER) --work_dir $(WORK_DIR_LOADER)

cosim-loader:
	vitis-run --mode hls --cosim --config ./$(CONFIG_LOADER) --work_dir $(WORK_DIR_LOADER)

export-loader:
	vitis-run --mode hls --package --config ./$(CONFIG_LOADER) --work_dir $(WORK_DIR_LOADER)

ip-loader: build-loader export-loader

# Clean
clean:
	rm -rf $(WORK_DIR) .Xil *.log *.jou
	rm -rf $(WORK_DIR_DDR) $(WORK_DIR_LOADER)

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
