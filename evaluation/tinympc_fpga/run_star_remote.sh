#!/bin/bash
set -eo pipefail
# Usage: HLS_INCLUDE=/path/to/Vitis/include TASK_PYTHON=/path/to/python bash run_star_remote.sh EXPERIMENT_DIR
cd "${1:?Pass the generated experiment directory}"
inc="${HLS_INCLUDE:?Set HLS_INCLUDE to the Vitis include directory}"
task_python="${TASK_PYTHON:-python3}"
g++ -O2 -ftrivial-auto-var-init=zero -std=c++14 -shared -fPIC -Wno-unknown-pragmas -I"$inc" -DDYNAMIC_CONSTRAINT_AXIS=0 -DDYNAMIC_CONSTRAINT_START_STAGE=10 vitis_projects/ADMM/ADMM.cpp vitis_projects/ADMM/bridge.cpp -o accel.so
g++ -O2 -std=c++14 -shared -fPIC -Wno-unknown-pragmas tiny/tinympc_solver.cpp tiny/bridge.cpp -o tiny.so
"$task_python" nonlinear_star.py --input . --solver accel --output results > accel.log 2>&1 &
a_pid=$!
"$task_python" nonlinear_star.py --input . --solver tiny --output results > tiny.log 2>&1 &
t_pid=$!
wait "$a_pid"
wait "$t_pid"
printf 'Both nonlinear-star rollouts finished.\n'
