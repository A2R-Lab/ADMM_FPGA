#!/usr/bin/env python3
"""Same-clock operating-point comparison using verified retained routed circuits."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import re
import subprocess


def run(task):
    name, checkpoint, cycles = task
    out = args.root.resolve() / f'operate_{args.mhz:g}mhz' / name
    out.mkdir(parents=True, exist_ok=True)
    manifest = dict(name=name, checkpoint=str(checkpoint), cycles=cycles,
                    clock_mhz=args.mhz, latency_us=cycles/args.mhz,
                    note='Existing 100 MHz HLS schedule; actual clock changed equally for both solvers.')
    (out/'manifest.json').write_text(json.dumps(manifest, indent=2))
    with (out/'vivado.log').open('w') as log:
        rc = subprocess.call(['vivado', '-mode', 'batch', '-source', str(Path(__file__).with_name('operate_clock.tcl')),
                              '-tclargs', str(checkpoint), str(out), str(args.mhz)], cwd=out, stdout=log, stderr=subprocess.STDOUT)
    manifest['returncode'] = rc
    report = out/'post_route_timing.rpt'
    if report.exists():
        m = re.search(r'WNS\(ns\).*?\n\s*-+[^\n]*\n\s*([-\d.]+)\s+([-\d.]+)\s+(\d+)\s+(\d+)\s+([-\d.]+)', report.read_text(), re.S)
        if m:
            manifest.update(wns_ns=float(m[1]), whs_ns=float(m[5]), timing_clean=float(m[1]) >= 0 and float(m[5]) >= 0)
    (out/'result.json').write_text(json.dumps(manifest, indent=2))
    print(json.dumps(manifest), flush=True)


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('root', type=Path)
    p.add_argument('--mhz', type=float, default=80)
    p.add_argument('--horizon', type=int, default=10)
    p.add_argument('--accel-variant', default='split_fused0')
    args = p.parse_args()
    h = f'h{args.horizon}'
    expected = json.loads((args.root/'tiny_expected.json').read_text())[h]
    matches = []
    search_roots = ['/home/agrillo/maolinComp/tiny-campaign', '/home/agrillo/maolinComp/tiny-sweep']
    for directory in search_roots:
        for dcp in Path(directory).rglob('post_route.dcp'):
            if h not in dcp.parts:
                continue
            source = dcp.parent.parent/'tinympc_solver.cpp'
            if source.exists() and hashlib.sha256(source.read_bytes()).hexdigest() == expected['source_sha256']:
                matches.append(dcp)
    (args.root/f'tiny_checkpoint_search_{h}.json').write_text(json.dumps([str(p) for p in matches], indent=2))
    if not matches:
        raise RuntimeError('No source-hash-matched TinyMPC checkpoint found; inspect retained campaign locations.')
    accel = args.root.resolve()/h/args.accel_variant
    result = json.loads((accel/'result.json').read_text())
    tasks = [(f'accel_{h}_{args.accel_variant}', accel/'implementation/post_route.dcp', int(result['Worst-caseLatency'])),
             (f'tiny_{h}', matches[0], expected['cycles'])]
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(run, tasks))
