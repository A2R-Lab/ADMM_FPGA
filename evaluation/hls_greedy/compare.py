#!/usr/bin/env python3
"""Collect synthesis/route results, compute energy and EDP, and mark Pareto points.

Energy uses total vectorless post-route estimated power, not board measurements.
Never treats HLS resource estimates as measured power or timing-clean hardware.
"""
import argparse
import csv
import json
from pathlib import Path
import re


def metrics(root):
    baseline = json.loads((root/'baseline/result.json').read_text())
    results = []
    for path in sorted(root.iterdir()):
        if not (path/'result.json').exists():
            continue
        row = json.loads((path/'result.json').read_text())
        row['bit_exact_checked'] = row.get('bits_sha256') == baseline['bits_sha256']
        row['clock_mhz'] = 100
        if row.get('hls_rc') == 0:
            row['hls_latency_us'] = int(row['Worst-caseLatency']) / 100
            row['hls_best_latency_us'] = int(row['Best-caseLatency']) / 100
        impl = path/'implementation'
        if (path/'implementation_refined/post_route_power.rpt').exists():
            impl = path/'implementation_refined'
        row['implementation_pass'] = impl.name
        if (impl/'post_route_power.rpt').exists() and (impl/'post_route_timing.rpt').exists():
            timing = (impl/'post_route_timing.rpt').read_text()
            m = re.search(r'WNS\(ns\).*?\n\s*-+[^\n]*\n\s*([-\d.]+)\s+([-\d.]+)\s+(\d+)\s+(\d+)\s+([-\d.]+)', timing, re.S)
            if m:
                row['wns_ns'] = float(m[1])
                row['whs_ns'] = float(m[5])
                row['timing_clean'] = float(m[1]) >= 0 and float(m[5]) >= 0
            power = (impl/'post_route_power.rpt').read_text()
            m = re.search(r'\|\s*Total On-Chip Power \(W\)\s*\|\s*([\d.]+)', power)
            if m:
                row['estimated_power_w'] = float(m[1])
            util = (impl/'post_route_utilization.rpt').read_text()
            for label, name in [('Slice LUTs', 'route_lut'), ('Slice Registers', 'route_ff'),
                                ('Block RAM Tile', 'route_bram_tiles'), ('DSPs', 'route_dsp')]:
                m = re.search(r'\|\s*'+label+r'\s*\|\s*([\d.]+)', util)
                if m: row[name] = float(m[1])
            if row.get('timing_clean') and 'estimated_power_w' in row:
                row['latency_us'] = row['hls_latency_us']
                row['energy_uj'] = row['latency_us'] * row['estimated_power_w']
                row['edp_uj_us'] = row['energy_uj'] * row['latency_us']
        results.append(row)
    return results


def pareto(rows):
    valid = [r for r in rows if 'energy_uj' in r]
    for r in valid:
        r['pareto_latency_energy'] = not any(
            s['latency_us'] <= r['latency_us'] and s['energy_uj'] <= r['energy_uj']
            and (s['latency_us'] < r['latency_us'] or s['energy_uj'] < r['energy_uj'])
            for s in valid)


