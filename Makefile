# =============================================================================
# ADMM FPGA - Top-Level Makefile
# =============================================================================
# Targets:
#   all       - Build everything (headers -> HLS -> Vivado -> bitstream)
#   headers   - Generate data.h from Python script
#   matrix-blob - Generate packed matrix blob and layout headers
#   hls       - Build HLS IP
#   hls-ddr   - Build DDR-based solver HLS IP
#   hls-loader - Build matrix loader HLS IP
#   vivado    - Run Vivado synthesis + implementation
#   bit       - Generate bitstream only (assumes impl done)
#   program   - Program FPGA via JTAG
#   flash     - Write to SPI flash
#   sync      - Rsync build/ from remote (for build-on-server, program-local workflow)
#   sim       - Run Vitis HLS C simulation (quick)
#   sim-csim  - Run Vitis HLS C simulation
#   sim-cosim - Run Vitis HLS C/RTL co-simulation
#   clean     - Clean Vivado build artifacts
#   clean-hls - Clean HLS build artifacts
#   clean-all - Clean everything
# =============================================================================

# Configuration
BOARD        ?= custom

PART          := xc7a100tcsg324-1

ifeq ($(BOARD),arty)
TOP_MODULE    := top
else
TOP_MODULE    := top_spi
endif
# For sync: remote repo path, e.g. user@host:~/ADMM_FPGA (path must exist on server)
REMOTE       ?=
# Optional SSH port for sync (default 22): make sync REMOTE=... SSH_PORT=2222
SSH_PORT     ?=
RSYNC_SSH    := $(if $(SSH_PORT),-e "ssh -p $(SSH_PORT)",)
VIVADO        := vivado
VITIS_HLS     := v++
PYTHON        := python3

# Directories
PROJ_ROOT     := $(shell pwd)
SCRIPTS_DIR   := $(PROJ_ROOT)/scripts
BUILD_DIR     := $(PROJ_ROOT)/build
HLS_DIR       := $(PROJ_ROOT)/vitis_projects/ADMM
HLS_WORK_DIR  := $(HLS_DIR)/ADMM
HLS_DDR_WORK_DIR := $(HLS_DIR)/ADMM_ddr
HLS_LOADER_WORK_DIR := $(HLS_DIR)/matrix_loader
RTL_DIR       := $(PROJ_ROOT)/vivado_project/vivado_project.srcs/sources_1/new
XDC_DIR       := $(PROJ_ROOT)/vivado_project/vivado_project.srcs/constrs_1/new
IP_DIR        := $(PROJ_ROOT)/vivado_project/vivado_project.gen/sources_1/ip/ADMM_solver_0
DDR_BD_DIR    := $(BUILD_DIR)/ddr_bd

