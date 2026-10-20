#!/usr/bin/env bash
# Requires a completed power build and test_power_hls.sh with the same HLS RTL.
# --simulate-only collects SAIF while routing is in progress; run
# power_activity_report.tcl after the matching routed checkpoint is ready.
set -euo pipefail
cd "$(dirname "$0")/.."
root_dir=$PWD
# Representative voltages, with deterministic +/-2 ADC-code variation so the
# acquisition datapath is not artificially constant. This is a simulation
# stimulus, not a recorded analog waveform or an ADC accuracy model.
python - <<'PY'
from pathlib import Path
import random
rng = random.Random(20261017)
with Path('build/power/profile_analog.txt').open('w') as f:
    f.write('TIME TEMP VCCINT VCCAUX VCCBRAM VAUXP[1] VAUXN[1] VAUXP[2] VAUXN[2] VAUXP[9] VAUXN[9] VAUXP[10] VAUXN[10]\n')
    for t in range(0, 50000001, 4640):
        vcore = 1.0 + rng.randint(-2, 2) * 3 / 4096
        v5 = 5.0 / 5.99 + rng.randint(-2, 2) / 4096
        i5 = 0.22 / 4 + rng.randint(-2, 2) / 4096
        icore = 0.265 / 2 + rng.randint(-2, 2) / 4096
        f.write(f'{t} 30.0 {vcore:.8f} 1.8 1.0 {v5:.8f} 0 0 0 {i5:.8f} 0 {icore:.8f} 0\n')
PY
cd build/power/hls_sim
xvlog --sv "$root_dir/tests/power/top_tb.sv"
xelab power_activity_tb glbl -debug typical -L unisims_ver -s power_activity_test
xsim power_activity_test -tclbatch "$root_dir/scripts/power_activity.tcl" > ../activity_sim.log 2>&1
rg '^PASS ' ../activity_sim.log
cd "$root_dir"
if [[ "${1:-}" != "--simulate-only" ]]; then
    vivado -mode batch -nolog -nojournal -source scripts/power_activity_report.tcl > build/power/activity_report.log 2>&1
fi
