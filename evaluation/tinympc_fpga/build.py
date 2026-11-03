#!/usr/bin/env python3
"""Build prevalidated TinyMPC kernels with Vivado/Vitis."""
import argparse
import json
from pathlib import Path
import subprocess
import sys


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--input',type=Path,required=True)
    ap.add_argument('--output',type=Path,required=True)
    ap.add_argument('--horizons',type=int,nargs='+',default=[5,10])
    args=ap.parse_args()
    root=args.output.resolve()
    root.mkdir(parents=True,exist_ok=False)
    results=[]
    for H in args.horizons:
        import shutil
        d=root/f'h{H}'
        shutil.copytree(args.input/f'h{H}',d)
        row=dict(horizon=H,iterations=10,hls_clock_mhz=100,clock_mhz=100)
        for stage,command in [
            ('hls',['v++','-c','--mode','hls','--config','hls_config.cfg','--work_dir','hls']),
            ('vivado',['vivado','-mode','batch','-source',str(Path(__file__).with_name('implement.tcl').resolve()),'-tclargs',str(d)])]:
            print(f'H{H}: {stage}',flush=True)
            with (d/f'{stage}.log').open('w') as f:
                rc=subprocess.run(command,cwd=d,stdout=f,stderr=subprocess.STDOUT).returncode
            if rc:
                row.update(status='failed',failed_stage=stage,returncode=rc)
                break
        else:
            timing=(d/'implementation/post_route_timing.rpt').read_text()
            row['status']='timing_closed' if 'All user specified timing constraints are met.' in timing else 'timing_not_closed'
        results.append(row)
        (root/'summary.json').write_text(json.dumps(results,indent=2)+'\n')
        print(row,flush=True)
    return int(any(r['status']!='timing_closed' for r in results))

if __name__=='__main__': sys.exit(main())
