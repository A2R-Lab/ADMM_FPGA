#!/usr/bin/env python3
"""Archive compact evidence and exact successful sources through the SSHFS mount."""
import argparse
import json
from pathlib import Path
import shutil


def copy(src, dst):
    if src.is_file():
        if dst.exists() and src.stat().st_size == dst.stat().st_size and src.stat().st_mtime <= dst.stat().st_mtime:
            return
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('remote_root', type=Path)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--selected', nargs='+', default=['split_fused0'])
    p.add_argument('--only', nargs='+', help='Limit refresh to these solver variants')
    args = p.parse_args()
    for h in ['h10', 'h40']:
        root = args.remote_root/h
        if not root.exists(): continue
        for variant in root.iterdir():
            if args.only and variant.name not in args.only: continue
            if not (variant/'result.json').exists(): continue
            dest = args.output/h/variant.name
            for name in ['result.json', 'manifest.json', 'hls_config.cfg', 'route_result.json',
                         'refine_route_result.json', 'cosim_result.json', 'timeout.json']:
                copy(variant/name, dest/name)
            for name in ['ADMM_solver_csynth.rpt', 'ADMM_solver_csynth.xml']:
                copy(variant/'hls/hls/syn/report'/name, dest/name)
            for flow in ['implementation', 'implementation_refined']:
                for name in ['post_route_timing.rpt', 'post_route_utilization.rpt', 'post_route_power.rpt']:
                    copy(variant/flow/name, dest/flow/name)
            if variant.name in args.selected or variant.name == 'baseline':
                for name in ['ADMM.cpp', 'ADMM.h', 'data_types.h', 'data.h', 'admm_runtime_config.h']:
                    copy(variant/name, dest/name)
    for clock in args.remote_root.glob('operate_*mhz'):
        for variant in clock.iterdir():
            for name in ['manifest.json', 'result.json', 'post_route_timing.rpt',
                         'post_route_utilization.rpt', 'post_route_power.rpt']:
                copy(variant/name, args.output/clock.name/variant.name/name)
    for name in ['check_rounding.log', 'tiny_expected.json', 'tiny_checkpoint_search_h10.json', 'tiny_checkpoint_search_h40.json']:
        copy(args.remote_root/name, args.output/name)
    print(args.output, flush=True)
