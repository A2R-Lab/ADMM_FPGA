#!/usr/bin/env python3
"""Prepare the paper's H27/K9 constrained star and unchanged nonlinear plant."""
import argparse,os,sys,json,shutil,subprocess,hashlib
from pathlib import Path
import numpy as np

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
ap=argparse.ArgumentParser(description=__doc__)
ap.add_argument('--output',type=Path,required=True)
a=ap.parse_args();out=a.output.resolve();out.mkdir(parents=True,exist_ok=False)
scripts=out/'scripts';scripts.mkdir();p=out/'vitis_projects/ADMM';p.mkdir(parents=True)
(out/'vivado_project/vivado_project.srcs/sources_1/new').mkdir(parents=True)
for n in ['parameters.py','crazyflie_model.py','trajectory_generator.py','header_generator.py']:shutil.copy2(ROOT/'scripts'/n,scripts/n)
for n in ['ADMM.cpp','ADMM.h','data_types.h','ADMM_closed_loop_tb.cpp']:shutil.copy2(ROOT/'vitis_projects/ADMM'/n,p/n)
env={k:v for k,v in os.environ.items() if not k.startswith('ADMM_')}
env.update(ADMM_HORIZON_LENGTH='27',ADMM_ITERATIONS='9',ADMM_ENABLE_TRAJECTORY='1',ADMM_SOLVER_ARCH='staged_a',
 ADMM_USE_FLOAT='0',ADMM_SIM_FREQ='1000',ADMM_SIM_DURATION_S='25.6',ADMM_TRAJ_SHAPE='star_hold',
 ADMM_TRAJ_AMP_X='2',ADMM_TRAJ_AMP_Y='2',ADMM_TRAJ_STAR_POINTS='12',ADMM_TRAJ_STAR_INNER_RATIO='0.25',
 ADMM_TRAJ_STAR_INNER_HOLD='0.25',ADMM_XY_MIN='-1',ADMM_XY_MAX='1',ADMM_REPETITIONS='1',
 ADMM_STEP_X='0',ADMM_STEP_Y='0',ADMM_STEP_Z='0',ADMM_STEP_YAW='0',OPENBLAS_NUM_THREADS='1')
code='''import sys,json,numpy as np
sys.path.insert(0,'scripts')
import trajectory_generator as tg
assert tg.main()==0
import header_generator as g
import parameters as c
ref=np.genfromtxt('vitis_projects/ADMM/trajectory_refs.csv',delimiter=',',names=True)
ref=np.column_stack([ref['x'+str(i)] for i in range(12)])
q=tg.build_traj_q_packed(ref,np.zeros((len(ref),4)),np.array(c.Q_DIAG),np.array(c.R_DIAG),27,c.TRAJ_ENTRY_ZERO_PAD)
refs=np.zeros((len(q),12));refs[:,:3]=-np.round(q,8)/np.array(c.Q_DIAG[:3])
np.savez('reference.npz',reference=ref,preview=refs,loop_start=c.TRAJ_ENTRY_ZERO_PAD,tick_div=c.TRAJ_TICK_DIV)
lo=float(g.l[12*28+4*27]);hi=float(g.u[12*28+4*27])
model=dict(A=g.A.tolist(),B=g.B.tolist(),Q=np.diag(c.Q_DIAG).tolist(),R=np.diag(c.R_DIAG).tolist(),hover=g.ug.tolist(),xy_bounds=[lo,hi],model_frequency=c.MODEL_FREQ,trajectory_shape=c.TRAJ_SHAPE)
open('model.json','w').write(json.dumps(dict(model=model),indent=2))
'''
with (out/'generate.log').open('w') as log:subprocess.run([sys.executable,'-c',code],cwd=out,env=env,stdout=log,stderr=subprocess.STDOUT,check=True)
d=np.load(out/'reference.npz');ref=d['reference']
paper=np.genfromtxt(ROOT/'evaluation/data/flight_metrics/star_reference.csv',delimiter=',',skip_header=1)
np.testing.assert_allclose(ref[28:,:3],paper[:,1:4],rtol=0,atol=1e-8)
m=json.loads((out/'model.json').read_text())['model'];low,high=m['xy_bounds']
np.testing.assert_allclose([low,high],[-1.3535533905932737,.6464466094067263])
outside=np.any((ref[:, :2]<low)|(ref[:,:2]>high),axis=1)
assert outside.any(),'Reference must leave the feasible XY box'
subprocess.run([sys.executable,str(HERE/'prepare.py'),'--generate-only','--horizon','27','--iterations','9','--model-report',str(out/'model.json'),'--output',str(out/'tiny')],check=True,env=env)
sys.path.insert(0,str(ROOT/'evaluation'))
from numerical_accuracy import BRIDGE
(p/'bridge.cpp').write_text(BRIDGE)
# Preserve a common float32 sensor/actuator interface, including hover addition.
(out/'tiny/bridge.cpp').write_text('''#include "tinympc_solver.h"
extern "C" void solve_tiny(const double* state,const double* refs,double* command){
 data_t m[MAIN_MEMORY_SIZE]={};
 for(int i=0;i<12;i++)m[X0_OFFSET+i]=float(state[i]);
 for(int i=0;i<N*12;i++)m[XREF_OFFSET+i]=float(refs[i]);
 tinympc_solver(m);
'''+f' const float hover={float(m["hover"][0]):.17g}f;\n'+'''
 for(int i=0;i<4;i++)command[i]=float(m[U_OUT_OFFSET+i]+hover);
}
''')
shutil.copy2(HERE/'nonlinear_star.py',out/'nonlinear_star.py')
manifest=dict(settings=env,reference_outside_fraction=float(outside.mean()),reference_extrema=[ref[:,:2].min(axis=0).tolist(),ref[:,:2].max(axis=0).tolist()],bounds=[low,high],
 source_sha256={n:hashlib.sha256((ROOT/'vitis_projects/ADMM'/n).read_bytes()).hexdigest() for n in ['ADMM.cpp','ADMM.h','data_types.h','ADMM_closed_loop_tb.cpp']})
manifest['settings']={k:v for k,v in env.items() if k.startswith('ADMM_')}
(out/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
print(json.dumps({k:manifest[k] for k in ['reference_outside_fraction','reference_extrema','bounds']},indent=2))
