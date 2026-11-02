#!/usr/bin/env python3
"""Archive completed build evidence through a mounted directory (no remote execution)."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil

ap=argparse.ArgumentParser(description=__doc__)
ap.add_argument('--run',type=Path,required=True)
ap.add_argument('--output',type=Path,required=True)
a=ap.parse_args()
summary=json.loads((a.run/'summary.json').read_text())
patterns=['tinympc_solver.*','hls_config.cfg','configuration.json','numerical.json',
          'hls/hls/syn/report/tinympc_solver_csynth.*','implementation/*.rpt','implementation/clock.xdc',
          'hls.log','vivado.log']
manifest={}
for row in summary:
    src=a.run/f"h{row['horizon']}"
    for pattern in patterns:
        for p in src.glob(pattern):
            relative=p.relative_to(a.run)
            target=a.output/relative
            target.parent.mkdir(parents=True,exist_ok=True)
            if not target.exists() or target.stat().st_size != p.stat().st_size or target.stat().st_mtime_ns != p.stat().st_mtime_ns:
                shutil.copy2(p,target)
            manifest[str(relative)]=hashlib.sha256(target.read_bytes()).hexdigest()
a.output.mkdir(parents=True,exist_ok=True)
(a.output/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
(a.output/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
print(f'Archived {len(summary)} completed points and {len(manifest)} files')
