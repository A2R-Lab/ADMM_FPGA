#!/usr/bin/env python3
"""Compare timing-closed solver implementations using post-route estimates only."""
import argparse
import csv
from pathlib import Path
import json

HERE=Path(__file__).resolve().parent
DATA=HERE.parent/'data'


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--output',type=Path,default=HERE/'comparison')
    args=ap.parse_args()
    tiny=list(csv.DictReader((DATA/'tinympc_fpga_comparison.csv').open()))
    accel=list(csv.DictReader((DATA/'benchmark_summary.csv').open()))
    moby=list(csv.DictReader((DATA/'mobydic_comparison.csv').open()))
    horizons={int(r['horizon']) for r in tiny}
    chosen={}
    for r in accel:
        if r['arch'] not in ['staged_a','full_sparse'] or r['admm_iters']!='10' or r['status']!='pass' or r['timing_clean']!='1':
            continue
        key=(r['arch'],int(r['horizon']))
        # Retain first published timing-closed record, not the lowest latency/power.
        chosen.setdefault(key,r)
    fields=['solver','horizon','iterations','clock_mhz','status','latency_us','estimated_power_w','estimated_energy_uj','edp_uj_us','lut_latency_lut_us','lut','ff','bram_tiles','dsp','source']
    rows=[]
    for r in tiny + [v for (arch,h),v in chosen.items() if h in horizons] + moby:
        good=r['timing_clean']=='1'
        latency=float(r['solve_us_cfg_clk']) if good else None
        power=float(r['route_power_total_w']) if good else None
        rows.append(dict(solver=r['arch'],horizon=int(r['horizon']),iterations=10,
            clock_mhz=r.get('clock_mhz',100),status=r['status'],latency_us=latency,
            estimated_power_w=power,estimated_energy_uj=latency*power if good else None,
            edp_uj_us=latency*latency*power if good else None,
            lut_latency_lut_us=latency*float(r['route_slice_luts_used']) if good else None,
            lut=r['route_slice_luts_used'],ff=r['route_slice_registers_used'],bram_tiles=r['route_bram_tile_used'],dsp=r['route_dsps_used'],
            source=r.get('provenance',r.get('campaign',''))))
    rows.sort(key=lambda r:(r['horizon'],r['solver']))
    args.output.mkdir(parents=True,exist_ok=True)
    with (args.output/'metrics.csv').open('w') as f:
        w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(rows)
    maximum={arch:max(h for a,h in chosen if a==arch) for arch in ['staged_a','full_sparse']}
    maximum['tinympc_fpga_float']=max(int(r['horizon']) for r in tiny if r['timing_clean']=='1')
    maximum['mobydic_small']=max(int(r['horizon']) for r in moby if r['timing_clean']=='1')
    (args.output/'largest_demonstrated.json').write_text(json.dumps(maximum,indent=2)+'\n')
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    fig,axes=plt.subplots(2,3,figsize=(15,8),layout='constrained')
    labels={'staged_a':'AccelMPC staged','full_sparse':'AccelMPC full-sparse','tinympc_fpga_float':'TinyMPC FPGA','mobydic_small':'MOBY-DIC (60 MHz)'}
    for ax,key,title in zip(axes.flat,['latency_us','estimated_energy_uj','edp_uj_us','lut','bram_tiles','lut_latency_lut_us'],['Solve latency (µs)','Estimated energy/solve (µJ)','EDP (µJ·µs)','LUTs','BRAM tiles','LUT–latency product (LUT·µs)']):
        for arch,label in labels.items():
            points=[r for r in rows if r['solver']==arch and r['latency_us'] is not None]
            ax.plot([r['horizon'] for r in points],[float(r[key]) for r in points],marker='o',label=label)
        ax.set_xscale('log',base=2)
        if key in ['latency_us','estimated_energy_uj','edp_uj_us','lut_latency_lut_us']:ax.set_yscale('log')
        if key=='lut':ax.axhline(63400,color='gray',ls=':',label='Device capacity')
        if key=='bram_tiles':ax.axhline(135,color='gray',ls=':',label='Device capacity')
        ax.set_xlabel('Control steps H');ax.set_ylabel(title);ax.grid(alpha=.25)
    axes[0,0].legend(fontsize=8)
    fig.suptitle('10 iterations · Artix-7 XC7A100T · 100 MHz except MOBY-DIC\nPost-route power estimates; native arithmetic and solver formulations')
    fig.savefig(args.output/'comparison.png',dpi=180)
    fig.savefig(args.output/'comparison.pdf')
    plt.close(fig)
    fig,ax=plt.subplots(figsize=(8,4),layout='constrained')
    names=list(labels)
    bars=ax.barh([labels[a] for a in names],[maximum[a] for a in names],color=['C0','C1','C2','C3'])
    ax.bar_label(bars,padding=5)
    ax.set_xlim(0,max(maximum.values())*1.15)
    ax.set_xlabel('Largest demonstrated timing-clean horizon H')
    ax.set_title('Capacity: 10 iterations · XC7A100T\n100 MHz except MOBY-DIC at 60 MHz')
    fig.savefig(args.output/'capacity.png',dpi=180)
    fig.savefig(args.output/'capacity.pdf')
    print(f'Wrote {len(rows)} comparison rows to {args.output}')

if __name__=='__main__':main()
