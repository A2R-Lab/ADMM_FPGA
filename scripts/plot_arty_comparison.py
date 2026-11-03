#!/usr/bin/env python3
"""Plot measured-only latency/energy and EDP; never fill missing points with estimates."""
import argparse
import csv
import hashlib
import json
from pathlib import Path


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--summary',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    a=p.parse_args()
    rows=list(csv.DictReader(a.summary.open()))
    valid=[r for r in rows if r['status']=='measured' and int(r['valid_repetitions'])==3]
    if not valid:raise SystemExit('No validated three-repetition measurements; no plots generated.')
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    a.output.mkdir(parents=True,exist_ok=True)
    labels={'staged_a':'AccelMPC staged','staged_fused':'AccelMPC staged','tinympc_fpga':'TinyMPC FPGA'}
    for rail,title in [('raw_core','Active core/BRAM'),('incremental_core','Incremental core/BRAM'),('five','Monitored 5 V')]:
        fig,ax=plt.subplots(1,2,figsize=(12,4.8),layout='constrained')
        for arch in labels:
            points=sorted([r for r in valid if r['arch']==arch],key=lambda r:int(r['horizon']))
            if not points:continue
            val=lambda key:[float(r[key]) for r in points]
            x=val('latency_us_mean');e=val(rail+'_energy_uj_mean')
            ax[0].errorbar(x,e,xerr=val('latency_us_std'),yerr=val(rail+'_energy_uj_std'),fmt='o-',capsize=2,label=labels[arch])
            for r,l,en in zip(points,x,e):ax[0].annotate('H'+r['horizon'],(l,en),xytext=(3,4),textcoords='offset points',fontsize=7)
            ax[1].errorbar([int(r['horizon']) for r in points],val(rail+'_edp_uj_us_mean'),yerr=val(rail+'_edp_uj_us_std'),fmt='o-',capsize=2,label=labels[arch])
        ax[0].set(xlabel='Measured transaction latency (µs)',ylabel='Energy per solve (µJ)')
        ax[1].set(xlabel='Horizon',ylabel='EDP (µJ·µs)')
        if rail!='incremental_core':
            ax[0].set_xscale('log');ax[0].set_yscale('log');ax[1].set_yscale('log')
        for panel in ax:panel.grid(alpha=.25);panel.legend()
        fig.suptitle(title+' — Arty, 100 MHz, 10 iterations; error bars: sample SD')
        for suffix in ('png','pdf'):fig.savefig(a.output/f'{rail}.{suffix}',dpi=180)
        plt.close(fig)
    (a.output/'provenance.json').write_text(json.dumps({'summary_sha256':hashlib.sha256(a.summary.read_bytes()).hexdigest(),'measured_points':len(valid),'excluded':[{k:r[k] for k in ('id','status')} for r in rows if r not in valid],'power_boundary':'separate core/BRAM and monitored 5 V; no estimated supplies added'},indent=2)+'\n')

if __name__=='__main__':main()
