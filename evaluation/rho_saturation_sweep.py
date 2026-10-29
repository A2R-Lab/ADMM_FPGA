#!/usr/bin/env python3
"""Reproduce the 479-pair, ten-iteration rho sweep with a 0.1% saturation allowance.

Run with ~/venv/bin/python and HLS_INCLUDE=/path/to/Vitis/include. Production
sources/headers are never edited. See evaluation/README.md for the methodology.
"""
from __future__ import annotations

import argparse
from contextlib import ExitStack
import csv
import ctypes as ct
import hashlib
import inspect
import itertools
import json
import math
import multiprocessing
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time

import numpy as np
from scipy import sparse

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
SOURCES = [ROOT / "scripts" / name for name in (
    "parameters.py", "crazyflie_model.py", "trajectory_generator.py", "header_generator.py")]
SOURCES += [ROOT / "vitis_projects/ADMM" / name for name in (
    "ADMM.cpp", "ADMM.h", "data_types.h", "ADMM_closed_loop_tb.cpp")]
SOURCES += [Path(__file__), HERE / "numerical_accuracy.py"]
METRICS = ("iterations", "converged", "feasibility", "stationarity", "split_primal",
           "primal_threshold", "dual_threshold")
F32 = np.ctypeslib.ndpointer(dtype=np.float32, flags="C_CONTIGUOUS")
F64 = np.ctypeslib.ndpointer(dtype=np.float64, flags="C_CONTIGUOUS")
DEPLOYED = (128.0, 32.0)  # Current defaults/build record; flight bitstream unverified.
WORKER_EXPERIMENTS = []



