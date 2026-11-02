#!/usr/bin/env python3
"""Matched linear-plant, cold-start controller diagnostics; no solver source edits."""
import argparse
import ctypes
import json
from pathlib import Path
import numpy as np


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--input',type=Path,required=True)
    ap.add_argument('--output',type=Path,required=True)
    ap.add_argument('--solvers',nargs='+',default=['accel','tiny'])
    args=ap.parse_args()
    args.output.mkdir(parents=True,exist_ok=True)
    records=[]
    for H in [10,40]:
        base=args.input/f'h{H}'
        config=json.loads((base/'model.json').read_text())
        m=config['model'];A,B,Q,R=[np.array(m[k]) for k in ['A','B','Q','R']]
        low,high=m['xy_bounds'];umin=np.array(config['input_min']);umax=np.array(config['input_max'])
        dt=1/m['model_frequency'];steps=250
        for name in args.solvers:
            lib=ctypes.CDLL(str((base/f'{name}.so').resolve()))
            fn=lib.control;ptr=np.ctypeslib.ndpointer(dtype=np.float64,flags='C_CONTIGUOUS')
            fn.argtypes=[ptr,ptr,ptr];fn.restype=None
            for scenario in ['offset','step','circle','boundary','disturbance']:
                for seed in range(5):
                    if name=='accel_warm': lib.reset()
                    rng=np.random.default_rng(seed)
                    x=np.zeros(12)
                    if scenario=='offset':x[:3]=[.15,-.1,.2]
                    x[:3]+=rng.normal(0,.01,size=3)
                    disturbances=rng.normal(0,.001,size=(steps,3)) if scenario=='disturbance' else np.zeros((steps,3))
                    history=[];cost=0.;viol=0.;saturations=0;status='complete'
                    for k in range(steps):
                        times=(k+np.arange(H+1))*dt
                        refs=np.zeros((H+1,12))
                        if scenario in ['step','disturbance']:
                            refs[times>=.5,:3]=[.3,-.2,.4]
                        elif scenario=='circle':
                            refs[:,0]=.25*np.sin(2*np.pi*.3*times)
                            refs[:,1]=.25*(np.cos(2*np.pi*.3*times)-1)
                            refs[:,2]=.3
                        elif scenario=='boundary':
                            refs[times>=.5,0]=high-.02
                            refs[times>=2.5,0]=low+.02
                            refs[:,2]=.3
                        raw=np.zeros(4);fn(np.ascontiguousarray(x),np.ascontiguousarray(refs),raw)
                        if not np.all(np.isfinite(raw)) or max(abs(x))>1e6:
                            status='diverged';break
                        u=np.clip(raw,umin,umax)
                        saturations+=int(max(abs(raw-u))>1e-6)
                        err=x-refs[0];cost+=float(err@Q@err+u@R@u)*dt
                        viol=max(viol,float(np.max(np.maximum(low-x[:2],x[:2]-high))))
                        history.append(np.r_[k*dt,x,refs[0],raw,u])
                        x=A@x+B@u;x[6:9]+=disturbances[k]
                    hist=np.array(history)
                    np.savez_compressed(args.output/f'h{H}_{name}_{scenario}_s{seed}.npz',trajectory=hist)
                    records.append(dict(horizon=H,solver=name,scenario=scenario,seed=seed,status=status,steps=len(hist),
                        position_rmse=float(np.sqrt(np.mean(np.sum((hist[:,1:4]-hist[:,13:16])**2,axis=1)))) if len(hist) else None,
                        integrated_stage_cost=cost,max_xy_violation=max(0,viol),input_clipped_steps=saturations,
                        max_attitude=float(np.max(abs(hist[:,4:7]))) if len(hist) else None))
                    (args.output/'results.json').write_text(json.dumps(dict(
                        basis='Matched linear plant at model sampling rate; same reference preview and disturbances; ten iterations; accel/tiny cold starts, accel_warm retains x/b/y between control steps; common Q/R stage cost; identical actuator clipping. Native solver objectives differ. Host diagnostics, not physical or RTL validation.',
                        results=records),indent=2)+'\n')
                    print(records[-1],flush=True)

if __name__=='__main__':main()
