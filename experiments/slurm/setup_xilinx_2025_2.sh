#!/usr/bin/env bash
# Source AMD/Xilinx 2025.2 toolchain settings for Slurm jobs.
set -Eeuo pipefail

VIVADO_SETTINGS="${VIVADO_SETTINGS:-/home/agrillo/amdfpga/2025.2/Vivado/settings64.sh}"
VITIS_SETTINGS="${VITIS_SETTINGS:-/home/agrillo/amdfpga/2025.2/Vitis/settings64.sh}"

if [[ ! -r "$VIVADO_SETTINGS" ]]; then
  echo "error: Vivado settings file not readable: $VIVADO_SETTINGS" >&2
  return 1 2>/dev/null || exit 1
fi
if [[ ! -r "$VITIS_SETTINGS" ]]; then
  echo "error: Vitis settings file not readable: $VITIS_SETTINGS" >&2
  return 1 2>/dev/null || exit 1
fi

source "$VIVADO_SETTINGS"
source "$VITIS_SETTINGS"
