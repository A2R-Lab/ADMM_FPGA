# =============================================================================
# ADMM FPGA - Top-Level Makefile
# =============================================================================
# Targets:
#   all       - Build everything (traj -> headers -> HLS -> Vivado -> bitstream)
#   traj      - Generate deterministic trajectory references
#   headers   - Generate data.h from Python script
#   hls       - Build HLS IP
#   vivado    - Run Vivado synthesis + implementation
#   bit       - Generate bitstream only (assumes impl done)
#   program   - Program FPGA via JTAG
#   flash     - Write to SPI flash
#   sync      - Rsync build/ from remote (for build-on-server, program-local workflow)
#   sim       - Run Vitis HLS C simulation (quick)
#   sim-csim  - Run Vitis HLS C simulation
#   sim-cosim - Run Vitis HLS C/RTL co-simulation
#   hls_closed_loop_sim - Run one HLS closed-loop simulation + plots
#   clean     - Clean Vivado build artifacts
#   clean-hls - Clean HLS build artifacts
#   clean-all - Clean everything
# =============================================================================

# Configuration
SUPPORTED_MAKE_OVERRIDE_VARS := BOARD REMOTE SSH_PORT VIVADO VITIS_HLS PYTHON HLS_CLOSED_LOOP_ARGS
CMDLINE_OVERRIDE_VARS := $(sort $(foreach tok,$(MAKEOVERRIDES),$(if $(findstring =,$(tok)),$(word 1,$(subst =, ,$(tok))),)))
UNKNOWN_CMDLINE_OVERRIDE_VARS := $(filter-out $(SUPPORTED_MAKE_OVERRIDE_VARS),$(CMDLINE_OVERRIDE_VARS))

ifneq ($(strip $(UNKNOWN_CMDLINE_OVERRIDE_VARS)),)
$(error Unsupported make variable override(s): $(UNKNOWN_CMDLINE_OVERRIDE_VARS). Supported overrides: $(SUPPORTED_MAKE_OVERRIDE_VARS))
endif

BOARD        ?= custom

PART          := xc7a100tcsg324-1

ifeq ($(BOARD),arty)
TOP_MODULE    := top_uart
else ifeq ($(BOARD),custom)
TOP_MODULE    := top_spi
else
$(error Unsupported BOARD='$(BOARD)'. Use BOARD=arty or BOARD=custom)
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
RTL_DIR       := $(PROJ_ROOT)/vivado_project/vivado_project.srcs/sources_1/new
XDC_DIR       := $(PROJ_ROOT)/vivado_project/vivado_project.srcs/constrs_1/new
IP_DIR        := $(PROJ_ROOT)/vivado_project/vivado_project.gen/sources_1/ip/ADMM_solver_0

