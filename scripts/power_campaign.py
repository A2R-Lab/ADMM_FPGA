#!/usr/bin/env python3
"""Prepare, build, measure and aggregate an isolated Arty power campaign.

No SSH sessions or detached processes are managed here. Run build on the server
and measure locally. Sources, settings and artifacts are checked by hash.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import contextmanager
import csv
import fcntl
import hashlib
import importlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import statistics
import subprocess
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
GIB = 1024**3
SMOKE = ('full_sparse_h20_k10', 'staged_a_h20_k10')
MODEL = {'id': 'core-plus-32mw-times-0.8-v1', 'auxiliary_w': 0.032,
         'retained_fraction': 0.8, 'label': 'measurement-based corrected FPGA power/energy',
         'vccadc_included': False}
GENERATED = {'data.h', 'admm_runtime_config.h', 'traj_data.h', 'traj_data_raw.h',
             'trajectory_refs.csv', 'admm_autogen_params.vh'}


class AcquisitionTransportError(RuntimeError):
    """A board connection failure must stop the whole measurement queue."""


def transport_failure(log):
    if not log.exists():
        return None
    lines = log.read_text(errors='replace').splitlines()
    for line in reversed(lines):
        if ('serial.serialutil.SerialException:' in line or
                line.startswith('ERROR: No hardware targets found') or
                'No such file or directory' in line and '/dev/' in line):
            return line.strip()
    return None


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda: f.read(1024*1024), b''):
            h.update(block)
    return h.hexdigest()


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def read(path):
    return json.loads(Path(path).read_text())


def save(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    tmp.write_text(json.dumps(value, indent=2, sort_keys=True) + '\n')
    os.replace(tmp, path)


@contextmanager
def locked(path):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with Path(path).open('a') as f:
        try:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError(f'Already in use: {path}') from None
        yield


def clean_environment():
    # All model choices come from the frozen parameters.py, not the login shell.
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(('ADMM_', 'VIVADO_', 'BENCHMARK_', 'SLURM_'))
           and k not in ('MAKEFLAGS', 'MAKEOVERRIDES', 'MFLAGS', 'PYTHONPATH', 'PYTHONHOME')}
    env.update(OMP_NUM_THREADS='1', OPENBLAS_NUM_THREADS='1', MKL_NUM_THREADS='1',
               NUMEXPR_NUM_THREADS='1', MPLBACKEND='Agg', PYTHONUNBUFFERED='1')
    return env


def matrix(path):
    # Same latency/power/stable-order ranking as paper best_rows, without its
    # presentation exclusions. No dependency on plotting packages on the server.
    best = {}
    with Path(path).open(newline='') as f:
        for row in csv.DictReader(f):
            if row['arch'] not in ('full_sparse', 'staged_a') or row['timing_clean'] != '1':
                continue
            if int(row['admm_iters']) != 10:
                continue
            key = row['arch'], int(row['horizon'])
            score = float(row['solve_us_cfg_clk']), float(row['route_power_total_w'])
            if key not in best or score < best[key][0]:
                best[key] = score, row
    points = []
    for (arch, horizon), (_, row) in sorted(best.items()):
        points.append({'id': f'{arch}_h{horizon}_k10', 'arch': arch, 'horizon': horizon,
                       'iterations': 10, 'variant': row.get('vivado_impl_variant') or 'baseline',
                       'historical': {k: row.get(k, '') for k in ('slug', 'campaign', 'git_head',
                           'source_summary', 'solve_us_cfg_clk', 'route_power_total_w')}})
    if not points:
        raise ValueError('No timing-clean FPGA configurations found')
    return points


def source_files(root):
    # Explicit source-only allowlist: never walk the SSHFS mount, .git, credentials,
    # stale IP exports, results, or arbitrary untracked directories.
    files = [root / 'Makefile']
    for folder, suffixes in (
        ('scripts', {'.py', '.tcl', '.sh'}),
        ('vitis_projects/ADMM', {'.cpp', '.h', '.cfg'}),
        ('vivado_project/vivado_project.srcs/sources_1/new', {'.v', '.sv', '.vh'}),
        ('vivado_project/vivado_project.srcs/constrs_1/new', {'.xdc'}),
        ('tests/power', {'.py', '.cpp', '.sv', '.txt'}),
    ):
        files += [p for p in (root / folder).iterdir()
                  if p.is_file() and p.suffix in suffixes and p.name not in GENERATED]
    files += [root / p for p in ('vitis_projects/ADMM/Makefile',
                                 'experiments/power/synthetic_states.csv',
                                 'paper_figures/data/benchmark_summary.csv')]
    for name in ('POWER_MEASUREMENT_HANDOFF.md', 'POWER_MEASUREMENT_PLAN.md', 'POWER_CAMPAIGN.md'):
        if (root / name).exists():
            files.append(root / name)
    for p in files:
        if p.is_symlink():
            raise ValueError(f'Symlinks are not allowed in source snapshot: {p}')
    return sorted(set(files))


def prepare(args):
    campaign = args.campaign.resolve()
    if campaign.exists():
        raise ValueError('Prepare requires a new campaign directory')
    files = source_files(ROOT)
    hashes = {str(p.relative_to(ROOT)): sha(p) for p in files}
    payload = {'schema': 1, 'source_hashes': hashes,
               'points': matrix(ROOT / 'paper_figures/data/benchmark_summary.csv'),
               'correction': MODEL, 'clock_hz': 100_000_000, 'trajectory': False,
               'workload_records': 256, 'repetitions': 3, 'settle_s': 5,
               'idle_s': 3, 'target_active_s': 2, 'minimum_solves': 1024,
               'smoke_ids': list(SMOKE), 'parameter_policy': 'frozen source defaults; sanitized environment'}
    payload['campaign_id'] = digest(payload)
    temp = campaign.with_name(campaign.name + '.preparing-' + uuid.uuid4().hex[:8])
    (temp / 'source').mkdir(parents=True)
    for p in files:
        dest = temp / 'source' / p.relative_to(ROOT)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(p, dest)
    save(temp / 'campaign.json', payload)
    os.replace(temp, campaign)
    print(f'Prepared {len(payload["points"])} points at {campaign}\nCampaign: {payload["campaign_id"]}')


def campaign_data(campaign, allow_runner_changes=False):
    m = read(campaign / 'campaign.json')
    body = {k: v for k, v in m.items() if k != 'campaign_id'}
    if digest(body) != m['campaign_id']:
        raise ValueError('Campaign manifest was modified')
    for name, expected in m['source_hashes'].items():
        if sha(campaign / 'source' / name) != expected:
            if allow_runner_changes and name == 'scripts/power_campaign.py':
                print('Using user-modified campaign runner; FPGA and acquisition sources remain verified.', flush=True)
                continue
            raise ValueError(f'Source snapshot changed: {name}')
    return m


def resources(campaign, threads=8, requested=None, memory_gib=32, scratch_gib=40):
    cpus = len(os.sched_getaffinity(0))
    # Honor a cgroup CPU quota where one is applied.
    quota = Path('/sys/fs/cgroup/cpu.max')
    if quota.exists():
        q, period = quota.read_text().split()
        if q != 'max':
            cpus = min(cpus, max(1, int(q)//int(period)))
    mem = dict(re.findall(r'^(\w+):\s+(\d+)', Path('/proc/meminfo').read_text(), re.M))
    available = int(mem['MemAvailable']) * 1024
    limit, used = Path('/sys/fs/cgroup/memory.max'), Path('/sys/fs/cgroup/memory.current')
    if limit.exists() and limit.read_text().strip() != 'max':
        available = min(available, int(limit.read_text()) - int(used.read_text()))
    disk = shutil.disk_usage(campaign).free
    capacity = min(max(0, (cpus-4)//threads), max(0, int((available-16*GIB)//(memory_gib*GIB))),
                   max(0, int((disk-40*GIB)//(scratch_gib*GIB))))
    jobs = min(8, capacity) if requested is None else requested
    if jobs < 1 or jobs > capacity:
        raise ValueError(f'Insufficient reserved resources for {jobs} workers; capacity={capacity}')
    return {'cpus': cpus, 'available_memory_gib': available/GIB, 'free_disk_gib': disk/GIB,
            'jobs': jobs, 'threads_per_build': threads, 'memory_gib_per_worker': memory_gib,
            'scratch_gib_per_worker': scratch_gib}


def preflight(args):
    m = campaign_data(args.campaign)
    versions = {}
    for exe, flag in (('vivado', '-version'), ('v++', '--version'), ('vitis-run', '--version'), ('g++', '--version')):
        if not shutil.which(exe):
            raise ValueError(f'Missing {exe}; source the server toolchain settings first')
        result = subprocess.run([exe, flag], text=True, capture_output=True, timeout=90, check=True)
        versions[exe] = (result.stdout + result.stderr)[:4000]
        if exe != 'g++' and '2025.2' not in versions[exe]:
            raise ValueError(f'{exe} is not the validated 2025.2 toolchain')
    for module in ('numpy', 'scipy', 'sksparse.cholmod', 'autograd', 'matplotlib'):
        importlib.import_module(module)
    includes = Path(os.environ.get('XILINX_HLS', '')) / 'include/ap_int.h'
    if not includes.is_file():
        raise ValueError('XILINX_HLS/include/ap_int.h missing; source Vitis settings')
    result = {'campaign_id': m['campaign_id'], 'python': sys.executable,
              'resources': resources(args.campaign, args.threads, args.jobs, args.memory_gib, args.scratch_gib), 'versions': versions,
              'time': time.time(), 'host': os.uname().nodename}
    save(args.campaign / 'preflight.json', result)
    print(json.dumps(result, indent=2))
    return result


def select(m, ids=None, smoke=False):
    wanted = set(SMOKE if smoke else ids.split(',') if ids else [p['id'] for p in m['points']])
    selected = [p for p in m['points'] if p['id'] in wanted]
    if wanted != {p['id'] for p in selected}:
        raise ValueError(f'Unknown point IDs: {wanted - {p["id"] for p in selected}}')
    return selected


def verify_bundle(bundle, campaign_id, point_id):
    info = read(bundle / 'artifact.json')
    if info['campaign_id'] != campaign_id or info['point']['id'] != point_id:
        raise ValueError('Artifact belongs to another campaign/point')
    required = {'top_uart_power.bit', 'top_uart_power.json', 'pilot_reference.json',
                'reports/post_route_timing.rpt', 'reports/post_route_utilization.rpt',
                'reports/post_route_hierarchical_utilization.rpt', 'toolchain.json'}
    if not required <= info['files'].keys():
        raise ValueError('Artifact is missing required files')
    for name, expected in info['files'].items():
        p = Path(name)
        if p.is_absolute() or '..' in p.parts or sha(bundle / p) != expected:
            raise ValueError(f'Artifact hash mismatch: {name}')
    if info['status'] != 'ready' or not info['timing_clean']:
        raise ValueError('Artifact is not validated for programming')
    manifest = read(bundle / 'top_uart_power.json')
    if manifest['bitstream_sha256'] != sha(bundle / 'top_uart_power.bit') or manifest.get('trajectory_compiled') is not False:
        raise ValueError('Invalid bitstream provenance or trajectory configuration')
    return info


def run(cmd, cwd, env, log):
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open('w') as f:
        f.write(json.dumps(cmd) + '\n'); f.flush()
        subprocess.run(cmd, cwd=cwd, env=env, stdout=f, stderr=subprocess.STDOUT, check=True)


def timing_values(path):
    text = path.read_text()
    match = re.search(r'\n\s*(-?[\d.]+)\s+(-?[\d.]+)\s+(\d+)\s+(\d+)\s+(-?[\d.]+)\s+(-?[\d.]+)\s+(\d+)\s+(\d+)\s+(-?[\d.]+)\s+(-?[\d.]+)\s+(\d+)\s+(\d+)', text)
    if not match or 'All user specified timing constraints are met.' not in text:
        raise ValueError('Routed timing is not clean')
    v = match.groups()
    if any(float(v[i]) < 0 for i in (0, 4, 8)) or any(int(v[i]) for i in (2, 6, 10)):
        raise ValueError('Routed timing has failing endpoints')
    return {'setup_slack_ns': float(v[0]), 'hold_slack_ns': float(v[4]), 'pulse_slack_ns': float(v[8])}


def golden(work, env, log):
    hls = work / 'vitis_projects/ADMM'
    exe = work / 'build/pilot_reference'
    run(['g++', '-std=c++14', '-O1', '-Wno-unknown-pragmas', '-I'+env['XILINX_HLS']+'/include',
         '-I'+str(hls), str(work/'tests/power/solver_reference.cpp'), str(hls/'ADMM.cpp'), '-o', str(exe)], work, env, log)
    output = subprocess.check_output([str(exe), str(work/'build/power/power_workload.mem'), '8'], cwd=work, env=env, text=True)
    lines = output.splitlines()
    if len(lines) != 8 or any(not re.fullmatch('[0-9a-fA-F]{32}', v) for v in lines):
        raise ValueError('Invalid C++ pilot outputs')
    checksum = 0
    for line in lines:
        number = int(line, 16)
        words = [(number >> (32*i)) & 0xffffffff for i in range(4)]
        checksum = ((checksum << 1) | (checksum >> 31)) & 0xffffffff
        for word in words:
            checksum ^= word
    return {'solves': 8, 'outputs_hex': lines, 'checksum': checksum, 'last_output_words': words}


def classify(stage, log):
    text = log.read_text(errors='replace') if log.exists() else ''
    if re.search(r'over.utiliz|exceed.*available|more.*than.*available|not enough.*(RAM|sites)|too many.*(RAM|LUT)', text, re.I):
        return 'capacity'
    return stage


def build_point(campaign, m, point, threads, retry_failed):
    pid = point['id']
    ready = campaign / 'ready' / pid
    state = campaign / 'state' / (pid+'.json')
    with locked(campaign / 'locks' / (pid+'.lock')):
        if ready.exists():
            verify_bundle(ready, m['campaign_id'], pid)
            print(f'{pid}: verified ready (resume)', flush=True)
            return True
        if state.exists() and read(state).get('status') == 'failed' and not retry_failed:
            print(f'{pid}: previous failure retained; use --retry-failed', flush=True)
            return False
        from run_max_horizon_parallel import IMPL_VARIANTS
        variants = {v['name']: v for v in IMPL_VARIANTS}
        names = [point['variant']]
        if names[0] not in variants:
            raise ValueError(f'Unknown historical implementation variant: {names[0]}')
        if names[0] != 'route_aggressive':
            names.append('route_aggressive')
        for index, name in enumerate(names):
            attempt = campaign / 'work' / pid / (name+'-'+uuid.uuid4().hex[:8])
            work = attempt / 'repo'
            shutil.copytree(campaign / 'source', work)
            logs = attempt / 'logs'
            env = clean_environment()
            env.update(ADMM_SOLVER_ARCH=point['arch'], ADMM_HORIZON_LENGTH=str(point['horizon']),
                       ADMM_ITERATIONS='10', ADMM_ENABLE_TRAJECTORY='0', ADMM_USE_FLOAT='0',
                       VIVADO_MAX_THREADS=str(threads))
            variant = variants[name]
            for k, suffix in (('opt','OPT_DIRECTIVE'), ('place','PLACE_DIRECTIVE'), ('phys','PHYS_OPT_DIRECTIVE'),
                              ('route','ROUTE_DIRECTIVE'), ('place_subdirective','PLACE_SUBDIRECTIVE'),
                              ('route_tns_cleanup','ROUTE_TNS_CLEANUP'), ('route_ultrathreads','ROUTE_ULTRATHREADS')):
                if k in variant:
                    env['VIVADO_'+suffix] = variant[k]
            stage, log = 'generation', logs/'generation.log'
            try:
                for stage, target in (('generation','headers'), ('hls','hls'), ('implementation','vivado')):
                    log = logs/(stage+'.log')
                    save(state, {'status':'building', 'stage':stage, 'point':point, 'variant':name,
                                 'attempt':str(attempt), 'campaign_id':m['campaign_id'], 'time':time.time()})
                    print(f'{pid}: {name} {stage}', flush=True)
                    run(['make','BOARD=arty-power',f'PYTHON={sys.executable}',target], work, env, log)
                stage = 'timing'
                timing = timing_values(work/'build/reports/post_route_timing.rpt')
                stage, log = 'packaging', logs/'packaging.log'
                run(['make','BOARD=arty-power',f'PYTHON={sys.executable}','bit'], work, env, log)
                manifest = read(work/'build/top_uart_power.json')
                constants = manifest['solver_constants']
                if (int(constants['HORIZON_LENGTH']) != point['horizon'] or manifest['trajectory_compiled']
                    or '#define ADMM_ITERATIONS 10' not in manifest['runtime_config']
                    or f'#define ADMM_SOLVER_ARCH_NAME "{point["arch"]}"' not in manifest['runtime_config']):
                    raise ValueError('Generated configuration mismatch')
                stage, log = 'reference', logs/'reference.log'
                expected = golden(work, env, log)
                temp = campaign/'ready'/('.'+pid+'-'+uuid.uuid4().hex)
                temp.mkdir(parents=True)
                for filename in ('top_uart_power.bit', 'top_uart_power.json'):
                    shutil.copy2(work/'build'/filename, temp/filename)
                shutil.copytree(work/'build/reports', temp/'reports')
                shutil.copytree(logs, temp/'logs')
                save(temp/'pilot_reference.json', expected)
                shutil.copy2(campaign/'preflight.json', temp/'toolchain.json')
                from run_max_horizon_point import parse_utilization
                util = parse_utilization((temp/'reports/post_route_utilization.rpt').read_text(), 'route')
                info = {'status':'ready', 'campaign_id':m['campaign_id'], 'point':point, 'variant':name,
                        'timing_clean':True, 'timing':timing, 'resources':util, 'created':time.time(),
                        'files':{str(p.relative_to(temp)):sha(p) for p in temp.rglob('*') if p.is_file()}}
                save(temp/'artifact.json', info)
                verify_bundle(temp, m['campaign_id'], pid)
                os.replace(temp, ready)
                save(state, {'status':'ready', 'campaign_id':m['campaign_id'], 'point':point, 'variant':name})
                print(f'{pid}: ready', flush=True)
                return True
            except Exception as exc:
                failure = classify(stage, log)
                timing_report = work/'build/reports/post_route_timing.rpt'
                if stage == 'implementation' and timing_report.exists() and 'constraints are not met' in timing_report.read_text():
                    failure = 'timing'
                save(state, {'status':'failed', 'stage':failure, 'error':str(exc), 'point':point,
                             'variant':name, 'attempt':str(attempt), 'campaign_id':m['campaign_id']})
                print(f'{pid}: failed {failure}: {exc}', flush=True)
                if failure != 'timing' or index+1 == len(names):
                    return False
        return False


def build(args):
    m = campaign_data(args.campaign)
    with locked(args.campaign/'locks/build.lock'):
        pf = preflight(args)
        points = select(m, args.ids, args.smoke)
        with ThreadPoolExecutor(max_workers=pf['resources']['jobs']) as pool:
            futures = {pool.submit(build_point,args.campaign,m,p,args.threads,args.retry_failed):p for p in points}
            for future in as_completed(futures):
                try:
                    future.result()
                except Exception as exc:
                    p = futures[future]
                    save(args.campaign/'state'/(p['id']+'.json'), {'status':'failed', 'stage':'runner',
                         'error':str(exc), 'point':p, 'campaign_id':m['campaign_id']})
                    print(f'{p["id"]}: runner failure: {exc}', flush=True)


def corrected(core_energy, duration, count):
    if duration <= 0 or count <= 0:
        raise ValueError('Positive duration and completed count required')
    energy = MODEL['retained_fraction']*(core_energy+MODEL['auxiliary_w']*duration)
    return energy/duration, energy/count


def solve_count(latency_cycles, clock_hz=100_000_000):
    if latency_cycles <= 0:
        raise ValueError('Invalid pilot latency')
    n = 256*math.ceil(max(1024,2*clock_hz/latency_cycles)/256)
    if n*latency_cycles/clock_hz+11 >= 590 or latency_cycles/clock_hz >= 10:
        raise ValueError('Experiment exceeds hardware watchdog budget')
    return n


def validate_run(folder, info, expected_count, expected=None):
    meta = read(folder/'metadata.json')
    st, summary = meta['status'], meta['summary']
    if meta['bitstream_sha256'] != info['files']['top_uart_power.bit']:
        raise ValueError('Measured bitstream hash mismatch')
    if not summary['valid'] or st['flags'] or st['overruns'] or st['completed'] != expected_count:
        raise ValueError('Invalid completion/status')
    if st['latency_min'] <= 0 or st['latency_min'] != st['latency_max']:
        raise ValueError('Unexpected variable solve latency')
    if expected and (st['checksum'] != expected['checksum'] or st['last_output_words'] != expected['last_output_words']):
        raise ValueError('Numerical pilot does not match C++')
    with (folder/'trace.csv').open(newline='') as f:
        rows = list(csv.DictReader(f))
    groups = {p:[] for p in (1,2,3)}
    for r in rows:
        p = int(r['phase'])
        if p not in groups or int(r['samples']) <= 0 or int(r['flags']):
            raise ValueError('Invalid trace samples/flags/phase')
        groups[p].append(r)
    durations = (meta['config_cycles'][3], st['active_cycles'], meta['config_cycles'][4])
    previous_end = None
    for phase, duration in zip((1,2,3),durations):
        if len(groups[phase]) != st['counts'][phase-1] or not groups[phase]:
            raise ValueError('Missing trace records')
        total = 0
        for r in groups[phase]:
            start = round(float(r['start_s'])*meta['clock_hz'])
            ticks = round(float(r['duration_s'])*meta['clock_hz'])
            if ticks <= 0 or (previous_end is not None and start != previous_end):
                raise ValueError('Trace gap/overlap')
            previous_end = start+ticks
            total += ticks
        if total != duration:
            raise ValueError('Incomplete phase coverage')
    return meta


def measure(args):
    m = campaign_data(args.campaign, allow_runner_changes=True)
    save(args.local/'provenance'/m['campaign_id']/'runner.json', {
        'frozen_sha256': m['source_hashes']['scripts/power_campaign.py'],
        'server_sha256': sha(args.campaign/'source/scripts/power_campaign.py'),
        'local_sha256': sha(Path(__file__)),
        'note': 'User authorized changes to server runner resource/integrity checks; FPGA and acquisition source hashes verified.'})
    # Use the frozen host tools locally; future edits in the working repository
    # must not silently change the acquisition protocol or interpretation.
    host = args.local/'host'/m['campaign_id']
    for name in ('scripts/power_benchmark.py', 'scripts/program_file.tcl'):
        dest = host/name
        if not dest.exists():
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(args.campaign/'source'/name, dest)
        if sha(dest) != m['source_hashes'][name]:
            raise ValueError(f'Cached acquisition tool changed: {name}')
    args.local.mkdir(parents=True, exist_ok=True)
    with locked(args.local/'measurement.lock'), locked(Path('/tmp')/('admm-power-'+Path(args.port).name+'.lock')):
        processed = set()
        while True:
            waiting = []
            for point in select(m,args.ids,args.smoke):
                pid = point['id']
                if pid in processed:
                    continue
                remote = args.campaign/'ready'/pid
                if not remote.exists():
                    state = args.campaign/'state'/(pid+'.json')
                    if not state.exists() or read(state).get('status') != 'failed':
                        waiting.append(pid)
                    continue
                processed.add(pid)
                cache = args.local/'cache'/m['campaign_id']/pid
                if not cache.exists():
                    cache.parent.mkdir(parents=True,exist_ok=True)
                    temp = cache.with_name('.'+pid+'-'+uuid.uuid4().hex)
                    shutil.copytree(remote,temp)
                    verify_bundle(temp,m['campaign_id'],pid)
                    os.replace(temp,cache)
                info = verify_bundle(cache,m['campaign_id'],pid)
                reference = read(cache/'pilot_reference.json')
                base = args.local/'measurements'/m['campaign_id']/pid
                base.mkdir(parents=True,exist_ok=True)
                expected_checksum = None
                pilot = None
                try:
                    for label in ('pilot','repeat1','repeat2','repeat3'):
                        count = 8 if label=='pilot' else solve_count(pilot['status']['latency_max'])
                        valid = None
                        for attempt in (1,2):
                            folder = base/f'{label}-attempt{attempt}'
                            decision = base/f'{label}-attempt{attempt}.json'
                            if decision.exists():
                                if read(decision)['valid']:
                                    valid = validate_run(folder,info,count,reference if label=='pilot' else None)
                                    break
                                continue
                            try:
                                if not folder.exists():
                                    log = base/f'{label}-attempt{attempt}.log'
                                    cmd=[sys.executable,str(host/'scripts/power_benchmark.py'), '--port',args.port,
                                         '--bitstream',str(cache/'top_uart_power.bit'), '--manifest',str(cache/'top_uart_power.json'),
                                         '--solves',str(count),'--settle-s','5','--idle-before-s','3','--idle-after-s','3',
                                         '--output',str(folder),'--no-plot']
                                    run(cmd,args.local,clean_environment(),log)
                                valid = validate_run(folder,info,count,reference if label=='pilot' else None)
                                if pilot and valid['status']['latency_max'] != pilot['status']['latency_max']:
                                    raise ValueError('Pilot/repetition latency mismatch')
                                if label!='pilot' and expected_checksum is not None and valid['status']['checksum'] != expected_checksum:
                                    raise ValueError('Repeated-run checksum mismatch')
                                save(decision,{'valid':True, 'campaign_id':m['campaign_id'],'point_id':pid})
                                break
                            except Exception as exc:
                                valid = None
                                save(decision,{'valid':False,'error':str(exc),'campaign_id':m['campaign_id'],'point_id':pid})
                                connection_error = transport_failure(base/f'{label}-attempt{attempt}.log')
                                if connection_error:
                                    raise AcquisitionTransportError(connection_error) from exc
                        if valid is None:
                            raise ValueError(f'{label}: both acquisition attempts invalid')
                        if label=='pilot':
                            pilot=valid
                        else:
                            if expected_checksum is not None and valid['status']['checksum']!=expected_checksum:
                                raise ValueError('Repeated-run checksum mismatch')
                            expected_checksum=valid['status']['checksum']
                        print(f'{pid}: {label} valid ({count} solves)',flush=True)
                    save(base/'complete.json',{'valid':True,'campaign_id':m['campaign_id'],'point_id':pid})
                except Exception as exc:
                    save(base/'complete.json',{'valid':False,'campaign_id':m['campaign_id'],'point_id':pid,'error':str(exc)})
                    print(f'{pid}: measurement failed: {exc}',flush=True)
                    if isinstance(exc, AcquisitionTransportError):
                        save(args.local/'connection_failure.json', {
                            'campaign_id':m['campaign_id'],'point_id':pid,
                            'error':str(exc),'time':time.time()})
                        raise
            if not args.watch or not waiting:
                break
            print(f'Waiting for {len(waiting)} build artifacts; checking again in {args.poll_seconds:g}s.',flush=True)
            time.sleep(args.poll_seconds)


def aggregate(args):
    m=campaign_data(args.campaign, allow_runner_changes=True)
    rows=[]
    for p in m['points']:
        pid=p['id']
        row={k:p[k] for k in ('id','arch','horizon','iterations')}
        state=args.campaign/'state'/(pid+'.json')
        row.update(campaign_id=m['campaign_id'],status=read(state)['status'] if state.exists() else 'pending',
                   correction_model=MODEL['id'])
        if state.exists():
            row['failed_stage']=read(state).get('stage','')
        bundle=args.campaign/'ready'/pid
        if bundle.exists():
            cache=args.local/'cache'/m['campaign_id']/pid
            if not cache.exists():
                # Publication says a build is available, but do not turn that
                # into a measurement claim or download every report for a status row.
                row.update(status='ready', valid_repetitions=0)
                rows.append(row)
                continue
            bundle=cache
            info=verify_bundle(bundle,m['campaign_id'],pid)
            row.update(bitstream_sha256=info['files']['top_uart_power.bit'],variant=info['variant'],**info['resources'])
            base=args.local/'measurements'/m['campaign_id']/pid
            runs=[]
            for label in ('repeat1','repeat2','repeat3'):
                for attempt in (1,2):
                    decision=base/f'{label}-attempt{attempt}.json'
                    if decision.exists() and read(decision).get('valid'):
                        pilot_decisions=[base/f'pilot-attempt{i}.json' for i in (1,2)]
                        pilot_path=next((x for x in pilot_decisions if x.exists() and read(x).get('valid')),None)
                        if pilot_path is None:
                            raise ValueError('Missing validated pilot')
                        pilot=validate_run(pilot_path.with_suffix(''),info,8,read(bundle/'pilot_reference.json'))
                        count=solve_count(pilot['status']['latency_max'])
                        r=validate_run(decision.with_suffix(''),info,count)
                        if r['status']['latency_max'] != pilot['status']['latency_max']:
                            raise ValueError('Pilot/repetition latency mismatch')
                        rail=r['summary']['rails']['core']
                        power,energy=corrected(rail['active']['energy_j'],rail['active']['duration_s'],count)
                        runs.append({'raw_core_w':rail['active']['power_w'], 'corrected_power_w':power,
                                     'raw_core_energy_uj':rail['energy_per_solve_j']*1e6,
                                     'corrected_energy_uj':energy*1e6,
                                     'incremental_core_energy_uj':rail['incremental_energy_per_solve_j']*1e6,
                                     'five_w':r['summary']['rails']['five']['active']['power_w'],
                                     'latency_us':r['status']['latency_total']/count/r['clock_hz']*1e6,
                                     'temperature_drift_c':r['summary']['temperature_change_c'],
                                     'checksum':r['status']['checksum']})
                        break
            row['valid_repetitions']=len(runs)
            complete=base/'complete.json'
            if complete.exists() and not read(complete).get('valid'):
                row['status']='measurement_failed'
            elif len(runs)==3 and len({r['checksum'] for r in runs})==1:
                row['status']='measured'
            else:
                row['status']='measurement_incomplete'
            if runs:
                for key in runs[0]:
                    if key=='checksum': continue
                    vals=[r[key] for r in runs]
                    row.update({key+'_mean':statistics.mean(vals), key+'_std':statistics.stdev(vals) if len(vals)>1 else 0,
                                key+'_min':min(vals),key+'_max':max(vals)})
        rows.append(row)
    output=args.local/'summaries'/m['campaign_id']
    save(output/'summary.json',{'campaign_id':m['campaign_id'],'correction':MODEL,'points':rows,
                              'note':'Spread measures repeatability, not uncertainty in the correction assumptions.'})
    keys=sorted({k for r in rows for k in r})
    tmp=output/'summary.csv.tmp'
    with tmp.open('w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=keys);w.writeheader();w.writerows(rows)
    os.replace(tmp,output/'summary.csv')
    smoke={r['id']:r for r in rows if r['id'] in SMOKE}
    if len(smoke)==2 and all(r['status']=='measured' for r in smoke.values()):
        save(args.campaign/'smoke_acceptance.json',{'campaign_id':m['campaign_id'],'passed':True,
             'points':{k:v['bitstream_sha256'] for k,v in smoke.items()},'time':time.time()})
    print(f'Summary: {output}')


def status(args):
    m=campaign_data(args.campaign)
    for p in m['points']:
        f=args.campaign/'state'/(p['id']+'.json')
        s=read(f) if f.exists() else {'status':'pending'}
        print(p['id'],s['status'],s.get('stage',''),s.get('error',''))


def main():
    p=argparse.ArgumentParser(description=__doc__)
    sub=p.add_subparsers(dest='command',required=True)
    for cmd in ('prepare','preflight','build','status','measure','aggregate'):
        s=sub.add_parser(cmd)
        s.add_argument('--campaign',type=Path,required=True)
        if cmd in ('preflight','build'):
            s.add_argument('--threads',type=int,default=8)
            s.add_argument('--jobs',type=int)
            s.add_argument('--memory-gib',type=float,default=32,help='Planning RAM budget per worker (not a hard limit)')
            s.add_argument('--scratch-gib',type=float,default=40,help='Planning disk budget per worker')
        if cmd in ('build','measure'):
            s.add_argument('--ids',help='Comma-separated configuration IDs')
            s.add_argument('--smoke',action='store_true')
        if cmd=='build': s.add_argument('--retry-failed',action='store_true')
        if cmd in ('measure','aggregate'):
            s.add_argument('--local',type=Path,default=ROOT/'results/power-campaign')
        if cmd=='measure':
            s.add_argument('--port',default='/dev/ttyUSB1')
            s.add_argument('--watch',action='store_true',help='Wait for and measure newly published artifacts')
            s.add_argument('--poll-seconds',type=float,default=30)
    args=p.parse_args()
    args.campaign=args.campaign.resolve()
    if hasattr(args,'local'): args.local=args.local.resolve()
    if hasattr(args,'threads') and args.threads<1: p.error('threads must be positive')
    for name in ('memory_gib', 'scratch_gib', 'poll_seconds'):
        if hasattr(args,name) and getattr(args,name)<=0: p.error(name+' must be positive')
    if getattr(args,'smoke',False) and getattr(args,'ids',None): p.error('Use --smoke or --ids, not both')
    globals()[args.command](args)


if __name__=='__main__':
    main()
