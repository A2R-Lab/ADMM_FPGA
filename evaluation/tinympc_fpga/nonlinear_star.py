#!/usr/bin/env python3
"""Independent nonlinear constrained-star rollouts at paper H27/K9, 1 kHz."""
import argparse,ctypes,json,time
from pathlib import Path
import numpy as np
ap=argparse.ArgumentParser(description=__doc__)
ap.add_argument('--input',type=Path,required=True);ap.add_argument('--solver',choices=['accel','tiny'],required=True)
ap.add_argument('--output',type=Path,required=True)
a=ap.parse_args();base=a.input.resolve();a.output.mkdir(parents=True,exist_ok=True)
ref=np.load(base/'reference.npz');preview=ref['preview'];length=len(ref['reference']);loop=int(ref['loop_start']);div=int(ref['tick_div'])
model=json.loads((base/'model.json').read_text())['model'];low,high=model['xy_bounds']
ptr=np.ctypeslib.ndpointer(dtype=np.float64,flags='C_CONTIGUOUS')
plant=ctypes.CDLL(str(base/'accel.so'));plant.advance.argtypes=[ptr,ptr,ptr];plant.advance.restype=None
if a.solver=='accel':
 fn=plant.solve;fn.argtypes=[ptr,ctypes.c_int,ptr]
else:
 lib=ctypes.CDLL(str(base/'tiny.so'));fn=lib.solve_tiny;fn.argtypes=[ptr,ptr,ptr]
fn.restype=None
state=np.zeros(12);actuator=np.array(model['hover']);previous=actuator.copy()
history=[];status='complete';reason='';idx=0;started=time.monotonic()
for step in range(25600):
 cmd=np.zeros(4)
 if a.solver=='accel':fn(np.ascontiguousarray(state.astype(np.float32).astype(float)),int(step==0),cmd)
 else:fn(np.ascontiguousarray(state.astype(np.float32).astype(float)),np.ascontiguousarray(preview[idx:idx+28]),cmd)
 if not np.all(np.isfinite(cmd)) or min(cmd)<-.02 or max(cmd)>1.02 or max(abs(cmd-previous))>.45:
  status='early_stop';reason='nonfinite/out-of-range/step-limited command';break
 # Keep the paper's motor lag/clipping, parameter mismatch, drag and rotor imbalance.
 target=preview[idx,:3].copy()
 plant.advance(state,actuator,cmd);previous=cmd.copy()
 history.append(np.r_[(step+1)/1000,state,cmd,actuator,target,idx])
 if not np.all(np.isfinite(state)) or np.any(abs(state[:3])>[3,3,1]) or np.any(abs(state[3:5])>.45) or np.any(abs(state[9:])>8):
  status='early_stop';reason='paper plant-state safety threshold';break
 if (step+1)%div==0:
  idx+=1
  if idx>=length:idx=loop
 if (step+1)%2000==0:print(a.solver,step+1,'of 25600',round(time.monotonic()-started,1),'s',flush=True)
hist=np.array(history);np.savez_compressed(a.output/f'{a.solver}.npz',trajectory=hist)
if len(hist):
 xy=hist[:,1:3];raw=hist[:,21:24];feasible=raw.copy();feasible[:,:2]=np.clip(feasible[:,:2],low,high)
 v=np.maximum(np.maximum(low-xy,xy-high),0)
 metrics=dict(raw_xyz_rmse=float(np.sqrt(np.mean(np.sum((hist[:,1:4]-raw)**2,axis=1)))),
  feasible_xyz_rmse=float(np.sqrt(np.mean(np.sum((hist[:,1:4]-feasible)**2,axis=1)))),
  max_xy_violation=float(v.max()),xy_violation_fraction_1mm=float(np.mean(np.max(v,axis=1)>.001)),
  xy_near_boundary_fraction_5cm=float(np.mean(np.min(np.minimum(abs(xy-low),abs(xy-high)),axis=1)<.05)),
  reference_outside_fraction=float(np.mean(np.any((raw[:,:2]<low)|(raw[:,:2]>high),axis=1))))
else:metrics={}
result=dict(solver=a.solver,status=status,reason=reason,steps=len(hist),duration_s=len(hist)/1000,horizon=27,iterations=9,control_hz=1000,bounds=[low,high],metrics=metrics,elapsed_s=time.monotonic()-started)
(a.output/f'{a.solver}.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2),flush=True)
