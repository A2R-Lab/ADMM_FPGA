#!/usr/bin/env python3
"""Incrementally import completed compact full-sparse Arty measurements."""
import argparse
import csv
import hashlib
import json
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--campaign-root', type=Path, required=True)
    parser.add_argument('--csv', type=Path, default=HERE / 'data/benchmarks.csv')
    args = parser.parse_args()
    with args.csv.open() as stream:
        reader = csv.DictReader(stream)
        fields = list(reader.fieldnames)
        rows = list(reader)
    additions = ['implementation', 'max_horizon_status', 'solver_luts_used',
                 'solver_bram_tiles_used', 'solver_dsps_used', 'solver_registers_used']
    fields += [key for key in additions if key not in fields]
    for row in rows:
        # Keep historical measurements, but distinguish their implementation.
        if row['arch'] == 'full_sparse' and row.get('implementation') != 'compact_rhs':
            row['arch'] = 'full_sparse_original'
            row['implementation'] = 'original'
    selected = {(r['arch'], int(r['horizon']), int(r['admm_iters']),
                 float(r['clock_mhz'])): r for r in rows}
    # The canonical CSV also retains the validated source and matched H40 resources.
    compact_source = selected['full_sparse', 40, 10, 100.0]['solver_source_sha256']
    if not re.fullmatch(r'[0-9a-f]{64}', compact_source):
        raise ValueError('Missing validated compact solver hash in canonical CSV')
    matched_resources = {
        arch: {key: selected[arch, 40, 10, 100.0][key]
               for key in ('solver_luts_used', 'solver_bram_tiles_used',
                           'solver_dsps_used', 'solver_registers_used')}
        for arch in ('full_sparse', 'staged_fused')
    }
    imported = set()
    for summary in sorted(args.campaign_root.glob('compact*-meas/summaries/*/summary.csv')):
        local = summary.parents[2]
        for result in csv.DictReader(summary.open()):
            if result['status'] != 'measured' or int(result['valid_repetitions'] or 0) != 3:
                continue
            if result['arch'] != 'full_sparse' or int(result['iterations']) != 10:
                raise ValueError('Unexpected measurement configuration')
            bundle = local / 'cache' / result['campaign_id'] / result['id']
            artifact = json.loads((bundle / 'artifact.json').read_text())
            manifest = json.loads((bundle / 'top_uart_power.json').read_text())
            complete = json.loads((local / 'measurements' / result['campaign_id'] /
                                   result['id'] / 'complete.json').read_text())
            if not complete['valid'] or not artifact['timing_clean']:
                raise ValueError('Invalid completed measurement')
            digest = hashlib.sha256((bundle / 'top_uart_power.bit').read_bytes()).hexdigest()
            if not (digest == result['bitstream_sha256'] ==
                    artifact['files']['top_uart_power.bit'] == manifest['bitstream_sha256']):
                raise ValueError('Bitstream mismatch')
            if manifest['trajectory_compiled'] or manifest['use_float']:
                raise ValueError('Unexpected solver configuration')
            if manifest['solver_file_sha256']['ADMM.cpp'] != compact_source:
                raise ValueError('Measurement uses a different solver implementation')
            power_file = bundle / 'reports/post_route_power.rpt'
            if hashlib.sha256(power_file.read_bytes()).hexdigest() != artifact['files']['reports/post_route_power.rpt']:
                raise ValueError('Power report mismatch')
            report = power_file.read_text()
            extra = 0.0
            for rail in ('Vccaux', 'Vcco33', 'Vcco25', 'Vcco18', 'Vcco15',
                         'Vcco135', 'Vcco12', 'Vccaux_io'):
                match = re.search(r'\| ' + rail + r'\s*\|\s*([\d.]+)\s*\|\s*([\d.]+)', report)
                if match:
                    extra += float(match[1]) * float(match[2])
            latency = float(result['latency_us_mean'])
            energy = float(result['raw_core_energy_uj_mean']) + extra * latency
            row = dict(arch='full_sparse', horizon=result['horizon'], admm_iters=10,
                       clock_mhz=100, timing_clean=1, status='pass',
                       solve_us_cfg_clk=latency, solve_us_per_iter_cfg_clk=latency / 10,
                       measured_latency_us=latency, energy_source='board_core_plus_estimated_aux_io',
                       measured_energy_uj=energy, measured_energy_std_uj=result['raw_core_energy_uj_std'],
                       measured_power_w=energy / latency, raw_core_energy_uj=result['raw_core_energy_uj_mean'],
                       estimated_aux_io_w=extra, valid_repetitions=3,
                       energy_per_solve_cfg_uj=energy, edp_uj_us=energy * latency,
                       implementation='compact_rhs', max_horizon_status='demonstrated', resource_scope='instrumented',
                       solver_source_sha256=compact_source)
            row.update(artifact['resources'])
            key = ('full_sparse', int(result['horizon']), 10, 100.0)
            if key in imported:
                raise ValueError(f'Duplicate completed point: {key}')
            imported.add(key)
            selected[key] = row
    if not imported:
        raise ValueError('No completed compact measurements found')
    # Matched solver/SPI resource comparison; board energy stays instrumented.
    for arch, values in matched_resources.items():
        selected[arch, 40, 10, 100.0].update(values)
    with args.csv.open('w', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction='ignore', lineterminator='\n')
        writer.writeheader()
        writer.writerows(selected[key] for key in sorted(selected))
    print(f'Imported {len(imported)} compact points; {len(selected)} total historical/current rows.')


if __name__ == '__main__':
    main()
