#!/usr/bin/env python3
"""Compare onboard runs with a Vivado report and the rows selected for the paper."""
import argparse
import csv
import hashlib
import json
from pathlib import Path
import statistics
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'paper_figures'))
import plot_benchmarks as paper


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('runs', nargs='+', type=Path, help='Back-to-back metadata.json files from the same bitstream')
    parser.add_argument('--report', type=Path, default=ROOT / 'build/reports/post_route_power.rpt')
    parser.add_argument('--paper-data', type=Path, default=ROOT / 'paper_figures/data/benchmark_summary.csv')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    runs = [json.loads(p.read_text()) for p in args.runs]
    hashes = {r['bitstream_sha256'] for r in runs}
    if len(hashes) != 1 or any(not r['summary']['valid'] or r['config_cycles'][1] for r in runs):
        parser.error('Use valid back-to-back runs from one bitstream')
    fields = {}
    for line in args.report.read_text().splitlines():
        cells = [v.strip() for v in line.split('|')[1:-1]]
        if len(cells) >= 2:
            fields.setdefault(cells[0], cells[1:])
    core_estimate = sum(float(fields[rail][0]) * float(fields[rail][1]) for rail in ('Vccint', 'Vccbram'))
    total_estimate = float(fields['Total On-Chip Power (W)'][0])
    measured = {}
    for rail in ('core', 'five'):
        values = [r['summary']['rails'][rail] for r in runs]
        powers = [v['active']['power_w'] for v in values]
        measured[rail] = {
            'active_power_mean_w': statistics.mean(powers),
            'active_power_range_w': [min(powers), max(powers)],
            'absolute_energy_mean_uj_per_solve': statistics.mean(v['energy_per_solve_j'] * 1e6 for v in values),
            'idle_subtracted_energy_mean_uj_per_solve': statistics.mean(v['incremental_energy_per_solve_j'] * 1e6 for v in values),
        }
    latency_us = statistics.mean(r['status']['latency_total'] / r['status']['completed'] / r['clock_hz'] * 1e6 for r in runs)
    selected = paper.best_rows(paper.load_rows(args.paper_data), 10)
    paper_rows = []
    for row in selected:
        paper_rows.append({
            **{key: row.get(key, '') for key in ('arch', 'horizon', 'admm_iters', 'slug', 'git_head', 'source_summary', 'point_dir')},
            'latency_us': paper.f(row, 'solve_us_cfg_clk'),
            'power_w': paper.power_w(row, paper.DEFAULT_TINYMPC_POWER_W),
            'absolute_energy_uj': paper.energy_mj(row, paper.DEFAULT_TINYMPC_POWER_W) * 1000,
            'power_basis': 'MCU datasheet estimate' if row['arch'] == 'tinympc_e' else 'Vivado total on-chip estimate',
        })
    result = {
        'sources': {str(p.resolve()): hashlib.sha256(p.read_bytes()).hexdigest() for p in [*args.runs, args.report, args.paper_data]},
        'bitstream_sha256': next(iter(hashes)),
        'run_count': len(runs),
        'solver_constants': runs[0]['workload']['solver_constants'],
        'runtime_config': runs[0]['workload']['runtime_config'],
        'latency_us': latency_us,
        'measured': measured,
        'vivado': {'core_plus_bram_w': core_estimate, 'total_on_chip_w': total_estimate,
                   'confidence': fields['Confidence Level'][0], 'activity_file': fields['Simulation Activity File'][0],
                   'total_on_chip_energy_at_measured_latency_uj': total_estimate * latency_us},
        'measured_core_below_estimate_percent': 100 * (1 - measured['core']['active_power_mean_w'] / core_estimate),
        'limitations': [
            'Report must belong to the measured build; source hashes preserve the inputs but cannot establish that association.',
            'Core measurement covers VCCINT and VCCBRAM, including instrumentation; it is not total FPGA power.',
            'Monitored 5 V includes board loads and regulator losses; it is not total FPGA power or a USB wall-power measurement.',
            'Nominal onboard scaling, without external calibration. Repeat range is not an accuracy bound.',
            'Paper uses absolute energy; idle-subtracted energy is a separate metric.',
            'Current H27/K9 synthetic workload has no exact paper configuration match; paper selected FPGA rows use K10.',
            'No measured correction factor or updated FPGA/MCU energy ratio is inferred for the paper.',
        ],
        'paper_selected_rows': paper_rows,
    }
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / 'comparison.json').write_text(json.dumps(result, indent=2) + '\n')
    with (args.output / 'paper_selected.csv').open('w', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(paper_rows[0]))
        writer.writeheader()
        writer.writerows(paper_rows)
    print(json.dumps({k: result[k] for k in ('measured', 'vivado', 'measured_core_below_estimate_percent')}, indent=2))


if __name__ == '__main__':
    main()
