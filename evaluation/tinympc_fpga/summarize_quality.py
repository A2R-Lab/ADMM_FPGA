#!/usr/bin/env python3
"""Summarize paired closed-loop scenarios without combining incompatible metrics."""
import argparse,csv,json
from pathlib import Path
import numpy as np
HERE=Path(__file__).resolve().parent
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--input', type=Path, required=True, help='Directory containing cold.json and warm.json; also receives summaries')
out=parser.parse_args().input
rows=[]
for name in ['cold','warm']:
    rows+=json.loads((out/f'{name}.json').read_text())['results']
assert len(rows)==150
assert len({(r['horizon'],r['solver'],r['scenario'],r['seed']) for r in rows})==150
assert all(r['status']=='complete' and r['steps']==250 for r in rows)
summary=[]
for h in [10,40]:
    for scenario in ['offset','step','circle','boundary','disturbance']:
        for solver in ['accel','accel_warm','tiny']:
            rs=[r for r in rows if (r['horizon'],r['scenario'],r['solver'])==(h,scenario,solver)]
            assert len(rs)==5
            summary.append(dict(horizon=h,scenario=scenario,solver=solver,
                rmse_mean_m=float(np.mean([r['position_rmse'] for r in rs])),
                rmse_std_m=float(np.std([r['position_rmse'] for r in rs])),
                cost_mean=float(np.mean([r['integrated_stage_cost'] for r in rs])),
                max_xy_violation_m=max(r['max_xy_violation'] for r in rs),
                max_attitude=max(r['max_attitude'] for r in rs),
                total_input_clipped_steps=sum(r['input_clipped_steps'] for r in rs)))
with (out/'summary.csv').open('w') as f:
    w=csv.DictWriter(f,fieldnames=summary[0]);w.writeheader();w.writerows(summary)
for h in [10,40]:
    for sc in ['offset','step','circle','boundary','disturbance']:
        print(h,sc,[(r['solver'],round(r['rmse_mean_m'],4),round(r['cost_mean'],3),round(r['max_xy_violation_m'],4)) for r in summary if r['horizon']==h and r['scenario']==sc])
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
fig,axes=plt.subplots(1,2,figsize=(11,4),layout='constrained',sharey=True)
scenarios=['offset','step','circle','boundary','disturbance']
for ax,h in zip(axes,[10,40]):
    for j,(solver,label) in enumerate([('accel','AccelMPC cold'),('accel_warm','AccelMPC retained state'),('tiny','TinyMPC FPGA cold')]):
        vals=[next(r['rmse_mean_m']*100 for r in summary if (r['horizon'],r['scenario'],r['solver'])==(h,sc,solver)) for sc in scenarios]
        ax.bar(np.arange(5)+(j-1)*.24,vals,width=.24,label=label)
    ax.set_xticks(range(5),scenarios,rotation=25);ax.set_title(f'H{h}: 10 iterations');ax.grid(axis='y',alpha=.2)
axes[0].set_ylabel('Mean position RMSE (cm), 5 initial-condition seeds')
axes[0].legend(fontsize=8)
fig.suptitle('Matched linear-plant simulation at 50 Hz; native formulations; identical actuator clipping')
fig.savefig(out/'tracking_rmse.png',dpi=180)
fig.savefig(out/'tracking_rmse.pdf')
