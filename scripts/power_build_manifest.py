#!/usr/bin/env python3
"""Freeze workload and solver provenance alongside a completed power bitstream."""
import argparse
import hashlib
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--bitstream',type=Path,required=True)
    p.add_argument('--workload',type=Path,default=ROOT/'build/power/power_workload.json')
    a=p.parse_args()
    data=json.loads(a.workload.read_text())
    data['bitstream_sha256']=hashlib.sha256(a.bitstream.read_bytes()).hexdigest()
    solver_dir=ROOT/'vitis_projects/ADMM'
    trajectory_enabled=bool(re.search(r'^#define ADMM_ENABLE_TRAJECTORY 1$',
        (solver_dir/'admm_runtime_config.h').read_text(),re.M))
    data['trajectory_compiled']=trajectory_enabled
    source_names=['ADMM.cpp','data_types.h','admm_runtime_config.h','data.h']
    if trajectory_enabled:
        source_names.append('traj_data.h')
    data['solver_file_sha256']={name:hashlib.sha256((solver_dir/name).read_bytes()).hexdigest()
        for name in source_names}
    data['solver_constants']=dict(re.findall(r'^#define[ \t]+(\w+)[ \t]+([^\n]+)',(solver_dir/'data.h').read_text(),re.M))
    target=a.bitstream.with_suffix('.json')
    target.write_text(json.dumps(data,indent=2)+'\n')
    print(f'Build manifest: {target}')

if __name__=='__main__':
    main()
