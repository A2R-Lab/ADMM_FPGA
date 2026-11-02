#!/usr/bin/env python3
"""One bounded RTL smoke check against the unchanged solver's host outputs."""
import json
from pathlib import Path
import shutil
import subprocess
import sys

root = Path(sys.argv[1]).resolve()
baseline = root/'baseline'
variant = root/sys.argv[2]
test = Path(__file__).with_name('check_top.cpp')
shutil.copy2(test, baseline/'check_top.cpp')
shutil.copy2(test, variant/'check_top.cpp')
cmd = ['g++', '-O2', '-std=c++17', '-ftrivial-auto-var-init=zero',
       '-I/home/agrillo/amdfpga/2025.2/Vitis/include', '-DGENERATE_GOLDEN',
       'ADMM.cpp', 'check_top.cpp', '-o', 'check_top']
subprocess.run(cmd, cwd=baseline, check=True)
bits = [int(v) for v in subprocess.check_output(['./check_top'], cwd=baseline, text=True).split()]
assert len(bits) == 12
header = 'static const unsigned golden[3][4] = {\n'
header += ',\n'.join('{' + ','.join(str(v)+'u' for v in bits[i:i+4]) + '}' for i in range(0,12,4))
header += '\n};\n'
(variant/'top_golden.h').write_text(header)
cfg = (variant/'hls_config.cfg').read_text() + 'tb.file=check_top.cpp\n'
(variant/'cosim_config.cfg').write_text(cfg)
with (variant/'cosim.log').open('w') as log:
    rc = subprocess.call(['timeout', '-k', '10', '240', 'vitis-run', '--mode', 'hls', '--cosim',
                          '--config', 'cosim_config.cfg', '--work_dir', 'hls'], cwd=variant,
                         stdout=log, stderr=subprocess.STDOUT)
(variant/'cosim_result.json').write_text(json.dumps(dict(returncode=rc, transactions=3,
    baseline_golden_bits=bits, timeout_s=240), indent=2))
print('RTL smoke returncode:', rc, flush=True)