FLOAT_BRIDGE = '// Host-only wrapper. Compiled against isolated copies of the actual float solver.\n// EVAL_MODIFIED enables runtime penalties/factors and observes projection outputs.\n#include "data.h"\n#include <algorithm>\n#include <cmath>\n#include <limits>\n#include <cstring>\n\n#if EVAL_MODIFIED\nstatic float eval_rho_eq = 128, eval_rho_ineq = 32;\nstatic float eval_z[N_CONSTR] = {};\n#endif\n#include "ADMM.cpp"\n#include "evaluation_matrices.h"\n\nstatic fp_t eval_x[N_VAR] = {}, eval_b[N_VAR] = {}, eval_y[N_CONSTR] = {};\n\nextern "C" void reset() {\n    std::fill_n(eval_x, N_VAR, 0);\n    std::fill_n(eval_b, N_VAR, 0);\n    std::fill_n(eval_y, N_CONSTR, 0);\n}\n\nextern "C" void step(const float *state, const float *q, int iterations,\n                     float *x, float *b, float *y) {\n    fp_t current[12];\n    std::copy_n(state, 12, current);\n    for (int k = 0; k < iterations; ++k)\n        ADMM_iteration(eval_x, eval_b, eval_y, current, false, 0,\n                       (fp_t)XY_MIN, (fp_t)XY_MAX, q, true);\n    std::copy_n(eval_x, N_VAR, x);\n    std::copy_n(eval_b, N_VAR, b);\n    std::copy_n(eval_y, N_CONSTR, y);\n}\n\n#if EVAL_MODIFIED\nextern "C" void configure(float eq, float ineq, const float *lower, const float *upper) {\n    eval_rho_eq = eq;\n    eval_rho_ineq = ineq;\n    std::memcpy(L_banded, lower, sizeof(L_banded));\n    std::memcpy(LT_banded, upper, sizeof(LT_banded));\n}\n\n// Diagnostics are evaluated in double precision against the original QP, while\n// every ADMM operation, including triangular solves, remains the float C++ code.\nstatic void residuals(const float *state, const float *q, double tolerance, double *r) {\n    double primal = 0, feasible = 0, axnorm = 0, znorm = 0;\n    double aty[N_VAR] = {}, px[N_VAR] = {};\n    for (int i = 0; i < N_CONSTR; ++i) {\n        double ax = 0;\n        for (int j = EA_PTR[i]; j < EA_PTR[i+1]; ++j)\n            ax += EA_VAL[j] * (double)eval_x[EA_COL[j]];\n        const double lo = i < 12 ? state[i] : E_LO[i];\n        const double hi = i < 12 ? state[i] : E_HI[i];\n        primal = std::max(primal, std::abs(ax - eval_z[i]));\n        feasible = std::max(feasible, std::max(lo - ax, ax - hi));\n        axnorm = std::max(axnorm, std::abs(ax));\n        znorm = std::max(znorm, std::abs((double)eval_z[i]));\n        const double lambda = (i < START_INEQ ? eval_rho_eq : eval_rho_ineq) * (double)eval_y[i];\n        for (int j = EA_PTR[i]; j < EA_PTR[i+1]; ++j)\n            aty[EA_COL[j]] += EA_VAL[j] * lambda;\n    }\n    double dual = 0, pxnorm = 0, qnorm = 0, atynorm = 0;\n    for (int i = 0; i < N_VAR; ++i) {\n        for (int j = EP_PTR[i]; j < EP_PTR[i+1]; ++j)\n            px[i] += EP_VAL[j] * (double)eval_x[EP_COL[j]];\n        dual = std::max(dual, std::abs(px[i] + q[i] + aty[i]));\n        pxnorm = std::max(pxnorm, std::abs(px[i]));\n        qnorm = std::max(qnorm, std::abs((double)q[i]));\n        atynorm = std::max(atynorm, std::abs(aty[i]));\n    }\n    r[2] = feasible;\n    r[3] = dual;\n    r[4] = primal;\n    r[5] = tolerance * (1 + std::max(axnorm, znorm));\n    r[6] = tolerance * (1 + std::max({pxnorm, qnorm, atynorm}));\n    for (int i = 0; i < N_VAR; ++i)\n        if (!std::isfinite(eval_x[i])) r[2] = r[3] = r[4] = std::numeric_limits<double>::infinity();\n    for (int i = 0; i < N_CONSTR; ++i)\n        if (!std::isfinite(eval_y[i])) r[2] = r[3] = r[4] = std::numeric_limits<double>::infinity();\n}\n\nextern "C" void cases(const float *states, const float *qs, int count, int maxiter,\n                      double tolerance, int warm, double *results, float *solutions) {\n    reset();\n    for (int c = 0; c < count; ++c) {\n        if (!warm) reset();\n        const float *state = states + c * 12, *q = qs + c * N_VAR;\n        double *r = results + c * 7;\n        fp_t current[12];\n        std::copy_n(state, 12, current);\n        for (int k = 1; k <= maxiter; ++k) {\n            ADMM_iteration(eval_x, eval_b, eval_y, current, false, 0,\n                           (fp_t)XY_MIN, (fp_t)XY_MAX, q, true);\n            if (warm && k != maxiter) continue;\n            residuals(state, q, tolerance, r);\n            r[0] = k;\n            r[1] = r[4] <= r[5] && r[3] <= r[6];\n            if (!warm && (r[1] || !std::isfinite(r[3]) || !std::isfinite(r[4]))) break;\n        }\n        std::copy_n(eval_x, N_VAR, solutions + c * N_VAR);\n    }\n}\n#endif\n'
FIXED_BRIDGE = '// Native host wrapper for paired float/ap_fixed tests. All ADMM arithmetic is\n// taken from ADMM.cpp; temporary source copies observe z and selected narrowings.\n#include "data.h"\n#include <algorithm>\n#include <cmath>\n#include <cstring>\n#include <limits>\n\nstatic fp_t observed_z[N_CONSTR] = {};\nstatic long long range_events[3] = {};\n\ntemplate<class T> static inline fp_t observed_cast(const T &v, int category) {\n#if !ADMM_USE_FLOAT && OBSERVE_CASTS\n    const double d = (double)v;\n    constexpr double lo = -512., hi = 512.-1./4194304.;\n    if (d < lo || d > hi) ++range_events[category];\n#endif\n    return (fp_t)v;\n}\n\n#include "ADMM.cpp"\n#include "evaluation_matrices.h"\n\nextern "C" void precision_replay(const double *states, const double *qs,\n                                  const int *resets, int count, int iterations,\n                                  double eq, double ineq, double *metrics, double *commands) {\n    fp_t x[N_VAR] = {}, b[N_VAR] = {}, y[N_CONSTR] = {};\n    for (int c=0; c<count; ++c) {\n        if (resets[c]) {\n            std::fill_n(x,N_VAR,0); std::fill_n(b,N_VAR,0); std::fill_n(y,N_CONSTR,0);\n        }\n        std::fill_n(range_events,3,0);\n        fp_t state[12], q[N_VAR];\n        for (int j=0;j<12;++j) state[j]=(fp_t)states[c*12+j];\n        for (int j=0;j<N_VAR;++j) q[j]=(fp_t)qs[c*N_VAR+j];\n        double rails=0, max_x=0, max_b=0, max_y=0;\n        for (int k=0;k<iterations;++k) {\n            ADMM_iteration(x,b,y,state,false,0,(fp_t)XY_MIN,(fp_t)XY_MAX,q,true);\n            for (int j=0;j<N_VAR;++j) {\n                const double xv=(double)x[j], bv=(double)b[j];\n                max_x=std::max(max_x,std::abs(xv)); max_b=std::max(max_b,std::abs(bv));\n#if !ADMM_USE_FLOAT\n                rails += xv == -512. || xv == 512.-1./4194304.;\n                rails += bv == -512. || bv == 512.-1./4194304.;\n#endif\n            }\n            for (int j=0;j<N_CONSTR;++j) {\n                const double v=(double)y[j]; max_y=std::max(max_y,std::abs(v));\n#if !ADMM_USE_FLOAT\n                rails += v == -512. || v == 512.-1./4194304.;\n#endif\n            }\n        }\n        double primal=0, feasible=0, axnorm=0, znorm=0, aty[N_VAR]={};\n        for (int i=0;i<N_CONSTR;++i) {\n            double ax=0;\n            for (int j=EA_PTR[i];j<EA_PTR[i+1];++j) ax+=EA_VAL[j]*(double)x[EA_COL[j]];\n            const double lo=i<12 ? states[c*12+i] : E_LO[i];\n            const double hi=i<12 ? states[c*12+i] : E_HI[i];\n            primal=std::max(primal,std::abs(ax-(double)observed_z[i]));\n            feasible=std::max(feasible,std::max(lo-ax,ax-hi));\n            axnorm=std::max(axnorm,std::abs(ax)); znorm=std::max(znorm,std::abs((double)observed_z[i]));\n            const double lambda=(i<START_INEQ?eq:ineq)*(double)y[i];\n            for (int j=EA_PTR[i];j<EA_PTR[i+1];++j) aty[EA_COL[j]]+=EA_VAL[j]*lambda;\n        }\n        double dual=0, pxnorm=0, qnorm=0, atynorm=0;\n        for (int i=0;i<N_VAR;++i) {\n            double px=0;\n            for (int j=EP_PTR[i];j<EP_PTR[i+1];++j) px+=EP_VAL[j]*(double)x[EP_COL[j]];\n            const double qi=qs[c*N_VAR+i];\n            dual=std::max(dual,std::abs(px+qi+aty[i]));\n            pxnorm=std::max(pxnorm,std::abs(px)); qnorm=std::max(qnorm,std::abs(qi));\n            atynorm=std::max(atynorm,std::abs(aty[i]));\n        }\n        double *m=metrics+c*12;\n        m[0]=feasible; m[1]=dual; m[2]=primal;\n        m[3]=1e-4*(1+std::max(axnorm,znorm));\n        m[4]=1e-4*(1+std::max({pxnorm,qnorm,atynorm}));\n        for (int j=0;j<3;++j) m[5+j]=range_events[j];\n        m[8]=rails; m[9]=max_x; m[10]=max_b; m[11]=max_y;\n        for (int j=0;j<4;++j) commands[c*4+j]=(double)x[12+j];\n    }\n}\n'