# Source files
HLS_SOURCES   := $(HLS_DIR)/ADMM.cpp $(HLS_DIR)/ADMM.h $(HLS_DIR)/data_types.h
RTL_SOURCES   := $(wildcard $(RTL_DIR)/*.v) $(wildcard $(RTL_DIR)/*.vh)
ifeq ($(BOARD),arty)
XDC_SOURCES   := $(XDC_DIR)/constraints_arty_a7.xdc
else
XDC_SOURCES   := $(XDC_DIR)/constraints.xdc
endif
HEADER_SCRIPT := $(SCRIPTS_DIR)/header_generator.py
TRAJ_SCRIPT   := $(SCRIPTS_DIR)/trajectory_generator.py
PARAMS_SCRIPT := $(SCRIPTS_DIR)/parameters.py
HLS_CLOSED_LOOP_SCRIPT := $(SCRIPTS_DIR)/run_hls_closed_loop_once.py
HLS_CLOSED_LOOP_ARGS ?=

# Generated files
DATA_HEADER   := $(HLS_DIR)/data.h
TRAJ_REFS     := $(HLS_DIR)/trajectory_refs.csv
TRAJ_HEADER   := $(HLS_DIR)/traj_data.h
HLS_IP_MARKER := $(HLS_WORK_DIR)/.export_done
BITSTREAM     := $(BUILD_DIR)/$(TOP_MODULE).bit
FLASH_BIN     := $(BUILD_DIR)/$(TOP_MODULE).bin
BUILD_TAG     := $(TOP_MODULE)_$(BOARD)
SYNTH_DCP     := $(BUILD_DIR)/post_synth_$(BUILD_TAG).dcp
ROUTE_DCP     := $(BUILD_DIR)/post_route_$(BUILD_TAG).dcp

# =============================================================================
# Main Targets
# =============================================================================

.PHONY: all traj headers hls vivado bit program flash sync sim sim-csim sim-cosim hls_closed_loop_sim clean clean-hls clean-all help

all: $(BITSTREAM)
	@echo "========================================="
	@echo "Build complete!"
	@echo "BOARD: $(BOARD)"
	@echo "TOP: $(TOP_MODULE)"
	@echo "Bitstream: $(BITSTREAM)"
	@echo "Flash bin: $(FLASH_BIN)"
	@echo "========================================="

help:
	@echo "ADMM FPGA Build System"
	@echo ""
	@echo "Targets:"
	@echo "  all       - Build everything (default)"
	@echo "  traj      - Generate deterministic trajectory references"
	@echo "  headers   - Generate data.h"
	@echo "  hls       - Build HLS IP"
	@echo "  vivado    - Synthesis + Implementation"
	@echo "  bit       - Generate bitstream"
	@echo "  program   - Program FPGA via JTAG"
	@echo "  flash     - Write to SPI flash"
	@echo "  sim       - Vitis HLS C simulation (quick)"
	@echo "  sim-csim  - Vitis HLS C simulation"
	@echo "  sim-cosim - Vitis HLS C/RTL co-simulation (requires HLS build)"
	@echo "  hls_closed_loop_sim - One HLS closed-loop simulation + plots"
	@echo "  sync      - Rsync build/ from remote (e.g. make sync REMOTE=user@host:~/ADMM_FPGA [SSH_PORT=2222])"
	@echo "  clean     - Clean Vivado build"
	@echo "  clean-hls - Clean HLS build"
	@echo "  clean-all - Clean everything"
	@echo ""
	@echo "Examples:"
	@echo "  make              # Full build"
	@echo "  make hls          # Rebuild HLS only"
	@echo "  make vivado       # Rebuild Vivado only"
	@echo "  make sim          # Vitis HLS C simulation"
	@echo "  make sim-cosim    # Vitis HLS C/RTL co-simulation"
	@echo "  make hls_closed_loop_sim"
	@echo "  make hls_closed_loop_sim HLS_CLOSED_LOOP_ARGS='--sim-duration-s 8 --traj-start-step 60'"
	@echo "  make program      # Program FPGA"
	@echo "  make sync REMOTE=user@host:~/ADMM_FPGA [SSH_PORT=2222]  # Fetch build from server"

# =============================================================================
# Trajectory Generation
# =============================================================================

traj: $(TRAJ_HEADER)

$(TRAJ_REFS) $(TRAJ_HEADER): $(TRAJ_SCRIPT) $(SCRIPTS_DIR)/crazyloihimodel.py $(PARAMS_SCRIPT)
	@echo "========================================="
	@echo "Generating trajectory references..."
	@echo "========================================="
	cd $(SCRIPTS_DIR) && $(PYTHON) trajectory_generator.py

# =============================================================================
# Header Generation
# =============================================================================

headers: $(DATA_HEADER)

$(DATA_HEADER): $(HEADER_SCRIPT) $(SCRIPTS_DIR)/crazyloihimodel.py $(PARAMS_SCRIPT) $(TRAJ_HEADER)
	@echo "========================================="
	@echo "Generating headers..."
	@echo "========================================="
	cd $(SCRIPTS_DIR) && $(PYTHON) header_generator.py
	@touch $(DATA_HEADER)

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

# =============================================================================
# Vivado Build
# =============================================================================

vivado: $(ROUTE_DCP)

# Synthesis
$(SYNTH_DCP): $(RTL_SOURCES) $(XDC_SOURCES) $(HLS_IP_MARKER)
	@echo "========================================="
	@echo "Running Vivado Synthesis (BOARD=$(BOARD), TOP=$(TOP_MODULE))..."
	@echo "========================================="
	@mkdir -p $(BUILD_DIR)/logs $(BUILD_DIR)/reports
	$(VIVADO) -mode batch \
		-source $(SCRIPTS_DIR)/synth.tcl \
		-tclargs $(TOP_MODULE) $(notdir $(XDC_SOURCES)) $(notdir $(SYNTH_DCP)) \
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
		-tclargs $(notdir $(SYNTH_DCP)) $(notdir $(ROUTE_DCP)) \
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
		-tclargs $(TOP_MODULE) $(notdir $(ROUTE_DCP)) \
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

hls_closed_loop_sim: $(DATA_HEADER)
	@echo "========================================="
	@echo "Running HLS closed-loop simulation..."
	@echo "========================================="
	cd $(PROJ_ROOT) && $(PYTHON) $(HLS_CLOSED_LOOP_SCRIPT) $(HLS_CLOSED_LOOP_ARGS)

# =============================================================================
# Programming (no build dependency: use existing bitstream, e.g. after 'make sync')
# =============================================================================

program:
	@if [ ! -f $(BITSTREAM) ]; then \
		echo "Error: $(BITSTREAM) not found. Run 'make' or 'make sync' first."; exit 1; \
	fi
	@echo "========================================="
	@echo "Programming FPGA (BOARD=$(BOARD), TOP=$(TOP_MODULE))..."
	@echo "========================================="
	$(VIVADO) -mode batch \
		-source $(SCRIPTS_DIR)/program.tcl \
		-tclargs $(TOP_MODULE) \
		-notrace

flash:
	@if [ ! -f $(BITSTREAM) ]; then \
		echo "Error: $(BITSTREAM) not found. Run 'make' or 'make sync' first."; exit 1; \
	fi
	@echo "========================================="
	@echo "Writing to SPI Flash (BOARD=$(BOARD), TOP=$(TOP_MODULE))..."
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
