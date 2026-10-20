#!/usr/bin/env python3
"""Prove the short profile has no trace reads before mapping its BRAM read enable."""
import argparse
import json
import re

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('saif')
a = p.parse_args()
duration = None
inside = False
depth = 0
values = {}
with open(a.saif) as stream:
    for line in stream:
        if m := re.search(r'\(DURATION\s+(\d+)\)', line):
            duration = int(m[1])
        if re.match(r'\s*\(INSTANCE\s+capture\s*$', line):
            inside = True
            depth = 0
        if inside:
            depth += line.count('(') - line.count(')')
            clean = line.replace('\\', '')
            if m := re.match(r'\s*\((read_enable|state\[1\]|state\[2\])\s+', clean):
                values[m[1]] = {k: int(v) for k, v in re.findall(r'\((T0|T1|TX|TZ|TC)\s+(\d+)\)', clean)}
            if depth == 0:
                break
assert duration and set(values) == {'read_enable', 'state[1]', 'state[2]'}, 'Missing capture activity'
for name, v in values.items():
    assert v['T0'] == duration and all(v[k] == 0 for k in ('T1', 'TX', 'TZ', 'TC')), f'{name} is not constantly zero'
# state bits 1 and 2 both zero excludes states 2..6, so the RTL read
# condition read_enable || (state>=2 && state<=6) is always false.
print(json.dumps({'saif': a.saif, 'duration_ps': duration, 'trace_read_enable': 0, 'evidence': values}))
