#!/usr/bin/env python3
"""Regenerate the H40 comparison radar from recorded compact-mapping builds.

Energy = Vivado total on-chip estimated power * HLS solve time.
Run from the repository root with ~/venv/bin/python.
"""
import csv
import json
import os
from pathlib import Path
import re

os.environ.setdefault('MPLCONFIGDIR', '/tmp/compact_radar_matplotlib')
import matplotlib.pyplot as plt
import numpy as np

HERE = Path(__file__).resolve().parent
SOURCE = HERE / 'full_sparse_memory_20261103'  # evidence lives under evaluation
RESULTS = SOURCE / 'results.csv'
FIGURES = HERE / 'output'


def main():
    runs = list(csv.DictReader(RESULTS.open()))
    specs = [
        ('baseline-single-l-spi-h40', 'Original full_sparse', '#888888', '--'),
        ('candidate-single-l-indexbanks-t2p-h40', 'Compact full_sparse', '#267ABA', '-'),
        ('staged-fused-spi-h40', 'staged_fused', '#00693E', '-'),
    ]
    metrics = ['Latency\n(ms, est.)', 'Energy/solve\n(mJ, est.)',
               'EDP\n(µJ·ms, est.)', 'BRAM\n(tiles)', 'Logic\n(LUTs)', 'DSPs']
    points = []
    for suffix, label, color, style in specs:
        run = next(r for r in runs if Path(r['run']).name == suffix)
        power = float(run['power_w_est'])
        latency_ms = float(run['latency_us_est']) / 1000
        energy_mj = float(run['energy_uj_est']) / 1000
        points.append(dict(label=label, color=color, style=style,
            values=[latency_ms, energy_mj, energy_mj * 1000 * latency_ms,
                    float(run['BRAM_tiles']), float(run['LUT']), float(run['DSP'])],
            estimated_on_chip_power_w=power, run=run['run']))
    values = np.array([p['values'] for p in points])
    normalized = values / values.max(axis=0)
    angles = np.linspace(0, 2*np.pi, len(metrics), endpoint=False)
    closed_angles = np.r_[angles, angles[0]]
    plt.rcParams.update({'font.family': 'DejaVu Sans', 'svg.fonttype': 'none', 'pdf.fonttype': 42})
    fig, ax = plt.subplots(figsize=(9, 8.4), subplot_kw={'polar': True})
    ax.set_theta_offset(np.pi/2)
    ax.set_theta_direction(-1)
    for i, point in enumerate(points):
        radial = np.r_[normalized[i], normalized[i, 0]]
        ax.plot(closed_angles, radial, color=point['color'], linestyle=point['style'],
                linewidth=2.2, marker='o', markersize=5, label=point['label'])
        ax.fill(closed_angles, radial, color=point['color'], alpha=0.06)
    ax.set_xticks(angles, metrics, fontsize=11)
    ax.tick_params(axis='x', pad=22)
    ax.set_ylim(0, 1.08)
    ax.set_yticks([0.25, 0.5, 0.75, 1.0], ['0.25', '0.50', '0.75', '1.00'], fontsize=8, color='#777777')
    ax.grid(color='#dddddd')
    ax.spines['polar'].set_color('#aaaaaa')
    ax.set_title('H40 · 10 iterations · 100 MHz · uninstrumented SPI\nCost normalized per axis: closer to center is better', pad=42, fontsize=13)
    ax.legend(loc='upper center', bbox_to_anchor=(0.5, -0.13), ncol=3, frameon=False, fontsize=10)
    table = [[p['label']] + [f'{v:.3f}' if j < 2 else f'{v:.1f}' if j in (2, 3) else f'{v:,.0f}'
                            for j, v in enumerate(p['values'])] for p in points]
    tab = fig.add_axes([0.04, 0.065, 0.92, 0.13]); tab.axis('off')
    tab.table(cellText=table, colLabels=['Mapping', 'ms est.', 'mJ est.', 'µJ·ms est.', 'BRAM', 'LUTs', 'DSPs'],
              colWidths=[0.28, .12, .12, .12, .12, .12, .12], loc='center', cellLoc='center').auto_set_font_size(False)
    fig.text(.5, .025, 'Energy/EDP: Vivado estimated total on-chip power × HLS solve time; no Arty measurements.\n'
             'Resources: post-route. Maximum horizon for the compact mapping has not been evaluated.',
             ha='center', fontsize=9)
    fig.subplots_adjust(left=.18, right=.82, top=.83, bottom=.34)
    FIGURES.mkdir(parents=True, exist_ok=True)
    for ext in ('png', 'svg', 'pdf'):
        fig.savefig(FIGURES / f'full_sparse_memory_radar.{ext}', dpi=220, bbox_inches='tight')
    (FIGURES / 'full_sparse_memory_radar_data.json').write_text(json.dumps({
        'metrics': metrics, 'energy_method': 'Vivado total on-chip estimated W times HLS latency ms gives mJ',
        'points': points}, indent=2) + '\n')
    plt.close(fig)
    print('Wrote compact full_sparse comparison radar (PNG, SVG, PDF) and input data JSON.')


if __name__ == '__main__':
    main()
