#!/usr/bin/env python3
"""Route selected Pareto candidates using the same 100 MHz OOC flow as TinyMPC."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import re
import subprocess
import time


def run(path, refine=False):
    start = time.time()
    name = 'refine_route' if refine else 'route'
    with (path / (name+'.log')).open('w') as log:
        rc = subprocess.call(['vivado', '-mode', 'batch', '-source', str(Path(__file__).with_name('refine_route.tcl' if refine else 'implement.tcl')),
                              '-tclargs', str(path)], cwd=path, stdout=log, stderr=subprocess.STDOUT)
    result = dict(variant=path.name, route_rc=rc, elapsed_s=round(time.time()-start, 1))
    report = path/('implementation_refined' if refine else 'implementation')/'post_route_timing.rpt'
    if report.exists():
        m = re.search(r'WNS\(ns\).*?\n\s*-+[^\n]*\n\s*([-\d.]+)\s+([-\d.]+)\s+(\d+)\s+(\d+)\s+([-\d.]+)', report.read_text(), re.S)
        if m:
            result.update(wns_ns=float(m[1]), whs_ns=float(m[5]), timing_clean=float(m[1]) >= 0 and float(m[5]) >= 0)
    (path/(name+'_result.json')).write_text(json.dumps(result, indent=2))
    print(json.dumps(result), flush=True)


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('root', type=Path)
    p.add_argument('variants', nargs='+')
    p.add_argument('--jobs', type=int, default=2)
    p.add_argument('--refine', action='store_true')
    args = p.parse_args()
    with ThreadPoolExecutor(max_workers=args.jobs) as pool:
        list(pool.map(lambda path: run(path, args.refine), [args.root.resolve()/v for v in args.variants]))
