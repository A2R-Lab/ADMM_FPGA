#!/usr/bin/env python3
"""Compile a recorded-state CSV into the benchmark's bitstream-initialized ROM."""
import argparse
import csv
import hashlib
import json
import math
from pathlib import Path
import re
import struct

STATE_COLUMNS = 'x y z roll pitch yaw vx vy vz wx wy wz'.split()

def encode_state(value, use_float):
    value = float(value)
    if not math.isfinite(value):
        raise ValueError('State values must be finite')
    if use_float:
        return int.from_bytes(struct.pack('<f', value), 'little')
    # ap_fixed<32,10,AP_RND,AP_SAT>: nearest, ties towards positive infinity.
    code = math.floor(value * (1 << 22) + 0.5)
    if not -(1 << 31) <= code < (1 << 31):
        raise ValueError(f'State {value} outside Q10.22 range')
    return code & 0xffffffff

def write_changed(path, text):
    if not path.exists() or path.read_text() != text:
        path.write_text(text)

def compile_workload(csv_path, config_path, output):
    config = Path(config_path).read_text()
    match = re.search(r'^#define ADMM_USE_FLOAT ([01])$', config, re.M)
    if not match:
        raise ValueError('Missing ADMM_USE_FLOAT in generated runtime configuration')
    use_float = bool(int(match[1]))
    records = []
    with Path(csv_path).open(newline='') as f:
        reader = csv.DictReader(f)
        if not set(STATE_COLUMNS).issubset(reader.fieldnames or []):
            raise ValueError('Required CSV columns: ' + ','.join(STATE_COLUMNS))
        for row in reader:
            words = [encode_state(row[name], use_float) for name in STATE_COLUMNS]
            constraints = int(row.get('constraints') or '0', 0)
            command = int(row.get('traj_cmd') or '0', 0)
            if not 0 <= constraints <= 0xffffffff or not 0 <= command <= 3:
                raise ValueError('constraints must be uint32 and traj_cmd must be 0..3')
            packed = sum(word << (32 * i) for i, word in enumerate(words))
            records.append(packed | (constraints << 384) | (command << 416))
    if not 1 <= len(records) <= 256:
        raise ValueError('Workload must contain 1..256 records')
    digest = hashlib.sha256(b''.join(x.to_bytes(53, 'little') for x in records)).hexdigest()
    out = Path(output)
    out.mkdir(parents=True, exist_ok=True)
    write_changed(out / 'power_workload.mem', ''.join(f'{x:0105x}\n' for x in records + [0] * (256-len(records))))
    write_changed(out / 'power_workload.vh', 
        f'`define POWER_WORKLOAD_COUNT {len(records)}\n'
        f"`define POWER_WORKLOAD_HASH 256'h{digest}\n"
        f'`define POWER_USE_FLOAT {int(use_float)}\n')
    metadata = dict(kind=('synthetic' if Path(csv_path).resolve() == Path(__file__).resolve().parents[1]/'scripts/power_synthetic_states.csv' else 'user-supplied'), source=str(Path(csv_path).resolve()), csv_sha256=hashlib.sha256(Path(csv_path).read_bytes()).hexdigest(),
                    workload_sha256=digest, record_count=len(records), use_float=use_float,
                    runtime_config=config, input_bits=418)
    write_changed(out / 'power_workload.json', json.dumps(metadata, indent=2) + '\n')
    return metadata

if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--csv', required=True)
    p.add_argument('--config', default='vitis_projects/ADMM/admm_runtime_config.h')
    p.add_argument('--output', default='build/power')
    a = p.parse_args()
    print(json.dumps(compile_workload(a.csv, a.config, a.output), indent=2))
