#!/usr/bin/env python3
"""Generate isolated MOBY-DIC HLS baseline and validate the original kernel."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import ast
import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import numpy as np
from scipy import sparse
import osqp

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / 'scripts'
sys.path.insert(0, str(SCRIPTS))
import parameters as cfg
from crazyflie_model import CrazyFlieModel


def compute_admm_matrices(P, q, G, h, E, b, rho):
    """Port of computeADMMmatrices.m, with a linear solve replacing inv."""
    A = np.vstack((G, E))
    c = np.concatenate((h, b))
    M1 = -np.linalg.solve(P + rho * A.T @ A, np.eye(len(q)))
    M2 = rho * M1 @ A.T
    return M1, M2, -G, A, M1 @ q - M2 @ c, c, h


def transform_kernel(source, architecture, nvar, nineq, neq):
    """Exact nontracking replacements from generateVHDL.m."""
    source = source.replace('DIM_TO_REPLACE', str(nvar + 2 * nineq + neq))
    if architecture == 'small':
        source = source.replace('#pragma HLS allocation operation instances=mul', '//')
        source = source.replace('#pragma HLS UNROLL //small', '#pragma HLS PIPELINE')
    return source


def declaration(name, array):
    shape = ''.join(f'[{n}]' for n in array.shape)
    def values(a):
        if a.ndim == 0:
            return format(float(a), '.17g')
        return '{' + ','.join(values(x) for x in a) + '}'
    return f'static const double {name}{shape} = {values(array)};\n'


def upstream_functions():
    # Compile only pure functions, avoiding header_generator's production writes.
    tree = ast.parse((SCRIPTS / 'header_generator.py').read_text())
    names = {'build_Aeq_interleaved', 'build_full_constraint_matrix'}
    module = ast.Module(body=[n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in names], type_ignores=[])
    namespace = {'np': np}
    exec(compile(module, 'header_generator.py:selected_functions', 'exec'), namespace)
    return namespace


def problem(H):
    if os.environ.get('ADMM_ABQR_OVERRIDE_PATH'):
        raise ValueError('Matrix overrides are not yet supported; unset ADMM_ABQR_OVERRIDE_PATH')
    with contextlib.redirect_stdout(io.StringIO()):
        model = CrazyFlieModel(freq=cfg.MODEL_FREQ)
    xg = np.zeros(13); xg[3] = 1
    A, B = model.get_linearized_dynamics(xg, model.hover_thrust)
    A[6, 6] -= cfg.MPC_LINEAR_DRAG_XY / model.mass / cfg.MODEL_FREQ
    A[7, 7] -= cfg.MPC_LINEAR_DRAG_XY / model.mass / cfg.MODEL_FREQ
    A[8, 8] -= cfg.MPC_LINEAR_DRAG_Z / model.mass / cfg.MODEL_FREQ
    Q, R = np.diag(cfg.Q_DIAG), np.diag(cfg.R_DIAG)
    P = sparse.block_diag([block for _ in range(H) for block in (Q, R)] + [Q]).toarray()
    funcs = upstream_functions()
    E, C, _ = funcs['build_full_constraint_matrix'](A, B, H, 12, 4, 6*H, 16*H+12)
    shift = 0.
    if cfg.TRAJ_SHAPE == 'star_hold':
        shift = cfg.AMP_X * cfg.STAR_INNER_RATIO * np.cos(np.arctan2(cfg.AMP_X, cfg.AMP_Y))
    low, high = cfg.XY_MIN-shift, cfg.XY_MAX-shift
    if cfg.TRAJ_SHAPE == 'diamond1m_hold':
        shift = .5/np.sqrt(2); low, high = -.5-shift, .5-shift
    l = np.r_[np.tile(cfg.U_ABS_MIN-model.hover_thrust, H), np.full(2*H, low)]
    u = np.r_[np.tile(cfg.U_ABS_MAX-model.hover_thrust, H), np.full(2*H, high)]
    # z_moby = z_accel[order], inputs first, then x0..xH.
    order = np.array([k*16+12+j for k in range(H) for j in range(4)] +
                     [k*16+j for k in range(H+1) for j in range(12)])
    Pm, Em, Cm = P[np.ix_(order, order)], E[:, order], C[:, order]
    G, h = np.vstack((Cm, -Cm)), np.r_[u, -l]
    # Independent block construction checks the ordering and objective mapping.
    expected = sparse.block_diag([R]*H + [Q]*(H+1)).toarray()
    np.testing.assert_array_equal(Pm, expected)
    rng = np.random.default_rng(7)
    for _ in range(5):
        z = rng.normal(size=len(order)); za = np.empty_like(z); za[order] = z
        np.testing.assert_allclose(Em@z, E@za, atol=1e-12)
        np.testing.assert_allclose(G@z-h, np.r_[C@za-u, l-C@za], atol=1e-12)
        np.testing.assert_allclose(z@Pm@z, za@P@za, atol=1e-10)
    return Pm, Em, G, h, order, (P, E, C, l, u), {
        'A': A.tolist(), 'B': B.tolist(), 'Q': Q.tolist(), 'R': R.tolist(),
        'terminal_weight': 'Q (as executed by AccelMPC generator)',
        'hover': model.hover_thrust.tolist(), 'xy_bounds': [low, high],
        'model_frequency': cfg.MODEL_FREQ, 'trajectory_shape': cfg.TRAJ_SHAPE,
        'drag_xy': cfg.MPC_LINEAR_DRAG_XY, 'drag_z': cfg.MPC_LINEAR_DRAG_Z}


def cases(H, order):
    result = []
    for name, position, reference in [('hover', [0,0,0], [0,0,0]),
                                      ('offset', [.15,-.1,.2], [0,0,0]),
                                      ('tracking', [0,0,0], [.3,-.2,.4]),
                                      ('input_active', [0,0,0], [0,0,5.])]:
        x = np.zeros(12); x[:3] = position
        q = np.zeros(16*H+12)
        for k in range(H+1):
            q[k*16:k*16+3] = -np.array(cfg.Q_DIAG[:3])*reference
        result.append((name, x, q[order]))
    return result


WRAPPER = '''#include "controller.h"
void control(fxd x[12], fxd q[nDim_CTRL], fxd u[4], fxd z[nDim_CTRL]) {
#pragma HLS ARRAY_PARTITION variable=x complete
#pragma HLS ARRAY_PARTITION variable=q complete
  fxd v1[nDim_CTRL], v2[nRows];
#pragma HLS ARRAY_PARTITION variable=v1 complete
#pragma HLS ARRAY_PARTITION variable=v2 complete
  for(int i=0;i<nRows;i++) {
#pragma HLS PIPELINE
    v2[i] = i<nCon ? v3[i] : (i<nCon+12 ? x[i-nCon] : fxd(0));
  }
  for(int j=0;j<nDim_CTRL;j++) {
#pragma HLS PIPELINE off
    fxd_tmp_m a=0, b=0;
    for(int i=0;i<nRows;i++) {
#pragma HLS PIPELINE
      a -= M2[j][i]*v2[i];
    }
    for(int i=0;i<nDim_CTRL;i++) {
#pragma HLS PIPELINE
      b += M1[j][i]*q[i];
    }
    v1[j]=a+b;
  }
  admm(v1,v2,z);
  for(int i=0;i<4;i++) u[i]=z[i];
}
'''


def generate(directory, arch, variant, H, matrices, testcases, iterations, accumulator="accelmpc"):
    M1,M2,M3,M4,_,_,h = matrices
    nv, nc, nr = M2.shape[0], len(h), M2.shape[1]
    W,I = {'native': (12,5), 'wide': (32,12), 'double': (32,12)}[variant]
    im = int(np.ceil(np.log2(max(np.max(abs(m)) for m in (M1,M2,M3,M4)))))+2
    # One carry bit for (y + lambda), then ceil(log2(number of products)).
    # Retain the full product fractional precision; only redundant integer bits shrink.
    terms = max(nv,nr)
    acc = 8 if accumulator == "accelmpc" else (terms if accumulator == "original" else (terms-1).bit_length() + 1)
    aw, ai = (W+acc, I+acc) if accumulator == "accelmpc" else (2*W+im+acc, I+im+acc)
    acc_modes = ",AP_RND,AP_SAT" if accumulator == "accelmpc" else ""
    types = ('typedef double fxd;\ntypedef double fxd_m;\ntypedef double fxd_tmp_m;\n' if variant=='double' else
             f'#include <ap_fixed.h>\ntypedef ap_fixed<{W},{I}> fxd;\n'
             f'typedef ap_fixed<{W+im},{im}> fxd_m;\n'
             f'typedef ap_fixed<{aw},{ai}{acc_modes}> fxd_tmp_m;\n')
    header = ('#pragma once\n'+types+f'#define N {H}\n#define nX_CTRL 12\n#define nDim_CTRL {nv}\n'
              f'#define nCon {nc}\n#define nRows {nr}\n#ifndef MOBYDIC_ITERATIONS\n#define MOBYDIC_ITERATIONS {iterations}\n#endif\n#define max_iter MOBYDIC_ITERATIONS\n')
    for name,m in [('M1',M1),('M2',M2),('M3',M3),('M4',M4),('v3',h)]:
        header += declaration(name,m).replace('const double', 'const fxd' if name=='v3' else 'const fxd_m')
    header += 'void admm(fxd*,fxd*,fxd*);\nvoid control(fxd*,fxd*,fxd*,fxd*);\n'
    directory.mkdir(parents=True,exist_ok=True)
    (directory/'controller.h').write_text(header)
    source = (ROOT/'evaluation/mobydic/upstream/cpp/implicitMPCctrl/admm.cpp').read_text()
    # Correct a scratch buffer dimension only when the problem requires it.
    if nc > nv:
        source = source.replace('y_tmp[nDim_CTRL]', 'y_tmp[nCon]')
        source = source.replace('for (int i = 0; i < nDim_CTRL; i++)\n\t\t{\n\t\t\t#pragma HLS UNROLL\n\t\t\ty_tmp[i] = 0;',
                                'for (int i = 0; i < nCon; i++)\n\t\t{\n\t\t\t#pragma HLS UNROLL\n\t\t\ty_tmp[i] = 0;')
    (directory/'admm.cpp').write_text(transform_kernel(source, arch,nv,nc,12*(H+1)))
    (directory/'controller.cpp').write_text(WRAPPER)
    tb = '#include "controller.h"\n#include <cstdio>\n#include <cstdlib>\n'
    tb += declaration('test_x',np.array([c[1] for c in testcases]))
    tb += declaration('test_q',np.array([c[2] for c in testcases]))
    tb += '''int main(int argc,char**argv){
      int c=argc>1 ? std::atoi(argv[1]):0;
      if(c<0 || c>=4) return 2;
      fxd x[12],q[nDim_CTRL],u[4],z[nDim_CTRL];
      for(int i=0;i<12;i++) x[i]=test_x[c][i];
      for(int i=0;i<nDim_CTRL;i++) q[i]=test_q[c][i];
      control(x,q,u,z);
      for(int i=0;i<nDim_CTRL;i++) std::printf("%.17g\\n",double(z[i]));
      return 0;
    }'''
    (directory/'testbench.cpp').write_text(tb)
    (directory/'hls_config.cfg').write_text(f'part=xc7a100t-csg324-1\n[hls]\nflow_target=vivado\nsyn.top=control\nclock={CLOCK_NS}ns\nsyn.file=controller.cpp\nsyn.file=admm.cpp\ntb.file=testbench.cpp\npackage.output.format=ip_catalog\n')
    (directory/'build.sh').write_text('#!/usr/bin/env bash\nset -euo pipefail\ncd -- "$(dirname -- "$0")"\nvitis-run --mode hls --csim --config hls_config.cfg --work_dir hls\nv++ -c --mode hls --config hls_config.cfg --work_dir hls\n')
    return {'accumulator_policy': accumulator, 'accumulator_guard_bits': acc, 'maximum_sum_terms': terms, 'fxd': [W,I] if variant!='double' else 'double', 'fxd_m': [W+im,im] if variant!='double' else 'double',
            'accumulator_rounding': 'AP_RND' if accumulator=='accelmpc' else 'AP_TRN', 'accumulator_overflow': 'AP_SAT' if accumulator=='accelmpc' else 'AP_WRAP',
            'fxd_tmp_m': [aw,ai] if variant!='double' else 'double'}


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--horizon',type=int,default=5)
    ap.add_argument('--output',type=Path,default=ROOT/'evaluation/mobydic/output/h5')
    ap.add_argument('--iterations',type=int,nargs='+',default=[10])
    ap.add_argument('--rho',type=float,default=1000.)
    ap.add_argument('--hls-iterations',type=int,default=10)
    ap.add_argument('--accumulator',choices=['accelmpc','bounded','original'],default='accelmpc')
    ap.add_argument('--architectures',nargs='+',choices=['small','fast'],default=['small'])
    ap.add_argument('--host-opt',choices=['0','1','2','3'],default=None)
    ap.add_argument('--case-workers',type=int,default=1)
    ap.add_argument('--hls-include',type=Path)
    ap.add_argument('--generate-only',action='store_true')
    ap.add_argument('--variants',nargs='+',choices=['double','native','wide'],default=['wide'])
    ap.add_argument('--clock-ns', type=float, default=10.)
    global CLOCK_NS
    args=ap.parse_args(); H=args.horizon
    CLOCK_NS = args.clock_ns
    if not (ROOT/'evaluation/mobydic/upstream/cpp/implicitMPCctrl/admm.cpp').exists():
        ap.error('Initialize upstream: git submodule update --init --recursive')
    if H<1 or args.rho<=0 or min(args.iterations)<1 or args.hls_iterations<1 or args.case_workers<1: ap.error('positive horizon, rho, and iterations required')
    out=args.output.resolve(); out.mkdir(parents=True,exist_ok=True)
    P,E,G,h,order,accel,metadata=problem(H)
    cs=cases(H,order); nv=len(order); nc=len(h)
    matrices=compute_admm_matrices(P,np.zeros(nv),G,h,E,np.zeros(len(E)),args.rho)
    np.savez(out/'qp.npz',P=P,E=E,G=G,h=h,order=order,**{k:np.array(v) for k,v in zip(['M1','M2','M3','M4'],matrices[:4])})
    report={'horizon':H,'rho':args.rho,'hls_iterations':args.hls_iterations,'n_variables':nv,'one_sided_inequalities':nc,'equality_rows':len(E),
            'model':metadata,'equivalence':'matrix permutation and one-sided conversion checked; OSQP both formulations',
            'environment':{k:v for k,v in os.environ.items() if k.startswith('ADMM_')},
            'sources':{str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in
                       [SCRIPTS/'parameters.py',SCRIPTS/'header_generator.py',SCRIPTS/'crazyflie_model.py', ROOT/'evaluation/mobydic/upstream/cpp/implicitMPCctrl/admm.cpp']},
            'numerical_profiles':{},'oracles':{},'results':[],
            'validation_mode':'fresh process for each input; cold starts only',
            'toolchain':{'numpy':np.__version__,'osqp':osqp.__version__,
                         'hls_include':str(args.hls_include) if args.hls_include else None,
                         'host_optimization_override':args.host_opt,
                         'compiler':subprocess.check_output(['g++','--version'],text=True).splitlines()[0]}}
    refs=[]
    for name,x,q in cs:
        b=np.r_[x,np.zeros(len(E)-12)]
        solver=osqp.OSQP(); solver.setup(P=sparse.csc_matrix(P),q=q,A=sparse.csc_matrix(np.vstack([G,E])),
                l=np.r_[np.full(nc,-np.inf),b],u=np.r_[h,b],eps_abs=1e-9,eps_rel=1e-9,max_iter=200000,polish=True,verbose=False)
        sol=solver.solve(); assert sol.info.status=='solved', (name,sol.info.status)
        Pa,Ea,Ca,l,u=accel; qa=np.empty_like(q); qa[order]=q
        other=osqp.OSQP(); other.setup(P=sparse.csc_matrix(Pa),q=qa,A=sparse.csc_matrix(np.vstack([Ea,Ca])),
                l=np.r_[b,l],u=np.r_[b,u],eps_abs=1e-9,eps_rel=1e-9,max_iter=200000,polish=True,verbose=False)
        so=other.solve(); assert so.info.status=='solved'
        np.testing.assert_allclose(sol.x,so.x[order],atol=1e-6,rtol=1e-6)
        refs.append(sol.x)
        report['oracles'][name]={'status':sol.info.status,'u0':sol.x[:4].tolist(),'formulation_solution_error':float(np.max(abs(sol.x-so.x[order])))}
    for arch in args.architectures:
        for variant in args.variants:
            d=out/f'{arch}_{variant}'
            report['numerical_profiles'][variant]=generate(d,arch,variant,H,matrices,cs,args.hls_iterations,args.accumulator)
            if args.generate_only or (variant!='double' and not args.hls_include):
                report['results'].append({'architecture':arch,'variant':variant,'status':'generated only; not compiled or simulated'})
                continue
            for iterations in args.iterations:
                executable=d/f'csim_k{iterations}'
                # One translation unit avoids repeating large ap_fixed constant
                # initializers; O0 avoids costly optimization of those initializers.
                (d/'host.cpp').write_text('#include "admm.cpp"\n#include "controller.cpp"\n#include "testbench.cpp"\n')
                command=['g++','-std=c++14','-O'+(args.host_opt or ('2' if variant=='double' else '0')),'-Wno-unknown-pragmas',f'-DMOBYDIC_ITERATIONS={iterations}']
                if args.hls_include: command += ['-I',str(args.hls_include)]
                command += [str(d/'host.cpp'),'-o',str(executable)]
                subprocess.run(command,check=True,stdout=subprocess.DEVNULL)
                with ThreadPoolExecutor(max_workers=args.case_workers) as pool:
                    outputs=list(pool.map(lambda i: subprocess.check_output([str(executable),str(i)],text=True),range(len(cs))))
                for i,(name,x,q) in enumerate(cs):
                    z=np.fromstring(outputs[i],sep='\n')
                    assert len(z)==nv and np.all(np.isfinite(z))
                    b=np.r_[x,np.zeros(len(E)-12)]
                    result={'architecture':arch,'variant':variant,'iterations':iterations,'case':name,
                            'first_control_error':float(np.max(abs(z[:4]-refs[i][:4]))),
                            'inequality_violation':float(max(0.,np.max(G@z-h))),
                            'equality_residual':float(np.max(abs(E@z-b))),
                            'objective_gap':float(.5*z@P@z+q@z-(.5*refs[i]@P@refs[i]+q@refs[i])),
                            'max_solution_error':float(np.max(abs(z-refs[i])))}
                    report['results'].append(result)
                    (out/'report.json').write_text(json.dumps(report,indent=2)+'\n')
                print(f'{arch} {variant} k={iterations}: completed',flush=True)
            (out/'report.json').write_text(json.dumps(report,indent=2)+'\n')
    (out/'report.json').write_text(json.dumps(report,indent=2)+'\n')
    print(f'Results: {out / "report.json"}')

if __name__=='__main__': main()
