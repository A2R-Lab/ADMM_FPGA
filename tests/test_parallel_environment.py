"""The horizon runner must use its caller's Python environment."""
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import run_max_horizon_parallel as runner


class ParallelEnvironmentTests(unittest.TestCase):
    def test_worker_uses_current_python_without_private_venv(self):
        with tempfile.TemporaryDirectory(prefix='parallel test ') as tmp:
            repo = Path(tmp)
            (repo/'scripts').mkdir()
            (repo/'scripts/run_max_horizon_point.py').write_text(
                'import json, sys\nprint(json.dumps(sys.executable))\n'
            )
            args = dict(out_dir=str(repo/'results'), arch='staged_a', iters=10,
                        threads_per_worker=2, git_head='test', git_status_short='',
                        board='custom', heartbeat_s=30, enable_trajectory=False,
                        skip_clean=False)
            result = runner.run_point(0, repo, {'horizon': 10}, args)
            self.assertEqual(result['returncode'], 0)
            output = Path(result['log']).read_text().splitlines()[-1]
            self.assertEqual(json.loads(output), sys.executable)


if __name__ == '__main__':
    unittest.main()
