#!/usr/bin/env python3
"""Export 100 MHz routed outcomes; failed builds retain evidence, not usable latency."""
import argparse
import csv
import json
from pathlib import Path
import re
import xml.etree.ElementTree as ET


def cell(text, label):
    match = re.search(r'^\|\s*' + re.escape(label) + r'\*?\s*\|\s*([\d.,]+)\s*\|', text, re.M)
    if not match:
        raise ValueError(f'Missing report field: {label}')
    return float(match.group(1).replace(',', ''))


def summarize(run):
    rows = []
    for result in json.loads((run / 'summary.json').read_text()):
        h = result['horizon']
        d = run / f'h{h}'
        row = dict(arch='tinympc_fpga_float', horizon=h, admm_iters=result['iterations'],
                   timing_clean=0, status=result['status'], hls_latency_cycles='', solve_us_cfg_clk='',
                   route_power_total_w='', energy_per_solve_cfg_uj='', clock_mhz=100, hls_clock_mhz=100,
                   provenance=f'{run.name}/h{h}; Vitis/Vivado 2025.2; float32 rho=1; steady-state Riccati; local memory; estimated power/energy',
                   route_slice_luts_used='', route_slice_registers_used='', route_bram_tile_used='', route_dsps_used='',
                   route_wns_ns='', synth_slice_luts_used='', synth_bram_tile_used='', failed_stage=result.get('failed_stage',''))
        xml = d / 'hls/hls/syn/report/tinympc_solver_csynth.xml'
        if xml.exists():
            tree = ET.parse(xml)
            assert tree.findtext('.//Part') == 'xc7a100t-csg324-1'
            assert float(tree.findtext('.//TargetClockPeriod')) == 10
            row['hls_latency_cycles'] = int(tree.findtext('.//Worst-caseLatency'))
        reports = d / 'implementation'
        synth = reports / 'post_synth_utilization.rpt'
        if synth.exists():
            row['synth_slice_luts_used'] = cell(synth.read_text(), 'Slice LUTs')
            row['synth_bram_tile_used'] = cell(synth.read_text(), 'Block RAM Tile')
        timing_file = reports / 'post_route_timing.rpt'
        if timing_file.exists():
            timing = timing_file.read_text()
            # Require the actual report clock, including legacy campaigns that
            # subsequently evaluated the same checkpoint at 60 MHz.
            assert re.search(r'^default\s+\{[^}]+\}\s+10\.000\s+100\.000', timing, re.M), timing_file
            wns = re.search(r'WNS\(ns\).*?\n\s*-+[^\n]*\n\s*([-\d.]+)', timing, re.S)
            if wns:
                row['route_wns_ns'] = float(wns.group(1))
            util = (reports / 'post_route_utilization.rpt').read_text()
            for key, label in [('route_slice_luts_used','Slice LUTs'), ('route_slice_registers_used','Slice Registers'),
                               ('route_bram_tile_used','Block RAM Tile'), ('route_dsps_used','DSPs')]:
                row[key] = cell(util, label)
            if 'All user specified timing constraints are met.' in timing:
                power = (reports / 'post_route_power.rpt').read_text()
                row.update(timing_clean=1, status='pass', solve_us_cfg_clk=row['hls_latency_cycles']/100,
                           route_power_total_w=cell(power, 'Total On-Chip Power (W)'))
                row['energy_per_solve_cfg_uj'] = row['solve_us_cfg_clk'] * row['route_power_total_w']
            else:
                row['status'] = 'timing_not_closed_100mhz'
        elif (d / 'vivado.log').exists():
            log = (d / 'vivado.log').read_text()
            if 'over-utilized' in log or 'UTLZ-1' in log:
                row['status'] = 'does_not_fit'
        rows.append(row)
    return rows


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--run', type=Path, action='append', required=True)
    ap.add_argument('--output', type=Path, required=True)
    args = ap.parse_args()
    rows = sorted([row for run in args.run for row in summarize(run)], key=lambda r:r['horizon'])
    assert rows and len({r['horizon'] for r in rows}) == len(rows), 'Empty results or duplicate horizon'
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('w') as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)
    print(json.dumps(rows, indent=2))

if __name__ == '__main__': main()
