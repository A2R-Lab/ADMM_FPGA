#!/usr/bin/env python3
"""Run the Arty power experiment; UART is silent between START and completion."""
import argparse
import binascii
import csv
import hashlib
import json
from pathlib import Path
import struct
import subprocess
import time

ROOT = Path(__file__).resolve().parents[1]
CLK = 100_000_000

def frame(opcode, payload=b''):
    body = struct.pack('<BBH', 1, opcode, len(payload)) + payload
    return b'\xa5\x5a' + body + struct.pack('<H', binascii.crc_hqx(body, 0xffff))

def read_exact(port, count):
    data = bytearray()
    while len(data) < count:
        part = port.read(count - len(data))
        if not part:
            raise TimeoutError(f'UART timeout: received {len(data)}/{count} bytes')
        data.extend(part)
    return bytes(data)

def receive(port, expected):
    if read_exact(port, 2) != b'\xa5\x5a':
        raise ValueError('UART framing error')
    header = read_exact(port, 4)
    version, opcode, length = struct.unpack('<BBH', header)
    if version != 1 or opcode != expected or length > 256:
        raise ValueError(f'Unexpected frame: version={version}, opcode={opcode}, length={length}')
    payload = read_exact(port, length)
    crc, = struct.unpack('<H', read_exact(port, 2))
    if crc != binascii.crc_hqx(header + payload, 0xffff):
        raise ValueError('UART CRC mismatch')
    return payload

def transact(port, op, payload=b''):
    port.write(frame(op, payload))
    port.flush()
    result = receive(port, op | 0x80)
    if len(result) == 4 and int.from_bytes(result, 'little') != 0:
        raise ValueError(f'FPGA rejected command {op}')
    return result

def decode_record(data):
    if len(data) != 64:
        raise ValueError('Trace record must be 64 bytes')
    raw = int.from_bytes(data, 'little')
    def field(offset, width):
        return (raw >> offset) & ((1 << width) - 1)
    n = field(96, 32)
    result = dict(start_s=field(0, 64)/CLK, duration_s=field(64, 32)/CLK,
                  samples=n, phase=field(464, 8), flags=field(456, 8))
    # Empty bins remain in the trace, with null measurements (never fake zero watts).
    for name, offset, factor in [('core_w',128,6/4096**2), ('five_w',192,23.96/4096**2),
                                ('core_v',256,3/4096), ('core_a',296,2/4096),
                                ('five_v',336,5.99/4096), ('five_a',376,4/4096),
                                ('temperature_c',416,503.975/4096)]:
        width = 64 if offset < 256 else 40
        value = field(offset, width)*factor/n if n else None
        if name == 'temperature_c' and value is not None:
            value -= 273.15
        result[name] = value
    result['raw_hex'] = data.hex()
    return result

def decode_status(data):
    if len(data) != 104:
        raise ValueError('Unexpected status length')
    a=struct.unpack('<8I3Q2I4IQ4I', data)
    return dict(state=a[0], flags=a[1], completed=a[2], overruns=a[3],
                counts=list(a[4:7]), checksum=a[7], busy_cycles=a[8], latency_total=a[9],
                active_cycles=a[10], latency_min=a[11], latency_max=a[12],
                last_output_words=list(a[13:17]), elapsed_cycles=a[17], latest_adc=list(a[18:22]))

def summarize(records, status):
    summary = {'valid': status['flags']==0 and all(r['samples'] and not r['flags'] for r in records),
               'completed_solves':status['completed'], 'deadline_overruns':status['overruns'], 'rails':{}}
    for rail in ('core','five'):
        groups = {p:[r for r in records if r['phase']==p] for p in (1,2,3)}
        stats={}
        for p, rows in groups.items():
            duration=sum(r['duration_s'] for r in rows)
            valid_rows=[r for r in rows if r[rail+'_w'] is not None]
            covered=sum(r['duration_s'] for r in valid_rows)
            energy=sum(r[rail+'_w']*r['duration_s'] for r in valid_rows)
            stats[p]=dict(duration_s=duration, covered_s=covered,
                          energy_j=energy if covered==duration and duration else None,
                          power_w=energy/covered if covered else None,
                          midpoint_s=(sum((r['start_s']+r['duration_s']/2)*r['duration_s'] for r in rows)/duration if duration else None))
        before, active, after = (stats[p] for p in (1,2,3))
        inc=None
        if all(s['energy_j'] is not None for s in stats.values()):
            slope=(after['power_w']-before['power_w'])/(after['midpoint_s']-before['midpoint_s'])
            baseline_at_active=before['power_w']+slope*(active['midpoint_s']-before['midpoint_s'])
            inc=active['energy_j']-baseline_at_active*active['duration_s']
        count=status['completed']
        summary['rails'][rail]=dict(idle_before=before, active=active, idle_after=after,
            idle_drift_w=(after['power_w']-before['power_w'] if before['power_w'] is not None and after['power_w'] is not None else None),
            energy_per_solve_j=(active['energy_j']/count if count and active['energy_j'] is not None else None),
            incremental_energy_j=inc, incremental_energy_per_solve_j=(inc/count if inc is not None and count else None))
    if not records or not all(any(r['phase']==p for r in records) for p in (1,2,3)):
        summary['valid']=False
    temps = {p:[r for r in records if r['phase']==p and r['temperature_c'] is not None] for p in (1,3)}
    means = {p:(sum(r['temperature_c']*r['duration_s'] for r in rows)/sum(r['duration_s'] for r in rows) if rows else None) for p,rows in temps.items()}
    summary['temperature_change_c'] = means[3]-means[1] if all(v is not None for v in means.values()) else None
    return summary

