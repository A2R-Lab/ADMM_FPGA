# Makefile for Vitis HLS project

PROJECT = ADMM
CONFIG = hls_config.cfg
WORK_DIR = $(PROJECT)

.PHONY: all clean build csim cosim export help

# Default target
all: build

# Help target
help:
	@echo "Available targets:"
	@echo "  csim    - Run C simulation"
	@echo "  build   - Run C synthesis"
	@echo "  cosim   - Run C/RTL co-simulation"
	@echo "  export  - Package/export RTL"
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

# Clean
clean:
	rm -rf $(WORK_DIR) .Xil *.log *.jou

# Full test flow
test: clean csim build cosim
	@echo "✓ Full test flow completed!"

# Show reports
report:
	@echo "=== Synthesis Report ==="
	@find $(WORK_DIR) -name "*csynth.rpt" -exec cat {} \; | grep -A 20 "Performance"
	@echo ""
	@echo "=== Cosim Report ==="
	@find $(WORK_DIR) -name "*cosim.rpt" -exec cat {} \;