# Source files
HLS_SOURCES   := $(HLS_DIR)/ADMM.cpp $(HLS_DIR)/ADMM.h $(HLS_DIR)/data_types.h
RTL_SOURCES   := $(wildcard $(RTL_DIR)/*.v)
ifeq ($(BOARD),arty)
XDC_SOURCES   := $(XDC_DIR)/constraints_arty_a7.xdc
else
XDC_SOURCES   := $(XDC_DIR)/constraints.xdc
endif
HEADER_SCRIPT := $(SCRIPTS_DIR)/header_generator.py

# Generated files
DATA_HEADER   := $(HLS_DIR)/data.h
TEST_HEADER   := $(HLS_DIR)/test_data.h
SOLVER_CONSTANTS := $(HLS_DIR)/solver_constants.h
MATRIX_LAYOUT := $(HLS_DIR)/matrix_layout.h
MATRIX_BLOB_SIM := $(HLS_DIR)/matrix_blob_sim.h
MATRIX_BLOB  := $(BUILD_DIR)/matrices.bin
HLS_IP_MARKER := $(HLS_WORK_DIR)/.export_done
HLS_DDR_IP_MARKER := $(HLS_DDR_WORK_DIR)/.export_done
HLS_LOADER_IP_MARKER := $(HLS_LOADER_WORK_DIR)/.export_done
DDR_BD_DESIGN := $(DDR_BD_DIR)/ddr_bd.srcs/sources_1/bd/admm_ddr_system/admm_ddr_system.bd
DDR_BD_WRAPPER := $(DDR_BD_DIR)/ddr_bd.gen/sources_1/bd/admm_ddr_system/hdl/admm_ddr_system_wrapper.v
SYNTH_DCP     := $(BUILD_DIR)/post_synth.dcp
ROUTE_DCP     := $(BUILD_DIR)/post_route.dcp
BITSTREAM     := $(BUILD_DIR)/$(TOP_MODULE).bit
FLASH_BIN     := $(BUILD_DIR)/$(TOP_MODULE).bin

ifeq ($(BOARD),arty)
SYNTH_FLOW_DEPS := $(HLS_DDR_IP_MARKER) $(HLS_LOADER_IP_MARKER) $(DDR_BD_WRAPPER)
else
SYNTH_FLOW_DEPS := $(HLS_IP_MARKER)
endif

# =============================================================================
# Main Targets
# =============================================================================

.PHONY: all headers matrix-blob hls hls-ddr hls-loader ddr-bd vivado bit program flash sync \
	sim sim-csim sim-cosim sim-ddr sim-loader estimate-ddr clean clean-hls clean-all help

all: $(BITSTREAM)
	@echo "========================================="
	@echo "Build complete!"
	@echo "Bitstream: $(BITSTREAM)"
	@echo "Flash bin: $(FLASH_BIN)"
	@echo "========================================="

help:
	@echo "ADMM FPGA Build System"
	@echo ""
	@echo "Targets:"
	@echo "  all       - Build everything (default)"
	@echo "  headers   - Generate data.h"
	@echo "  matrix-blob - Generate packed matrix blob and layout headers"
	@echo "  hls       - Build HLS IP"
	@echo "  hls-ddr   - Build DDR-based ADMM solver HLS IP"
	@echo "  hls-loader - Build matrix preload/copy HLS IP"
	@echo "  ddr-bd    - Generate DDR block design + HDL wrapper (Arty DDR flow)"
	@echo "  vivado    - Synthesis + Implementation"
	@echo "  bit       - Generate bitstream"
	@echo "  program   - Program FPGA via JTAG"
	@echo "  flash     - Write to SPI flash"
	@echo "  sim       - Vitis HLS C simulation (quick)"
	@echo "  sim-csim  - Vitis HLS C simulation"
	@echo "  sim-cosim - Vitis HLS C/RTL co-simulation (requires HLS build)"
	@echo "  sim-ddr   - Vitis HLS C simulation for ADMM_solver_ddr"
	@echo "  sim-loader - Vitis HLS C simulation for matrix_loader"
	@echo "  estimate-ddr - Estimate DDR fetch overhead from generated layout/constants"
	@echo "  sync      - Rsync build/ from remote (e.g. make sync REMOTE=user@host:~/ADMM_FPGA [SSH_PORT=2222])"
	@echo "  clean     - Clean Vivado build"
	@echo "  clean-hls - Clean HLS build"
	@echo "  clean-all - Clean everything"
	@echo ""
	@echo "Examples:"
	@echo "  make              # Full build"
	@echo "  make hls          # Rebuild HLS only"
	@echo "  make hls-ddr      # Build DDR solver HLS IP"
	@echo "  make hls-loader   # Build matrix loader HLS IP"
	@echo "  make ddr-bd       # Generate DDR block design + wrapper"
	@echo "  make matrix-blob  # Regenerate matrices.bin + layout headers"
	@echo "  make vivado       # Rebuild Vivado only"
	@echo "  make sim          # Vitis HLS C simulation"
	@echo "  make sim-cosim    # Vitis HLS C/RTL co-simulation"
	@echo "  make program      # Program FPGA"
	@echo "  make sync REMOTE=user@host:~/ADMM_FPGA [SSH_PORT=2222]  # Fetch build from server"

# =============================================================================
# Header Generation
# =============================================================================

headers: $(DATA_HEADER) $(SOLVER_CONSTANTS) $(MATRIX_LAYOUT) $(MATRIX_BLOB_SIM) $(MATRIX_BLOB)

matrix-blob: headers

$(DATA_HEADER): $(HEADER_SCRIPT) $(SCRIPTS_DIR)/crazyloihimodel.py
	@echo "========================================="
	@echo "Generating headers..."
	@echo "========================================="
	@mkdir -p $(BUILD_DIR)
	cd $(SCRIPTS_DIR) && $(PYTHON) header_generator.py
	@touch $(DATA_HEADER)

$(SOLVER_CONSTANTS) $(MATRIX_LAYOUT) $(MATRIX_BLOB_SIM) $(MATRIX_BLOB) $(TEST_HEADER): $(DATA_HEADER)
	@true

# =============================================================================
# HLS Build
# =============================================================================

hls: $(HLS_IP_MARKER)

$(HLS_IP_MARKER): $(HLS_SOURCES) $(DATA_HEADER)
	@echo "========================================="
	@echo "Building HLS IP..."
	@echo "========================================="
	cd $(HLS_DIR) && $(MAKE) build
	cd $(HLS_DIR) && $(MAKE) export
	@mkdir -p $(dir $(HLS_IP_MARKER))
	@touch $(HLS_IP_MARKER)

hls-ddr: $(HLS_DDR_IP_MARKER)

$(HLS_DDR_IP_MARKER): $(HLS_DIR)/ADMM_ddr.cpp $(HLS_DIR)/ADMM_ddr.h $(HLS_DIR)/ADMM_ddr_test.cpp $(SOLVER_CONSTANTS) $(MATRIX_LAYOUT) $(MATRIX_BLOB_SIM) $(TEST_HEADER)
	@echo "========================================="
	@echo "Building DDR Solver HLS IP..."
	@echo "========================================="
	cd $(HLS_DIR) && $(MAKE) build-ddr
	cd $(HLS_DIR) && $(MAKE) export-ddr
	@mkdir -p $(dir $(HLS_DDR_IP_MARKER))
	@touch $(HLS_DDR_IP_MARKER)

hls-loader: $(HLS_LOADER_IP_MARKER)

$(HLS_LOADER_IP_MARKER): $(HLS_DIR)/matrix_loader.cpp $(HLS_DIR)/matrix_loader.h $(HLS_DIR)/matrix_loader_test.cpp $(MATRIX_LAYOUT) $(MATRIX_BLOB_SIM)
	@echo "========================================="
	@echo "Building Matrix Loader HLS IP..."
	@echo "========================================="
	cd $(HLS_DIR) && $(MAKE) build-loader
	cd $(HLS_DIR) && $(MAKE) export-loader
	@mkdir -p $(dir $(HLS_LOADER_IP_MARKER))
	@touch $(HLS_LOADER_IP_MARKER)

ddr-bd: $(DDR_BD_WRAPPER)

$(DDR_BD_DESIGN): $(SCRIPTS_DIR)/create_arty_ddr_bd.tcl $(SCRIPTS_DIR)/mig_arty_a7.prj $(HLS_DDR_IP_MARKER) $(HLS_LOADER_IP_MARKER)
	@echo "========================================="
	@echo "Generating DDR block design..."
	@echo "========================================="
	$(VIVADO) -mode batch \
		-source $(SCRIPTS_DIR)/create_arty_ddr_bd.tcl \
		-notrace

$(DDR_BD_WRAPPER): $(DDR_BD_DESIGN) $(SCRIPTS_DIR)/generate_ddr_wrapper.tcl
	@echo "========================================="
	@echo "Generating DDR block design wrapper..."
	@echo "========================================="
	$(VIVADO) -mode batch \
		-source $(SCRIPTS_DIR)/generate_ddr_wrapper.tcl \
		-notrace

# =============================================================================
# Vivado Build
# =============================================================================

vivado: $(ROUTE_DCP)

# Synthesis
$(SYNTH_DCP): $(RTL_SOURCES) $(XDC_SOURCES) $(SYNTH_FLOW_DEPS)
	@echo "========================================="
	@echo "Running Vivado Synthesis (BOARD=$(BOARD), TOP=$(TOP_MODULE))..."
	@echo "========================================="
	@mkdir -p $(BUILD_DIR)/logs $(BUILD_DIR)/reports
	$(VIVADO) -mode batch \
		-source $(SCRIPTS_DIR)/synth.tcl \
		-tclargs $(TOP_MODULE) $(notdir $(XDC_SOURCES)) \
		-log $(BUILD_DIR)/logs/synth.log \
		-journal $(BUILD_DIR)/logs/synth.jou \
		-notrace

# Implementation (Place & Route)
$(ROUTE_DCP): $(SYNTH_DCP)
	@echo "========================================="
	@echo "Running Vivado Implementation..."
	@echo "========================================="
	$(VIVADO) -mode batch \
		-source $(SCRIPTS_DIR)/impl.tcl \
		-log $(BUILD_DIR)/logs/impl.log \
		-journal $(BUILD_DIR)/logs/impl.jou \
		-notrace

# =============================================================================
# Bitstream Generation
# =============================================================================

bit: $(BITSTREAM)

$(BITSTREAM): $(ROUTE_DCP)
	@echo "========================================="
	@echo "Generating Bitstream ($(TOP_MODULE))..."
	@echo "========================================="
	$(VIVADO) -mode batch \
		-source $(SCRIPTS_DIR)/bitstream.tcl \
		-tclargs $(TOP_MODULE) \
		-log $(BUILD_DIR)/logs/bitstream.log \
		-journal $(BUILD_DIR)/logs/bitstream.jou \
		-notrace

# =============================================================================
# Vitis HLS Simulation
# =============================================================================

sim: sim-csim

sim-csim: $(DATA_HEADER)
	@echo "========================================="
	@echo "Running Vitis HLS C simulation..."
	@echo "========================================="
	cd $(HLS_DIR) && $(MAKE) csim

sim-cosim: $(HLS_IP_MARKER)
	@echo "========================================="
	@echo "Running Vitis HLS C/RTL co-simulation..."
	@echo "========================================="
	cd $(HLS_DIR) && $(MAKE) cosim

sim-ddr: headers
	@echo "========================================="
	@echo "Running Vitis HLS C simulation (DDR solver)..."
	@echo "========================================="
	cd $(HLS_DIR) && $(MAKE) csim-ddr

sim-loader: headers
	@echo "========================================="
	@echo "Running Vitis HLS C simulation (matrix loader)..."
	@echo "========================================="
	cd $(HLS_DIR) && $(MAKE) csim-loader

estimate-ddr:
	@echo "========================================="
	@echo "Estimating DDR fetch overhead..."
	@echo "========================================="
	cd $(SCRIPTS_DIR) && $(PYTHON) ddr_fetch_overhead.py

# =============================================================================
# Programming (no build dependency: use existing bitstream, e.g. after 'make sync')
# =============================================================================

program:
	@if [ ! -f $(BITSTREAM) ]; then \
		echo "Error: $(BITSTREAM) not found. Run 'make' or 'make sync' first."; exit 1; \
	fi
	@echo "========================================="
	@echo "Programming FPGA..."
	@echo "========================================="
	$(VIVADO) -mode batch \
		-source $(SCRIPTS_DIR)/program.tcl \
		-tclargs $(TOP_MODULE) \
		-notrace

flash:
	@if [ ! -f $(FLASH_BIN) ]; then \
		echo "Error: $(FLASH_BIN) not found. Run 'make' or 'make sync' first."; exit 1; \
	fi
	@echo "========================================="
	@echo "Writing to SPI Flash..."
	@echo "========================================="
	$(VIVADO) -mode batch \
		-source $(SCRIPTS_DIR)/program_flash.tcl \
		-tclargs $(TOP_MODULE) \
		-notrace

$(FLASH_BIN): $(BITSTREAM)
	@echo "Flash binary already generated: $(FLASH_BIN)"

# =============================================================================
# Sync from remote (build on server, program locally)
# =============================================================================

sync:
	@if [ -z "$(REMOTE)" ]; then \
		echo "Usage: make sync REMOTE=user@hostname:path/to/ADMM_FPGA"; \
		echo "Example: make sync REMOTE=me@buildserver:~/ADMM_FPGA"; \
		exit 1; \
	fi
	@echo "========================================="
	@echo "Syncing build/ from $(REMOTE)..."
	@echo "========================================="
	@mkdir -p $(BUILD_DIR)
	rsync -avz --progress $(RSYNC_SSH) $(REMOTE)/build/ $(BUILD_DIR)/

# =============================================================================
# Clean Targets
# =============================================================================

clean:
	@echo "Cleaning Vivado build..."
	rm -rf $(BUILD_DIR)
	rm -rf $(PROJ_ROOT)/.Xil
	rm -rf $(PROJ_ROOT)/*.log $(PROJ_ROOT)/*.jou
	rm -rf $(SCRIPTS_DIR)/*.log $(SCRIPTS_DIR)/*.jou

clean-hls:
	@echo "Cleaning HLS build..."
	cd $(HLS_DIR) && $(MAKE) clean
	rm -f $(HLS_IP_MARKER)
	rm -f $(HLS_DDR_IP_MARKER)
	rm -f $(HLS_LOADER_IP_MARKER)

clean-all: clean clean-hls
	@echo "All build artifacts cleaned."

# =============================================================================
# Utility
# =============================================================================

.PHONY: report
report:
	@echo "=== Utilization Report ==="
	@cat $(BUILD_DIR)/reports/post_route_utilization.rpt 2>/dev/null || echo "No report found"
	@echo ""
	@echo "=== Timing Summary ==="
	@cat $(BUILD_DIR)/reports/post_route_timing.rpt 2>/dev/null | head -50 || echo "No report found"
