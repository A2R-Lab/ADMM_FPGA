#!/usr/bin/env python3
"""Compare unchanged AccelMPC benchmark interface with recorded TinyMPC cases.

OSQP uses the AccelMPC objective; these command errors are not own-objective
optimality measures for TinyMPC and do not establish closed-loop superiority.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import numpy as np
from scipy import sparse
import osqp

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
sys.path.insert(0,str(ROOT/'evaluation/mobydic'))
from quadrotor import problem, cases, declaration


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--hls-include',type=Path,required=True)
    args=ap.parse_args()
    results=[]
    for H in [5,10]:
        P,E,G,h,order,_,model=problem(H)
        cs=cases(H,order)
        tiny=json.loads((HERE/f'validation/h{H}.json').read_text())
        with tempfile.TemporaryDirectory(prefix='accel-quality-') as tmp:
            work=Path(tmp)
            scripts=work/'scripts'; scripts.mkdir()
            project=work/'vitis_projects/ADMM'; project.mkdir(parents=True)
            (work/'vivado_project/vivado_project.srcs/sources_1/new').mkdir(parents=True)
            for name in ['parameters.py','crazyflie_model.py','header_generator.py']:
                shutil.copy2(ROOT/'scripts'/name,scripts/name)
            for name in ['ADMM.cpp','ADMM.h','data_types.h']:
                shutil.copy2(ROOT/'vitis_projects/ADMM'/name,project/name)
            env={k:v for k,v in os.environ.items() if not k.startswith('ADMM_')}
            env.update(ADMM_HORIZON_LENGTH=str(H),ADMM_ITERATIONS='10',ADMM_ENABLE_TRAJECTORY='0',
                       ADMM_SOLVER_ARCH='staged_a',ADMM_USE_FLOAT='0',OPENBLAS_NUM_THREADS='1')
            with (work/'generate.log').open('w') as log:
                p=subprocess.run([sys.executable,str(scripts/'header_generator.py')],cwd=work,env=env,stdout=log,stderr=subprocess.STDOUT)
            if p.returncode: raise RuntimeError((work/'generate.log').read_text()[-4000:])
            qa=[]
            for _,x,q in cs:
                a=np.empty_like(q);a[order]=q;qa.append(a)
            tb='#include "ADMM.h"\n#include <cstdio>\n#include <cstdlib>\n'
            tb+=declaration('xs',np.array([x for _,x,_ in cs]))+declaration('qs',np.array(qa))
            tb+='''int main(int argc,char**argv){
              int c=std::atoi(argv[1]); fp_t x[12],q[N_VAR],z[N_VAR];
              for(int i=0;i<12;i++)x[i]=xs[c][i];
              for(int i=0;i<N_VAR;i++)q[i]=qs[c][i];
              ADMM_benchmark_solve(x,q,(fp_t)XY_MIN,(fp_t)XY_MAX,z);
              for(int i=0;i<N_VAR;i++)std::printf("%.17g\\n",double(z[i]));
            }'''
            (project/'quality_tb.cpp').write_text(tb)
            subprocess.run(['g++','-O2','-ftrivial-auto-var-init=zero','-std=c++14','-Wno-unknown-pragmas','-I'+str(args.hls_include),str(project/'ADMM.cpp'),str(project/'quality_tb.cpp'),'-o',str(work/'run')],check=True,capture_output=True)
            for i,(name,x,q) in enumerate(cs):
                za=np.fromstring(subprocess.check_output([str(work/'run'),str(i)],text=True),sep='\n');z=za[order]
                assert len(z)==len(q) and np.all(np.isfinite(z))
                if name=='hover': assert max(abs(z)) < 1e-5, 'zero-input cold-start sanity check failed'
                b=np.r_[x,np.zeros(len(E)-12)]
                solver=osqp.OSQP();solver.setup(P=sparse.csc_matrix(P),q=q,A=sparse.csc_matrix(np.vstack([G,E])),l=np.r_[np.full(len(h),-np.inf),b],u=np.r_[h,b],eps_abs=1e-9,eps_rel=1e-9,max_iter=200000,polish=True,verbose=False)
                ref=solver.solve();assert ref.info.status=='solved'
                t=tiny['results'][i];assert t['case']==name
                results.append(dict(horizon=H,case=name,iterations=10,
                    accel_command_error=float(max(abs(z[:4]-ref.x[:4]))),tiny_command_error=t['first_control_error'],
                    accel_dynamics_residual=float(max(abs((E@z-b)[12:]))),tiny_projected_dynamics_residual=t['projected_dynamics_residual'],tiny_primal_dynamics_residual=t['primal_dynamics_residual'],
                    accel_bound_violation=float(max(0,max(G@z-h))),tiny_projected_bound_violation=t['inequality_violation']))
    report=dict(host_compiler_flags=['-O2','-ftrivial-auto-var-init=zero'],
        initialization_note='Host automatic storage forced to zero for deterministic cold-start emulation; without this flag the ap_fixed host test failed the zero-input sanity check. Solver source is unchanged. These are host diagnostics, not RTL quality validation.',
        basis='Four cold-start cases; unchanged fixed-point staged ADMM_benchmark_solve; OSQP uses AccelMPC objective. TinyMPC retains different terminal and rho/reference weighting. Not evidence of equal-quality latency or closed-loop superiority.',results=results,
        sources={name:hashlib.sha256((ROOT/'vitis_projects/ADMM'/name).read_bytes()).hexdigest() for name in ['ADMM.cpp','ADMM.h','data_types.h']})
    (HERE/'comparison/quality.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(results,indent=2))

if __name__=='__main__':main()
