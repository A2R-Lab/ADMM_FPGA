import sys, tempfile
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'scripts'))
import power_campaign as c
import unittest

class BuildFlowTests(unittest.TestCase):
    def test_isolated_timing_retry_publication_resume_and_tampering(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); (root/'source').mkdir()
            m={'campaign_id':'test'}
            p={'id':'staged_a_h20_k10','arch':'staged_a','horizon':20,'iterations':10,'variant':'baseline'}
            c.save(root/'preflight.json', {'versions':{'fake':'test only'}})
            attempts=[]
            def fake_run(cmd,work,env,log):
                log.parent.mkdir(parents=True,exist_ok=True); log.write_text('fake test log')
                stage=cmd[-1]
                if stage=='headers':
                    attempts.append(work)
                    assert env['ADMM_HORIZON_LENGTH']=='20' and env['ADMM_ENABLE_TRAJECTORY']=='0'
                if stage=='vivado':
                    reports=work/'build/reports'; reports.mkdir(parents=True)
                    (reports/'post_route_timing.rpt').write_text('\n 0.1 0 0 100 0.01 0 0 100 2 0 0 100\nAll user specified timing constraints are met.' if len(attempts)>1 else 'Timing constraints are not met.')
                    for name in ('post_route_utilization.rpt','post_route_hierarchical_utilization.rpt'):
                        (reports/name).write_text('fake report')
                if stage=='bit':
                    bit=work/'build/top_uart_power.bit'; bit.write_bytes(b'not a physical bitstream')
                    c.save(bit.with_suffix('.json'), {'bitstream_sha256':c.sha(bit),'trajectory_compiled':False,
                        'solver_constants':{'HORIZON_LENGTH':'20'},'runtime_config':'#define ADMM_ITERATIONS 10\n#define ADMM_SOLVER_ARCH_NAME "staged_a"'})
            with patch.object(c,'run',fake_run),patch.object(c,'golden',return_value={'checksum':1}):
                assert c.build_point(root,m,p,8,False)
                assert len(attempts)==2 and attempts[0]!=attempts[1]
                assert c.read(root/'ready'/p['id']/'artifact.json')['variant']=='route_aggressive'
                assert c.build_point(root,m,p,8,False)
                assert len(attempts)==2
            bit=root/'ready'/p['id']/'top_uart_power.bit'; bit.write_bytes(b'tampered')
            try: c.verify_bundle(bit.parent,'test',p['id'])
            except ValueError: pass
            else: raise AssertionError('tamper accepted')

if __name__ == "__main__": unittest.main()