GENERATION = r"""
import sys, json, numpy as np
sys.path.insert(0, 'scripts')
import trajectory_generator as tg
assert tg.main() == 0
import header_generator as g
import parameters as p
ref = np.genfromtxt('vitis_projects/ADMM/trajectory_refs.csv', delimiter=',', names=True)
ref = np.column_stack([ref['x'+str(i)] for i in range(12)])
q = tg.build_traj_q_packed(ref, np.zeros((len(ref),4)), np.array(p.Q_DIAG),
                         np.array(p.R_DIAG), p.HORIZON_LENGTH, p.TRAJ_ENTRY_ZERO_PAD)
plant = g.CrazyFlieModel(freq=1000.)
a, b = plant.get_linearized_dynamics(g.xg, plant.hover_thrust)
a[6,6] -= p.MPC_LINEAR_DRAG_XY / plant.mass / 1000.
a[7,7] -= p.MPC_LINEAR_DRAG_XY / plant.mass / 1000.
a[8,8] -= p.MPC_LINEAR_DRAG_Z / plant.mass / 1000.
np.savez('problem.npz', P=g.P_sparse.toarray(), A=g.A_full.toarray(), l=g.l, u=g.u,
         q=q, reference=ref, plant_A=a, plant_B=b, horizon=p.HORIZON_LENGTH,
         eq_rows=g.num_eq_rows, constants=json.dumps(g.constants))
"""



def source_hashes():
    return {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in SOURCES}

def run(command, cwd, env, log):
    result = subprocess.run(command, cwd=cwd, env=env, stdout=log, stderr=subprocess.STDOUT)
    if result.returncode:
        log.flush()
        raise RuntimeError(f"Command failed: {command!r}; see {log.name}")

def quantize(values):
    """Match the generator's eight-decimal text export followed by float32 cast."""
    values = np.asarray(values)
    return np.array([float(f"{v:.8f}") for v in values.flat], np.float32).reshape(values.shape)

def q_vectors(data, steps):
    horizon = int(data["horizon"])
    indices = data["reference_index"][steps]
    q = np.zeros((len(indices), len(data["P"])), dtype=np.float32)
    for k in range(horizon + 1):
        q[:, 16*k:16*k+3] = data["q_packed"][indices + k]
    return q

def write_matrices(project, data):
    def array(name, values, dtype):
        vals = ','.join(str(int(v)) if dtype == 'int' else f'{v:.17g}' for v in values)
        return f'static const {dtype} {name}[] = {{{vals}}};\n'
    text = ''
    for label, matrix in (("EA", data["A"]), ("EP", data["P"])):
        m = sparse.csr_matrix(matrix)
        text += array(label + '_PTR', m.indptr, 'int')
        text += array(label + '_COL', m.indices, 'int')
        text += array(label + '_VAL', m.data, 'double')
    text += array('E_LO', data['l'], 'double') + array('E_HI', data['u'], 'double')
    (project / 'evaluation_matrices.h').write_text(text)

def load_library(path, modified):
    lib = ct.CDLL(str(path))
    lib.reset.argtypes = []
    lib.reset.restype = None
    lib.step.argtypes = [F32, F32, ct.c_int, F32, F32, F32]
    lib.step.restype = None
    if modified:
        lib.configure.argtypes = [ct.c_float, ct.c_float, F32, F32]
        lib.configure.restype = None
        lib.cases.argtypes = [F32, F32, ct.c_int, ct.c_int, ct.c_double, ct.c_int, F64, F32]
        lib.cases.restype = None
    else:
        lib.solve.argtypes = [F64, ct.c_int, F64]
        lib.solve.restype = None
        lib.advance.argtypes = [F64, F64, F64]
        lib.advance.restype = None
    return lib

