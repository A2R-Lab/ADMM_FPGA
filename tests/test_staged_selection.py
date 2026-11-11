"""Public architecture selection and default build environment regression checks."""
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]


class StagedSelectionTests(unittest.TestCase):
    def environment(self, **settings):
        env = {k: v for k, v in os.environ.items() if not k.startswith('ADMM_')}
        env.update(settings)
        return env

    def runtime(self, **settings):
        # Exercise the real parameter parser and runtime-header function without
        # running unrelated matrix generation for each selector combination.
        script = """
import ast, json, parameters
from pathlib import Path
tree = ast.parse(Path('scripts/header_generator.py').read_text())
function = next(n for n in tree.body if isinstance(n, ast.FunctionDef)
                and n.name == 'generate_runtime_config_header')
namespace = vars(parameters).copy()
exec(compile(ast.Module(body=[function], type_ignores=[]), '<runtime>', 'exec'), namespace)
print(json.dumps(namespace['generate_runtime_config_header']()))
"""
        result = subprocess.run([sys.executable, '-c', script], cwd=ROOT,
                                env=dict(self.environment(**settings), PYTHONPATH=str(ROOT/'scripts')),
                                text=True, capture_output=True)
        return result

    def test_default_and_explicit_staged_select_optimized_fixed_mapping(self):
        for settings in ({}, {'ADMM_SOLVER_ARCH': 'staged_a'}):
            result = self.runtime(**settings)
            self.assertEqual(result.returncode, 0, result.stderr)
            header = json.loads(result.stdout)
            self.assertIn('#define ADMM_SOLVER_ARCH_NAME "staged_a"', header)
            self.assertIn('#define ADMM_SOLVER_ARCH_STAGED_FUSED 1', header)
            self.assertIn('#define ADMM_SOLVER_ARCH_FULL_SPARSE 0', header)

    def test_full_sparse_and_float_reference_do_not_select_fixed_mapping(self):
        for settings in ({'ADMM_SOLVER_ARCH': 'full_sparse'}, {'ADMM_USE_FLOAT': '1'}):
            result = self.runtime(**settings)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('#define ADMM_SOLVER_ARCH_STAGED_FUSED 0', json.loads(result.stdout))

    def test_removed_public_architecture_is_rejected(self):
        result = self.runtime(ADMM_SOLVER_ARCH='staged_fused')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('ADMM_SOLVER_ARCH', result.stderr)

    def test_make_exports_default_and_explicit_architecture(self):
        target = 'test-print-architecture:\n\t@printenv ADMM_SOLVER_ARCH'
        for settings, expected in (({}, 'staged_a'),
                                   ({'ADMM_SOLVER_ARCH': 'full_sparse'}, 'full_sparse')):
            output = subprocess.check_output(
                ['make', '--no-print-directory', '--eval', target, 'test-print-architecture'],
                cwd=ROOT, env=self.environment(**settings), text=True)
            self.assertEqual(output.strip(), expected)


if __name__ == '__main__':
    unittest.main()
