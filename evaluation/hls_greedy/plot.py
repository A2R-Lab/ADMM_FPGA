#!/usr/bin/env python3
"""Latency/estimated-energy Pareto views; reports exclude timing-failing builds."""
import argparse
import json
import os
from pathlib import Path
os.environ.setdefault('MPLCONFIGDIR', '/tmp/admm-greedy-matplotlib')
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

p = argparse.ArgumentParser()
p.add_argument('summaries', nargs='+', type=Path)
p.add_argument('--output', type=Path, required=True)
args = p.parse_args()
fig, axes = plt.subplots(1, len(args.summaries), figsize=(7 * len(args.summaries), 5.2), squeeze=False)
for ax, summary in zip(axes[0], args.summaries):
    rows = [r for r in json.loads(summary.read_text()) if 'energy_uj' in r and r.get('timing_clean')]
    rows = [r for r in rows if r.get('pareto_latency_energy') or 'tiny' in r['variant']
            or r['variant'] in ['baseline', 'fused_loop', 'published_full_sparse', 'split_far3']
            or r['variant'].startswith('accel_')]
    for r in rows:
        name = r['variant']
        tiny = 'tiny' in name
        fast = name.startswith('accel_') or name.startswith('split_')
        color = '#df7520' if tiny else '#168768' if fast else '#617182'
        marker = 's' if r.get('clock_mhz') == 80 else 'o'
        ax.scatter(r['latency_us'], r['energy_uj'], color=color, marker=marker, s=65, zorder=3)
        label = name.replace('accel_h10_', '').replace('accel_h40_', '').replace('published_', '')
        label = label.replace('tinympc_fpga', 'TinyMPC 100 MHz').replace('tiny_h10_80mhz', 'TinyMPC 80 MHz').replace('tiny_h40_80mhz', 'TinyMPC 80 MHz')
        label = label.replace('split_fused0_80mhz', 'Aggressive 80 MHz').replace('baseline', 'Original staged 100 MHz')
        label = label.replace('fused_loop', 'Fused updates 100 MHz').replace('full_sparse', 'Original full-sparse 100 MHz')
        label = label.replace('split_far2', 'Fast 100 MHz (2-stage)').replace('split_far3', 'Fast 100 MHz (3-stage)')
        right = r['latency_us'] > .8 * max(s['latency_us'] for s in rows)
        offset = (-5 if right else 5, -14 if name in ['tinympc_fpga', 'split_far2'] else 7)
        ax.annotate(label, (r['latency_us'], r['energy_uj']), xytext=offset,
                    ha='right' if right else 'left', textcoords='offset points', fontsize=8)
    frontier = sorted([r for r in rows if r.get('pareto_latency_energy')], key=lambda r: r['latency_us'])
    ax.plot([r['latency_us'] for r in frontier], [r['energy_uj'] for r in frontier], '--', color='#168768', alpha=.6)
    ax.set_xlabel('Solve latency (µs) — lower is better')
    ax.set_ylabel('Estimated energy per solve (µJ) — lower is better')
    ax.set_title(summary.stem.upper() + ': timing-clean operating points')
    ax.grid(alpha=.2)
    ax.margins(.22)
fig.suptitle('AccelMPC HLS implementation search: latency / energy frontier', fontsize=14)
fig.text(.5, .01, 'Energy uses vectorless Vivado power estimates, not board measurements. Circles: 100 MHz; squares: 80 MHz.', ha='center', fontsize=9)
fig.tight_layout(rect=(0,.04,1,.94))
args.output.parent.mkdir(parents=True, exist_ok=True)
fig.savefig(args.output.with_suffix('.png'), dpi=180)
fig.savefig(args.output.with_suffix('.pdf'))
