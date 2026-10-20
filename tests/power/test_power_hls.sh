#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/../.."
root_dir=$PWD
python scripts/power_workload.py --csv experiments/power/synthetic_states.csv --output build/power/test_workload >/dev/null
mkdir -p build/power/hls_sim
hls_dir="$root_dir/vitis_projects/ADMM"
g++ -std=c++14 -O1 -Wno-unknown-pragmas -I"$XILINX_HLS/include" -I"$hls_dir" tests/power/solver_reference.cpp "$hls_dir/ADMM.cpp" -o build/power/solver_reference
build/power/solver_reference build/power/test_workload/power_workload.mem > build/power/golden.mem
cd build/power/hls_sim
cp "$hls_dir"/ADMM/hls/impl/ip/hdl/verilog/*.dat .
xvlog "$hls_dir"/ADMM/hls/impl/ip/hdl/verilog/*.v "$XILINX_VIVADO/data/verilog/src/glbl.v"
xvlog --sv "$root_dir/vivado_project/vivado_project.srcs/sources_1/new/power_benchmark.sv" "$root_dir/tests/power/solver_tb.sv"
xelab solver_tb glbl -L unisims_ver -s power_solver_test
xsim power_solver_test -runall > ../solver_test.log 2>&1
rg '^PASS ' ../solver_test.log

rtl="$root_dir/vivado_project/vivado_project.srcs/sources_1/new"
xvlog --sv -i "$root_dir/build/power/test_workload" "$rtl/power_capture.sv" "$rtl/power_uart.sv" "$rtl/power_xadc.v" "$rtl/top_uart_power.sv" "$rtl/uart_rx.v" "$rtl/uart_tx.v" "$root_dir/tests/power/top_tb.sv"
xelab top_tb glbl -L unisims_ver -s power_top_test
xsim power_top_test -runall > ../top_test.log 2>&1
rg '^PASS ' ../top_test.log
