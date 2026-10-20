#!/usr/bin/env bash
# Source Vivado settings64.sh and activate the Python environment first.
set -euo pipefail
cd "$(dirname "$0")/.."
python -m unittest discover -s tests -v
python scripts/power_workload.py --csv scripts/power_synthetic_states.csv --output build/power/test_workload >/dev/null
rtl=vivado_project/vivado_project.srcs/sources_1/new
xvlog --sv -i build/power "$rtl/power_capture.sv" "$rtl/power_benchmark.sv" "$rtl/power_uart.sv" "$rtl/power_xadc.v" "$rtl/uart_rx.v" "$rtl/uart_tx.v" tests/capture_tb.sv tests/benchmark_tb.sv tests/uart_tb.sv tests/xadc_tb.sv "$XILINX_VIVADO/data/verilog/src/glbl.v"
for tb in capture benchmark uart xadc; do
    xelab "${tb}_tb" glbl -L unisims_ver -s "power_${tb}_test"
    xsim "power_${tb}_test" -runall > "build/power/${tb}_test.log" 2>&1
    # xsim can exit zero on HDL $fatal; require the explicit success marker.
    rg '^PASS ' "build/power/${tb}_test.log"
done
