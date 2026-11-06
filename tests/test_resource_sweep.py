"""Point settings must survive Make's header regeneration."""
import importlib.util
import os
from pathlib import Path
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('resource_sweep', ROOT/'scripts/sweep_resource_utilization.py')
sweep = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sweep)


class PointConfigurationTests(unittest.TestCase):
    def test_make_receives_point_settings_for_both_stages(self):
        with patch.dict(os.environ, {'ADMM_SOLVER_ARCH': 'full_sparse', 'ADMM_ITERATIONS': '9'}):
            for target in ('hls', 'vivado'):
                with patch.object(sweep, 'run_cmd') as run, patch.object(sweep, 'verify_generated_config') as verify:
                    sweep.run_build_stage(ROOT, board='custom', target=target,
                                          horizon=5, admm_iters=10, enable_trajectory=False)
                    env = run.call_args.kwargs['env']
                    self.assertEqual(env['ADMM_HORIZON_LENGTH'], '5')
                    self.assertEqual(env['ADMM_ITERATIONS'], '10')
                    self.assertEqual(env['ADMM_ENABLE_TRAJECTORY'], '0')
                    self.assertEqual(env['ADMM_SOLVER_ARCH'], 'full_sparse')
                    verify.assert_called_once_with(ROOT, horizon=5, admm_iters=10, enable_trajectory=False)

    def test_regenerated_configuration_mismatch_rejects_point(self):
        with patch.object(sweep, 'run_cmd'), patch.object(sweep, 'verify_generated_config', side_effect=RuntimeError('mismatch')):
            with self.assertRaisesRegex(RuntimeError, 'mismatch'):
                sweep.run_build_stage(ROOT, board='custom', target='hls', horizon=5,
                                      admm_iters=10, enable_trajectory=False)