def operating_metrics(root, horizon):
    rows = []
    for clock in root.glob('operate_*mhz'):
        for path in clock.iterdir():
            if f'_h{horizon}_' not in path.name and not path.name.endswith(f'_h{horizon}'):
                continue
            if not (path/'result.json').exists(): continue
            row = json.loads((path/'result.json').read_text())
            latency = row.pop('latency_us')
            row['variant'] = path.name + f"_{row['clock_mhz']:g}mhz"
            row['implementation_pass'] = 'operating_clock'
            timing = (path/'post_route_timing.rpt').read_text()
            m = re.search(r'WNS\(ns\).*?\n\s*-+[^\n]*\n\s*([-\d.]+)\s+([-\d.]+)\s+(\d+)\s+(\d+)\s+([-\d.]+)', timing, re.S)
            if m:
                row.update(wns_ns=float(m[1]), whs_ns=float(m[5]), timing_clean=float(m[1]) >= 0 and float(m[5]) >= 0)
            power = (path/'post_route_power.rpt').read_text()
            m = re.search(r'Total On-Chip Power \(W\)\s*\|\s*([\d.]+)', power)
            if m:
                row['estimated_power_w'] = float(m[1])
            if row.get('timing_clean') and 'estimated_power_w' in row:
                row['latency_us'] = latency
                row['energy_uj'] = latency * row['estimated_power_w']
                row['edp_uj_us'] = latency * row['energy_uj']
            util = (path/'post_route_utilization.rpt').read_text()
            for label, name in [('Slice LUTs', 'route_lut'), ('DSPs', 'route_dsp'), ('Block RAM Tile', 'route_bram_tiles')]:
                m = re.search(r'\|\s*'+label+r'\s*\|\s*([\d.]+)', util)
                if m: row[name] = float(m[1])
            rows.append(row)
    return rows


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('root', type=Path)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--tiny-csv', type=Path)
    p.add_argument('--horizon', type=int, default=10)
    p.add_argument('--operating-root', type=Path)
    p.add_argument('--reference-csv', type=Path)
    args = p.parse_args()
    rows = metrics(args.root)
    if args.operating_root:
        rows += operating_metrics(args.operating_root, args.horizon)
    if args.reference_csv:
        for ref in csv.DictReader(args.reference_csv.open()):
            if int(ref['horizon']) != args.horizon or ref['solver'] != 'full_sparse' or ref['status'] != 'pass': continue
            rows.append(dict(variant='published_full_sparse', timing_clean=True, clock_mhz=float(ref['clock_mhz']),
                latency_us=float(ref['latency_us']), energy_uj=float(ref['estimated_energy_uj']),
                edp_uj_us=float(ref['edp_uj_us']), estimated_power_w=float(ref['estimated_power_w']),
                route_lut=float(ref['lut']), route_dsp=float(ref['dsp']), route_bram_tiles=float(ref['bram_tiles']),
                provenance=ref['source']))
    if args.tiny_csv:
        tiny = next(r for r in csv.DictReader(args.tiny_csv.open()) if int(r['horizon']) == args.horizon and r['timing_clean'] == '1')
        latency = float(tiny['solve_us_cfg_clk'])
        energy = float(tiny['energy_per_solve_cfg_uj'])
        rows.append(dict(variant='tinympc_fpga', latency_us=latency, energy_uj=energy,
                         edp_uj_us=latency*energy, estimated_power_w=float(tiny['route_power_total_w']),
                         timing_clean=True, clock_mhz=100, route_lut=float(tiny['route_slice_luts_used']),
                         route_dsp=float(tiny['route_dsps_used']), route_bram_tiles=float(tiny['route_bram_tile_used'])))
    pareto(rows)
    tiny = next((r for r in rows if r['variant'] == 'tinympc_fpga'), None)
    if tiny:
        for r in rows:
            latency = r.get('latency_us', r.get('hls_latency_us'))
            if latency:
                r['energy_break_even_power_w_vs_tiny'] = tiny['energy_uj'] / latency
                r['edp_break_even_power_w_vs_tiny'] = tiny['edp_uj_us'] / latency**2
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(rows, indent=2)+'\n')
    columns = ['variant', 'clock_mhz', 'bit_exact_checked', 'hls_latency_us', 'timing_clean', 'latency_us',
               'estimated_power_w', 'energy_uj', 'edp_uj_us', 'pareto_latency_energy',
               'route_lut', 'route_dsp', 'route_bram_tiles', 'wns_ns', 'whs_ns']
    with args.output.with_suffix('.csv').open('w') as f:
        writer = csv.DictWriter(f, columns, extrasaction='ignore')
        writer.writeheader()
        writer.writerows(rows)
    for r in rows:
        print(' '.join(f'{k}={r[k]}' for k in columns if k in r))
