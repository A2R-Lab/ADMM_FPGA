import csv
import importlib.util
import io
import json
from pathlib import Path
import struct
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[2]
def load(name):
    spec=importlib.util.spec_from_file_location(name,ROOT/'scripts'/f'{name}.py')
    mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod);return mod
work=load('power_workload');host=load('power_benchmark')

class PowerTests(unittest.TestCase):
    def test_rom_layout_and_validation(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);(p/'config.h').write_text('#define ADMM_USE_FLOAT 0\n')
            (p/'data.csv').write_text(','.join(work.STATE_COLUMNS+['constraints','traj_cmd'])+'\n'+','.join(['-1.25']*12+['0x12345678','3'])+'\n')
            m=work.compile_workload(p/'data.csv',p/'config.h',p/'out')
            v=int((p/'out/power_workload.mem').read_text().splitlines()[0],16)
            self.assertEqual(v&0xffffffff,0xffb00000)
            self.assertEqual((v>>384)&0xffffffff,0x12345678)
            self.assertEqual(v>>416,3)
            self.assertEqual(m['record_count'],1)
            self.assertEqual(len((p/'out/power_workload.mem').read_text().splitlines()),256)
        for x in ('nan','inf',512,-513):
            with self.assertRaises(ValueError):work.encode_state(x,False)
        self.assertEqual(work.encode_state(1.0,True),0x3f800000)
        self.assertEqual(work.encode_state(-0.5/2**22,False),0)

    def test_frames(self):
        packet=host.frame(0x81,b'abc')
        self.assertEqual(host.receive(io.BytesIO(packet),0x81),b'abc')
        bad=bytearray(packet);bad[-1]^=1
        with self.assertRaises(ValueError):host.receive(io.BytesIO(bad),0x81)
        with self.assertRaises(TimeoutError):host.receive(io.BytesIO(packet[:-1]),0x81)

    def test_record_scaling_and_energy(self):
        # Two samples: vcore=1365 (~1V), icore=1024 (.5A), v5=3420 (~5V), i5=512 (.5A).
        n=2;v=100000<<64 | n<<96 | (1365*1024*n)<<128 | (3420*512*n)<<192
        for j,x in enumerate((1365,1024,3420,512,2423)):v|=(x*n)<<(256+j*40)
        v|=2<<464
        r=host.decode_record(v.to_bytes(64,'little'))
        self.assertAlmostEqual(r['core_w'],.4998779296875)
        self.assertAlmostEqual(r['five_w'],2.5007080078125)
        self.assertAlmostEqual(r['temperature_c'],24.97778930664066)
        records=[]
        for phase,start,power in ((1,0,1),(2,1,3),(3,2,1)):
            records.append(dict(r,phase=phase,start_s=start,duration_s=1,core_w=power,five_w=power))
        s=host.summarize(records,dict(flags=0,completed=10,overruns=0))
        self.assertTrue(s['valid']);self.assertAlmostEqual(s['rails']['core']['incremental_energy_per_solve_j'],.2)
        records[1]['samples']=0;records[1]['core_w']=None
        self.assertFalse(host.summarize(records,dict(flags=0,completed=10,overruns=0))['valid'])

if __name__=='__main__':unittest.main()