def plot_trace(records, output):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    fig, axes=plt.subplots(2,1,sharex=True,figsize=(10,6))
    for ax,rail,title in zip(axes,('core','five'),('FPGA core rail','Monitored 5 V supply')):
        for phase,label in ((1,'Idle before'),(2,'Solves'),(3,'Idle after')):
            rows=[r for r in records if r['phase']==phase and r[rail+'_w'] is not None]
            ax.plot([r['start_s']+r['duration_s']/2 for r in rows], [r[rail+'_w'] for r in rows],label=label)
        ax.set_ylabel('Power (W)'); ax.set_title(title); ax.grid(alpha=.3); ax.legend()
    axes[-1].set_xlabel('FPGA time (s)'); fig.tight_layout(); fig.savefig(output); plt.close(fig)

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--port',default='/dev/ttyUSB1')
    p.add_argument('--bitstream',type=Path,default=ROOT/'build/top_uart_power.bit')
    p.add_argument('--manifest',type=Path,help='Default: JSON sidecar alongside the selected bitstream')
    p.add_argument('--already-programmed',action='store_true',help='Skip JTAG; board must have been freshly programmed')
    p.add_argument('--solves',type=int,default=1000)
    p.add_argument('--period-ms',type=float,default=0)
    p.add_argument('--settle-s',type=float,default=2)
    p.add_argument('--idle-before-s',type=float,default=3)
    p.add_argument('--idle-after-s',type=float,default=3)
    p.add_argument('--watchdog-s',type=float,default=10)
    p.add_argument('--output',type=Path,default=ROOT/'results'/time.strftime('power-%Y%m%d-%H%M%S'))
    p.add_argument('--no-plot',action='store_true')
    args=p.parse_args()
    settings=[args.solves, round(args.period_ms*CLK/1000), round(args.settle_s*CLK),
              round(args.idle_before_s*CLK),round(args.idle_after_s*CLK),round(args.watchdog_s*CLK)]
    if not 1<=settings[0]<=0xffffffff or not 0<=settings[1]<=0xffffffff or not 0<=settings[2]<=3_000_000_000 or not all(1<=v<=3_000_000_000 for v in settings[3:5]) or not 1<=settings[5]<=1_000_000_000:
        p.error('Invalid counts/durations: idle <=30s, settle <=30s, watchdog <=10s; positive solves/idle/watchdog')
    if args.period_ms and args.solves*args.period_ms/1000+args.settle_s+args.idle_before_s+args.idle_after_s>=600:
        p.error('Scheduled experiment must fit within the 600-second hardware watchdog')
    manifest=json.loads((args.manifest or args.bitstream.with_suffix('.json')).read_text())
    bit_hash=hashlib.sha256(args.bitstream.read_bytes()).hexdigest()
    if manifest.get('bitstream_sha256') != bit_hash:
        raise ValueError('Build manifest does not match the selected bitstream')
    if not args.already_programmed:
        subprocess.run(['vivado','-mode','batch','-source',str(ROOT/'scripts/program_file.tcl'),
                        '-tclargs',str(args.bitstream.resolve())],cwd=ROOT,check=True)
    import serial
    args.output.mkdir(parents=True,exist_ok=False)
    metadata=dict(board='Arty A7-100T Rev E', power_source='USB', bitstream=str(args.bitstream.resolve()),
                  bitstream_sha256=bit_hash, workload=manifest, config_cycles=settings,
                  calibration='nominal board scaling; no external calibration', clock_hz=CLK)
    (args.output/'metadata.json').write_text(json.dumps(metadata,indent=2)+'\n')
    with serial.Serial(args.port,921600,timeout=5) as port:
        time.sleep(.2); port.reset_input_buffer()
        caps=transact(port,1)
        if len(caps)!=48:
            raise ValueError('Invalid capabilities response')
        clk,count,use_float,record_bytes=struct.unpack('<4I',caps[:16])
        digest=f'{int.from_bytes(caps[16:],"little"):064x}'
        if (clk,count,use_float,record_bytes,digest)!=(CLK,manifest['record_count'],int(manifest['use_float']),64,manifest['workload_sha256']):
            raise ValueError('FPGA capabilities do not match the selected workload manifest')
        status=decode_status(transact(port,4))
        if status['state'] & 1 or not status['state'] & 4 or status['state'] & 8:
            raise ValueError('Reprogram the board; XADC must be ready and experiment unused')
        transact(port,2,struct.pack('<6I',*settings))
        transact(port,3)
        print('Acquiring; UART will remain silent until FPGA completion.',flush=True)
        port.timeout=610
        completion=receive(port,0x86)
        if len(completion)!=4: raise ValueError('Malformed completion notification')
        port.timeout=5
        status=decode_status(transact(port,4))
        if not status['state'] & 2: raise ValueError('FPGA capture is not complete')
        records=[]
        for base,count in zip((0,512,1536),status['counts']):
            for index in range(base,base+count):
                records.append(decode_record(transact(port,5,struct.pack('<I',index))))
    metadata['status']=status
    metadata['summary']=summarize(records,status)
    metadata['summary']['valid'] &= status['completed']==args.solves
    (args.output/'metadata.json').write_text(json.dumps(metadata,indent=2)+'\n')
    with (args.output/'trace.csv').open('w',newline='') as f:
        if records:
            writer=csv.DictWriter(f,fieldnames=list(records[0]));writer.writeheader();writer.writerows(records)
    if not args.no_plot: plot_trace(records,args.output/'power.png')
    print(json.dumps(metadata['summary'],indent=2))
    print(f'Results: {args.output}')
    if not metadata['summary']['valid']: raise SystemExit('Capture marked invalid; retained data for diagnosis')

if __name__=='__main__':
    main()
