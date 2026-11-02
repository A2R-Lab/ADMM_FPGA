#!/usr/bin/env python3
"""Run bounded concurrent HLS jobs and retain complete reports on the build server."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import subprocess
import time
import xml.etree.ElementTree as ET


def run(path):
    result = {'variant': path.name}
    start = time.time()
    with (path / 'check_build.log').open('w') as log:
        rc = subprocess.call(['g++', '-O2', '-std=c++17', '-ftrivial-auto-var-init=zero',
            '-I/home/agrillo/amdfpga/2025.2/Vitis/include', 'ADMM.cpp', 'check.cpp', '-o', 'check'], cwd=path, stdout=log, stderr=subprocess.STDOUT)
    result['compile_rc'] = rc
    if rc == 0:
        with (path / 'check.bits').open('w') as out:
            result['check_rc'] = subprocess.call(['./check'], cwd=path, stdout=out)
        result['bits_sha256'] = hashlib.sha256((path / 'check.bits').read_bytes()).hexdigest()
    if rc == 0 and result['check_rc'] == 0:
        with (path / 'hls.log').open('w') as log:
            result['hls_rc'] = subprocess.call(['v++', '-c', '--mode', 'hls', '--config', 'hls_config.cfg', '--work_dir', 'hls'], cwd=path, stdout=log, stderr=subprocess.STDOUT)
        xmls = list(path.glob('hls/**/ADMM_solver_csynth.xml'))
        if xmls:
            tree = ET.parse(xmls[0])
            for key in ['Best-caseLatency', 'Worst-caseLatency', 'EstimatedClockPeriod', 'BRAM_18K', 'DSP', 'FF', 'LUT']:
                node = tree.find('.//' + key)
                result[key] = node.text if node is not None else None
    result['elapsed_s'] = round(time.time() - start, 1)
    (path / 'result.json').write_text(json.dumps(result, indent=2))
    print(json.dumps(result), flush=True)
    return result


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('root', type=Path)
    p.add_argument('variants', nargs='+')
    p.add_argument('--jobs', type=int, default=2)
    args = p.parse_args()
    with ThreadPoolExecutor(max_workers=args.jobs) as pool:
        results = list(pool.map(run, [args.root.resolve() / v for v in args.variants]))
    (args.root / ('summary_' + '_'.join(args.variants) + '.json')).write_text(json.dumps(results, indent=2))