class Experiment:
    def __init__(self, scenario, directory, args):
        from numerical_accuracy import BRIDGE

        self.scenario, self.args = scenario, args
        self.work = Path(directory) / scenario
        self.project = self.work / 'vitis_projects/ADMM'
        self.project.mkdir(parents=True)
        (self.work / 'scripts').mkdir()
        (self.work / 'vivado_project/vivado_project.srcs/sources_1/new').mkdir(parents=True)
        for source in SOURCES[:8]:
            dest = self.work / source.relative_to(ROOT)
            shutil.copy2(source, dest)
        env = {k: v for k, v in os.environ.items() if not k.startswith('ADMM_')}
        env.update(ADMM_HORIZON_LENGTH='27', ADMM_ITERATIONS='9', ADMM_USE_FLOAT='1',
                   ADMM_ENABLE_TRAJECTORY='1', ADMM_SOLVER_ARCH='staged_a',
                   ADMM_RHO_EQ_PARAM='128', ADMM_RHO_INEQ_PARAM='32',
                   ADMM_TRAJ_SHAPE='fig8' if scenario == 'fig8' else 'star_hold',
                   ADMM_TRAJ_AMP_X='1' if scenario == 'fig8' else '2',
                   ADMM_TRAJ_AMP_Y='1' if scenario == 'fig8' else '2',
                   ADMM_TRAJ_STAR_POINTS='12', ADMM_TRAJ_STAR_INNER_RATIO='0.25',
                   ADMM_TRAJ_STAR_INNER_HOLD='0.25', ADMM_XY_MIN='-1', ADMM_XY_MAX='1',
                   ADMM_REPETITIONS='1', OPENBLAS_NUM_THREADS='1',
                   MPLCONFIGDIR=str(self.work / 'mpl'))
        with (args.output / f'build_{scenario}.log').open('w') as log:
            run([sys.executable, '-c', GENERATION], self.work, env, log)
            self.data = dict(np.load(self.work / 'problem.npz'))
            self.constants = json.loads(str(self.data['constants']))
            self.data['q_packed'] = quantize(self.data.pop('q'))
            self.bandwidth = int(re.search(r'#define L_BANDED_COLS (\d+)',
                                          (self.project / 'data.h').read_text())[1])
            write_matrices(self.project, self.data)
            (self.project / 'wrapper.cpp').write_text(FLOAT_BRIDGE)
            # The original library includes an unmodified ADMM.cpp plus the plant
            # and ABI bridge already used in numerical_accuracy.py.
            (self.project / 'plant.cpp').write_text(BRIDGE)
            self.compile('original', False, env, log, extra=['plant.cpp'])
            original = (self.project / 'ADMM.cpp').read_text()
            patched = original
            replacements = {
                'return std::ldexp(v, RHO_SHIFT_EQ_V);': 'return v * eval_rho_eq;',
                'return std::ldexp(v, RHO_SHIFT_INEQ_V);': 'return v * eval_rho_ineq;',
                'return std::ldexp(v, -RHO_SHIFT_EQ_V);': 'return v / eval_rho_eq;',
                'return std::ldexp(v, -RHO_SHIFT_INEQ_V);': 'return v / eval_rho_ineq;',
            }
            for old, new in replacements.items():
                if patched.count(old) != 1:
                    raise RuntimeError(f'Solver arithmetic marker changed: {old}')
                patched = patched.replace(old, new)
            # Observe z directly, rather than approximating complementarity using
            # feasibility alone. Both architecture branches are covered.
            patched, n = re.subn(r'(b_tmp\[i\] = rho_mul\(zi - yi, (?:true|false)\);)',
                                 r'eval_z[i] = zi; \1', patched)
            if n != 5:
                raise RuntimeError(f'Projection markers changed: found {n}, expected 5')
            patched, n = re.subn(r'(b_tmp\[i\] = rho_mul\(-yi, false\);)',
                                 r'eval_z[i] = 0; \1', patched)
            if n != 2:
                raise RuntimeError('Dynamics projection markers changed')
            (self.project / 'ADMM.cpp').write_text(patched)
            header = (self.project / 'data.h').read_text()
            for name in ('L_banded', 'LT_banded'):
                marker = f'const fp_t {name}['
                if header.count(marker) != 1:
                    raise RuntimeError(f'Factor marker changed: {name}')
                header = header.replace(marker, f'fp_t {name}[')
            (self.project / 'data.h').write_text(header)
            self.compile('evaluation', True, env, log)
        self.original = load_library(self.work / 'original.so', False)
        self.lib = load_library(self.work / 'evaluation.so', True)
        self.factor_cache = {}
        self.validate_original()
        self.validate_unrestricted()
        self.make_baseline()
        self.steps = np.unique(np.linspace(0, len(self.data['states'])-1, args.samples,
                                          dtype=int))
        self.states = np.ascontiguousarray(self.data['states'][self.steps], dtype=np.float32)
        self.qs = q_vectors(self.data, self.steps)
        self.references, self.osqp_rows = osqp_references(self)
        self.eligible = np.isfinite(self.references).all(axis=1)
        if not self.eligible.any():
            raise RuntimeError(f'{scenario}: no sampled QP has a solved OSQP reference')
        print(f'{scenario}: OSQP screening: {self.eligible.sum()}/{len(self.steps)} feasible sampled QPs', flush=True)

    def compile(self, name, modified, env, log, extra=()):
        run(['g++', '-O2', '-std=c++14', '-shared', '-fPIC', '-fno-fast-math',
             '-ffp-contract=off', '-Wno-unknown-pragmas', f'-DEVAL_MODIFIED={int(modified)}',
             '-I' + self.args.hls_include, 'wrapper.cpp', *extra,
             '-o', str(self.work / (name + '.so'))], self.project, env, log)

    def configure(self, pair):
        from sksparse.cholmod import cholesky

        pair = tuple(pair)
        if pair not in self.factor_cache:
            a = sparse.csc_matrix(self.data['A'])
            rows = int(self.data['eq_rows'])
            rho = np.r_[np.full(rows, pair[0]), np.full(a.shape[0]-rows, pair[1])]
            kkt = sparse.csc_matrix(self.data['P']) + a.T @ sparse.diags(rho) @ a
            params = inspect.signature(cholesky).parameters
            factor = (cholesky(kkt, lower=True, order='natural')
                      if 'lower' in params and 'order' in params
                      else cholesky(kkt, ordering_method='natural'))
            lower, permutation = factor if isinstance(factor, tuple) else (factor.L(), factor.P())
            if not np.array_equal(permutation, np.arange(len(self.data['P']))):
                raise RuntimeError('Unexpected factor permutation')
            coo = lower.tocoo()
            if np.any(coo.row - coo.col >= self.bandwidth):
                raise RuntimeError('Candidate factor exceeds generated bandwidth')
            lower = lower.toarray()
            n, w = len(lower), self.bandwidth
            lb, ub = np.zeros((n, w)), np.zeros((n, w))
            for i in range(n):
                for d in range(1, w):
                    if i >= d:
                        lb[i, w-1-d] = lower[i, i-d]
                    if i+d < n:
                        ub[i, d] = lower[i+d, i]
                lb[i, -1] = ub[i, 0] = 1 / lower[i, i]
            self.factor_cache[pair] = quantize(lb), quantize(ub)
        self.lib.configure(*pair, *self.factor_cache[pair])

    def validate_original(self):
        """Compare all iterates/buffers, not just a final motor command."""
        self.configure(DEPLOYED)
        n, m = len(self.data['P']), len(self.data['A'])
        max_error = 0.
        rng = np.random.default_rng(1729)
        for index in (0, 90, 500):
            state = rng.normal(0, .025, 12).astype(np.float32)
            q = np.zeros(n, np.float32)
            for k in range(28):
                q[k*16:k*16+3] = self.data['q_packed'][index+k]
            buffers = [[np.zeros(n, np.float32), np.zeros(n, np.float32), np.zeros(m, np.float32)]
                       for _ in range(2)]
            self.original.reset()
            self.lib.reset()
            for iteration in range(32):
                for lib, buf in zip((self.original, self.lib), buffers):
                    lib.step(state, q, 1, *buf)
                for a, b in zip(*buffers):
                    error = float(np.max(np.abs(a-b)))
                    max_error = max(max_error, error)
                    np.testing.assert_array_equal(a, b, err_msg=f'{self.scenario}: iteration {iteration+1}')
        self.validation = {'iterates_checked': 96, 'max_buffer_difference': max_error}
        print(f'{self.scenario}: original/evaluation float iterates agree exactly', flush=True)

    def validate_unrestricted(self):
        """Independent double ADMM recurrence catches inconsistent rho/factor updates."""
        from scipy.linalg import cho_factor, cho_solve

        pair = (150.5, 27.25)
        self.configure(pair)
        a, p = self.data['A'], self.data['P']
        n, m = p.shape[0], a.shape[0]
        state = np.random.default_rng(17).normal(0, .025, 12).astype(np.float32)
        q = np.zeros(n, np.float32)
        for k in range(28):
            q[k*16:k*16+3] = self.data['q_packed'][500+k]
        lo, hi = self.data['l'].copy(), self.data['u'].copy()
        lo[:12] = hi[:12] = state
        rho = np.r_[np.full(int(self.data['eq_rows']), pair[0]),
                    np.full(m-int(self.data['eq_rows']), pair[1])]
        factor = cho_factor(p + a.T @ (rho[:, None]*a))
        dual, rhs = np.zeros(m), np.zeros(n)
        x, b, y = np.zeros(n, np.float32), np.zeros(n, np.float32), np.zeros(m, np.float32)
        self.lib.reset()
        worst = 0.
        for _ in range(16):
            reference = cho_solve(factor, rhs-q)
            ax = a @ reference
            z = np.clip(ax+dual, lo, hi)
            dual += ax-z
            rhs = a.T @ (rho*(z-dual))
            self.lib.step(state, q, 1, x, b, y)
            error = float(np.max(np.abs(x-reference))/(1+np.max(np.abs(reference))))
            worst = max(worst, error)
            if error > 2e-4:
                raise AssertionError(f'{self.scenario}: arbitrary-rho recurrence error {error:g}')
        self.validation.update(arbitrary_pair=pair, arbitrary_reference_iterations=16,
                               arbitrary_reference_normalized_max_error=worst)
        print(f'{self.scenario}: arbitrary-rho recurrence checked against independent double ADMM '
              f'(normalized error {worst:.2g})', flush=True)

    def make_baseline(self):
        path = self.args.output / f'baseline_{self.scenario}.npz'
        hashes = {k: v for k, v in source_hashes().items() if k != str(Path(__file__).relative_to(ROOT))}
        settings = dict(source_hashes=hashes, scenario=self.scenario,
                        duration=self.args.duration, baseline_pair=DEPLOYED,
                        generation_sha256=hashlib.sha256(GENERATION.encode()).hexdigest(),
                        numpy=np.__version__)
        fingerprint = json.dumps(settings, sort_keys=True)
        if path.exists() and not self.args.regenerate:
            cached = dict(np.load(path))
            if str(cached['fingerprint']) != fingerprint:
                raise RuntimeError(f'Stale baseline {path}; choose a fresh --output directory')
            for key in ('states', 'reference_index', 'baseline_command'):
                self.data[key] = cached[key]
            print(f'{self.scenario}: using baseline cache ({len(cached["states"])} inputs)', flush=True)
            return
        count = round(self.args.duration * 1000)
        state, actuator, command = np.zeros(12), np.full(4, .048*9.81/(4*2.90e-6*65535)), np.zeros(4)
        states, commands, indices = [], [], []
        index, tick = 0, 0
        hover = .048*9.81/(4*2.90e-6*65535)
        for step in range(count):
            states.append(state.astype(np.float32))
            indices.append(index)
            self.original.solve(state, int(step == 0), command)
            commands.append(command.copy())
            if self.scenario == 'star':
                state = self.data['plant_A'] @ state + self.data['plant_B'] @ (command-hover)
            else:
                self.original.advance(state, actuator, command)
            if not np.isfinite(state).all() or np.max(np.abs(state[:3])) > 10:
                raise RuntimeError(f'{self.scenario}: baseline diverged at step {step}')
            tick += 1
            if tick == self.constants['TRAJ_TICK_DIV']:
                tick = 0
                index += 1
                if index == self.constants['TRAJ_LENGTH']:
                    index = self.constants['TRAJ_LOOP_START_IDX']
        self.data.update(states=np.asarray(states, np.float32),
                         reference_index=np.asarray(indices, int), baseline_command=np.asarray(commands))
        np.savez_compressed(path, **self.data, fingerprint=fingerprint)
        print(f'{self.scenario}: froze {count} float-controller inputs', flush=True)


