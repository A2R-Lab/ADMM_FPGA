#!/usr/bin/env python3
"""Summarize Vivado hierarchical dynamic power; no module attribution of static power."""
import argparse
import hashlib
import json
from pathlib import Path


def summarize(path):
    fields = {}
    for line in path.read_text().splitlines():
        cells = [cell.strip() for cell in line.split('|')[1:-1]]
        if len(cells) >= 2:
            fields.setdefault(cells[0], cells[1:])
    # Treat report entries such as <0.001 as their upper bound.
    modules = {name: float(fields[name][0].lstrip('<')) for name in ('solver', 'capture', 'sensor', 'benchmark', 'comm')}
    total = float(fields['Total On-Chip Power (W)'][0])
    support = sum(value for name, value in modules.items() if name != 'solver')
    return {'report': str(path.resolve()), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
            'total_w': total, 'static_w': float(fields['Device Static (W)'][0]),
            'dynamic_w': float(fields['Dynamic (W)'][0]), 'modules_dynamic_w': modules,
            'capture_and_sensor_w': modules['capture'] + modules['sensor'],
            'all_support_dynamic_w': support, 'support_percent_of_total': 100 * support / total,
            'within_15_percent_threshold': support / total <= 0.15,
            'confidence': fields['Confidence Level'][0]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('reports', nargs='+', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = {'reports': [summarize(p) for p in args.reports],
              'limitations': ['Hierarchical values are dynamic estimates, not measured module power.',
                              'Static and any unassigned top-level power are not attributed to modules.',
                              'Report precision is 1 mW; entries marked < are treated as upper bounds.',
                              'RTL SAIF omits gate glitches and has incomplete post-route name matching.',
                              'Profile uses five synthetic solves, 2 ms idle windows and simulated ADC variation; it does not exercise trace compaction.']}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + '\n')
    for r in result['reports']:
        print(f"{r['report']}: support={r['all_support_dynamic_w']:.3f} W, total={r['total_w']:.3f} W, fraction={r['support_percent_of_total']:.1f}%")


if __name__ == '__main__':
    main()
