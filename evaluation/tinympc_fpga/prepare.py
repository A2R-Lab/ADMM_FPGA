#!/usr/bin/env python3
"""Adapt upstream fused TinyMPC to AccelMPC dynamics; retain steady-state algorithm."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

import numpy as np
import osqp
from scipy import sparse

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / 'evaluation/mobydic'))
from quadrotor import problem, cases, declaration, cfg


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--upstream', type=Path, default=HERE / 'upstream')
    ap.add_argument('--output', type=Path, required=True)
    ap.add_argument('--horizon', type=int, default=5)
    ap.add_argument('--iterations', type=int, default=10)
    ap.add_argument('--rho', type=float, default=1.0)
    ap.add_argument('--generate-only', action='store_true', help='Skip dense QP/oracle and host validation for horizon sweeps')
    ap.add_argument('--model-report', type=Path, help='Use model metadata from a validated numerical.json')
    args = ap.parse_args()
    if args.horizon < 1 or args.iterations < 1 or args.rho <= 0:
        ap.error('positive horizon, iterations and rho required')
    upstream = args.upstream.resolve()
    sys.path.insert(0, str(upstream))
    from tinympcref import tinympcref
    from tinympc_ip_generator import TinyMPCIPGenerator
    from hls_generator import TinyMPCFunctionGenerator, BaseFunctionGenerator

    H, K = args.horizon, args.iterations
    if args.generate_only:
        if args.model_report is None:
            ap.error('--generate-only requires --model-report')
        model = json.loads(args.model_report.read_text())['model']
    else:
        P, E, G, h, order, _, model = problem(H)
    A, B, Q, R = [np.array(model[k]) for k in ('A', 'B', 'Q', 'R')]
    # Match the existing baseline bounds exactly, including no bound on x0.
    if args.generate_only:
        umin = np.asarray(cfg.U_ABS_MIN)-np.array(model['hover'])
        umax = np.asarray(cfg.U_ABS_MAX)-np.array(model['hover'])
    else:
        umin, umax = -h[6*H:6*H+4], h[:4]
    xmin, xmax = np.full((H+1,12), -np.inf), np.full((H+1,12), np.inf)
    xmin[1:,:2], xmax[1:,:2] = model['xy_bounds']

    class Reference(tinympcref):
        def _update_slack(self):
            # Upstream solve() replaces x/u with slack outputs before returning.
            self.primal_x = self.x.copy()
            self.primal_u = self.u.copy()
            super()._update_slack()

    def reference():
        s = Reference()
        s.setup(A, B, Q, R, H+1, rho=args.rho, u_min=umin, u_max=umax,
                max_iter=K, check_termination=0)
        s.x_min, s.x_max = xmin.copy(), xmax.copy()
        return s

    class Adapter(TinyMPCIPGenerator):
        def _format_value(self, v):
            if np.isposinf(v): return 'INFINITY'
            if np.isneginf(v): return '-INFINITY'
            return super()._format_value(v)

        def generate_subfunctions(self):
            parts = []
            for name in ('forward_pass','backward_pass','update_slack','update_dual','update_linear_cost'):
                g = TinyMPCFunctionGenerator.__new__(TinyMPCFunctionGenerator)
                g.function_name, g.solver = name, self.solver
                g.precision, g.data_type, g.suffix = 'float', 'float', 'f'
                g.base_gen = BaseFunctionGenerator(self.solver, 'float')
                parts.append(g.generate_implementation())
            return '\n'.join(parts)

    g = Adapter.__new__(Adapter)
    g.solver, g.N, g.max_iter = reference(), H+1, K
    g.precision, g.data_type, g.suffix = 'float', 'float', 'f'
    g.constraints = dict(u_min=umin, u_max=umax, x_min=xmin[1], x_max=xmax[1])
    source = g.generate_main_solver()
    # A local-memory interface isolates the solver, as in the MOBY-DIC OOC build.
    source = '\n'.join(line for line in source.splitlines() if '#pragma HLS INTERFACE' not in line)
    source = source.replace('    int max_iter,\n    int check_termination_iter\n', '')
    source = source.replace('data_t main_memory[MAIN_MEMORY_SIZE],', 'data_t main_memory[MAIN_MEMORY_SIZE]')
    source = source.replace('iter < max_iter', 'iter < MAX_ITER')
    begin = source.index('        // Step 5: Check termination')
    end = source.index('        // Update workspace', begin)
    source = source[:begin] + source[end:]
    # Emit per-stage bounds, avoiding additional constraints on the initial state.
    for name, bounds in [('X_MIN',xmin),('X_MAX',xmax)]:
        start = source.index(f'const data_t {name}')
        end = source.index('};', start)+2
        rows = ',\n'.join('{' + ','.join(g._format_value(v) for v in row) + '}' for row in bounds)
        source = source[:start] + f'const data_t {name}[N][NX] = {{\n{rows}\n}};' + source[end:]
    header = g.generate_header().replace('    int max_iter,\n    int check_termination_iter\n', '').replace('data_t main_memory[MAIN_MEMORY_SIZE],', 'data_t main_memory[MAIN_MEMORY_SIZE]')
    source = '#include <cmath>\n' + source + '\n' + g.generate_subfunctions()
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=True)
    (out/'tinympc_solver.h').write_text(header)
    (out/'tinympc_solver.cpp').write_text(source)
    if args.generate_only:
        (out/'testbench.cpp').write_text('#include "tinympc_solver.h"\nint main(){data_t m[MAIN_MEMORY_SIZE]={};tinympc_solver(m);return 0;}\n')
        (out/'hls_config.cfg').write_text('part=xc7a100t-csg324-1\n[hls]\nflow_target=vivado\nsyn.top=tinympc_solver\nclock=10ns\nsyn.file=tinympc_solver.cpp\ntb.file=testbench.cpp\npackage.output.format=ip_catalog\n')
        (out/'configuration.json').write_text(json.dumps(dict(horizon=H,iterations=K,rho=args.rho,model=model,input_min=umin.tolist(),input_max=umax.tolist()),indent=2)+'\n')
        return
    testcases = cases(H, order)
    xs, xrefs, expected, primal_expected = [], [], [], []
    for name, x, q in testcases:
        xr = np.zeros((H+1,12))
        xr[:] = -q[4*H:].reshape(H+1,12)/np.diag(Q)
        s = reference(); s.set_x0(x); s.set_x_ref(xr); s.solve()
        xs.append(x); xrefs.append(xr)
        expected.append(np.r_[s.znew.ravel(),s.vnew.ravel()])
        primal_expected.append(np.r_[s.primal_u.ravel(),s.primal_x.ravel()])
    tb = '#include "tinympc_solver.h"\n#include <cstdio>\n#include <cstdlib>\n'
    tb += declaration('xs',np.array(xs))+declaration('refs',np.array(xrefs))
    tb += '''int main(int argc,char** argv){
      int c=argc>1 ? std::atoi(argv[1]):0;
      if(c<0 || c>=4) return 2;
      data_t m[MAIN_MEMORY_SIZE]={};
      for(int i=0;i<NX;i++) m[X0_OFFSET+i]=xs[c][i];
      for(int k=0;k<N;k++) for(int i=0;i<NX;i++) m[XREF_OFFSET+k*NX+i]=refs[c][k][i];
      tinympc_solver(m);
      for(int i=0;i<N_MINUS_1*NU;i++) std::printf("%.17g\\n",double(m[U_OUT_OFFSET+i]));
      for(int i=0;i<N*NX;i++) std::printf("%.17g\\n",double(m[X_OUT_OFFSET+i]));
      return 0;
    }
'''
    (out/'testbench.cpp').write_text(tb)
    subprocess.run(['g++','-O2','-std=c++14','-Wno-unknown-pragmas',str(out/'tinympc_solver.cpp'),str(out/'testbench.cpp'),'-o',str(out/'csim')],check=True)
    # Separate host-only diagnostic source: synthesis source stays identical.
    diagnostic = source.replace('    // Store results back to main memory',
        '    for(int k=0;k<N_MINUS_1;k++) for(int j=0;j<NU;j++) std::printf("%.17g\\n",double(u[k][j]));\n'
        '    for(int k=0;k<N;k++) for(int j=0;j<NX;j++) std::printf("%.17g\\n",double(x[k][j]));\n'
        '    // Store results back to main memory')
    (out/'diagnostic.cpp').write_text('#include <cstdio>\n'+diagnostic)
    subprocess.run(['g++','-O2','-std=c++14','-Wno-unknown-pragmas',str(out/'diagnostic.cpp'),str(out/'testbench.cpp'),'-o',str(out/'diagnostic')],check=True)
    results=[]
    for i,(name,x,q) in enumerate(testcases):
        z=np.fromstring(subprocess.check_output([str(out/'csim'),str(i)],text=True),sep='\n')
        assert z.shape == expected[i].shape and np.all(np.isfinite(z))
        np.testing.assert_allclose(z,expected[i],rtol=2e-4,atol=2e-4)
        diagnostic_values=np.fromstring(subprocess.check_output([str(out/'diagnostic'),str(i)],text=True),sep='\n')
        assert diagnostic_values.size == 2*z.size and np.all(np.isfinite(diagnostic_values))
        primal, projected = np.split(diagnostic_values,2)
        np.testing.assert_array_equal(projected,z)
        np.testing.assert_allclose(primal,primal_expected[i],rtol=2e-4,atol=2e-4)
        b=np.r_[x,np.zeros(len(E)-12)]
        primal_residual=float(max(abs(E@primal-b)))
        assert primal_residual < 2e-4, (name,primal_residual)
        oracle=osqp.OSQP()
        oracle.setup(P=sparse.csc_matrix(P),q=q,A=sparse.csc_matrix(np.vstack([G,E])),
                     l=np.r_[np.full(len(h),-np.inf),b],u=np.r_[h,b],
                     eps_abs=1e-9,eps_rel=1e-9,max_iter=200000,polish=True,verbose=False)
        ref=oracle.solve()
        assert ref.info.status=='solved'
        results.append(dict(case=name,python_max_error=float(max(abs(z-expected[i]))),
            first_control_error=float(max(abs(z[:4]-ref.x[:4]))),
            inequality_violation=float(max(0,np.max(G@z-h))),
            projected_dynamics_residual=float(max(abs((E@z-b)[12:]))),
            primal_dynamics_residual=float(max(abs((E@primal-b)[12:]))),
            primal_initial_state_residual=float(max(abs((E@primal-b)[:12]))),
            primal_bound_violation=float(max(0,np.max(G@primal-h))),
            consensus_state=float(max(abs(primal[4*H:]-z[4*H:]))),
            consensus_input=float(max(abs(primal[:4*H]-z[:4*H]))),
            primal_python_max_error=float(max(abs(primal-primal_expected[i]))),
            accelmpc_objective_difference=float(.5*z@P@z+q@z-(.5*ref.x@P@ref.x+q@ref.x)),
            u0=z[:4].tolist(),osqp_u0=ref.x[:4].tolist()))
    report=dict(horizon=H,knot_points=H+1,iterations=K,rho=args.rho,precision='float32',
        model=model,results=results,validation='fresh cold-start Python and C++ for each case; OSQP is the AccelMPC objective, not an equivalence oracle',
        preserved_differences=['steady-state Riccati and Pinf terminal term','upstream rho additions and reference weighting'],
        interface='local array memory; fixed iterations; no convergence checks; includes initialization and input/output copies',
        sources={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in [upstream/'tinympcref.py',upstream/'hls_generator.py',upstream/'tinympc_ip_generator.py',Path(__file__)]})
    (out/'numerical.json').write_text(json.dumps(report,indent=2)+'\n')
    (out/'hls_config.cfg').write_text('part=xc7a100t-csg324-1\n[hls]\nflow_target=vivado\nsyn.top=tinympc_solver\nclock=10ns\nsyn.file=tinympc_solver.cpp\ntb.file=testbench.cpp\npackage.output.format=ip_catalog\n')
    print(json.dumps(results,indent=2))

if __name__=='__main__': main()
