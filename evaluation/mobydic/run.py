#!/usr/bin/env python3
"""Build small H5/H10, K10 with 100 MHz synthesis/routing, evaluated at 60 MHz; retain actual outcomes."""
import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys

HERE = Path(__file__).resolve().parent
HLS_PERIOD = '10'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=HERE / 'output' / 'build100_operate60')
    args = parser.parse_args()
    out = args.output.resolve()
    for tool in ('v++', 'vivado', 'g++'):
        if not shutil.which(tool):
            parser.error(f'{tool} missing; source Vitis/Vivado settings64.sh first')
    if out.exists():
        parser.error('Output already exists; choose a fresh --output directory')
    out.mkdir(parents=True)
    results = []
    for horizon in (5, 10):
        folder = out / f'h{horizon}'
        folder.mkdir()
        design = folder / 'small_wide'
        row = dict(horizon=horizon, iterations=10, hls_clock_mhz=100, implementation_clock_mhz=100, clock_mhz=60)
        stages = [
            ('generate', [sys.executable, str(HERE / 'quadrotor.py'), '--generate-only',
                          '--horizon', str(horizon), '--clock-ns', HLS_PERIOD,
                          '--output', str(folder)], folder),
            ('hls', ['v++', '-c', '--mode', 'hls', '--config', 'hls_config.cfg',
                     '--work_dir', 'hls'], design),
            ('vivado', ['vivado', '-mode', 'batch', '-source', str(HERE / 'implement.tcl'),
                        '-tclargs', str(design)], design),
        ]
        for stage, command, cwd in stages:
            print(f'H{horizon}: {stage}', flush=True)
            with (folder / f'{stage}.log').open('w') as log:
                rc = subprocess.run(command, cwd=cwd, stdout=log, stderr=subprocess.STDOUT).returncode
            if rc:
                row.update(status='failed', failed_stage=stage, returncode=rc)
                break
        else:
            report = (design / 'operating_60mhz/timing.rpt').read_text()
            row['status'] = ('timing_closed' if 'All user specified timing constraints are met.' in report
                             else 'timing_not_closed')
        results.append(row)
        (out / 'summary.json').write_text(json.dumps(results, indent=2) + '\n')
        print(row, flush=True)
    return 0 if all(r['status'] == 'timing_closed' for r in results) else 1


if __name__ == '__main__':
    sys.exit(main())
