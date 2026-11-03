#!/usr/bin/env bash
# Run from the generated experiment directory with a C++ compiler and Vitis headers.
set -euo pipefail
: "${HLS_INCLUDE:?Set HLS_INCLUDE to the Vitis include directory}"
for h in 10 40; do
  g++ -O2 -ftrivial-auto-var-init=zero -std=c++14 -Wno-unknown-pragmas -shared -fPIC -I"$HLS_INCLUDE" "h${h}/vitis_projects/ADMM/ADMM.cpp" "h${h}/vitis_projects/ADMM/bridge.cpp" -o "h${h}/accel.so"
  g++ -O2 -ftrivial-auto-var-init=zero -std=c++14 -Wno-unknown-pragmas -shared -fPIC -I"$HLS_INCLUDE" "h${h}/vitis_projects/ADMM/ADMM.cpp" "h${h}/vitis_projects/ADMM/warm_bridge.cpp" -o "h${h}/accel_warm.so"
  g++ -O2 -std=c++14 -Wno-unknown-pragmas -shared -fPIC "h${h}/tiny/tinympc_solver.cpp" "h${h}/tiny/bridge.cpp" -o "h${h}/tiny.so"
done
