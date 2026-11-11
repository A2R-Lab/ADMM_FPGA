"""Single CSV-derived source for the video's H40 benchmark card and speech."""
import csv
import hashlib
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'evaluation'))
from paper_figures import at, latency_us, energy_uj


def benchmark_evidence():
    source = ROOT / 'evaluation/data/benchmarks.csv'
    rows = list(csv.DictReader(source.open()))
    designs = {}
    for arch in ('tinympc_e', 'tinympc_fpga_float', 'full_sparse', 'staged_fused'):
        row = at(rows, arch, 40)
        if row is None:
            raise ValueError(f'Missing H40 k10 benchmark: {arch}')
        latency, energy = latency_us(row), energy_uj(row)
        designs[arch] = {'latency_ms': latency / 1000, 'energy_mj': energy / 1000,
                         'edp_mj_ms': energy * latency / 1e6, 'csv_row': row}
    staged = designs['staged_fused']
    ratios = {arch: {'speedup': v['latency_ms'] / staged['latency_ms'],
                     'edp_reduction': v['edp_mj_ms'] / staged['edp_mj_ms']}
              for arch, v in designs.items()}
    return {'source': str(source.relative_to(ROOT)), 'sha256': hashlib.sha256(source.read_bytes()).hexdigest(),
            'horizon': 40, 'iterations': 10, 'designs': designs, 'ratios': ratios,
            'scope': 'Solve only. FPGA: Arty core/BRAM measurements + auxiliary/I/O estimates. MCU: measured latency × nominal 0.2871 W. No communication, host or board support energy.',
            'mapping': 'staged_fused is current staged_a; full_sparse is compact_rhs; flight footage uses historical implementations.'}
