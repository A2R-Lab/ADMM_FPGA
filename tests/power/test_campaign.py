"""Campaign acceptance checks; no FPGA tools or hardware required."""
import csv
import json
from pathlib import Path
import sys
import tempfile
import unittest
import subprocess
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'scripts'))
import power_campaign as c


class CampaignTests(unittest.TestCase):
    def test_transport_failure_stops_before_retry_or_next_design(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            m={'campaign_id':'test', 'points':[{'id':'first'}, {'id':'second'}], 'source_hashes':{}}
            for name in ('scripts/power_campaign.py','scripts/power_benchmark.py','scripts/program_file.tcl'):
                p=root/'source'/name; p.parent.mkdir(parents=True,exist_ok=True); p.write_text('test fixture')
                m['source_hashes'][name]=c.sha(p)
            for pid in ('first','second'):
                (root/'ready'/pid).mkdir(parents=True)
                c.save(root/'local/cache/test'/pid/'pilot_reference.json',{})
            args=SimpleNamespace(campaign=root,local=root/'local',port='/dev/admm-unit-test',
                                 ids=None,smoke=False,watch=False)
            def disconnected(cmd,cwd,env,log):
                log.write_text('serial.serialutil.SerialException: [Errno 5] Input/output error\n')
                raise subprocess.CalledProcessError(1,cmd)
            with patch.object(c,'campaign_data',return_value=m), patch.object(c,'verify_bundle',return_value={}), \
                    patch.object(c,'run',side_effect=disconnected) as run:
                with self.assertRaises(c.AcquisitionTransportError): c.measure(args)
                self.assertEqual(run.call_count,1)
            self.assertTrue((root/'local/connection_failure.json').exists())
            self.assertFalse((root/'local/measurements/test/second').exists())

    def test_echoed_tcl_is_not_a_transport_failure(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'log'
            p.write_text('# puts "ERROR: No hardware targets found. Check cable connection."\nProgramming complete!\n')
            self.assertIsNone(c.transport_failure(p))
            p.write_text('ERROR: No hardware targets found. Check cable connection.\n')
            self.assertIsNotNone(c.transport_failure(p))

    def test_matrix_includes_all_timing_clean_points(self):
        points = c.matrix(c.ROOT/'paper_figures/data/benchmark_summary.csv')
        self.assertEqual(len(points), 42)
        self.assertEqual(sum(p['arch']=='full_sparse' for p in points), 10)
        self.assertEqual(max(p['horizon'] for p in points), 1350)
        self.assertEqual({p['iterations'] for p in points}, {10})
        self.assertEqual(len({p['id'] for p in points}), 42)
        self.assertEqual(len(c.select({'points':points}, smoke=True)), 2)

    def test_correction_is_applied_after_auxiliary_addition(self):
        power, energy = c.corrected(.6, 2, 1000)
        self.assertAlmostEqual(power, .2656)
        self.assertAlmostEqual(energy, .0005312)
        with self.assertRaises(ValueError):
            c.corrected(.6, 0, 1000)

    def test_counts_cover_workload_and_active_window(self):
        for latency in (1000, 84041, 10000000):
            count=c.solve_count(latency)
            self.assertEqual(count % 256, 0)
            self.assertGreaterEqual(count,1024)
            self.assertGreaterEqual(count*latency/1e8,2)
        with self.assertRaises(ValueError): c.solve_count(1000000000)

    def test_environment_cannot_override_frozen_model(self):
        with patch.dict(c.os.environ, {'ADMM_HORIZON_LENGTH':'999', 'VIVADO_ROUTE_DIRECTIVE':'x', 'MAKEFLAGS':'-e', 'XILINX_HLS':'/tools'}):
            env=c.clean_environment()
        self.assertNotIn('ADMM_HORIZON_LENGTH',env)
        self.assertNotIn('MAKEFLAGS',env)
        self.assertNotIn('VIVADO_ROUTE_DIRECTIVE',env)
        self.assertEqual(env['XILINX_HLS'],'/tools')

    def test_snapshot_contains_only_campaign_script_dependencies(self):
        names=[str(p.relative_to(c.ROOT)) for p in c.source_files(c.ROOT)]
        self.assertEqual({p for p in names if p.startswith('scripts/')},
                         {'scripts/'+name for name in c.CAMPAIGN_SCRIPTS})
        self.assertIn('tests/power/test_power.sh', names)
        self.assertIn('tests/power/test_power_hls.sh', names)
        self.assertIn('experiments/power/requirements.txt', names)
        self.assertFalse(any(p.startswith(('build/', 'results/', '.git/')) for p in names))
        self.assertFalse(any(Path(p).name in c.GENERATED for p in names))

    def test_snapshot_detects_mutation(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); (root/'source').mkdir(); (root/'source/a').write_text('first')
            m={'source_hashes':{'a':c.sha(root/'source/a')}}
            m['campaign_id']=c.digest(m); c.save(root/'campaign.json',m)
            c.campaign_data(root)
            (root/'source/a').write_text('changed')
            with self.assertRaisesRegex(ValueError,'snapshot changed'): c.campaign_data(root)

    def test_measure_and_aggregate_reject_modified_frozen_runner(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            runner=root/'source/scripts/power_campaign.py'
            runner.parent.mkdir(parents=True)
            runner.write_text('original runner')
            m={'source_hashes':{'scripts/power_campaign.py':c.sha(runner)}}
            m['campaign_id']=c.digest(m)
            c.save(root/'campaign.json',m)
            runner.write_text('changed runner')
            args=SimpleNamespace(campaign=root,local=root/'measurements')
            for operation in (c.measure,c.aggregate):
                with self.subTest(operation=operation.__name__):
                    with self.assertRaisesRegex(ValueError,'Source snapshot changed'):
                        operation(args)
            self.assertFalse(args.local.exists())

    def test_timing_rejects_hold_failure(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'timing.rpt'
            p.write_text('\n 0.1 0 0 100 -0.01 -0.01 1 100 2 0 0 100\nAll user specified timing constraints are met.')
            with self.assertRaises(ValueError): c.timing_values(p)
            p.write_text('\n 0.1 0 0 100 0.01 0 0 100 2 0 0 100\nAll user specified timing constraints are met.')
            self.assertEqual(c.timing_values(p)['hold_slack_ns'],.01)

    def test_trace_validation_rejects_gap_and_wrong_pilot(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            meta={'bitstream_sha256':'abc','clock_hz':100,'config_cycles':[8,0,0,100,100],
                  'summary':{'valid':True},'status':{'flags':0,'overruns':0,'completed':8,
                  'latency_min':10,'latency_max':10,'active_cycles':100,'counts':[1,1,1],
                  'checksum':123,'last_output_words':[1,2,3,4]}}
            c.save(root/'metadata.json',meta)
            def trace(gap=False):
                with (root/'trace.csv').open('w') as f:
                    f.write('phase,samples,flags,start_s,duration_s\n1,10,0,0,1\n2,10,0,1,1\n3,10,0,'+('2.01' if gap else '2')+',1\n')
            info={'files':{'top_uart_power.bit':'abc'}}
            trace(); c.validate_run(root,info,8)
            with self.assertRaisesRegex(ValueError,'Numerical pilot'):
                c.validate_run(root,info,8,{'checksum':999,'last_output_words':[1,2,3,4]})
            trace(True)
            with self.assertRaisesRegex(ValueError,'gap'): c.validate_run(root,info,8)

    def test_incomplete_bundle_never_ready(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            c.save(root/'artifact.json',{'campaign_id':'c','point':{'id':'p'},'files':{}})
            with self.assertRaisesRegex(ValueError,'missing required'): c.verify_bundle(root,'c','p')


if __name__=='__main__': unittest.main()
