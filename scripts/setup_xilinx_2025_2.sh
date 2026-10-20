#!/usr/bin/env bash
# Source AMD/Xilinx 2025.2 toolchain settings for builds and benchmarks.
set -Eeuo pipefail

VIVADO_SETTINGS="${VIVADO_SETTINGS:-}"
VITIS_SETTINGS="${VITIS_SETTINGS:-}"

if [[ ! -r "$VIVADO_SETTINGS" ]]; then
  echo "error: Set VIVADO_SETTINGS to a readable Vivado settings64.sh; got: $VIVADO_SETTINGS" >&2
  return 1 2>/dev/null || exit 1
fi
if [[ ! -r "$VITIS_SETTINGS" ]]; then
  echo "error: Set VITIS_SETTINGS to a readable Vitis settings64.sh; got: $VITIS_SETTINGS" >&2
  return 1 2>/dev/null || exit 1
fi

source "$VIVADO_SETTINGS"
source "$VITIS_SETTINGS"