def write_csv(path, records):
    if not records:
        return
    with path.open('w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=list(records[0]))
        writer.writeheader()
        writer.writerows(records)

def osqp_references(experiment):
    import osqp

    d = experiment.data
    solver = osqp.OSQP()
    solver.setup(P=sparse.csc_matrix(d['P']), A=sparse.csc_matrix(d['A']),
                 q=np.zeros(len(d['P'])), l=d['l'], u=d['u'], eps_abs=1e-7, eps_rel=1e-7,
                 max_iter=1000000, polish=True, verbose=False, adaptive_rho_interval=25)
    solved = osqp.constant('OSQP_SOLVED')
    infeasible = osqp.constant('OSQP_PRIMAL_INFEASIBLE')
    xs, statuses, diagnostics = [], [], []
    for step, state, q in zip(experiment.steps, experiment.states, experiment.qs):
        lo, hi = d['l'].copy(), d['u'].copy()
        lo[:12] = hi[:12] = state
        solver.update(q=q.astype(float), l=lo, u=hi)
        result = solver.solve()
        statuses.append(result.info.status)
        if result.info.status_val not in (solved, infeasible):
            raise RuntimeError(f'{experiment.scenario}: OSQP could not classify step {step}: {result.info.status}')
        x = result.x.copy() if result.info.status_val == solved else np.full(len(d['P']), np.nan)
        xs.append(x)
        diagnostics.append(dict(scenario=experiment.scenario, step=int(step), status=result.info.status,
                                eligible=int(result.info.status_val == solved),
                                primal=float(max(0, np.max(np.maximum(lo-d['A']@x, d['A']@x-hi)))) if result.info.status_val == solved else None,
                                stationarity=float(np.max(np.abs(d['P']@x+q+d['A'].T@result.y))) if result.info.status_val == solved else None))
    return np.asarray(xs), diagnostics

def replay_windows(steps, warmup):
    indices, resets, endpoints = [], [], []
    for step in steps:
        window=list(range(max(0,int(step)-warmup),int(step)+1))
        indices.extend(window)
        resets.extend([1]+[0]*(len(window)-1))
        endpoints.append(len(indices)-1)
    return np.array(indices,int), np.array(resets,np.int32), np.array(endpoints,int)

def patch_observers(text):
    text,n=re.subn(r'(b_tmp\[i\] = rho_mul\(zi - yi, (?:true|false)\);)',
                   r'observed_z[i] = zi; \1',text)
    if n!=5: raise RuntimeError('Projection observer markers changed')
    text,n=re.subn(r'(b_tmp\[i\] = rho_mul\(-yi, false\);)',r'observed_z[i] = 0; \1',text)
    if n!=2: raise RuntimeError('Dynamics observer markers changed')
    for old,new,count in [('return (fp_t)t;','return observed_cast(t,0);',4),
                          ('(fp_t)new_x','observed_cast(new_x,1)',4),
                          ('(fp_t)acc_xk','observed_cast(acc_xk,2)',1),
                          ('(fp_t)acc_uk','observed_cast(acc_uk,2)',1)]:
        if text.count(old)!=count: raise RuntimeError(f'Narrowing marker changed: {old}')
        text=text.replace(old,new)
    return text

def library(path):
    lib=ct.CDLL(str(path))
    i32=np.ctypeslib.ndpointer(dtype=np.int32,flags='C_CONTIGUOUS')
    lib.precision_replay.argtypes=[r.F64,r.F64,i32,ct.c_int,ct.c_int,ct.c_double,ct.c_double,r.F64,r.F64]
    lib.precision_replay.restype=None
    return lib

def replay(lib,states,qs,resets,pair,iterations):
    metrics=np.zeros((len(states),12)); commands=np.zeros((len(states),4))
    started=time.monotonic()
    lib.precision_replay(states,qs,resets,len(states),iterations,*pair,metrics,commands)
    return metrics,commands,time.monotonic()-started

r = sys.modules[__name__]
f = r
def instrument_headers(include, destination):
    shutil.copytree(include, destination, symlinks=False)
    header = destination/'etc/ap_fixed_base.h'
    text = header.read_text()
    marker = 'if (!underflow && !overflow) return;'
    if text.count(marker) != 1:
        raise RuntimeError('Native overflow handler changed')
    text = text.replace(marker, marker + '''
#ifdef RHO_SATURATION_AUDIT
    if (_AP_O == AP_SAT || _AP_O == AP_SAT_ZERO || _AP_O == AP_SAT_SYM)
      rho_saturation_event(_AP_W, _AP_I);
#endif
''')
    header.write_text(text)


def fixed_library(exp, include, output, audit=True):
    project = exp.project
    # Start from the unmodified production solver; only rho and z observation differ.
    source = (r.ROOT/'vitis_projects/ADMM/ADMM.cpp').read_text()
    source = f.patch_observers(source)
    source = source.replace('(RHO_SHIFT_EQ_V > RHO_SHIFT_INEQ_V) ? RHO_SHIFT_EQ_V : RHO_SHIFT_INEQ_V', '16')
    for name in ('eq','ineq'):
        for operation, symbol in [('mul','*'),('div','/')]:
            start = source.index(f'static inline fp_t rho_{operation}_{name}(fp_t v)')
            end = source.index('\n}', start)+2
            shift = '<<' if operation=='mul' else '>>'
            body = f'''static inline fp_t rho_{operation}_{name}(fp_t v) {{
    if (eval_shift_{name} >= 0) {{
        rho_acc_t t = v;
        t {shift}= eval_shift_{name};
        return (fp_t)t;
    }}
    return (fp_t)(v {symbol} eval_rho_{name});
}}'''
            source = source[:start]+body+source[end:]
    (project/'ADMM.cpp').write_text(source)
    config = project/'admm_runtime_config.h'
    config.write_text(config.read_text().replace('#define ADMM_USE_FLOAT 1','#define ADMM_USE_FLOAT 0'))
    bridge = FIXED_BRIDGE
    bridge = bridge.replace('#include "data.h"', '''static long long native_events[3] = {};
static bool stop_on_saturation = true;
static int allowed_affected_inputs = 0;
extern "C" void audit_allow(int count) { allowed_affected_inputs=count; }
extern "C" void audit_stop(int enabled) { stop_on_saturation=enabled; }
static void rho_saturation_event(int w, int i) {
    ++native_events[(w==32 && i==10) ? 0 : ((w==40 && i==18) ? 1 : 2)];
}
#include "data.h"
static ap_fixed<64,32,AP_RND,AP_SAT> eval_rho_eq, eval_rho_ineq;
static int eval_shift_eq, eval_shift_ineq;
extern "C" void configure(float eq, float ineq, const double *lower, const double *upper) {
    eval_rho_eq=eq; eval_rho_ineq=ineq;
    eval_shift_eq = std::log2(eq)==std::floor(std::log2(eq)) ? int(std::log2(eq)) : -1;
    eval_shift_ineq = std::log2(ineq)==std::floor(std::log2(ineq)) ? int(std::log2(ineq)) : -1;
    for(int i=0;i<N_VAR;++i) for(int j=0;j<L_BANDED_COLS;++j) {
        L_banded[i][j]=lower[i*L_BANDED_COLS+j];
        LT_banded[i][j]=upper[i*L_BANDED_COLS+j];
    }
}
extern "C" void audit_reset() { for(int i=0;i<3;++i) native_events[i]=0; }
extern "C" long long audit_count() { return native_events[0]+native_events[1]+native_events[2]; }
extern "C" int audit_self_test() {
    audit_reset();
    fp_t a=512.; // input conversion saturates
    ap_fixed<40,18,AP_RND,AP_SAT> b=131072.; // accumulator conversion
    fp_t c=-512.; // exact rail is representable, not a saturation
    fp_t d=511.;
    d += c-c+2; // implicit assignment saturates
    return a==fp_t(512.-1./4194304.) && b==ap_fixed<40,18,AP_RND,AP_SAT>(131072.-1./4194304.)
        && c==fp_t(-512.) && native_events[0]==2 && native_events[1]==1;
}

''')
    bridge = bridge.replace('#include "data.h"', '#include <cmath>\n#include "data.h"',1)
    bridge = bridge.replace('std::fill_n(range_events,3,0);','std::fill_n(native_events,3,0);')
    bridge = bridge.replace('m[5+j]=range_events[j]','m[5+j]=native_events[j]')
    bridge=bridge.replace('fp_t x[N_VAR] = {}, b[N_VAR]', 'int affected_inputs=0;\n    fp_t x[N_VAR] = {}, b[N_VAR]')
    bridge=bridge.replace('commands[c*4+j]=(double)x[12+j];', 'commands[c*4+j]=(double)x[12+j];\n        if (audit_count()) ++affected_inputs;\n        if (stop_on_saturation && affected_inputs > allowed_affected_inputs) return;')
    (project/'wrapper.cpp').write_text(bridge)
    path = output/('fixed_audit.so' if audit else 'fixed_plain.so')
    with (output/'fixed_build.log').open('a') as log:
        r.run(['g++','-O2','-std=c++14','-shared','-fPIC','-fno-fast-math','-ffp-contract=off',
               '-Wno-unknown-pragmas','-DOBSERVE_CASTS=0',*(['-DRHO_SATURATION_AUDIT'] if audit else []),
               '-I'+str(include),'wrapper.cpp','-o',str(path)],project,os.environ.copy(),log)
    lib=f.library(path)
    lib.configure.argtypes=[ct.c_float,ct.c_float,r.F64,r.F64]
    lib.audit_count.restype=ct.c_longlong
    return lib


def fixed_factors(exp, pair):
    from sksparse.cholmod import cholesky
    a=r.sparse.csc_matrix(exp.data['A'])
    eq=int(exp.data['eq_rows'])
    rho=np.r_[np.full(eq,pair[0]),np.full(a.shape[0]-eq,pair[1])]
    kkt=r.sparse.csc_matrix(exp.data['P'])+a.T@r.sparse.diags(rho)@a
    params=r.inspect.signature(cholesky).parameters
    factor=cholesky(kkt,lower=True,order='natural') if 'lower' in params and 'order' in params else cholesky(kkt,ordering_method='natural')
    lower,perm=factor if isinstance(factor,tuple) else (factor.L(),factor.P())
    if not np.array_equal(perm,np.arange(len(exp.data['P']))):
        raise RuntimeError('Unexpected factor permutation')
    lower=lower.toarray(); n,w=len(lower),exp.bandwidth
    lb=np.zeros((n,w)); ub=np.zeros((n,w))
    for i in range(n):
        for d in range(1,w):
            if i>=d: lb[i,w-1-d]=lower[i,i-d]
            if i+d<n: ub[i,d]=lower[i+d,i]
        lb[i,-1]=ub[i,0]=1/lower[i,i]
    # Match generated decimal literals before native fixed-point conversion.
    return tuple(np.array([float(f'{v:.8f}') for v in matrix.flat],dtype=np.float64).reshape(matrix.shape)
                 for matrix in (lb,ub))

WORKER = None

def worker(pair):
    return WORKER(pair)

def passes_threshold(row, threshold):
    return (row['complete'] and row['factor_events']==0 and row['nonfinite']==0
            and 100*row['saturated_inputs'] <= threshold*row['planned_inputs'])


def eligible_rank(row):
    if not row['eligible'] or not np.isfinite([row['float_error_mean'],row['float_error_p95']]).all():
        return (1,float('inf'),float('inf'),row['rho_eq'],row['rho_ineq'])
    return (0,row['float_error_mean'],row['float_error_p95'],row['rho_eq'],row['rho_ineq'])


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--hls-include',required=True)
    p.add_argument('--output',type=Path,default=r.HERE/'output/rho_saturation')
    p.add_argument('--jobs',type=int,default=8)
    a=p.parse_args()
    a.samples=64; a.warmup=32; a.iterations=10; a.log2_min=0; a.log2_max=10
    a.thresholds=[.1]; a.smoke=False; a.current_only=False
    if any(not np.isfinite(v) or not 0<=v<=100 for v in a.thresholds) or a.jobs<1 or not 0<=a.log2_min<=a.log2_max<=16 or a.samples<2 or a.warmup<0 or a.iterations<1:
        p.error('Require exponent bounds within [0,16], samples>=2, warmup>=0, iterations>=1')
    a.output=a.output.resolve(); a.output.mkdir(parents=True,exist_ok=True)
    if a.smoke: a.samples=4; a.warmup=1; a.log2_min=5; a.log2_max=6
    rows=[]
    with tempfile.TemporaryDirectory(prefix='rho-saturation-') as tmp:
        tmp=Path(tmp); inc=tmp/'include'
        instrument_headers(a.hls_include,inc)
        experiments=[]
        for scenario in ('fig8','star'):
            args=argparse.Namespace(**vars(a),duration=25.6,max_iterations=a.iterations,tolerance=1e-4,regenerate=False)
            exp=r.Experiment(scenario,str(tmp),args)
            folder=a.output/scenario; folder.mkdir(exist_ok=True)
            exp.fixed=fixed_library(exp,inc,folder)
            exp.startup_events=exp.fixed.audit_count()
            if exp.fixed.audit_self_test()!=1: raise AssertionError('Native saturation hook self-test failed')
            exp.plain=fixed_library(exp,inc,folder,False)
            indices,resets,endpoints=f.replay_windows(exp.steps,a.warmup)
            exp.replay_states=np.ascontiguousarray(exp.data['states'][indices],dtype=np.float64)
            exp.replay_qs=np.ascontiguousarray(r.q_vectors(exp.data,indices),dtype=np.float64)
            exp.resets=resets; exp.endpoints=endpoints
            experiments.append(exp)
        planned=sum(len(exp.replay_states) for exp in experiments)
        allowed=int(np.floor(max(a.thresholds)*planned/100))
        scores={}
        def evaluate(pair):
            pair=tuple(float(np.float32(v)) for v in pair)
            if pair in scores: return
            errors=[]; fixed_errors=[]; gaps=[]; saturation=0; total_nonfinite=0; pair_rows=[]; affected=0; total_loading=0; complete=True
            for exp in experiments:
                exp.configure(pair)
                factors=fixed_factors(exp,pair)
                exp.fixed.audit_allow(allowed)
                exp.fixed.audit_stop(0 if pair==r.DEPLOYED or a.smoke else 1)
                exp.fixed.audit_reset()
                exp.fixed.configure(*pair,*factors)
                loading=exp.fixed.audit_count()+exp.startup_events
                metrics,commands,elapsed=f.replay(exp.fixed,exp.replay_states,exp.replay_qs,exp.resets,pair,a.iterations)
                events=int(metrics[:,5:8].sum())+loading
                # Native audit must not change a single command on the full replay.
                if pair==r.DEPLOYED or a.smoke:
                    exp.plain.configure(*pair,*factors)
                    _,plain,_=f.replay(exp.plain,exp.replay_states,exp.replay_qs,exp.resets,pair,a.iterations)
                    np.testing.assert_array_equal(commands,plain)
                # Float wrapper supports warm memory per call: replay each window separately.
                float_commands=[]; float_nonfinite=0; float_all_commands=np.zeros_like(commands)
                begins=np.flatnonzero(exp.resets)
                for begin,end in zip(begins,exp.endpoints):
                    count=end-begin+1
                    m=np.zeros((count,7)); x=np.zeros((count,len(exp.data['P'])),np.float32)
                    states=np.ascontiguousarray(exp.replay_states[begin:end+1],dtype=np.float32)
                    qs=np.ascontiguousarray(exp.replay_qs[begin:end+1],dtype=np.float32)
                    exp.lib.cases(states,qs,count,a.iterations,1e-4,1,m,x)
                    float_nonfinite+=int(not np.isfinite(m).all() or not np.isfinite(x).all())
                    float_commands.append(x[-1,12:16].copy())
                    float_all_commands[begin:end+1]=x[:,12:16]
                float_commands=np.asarray(float_commands)
                err=np.max(np.abs(float_commands[exp.eligible]-exp.references[exp.eligible,12:16]),axis=1)
                completed=int(np.count_nonzero(metrics[:,3]))
                fixed_err=np.max(np.abs(commands[exp.endpoints[exp.eligible]]-exp.references[exp.eligible,12:16]),axis=1) if completed==len(metrics) else np.array([np.nan])
                nonfinite=float_nonfinite+int(not np.isfinite(commands).all())
                saturated_inputs=int(np.count_nonzero(metrics[:,5:8].sum(axis=1)))
                affected+=saturated_inputs; total_loading+=loading; complete &= completed==len(metrics)
                fixed_errors.extend(fixed_err)
                gap=np.max(np.abs(commands[:completed]-float_all_commands[:completed]),axis=1)
                gaps.extend(gap)
                saturation+=events; total_nonfinite+=nonfinite; errors.extend(err)
                pair_rows.append(dict(scenario=exp.scenario,rho_eq=pair[0],rho_ineq=pair[1],saturation_events=events,nonfinite=nonfinite,
                                 replayed_inputs=completed,planned_inputs=len(metrics),saturated_inputs=saturated_inputs,saturated_input_percent=100*saturated_inputs/len(metrics),fixed_float_gap_max=float(gap.max()),factor_events=loading,fp_events=int(metrics[:,5].sum()),accumulator_events=int(metrics[:,6].sum()),
                                 other_events=int(metrics[:,7].sum()),float_error_mean=float(err.mean()),
                                 fixed_error_mean=float(fixed_err.mean()) if np.isfinite(fixed_err).all() else None,samples=len(err),seconds=elapsed))
            score=dict(rho_eq=pair[0],rho_ineq=pair[1],eligible=complete and affected<=allowed and total_nonfinite==0 and total_loading==0,complete=complete,saturation_events=saturation,nonfinite=total_nonfinite,
                              saturated_inputs=affected,planned_inputs=planned,saturated_input_percent=100*affected/planned,factor_events=total_loading,
                              fixed_error_mean=float(np.mean(fixed_errors)) if complete else None,fixed_float_gap_max=float(np.max(gaps)),
                              float_error_mean=float(np.mean(errors)),float_error_p95=float(np.percentile(errors,95)))
            return pair,score,pair_rows
        global WORKER
        WORKER=evaluate
        def evaluate_many(pairs):
            pending=list(dict.fromkeys(tuple(float(np.float32(v)) for v in p) for p in pairs))
            pending=[p for p in pending if p not in scores]
            with multiprocessing.get_context('fork').Pool(a.jobs) as pool:
                for pair,score,pair_rows in pool.imap_unordered(worker,pending):
                    scores[pair]=score; rows.extend(pair_rows)
                    r.write_csv(a.output/'candidates.csv',list(scores.values()))
                    print(f'{len(scores)} rho={pair} events={score["saturation_events"]} '
                          f'float error={score["float_error_mean"]:.8g}',flush=True)
        with (HERE/'data/rho_saturation_candidates.csv').open() as handle:
            candidates=[(float(row['rho_eq']),float(row['rho_ineq'])) for row in csv.DictReader(handle)]
        evaluate_many(candidates)
        powers=[p for p in scores if all(np.log2(v).is_integer() for v in p)]
        comparisons=[]; selected_rows=[]
        for threshold in sorted(set(a.thresholds)):
            selected=[('Current',r.DEPLOYED)]
            p2=[p for p in powers if passes_threshold(scores[p],threshold)]
            free=[p for p in scores if passes_threshold(scores[p],threshold)]
            comparison=dict(threshold_percent=threshold,eligible_power_candidates=len(p2),eligible_all_candidates=len(free),power_of_two=None,unrestricted=None,overhead_percent=None)
            if p2 and free and not a.current_only:
                best=min(p2,key=lambda p:eligible_rank(scores[p]))
                unrestricted=min(free,key=lambda p:eligible_rank(scores[p]))
                selected += [('Best power of two',best),('Best unrestricted',unrestricted)]
                overhead=100*(scores[best]['float_error_mean']/scores[unrestricted]['float_error_mean']-1)
                comparison.update(power_of_two=best,unrestricted=unrestricted,overhead_percent=overhead)
            for label,pair in selected:
                row=scores[pair]; eligible=passes_threshold(row,threshold)
                selected_rows.append(dict(threshold_percent=threshold,candidate=label,passes_threshold=eligible,**row))
            comparisons.append(comparison)
        for row in selected_rows:
            if row['candidate']!='Current':
                print(f"{row['candidate']}: rho=({row['rho_eq']:.8g}, {row['rho_ineq']:.8g}), mean float error={row['float_error_mean']:.8g}, affected inputs={row['saturated_inputs']}/{row['planned_inputs']}")
        print(f"Mean command-error increase: {comparisons[0]['overhead_percent']}%")

if __name__=='__main__': main()
