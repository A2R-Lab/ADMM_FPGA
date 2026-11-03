#!/usr/bin/env python3
"""Compare independent baseline/candidate C++ objects; emit baseline RTL vectors."""
import argparse
from pathlib import Path
import re
import subprocess

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('--baseline', type=Path, required=True)
p.add_argument('--candidate', type=Path, required=True)
p.add_argument('--output', type=Path, required=True)
p.add_argument('--hls-include', type=Path, required=True)
a = p.parse_args()
def config(directory):
    src = directory / 'vitis_projects/ADMM'
    text = (src / 'data.h').read_text() + (src / 'admm_runtime_config.h').read_text()
    defines = dict(re.findall(r'^#define\s+(\w+)\s+([^\n]+)', text, re.M))
    keys = ['HORIZON_LENGTH', 'N_VAR', 'N_CONSTR', 'L_BANDED_ROWS',
            'L_BANDED_COLS', 'ADMM_ITERATIONS', 'ADMM_ENABLE_TRAJECTORY',
            'ADMM_USE_FLOAT', 'ADMM_SOLVER_ARCH_NAME']
    return {key: defines[key].strip() for key in keys}

baseline_config = config(a.baseline)
if baseline_config != config(a.candidate):
    raise SystemExit('Baseline and candidate configurations differ')
if (baseline_config['ADMM_SOLVER_ARCH_NAME'] != '"full_sparse"' or
        baseline_config['ADMM_USE_FLOAT'] != '0'):
    raise SystemExit('This raw-bit check requires fixed-point full_sparse')
a.output.mkdir(parents=True, exist_ok=True)
root = Path(__file__).resolve().parents[1]
names = ['forward_substitution', 'backward_substitution', 'AT_mul',
         'ADMM_iteration', 'ADMM_benchmark_solve', 'ADMM_solver',
         'admm_test_rho_mul', 'admm_test_rho_div', 'admm_test_fp_width',
         'admm_test_acc_width']
common = ['g++', '-std=c++14', '-O1', '-Wno-unknown-pragmas',
          '-I' + str(a.hls_include)]
for label, directory in [('baseline', a.baseline), ('candidate', a.candidate)]:
    src = directory / 'vitis_projects/ADMM'
    flags = [f'-D{n}=baseline_{n}' for n in names] if label == 'baseline' else []
    subprocess.run(common + flags + ['-I' + str(src), '-c', str(src / 'ADMM.cpp'),
                   '-o', str(a.output / (label + '.o'))], check=True)
exe = a.output / 'compare'
subprocess.run(common + ['-I' + str(a.candidate / 'vitis_projects/ADMM'),
    str(root / 'tests/full_sparse_shared_l_test.cpp'),
    str(a.output / 'baseline.o'), str(a.output / 'candidate.o'), '-o', str(exe)], check=True)
subprocess.run([str(exe), str(a.output / 'vectors.h')], check=True)
(a.output / 'rtl_tb.cpp').write_text('''#include "ADMM.h"
#include "vectors.h"
#include <iostream>
int main() {
    for (const auto &v : shared_l_vectors) {
        ap_uint<128> actual;
        ADMM_solver(ap_uint<418>(v[0], 16), actual);
        if (actual != ap_uint<128>(v[1], 16)) {
            std::cerr << "RTL mismatch\\n"; return 1;
        }
    }
    std::cout << "PASS: baseline warm-start vectors\\n";
    return 0;
}
''')
