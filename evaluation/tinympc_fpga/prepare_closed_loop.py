import os,sys,json,shutil,subprocess
from pathlib import Path
import argparse
ap=argparse.ArgumentParser(description='Prepare unchanged solver sources and closed-loop bridges')
ap.add_argument('--output',type=Path,required=True)
args=ap.parse_args()
root=Path(__file__).resolve().parents[2]
out=args.output.resolve();out.mkdir(parents=True,exist_ok=True)
model=json.loads((root/'evaluation/tinympc_fpga/validation/h5.json').read_text())['model']
sys.path.insert(0,str(root/'scripts'));import parameters as cfg
for H in [10,40]:
 d=out/f'h{H}';s=d/'scripts';p=d/'vitis_projects/ADMM';s.mkdir(parents=True,exist_ok=True);p.mkdir(parents=True,exist_ok=True)
 (d/'vivado_project/vivado_project.srcs/sources_1/new').mkdir(parents=True,exist_ok=True)
 for n in ['parameters.py','crazyflie_model.py','header_generator.py']:shutil.copy2(root/'scripts'/n,s/n)
 for n in ['ADMM.cpp','ADMM.h','data_types.h']:shutil.copy2(root/'vitis_projects/ADMM'/n,p/n)
 env={k:v for k,v in os.environ.items() if not k.startswith('ADMM_')}
 env.update(ADMM_HORIZON_LENGTH=str(H),ADMM_ITERATIONS='10',ADMM_ENABLE_TRAJECTORY='0',ADMM_SOLVER_ARCH='staged_a',ADMM_USE_FLOAT='0',OPENBLAS_NUM_THREADS='1')
 with (d/'generate.log').open('w') as log:subprocess.run([sys.executable,str(s/'header_generator.py')],cwd=d,env=env,stdout=log,stderr=subprocess.STDOUT,check=True)
 subprocess.run([sys.executable,str(root/'evaluation/tinympc_fpga/prepare.py'),'--generate-only','--horizon',str(H),'--model-report',str(root/'evaluation/tinympc_fpga/validation/h5.json'),'--output',str(d/'tiny')],check=True)
 q=','.join(str(v) for v in cfg.Q_DIAG)
 (p/'bridge.cpp').write_text('#include "ADMM.h"\nextern "C" void control(const double* state,const double* ref,double* u){\n'+f'const double weights[12]={{{q}}};\n'+'''fp_t x[12],q[N_VAR],z[N_VAR];
 for(int i=0;i<12;i++)x[i]=state[i];
 for(int i=0;i<N_VAR;i++)q[i]=0;
 for(int k=0;k<=HORIZON_LENGTH;k++)for(int i=0;i<12;i++)q[k*16+i]=-ref[k*12+i]*weights[i];
 ADMM_benchmark_solve(x,q,(fp_t)XY_MIN,(fp_t)XY_MAX,z);
 for(int i=0;i<4;i++)u[i]=double(z[12+i]);}
''')
 (p/'warm_bridge.cpp').write_text((Path(__file__).with_name('warm_bridge.cpp.in')).read_text().replace('@WEIGHTS@',q))
 (d/'tiny/bridge.cpp').write_text('''#include "tinympc_solver.h"
extern "C" void control(const double* state,const double* ref,double* u){
 data_t m[MAIN_MEMORY_SIZE]={};
 for(int i=0;i<12;i++)m[X0_OFFSET+i]=state[i];
 for(int i=0;i<N*12;i++)m[XREF_OFFSET+i]=ref[i];
 tinympc_solver(m);
 for(int i=0;i<4;i++)u[i]=double(m[U_OUT_OFFSET+i]);}
''')
 import numpy as np
 (d/'model.json').write_text(json.dumps(dict(model=model,input_min=(np.asarray(cfg.U_ABS_MIN)-model['hover']).tolist(),input_max=(np.asarray(cfg.U_ABS_MAX)-model['hover']).tolist()),indent=2))
shutil.copy2(root/'evaluation/tinympc_fpga/closed_loop.py',out/'closed_loop.py')

shutil.copy2(Path(__file__).with_name("build_closed_loop.sh"),out/"build_closed_loop.sh")
