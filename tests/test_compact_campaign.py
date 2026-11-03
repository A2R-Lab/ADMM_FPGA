"""Check frozen compact campaign provenance without synthesis or board access."""
from pathlib import Path
from types import SimpleNamespace
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import power_campaign as c


class CompactCampaignTests(unittest.TestCase):
    def test_prepared_source_matches_measured_compact_solver(self):
        source = c.ROOT / 'vitis_projects/ADMM/ADMM.cpp'
        original = source.read_bytes()
        with tempfile.TemporaryDirectory() as tmp:
            campaign = Path(tmp) / 'campaign'
            c.prepare(SimpleNamespace(campaign=campaign, comparison=False,
                                      compact_full_sparse=True, horizons='40,10,40'))
            manifest = c.campaign_data(campaign)
            self.assertEqual([p['horizon'] for p in manifest['points']], [10, 40])
            self.assertEqual({p['arch'] for p in manifest['points']}, {'full_sparse'})
            frozen = campaign / 'source/vitis_projects/ADMM/ADMM.cpp'
            # Source hash recorded by the completed compact Arty campaign.
            self.assertEqual(c.sha(frozen),
                             'de53a70d03607b33e3f2b91da7d04b27e2f0440bec203410c1bfc3492b05c456')
            self.assertEqual(manifest['source_hashes']['vitis_projects/ADMM/ADMM.cpp'], c.sha(frozen))
            self.assertEqual(source.read_bytes(), original)

    def test_tiny_model_is_in_frozen_source_without_result_archives(self):
        files = {str(p.relative_to(c.ROOT)) for p in c.source_files(c.ROOT)}
        self.assertIn('evaluation/tinympc_fpga/model.json', files)
        self.assertFalse(any('/validation/' in p or '/results/' in p for p in files))

    def test_custom_horizons_require_compact_and_positive_values(self):
        with tempfile.TemporaryDirectory() as tmp:
            for compact, horizons in [(False, '10'), (True, '0,10')]:
                campaign = Path(tmp) / 'campaign'
                with self.assertRaises(ValueError):
                    c.prepare(SimpleNamespace(campaign=campaign, comparison=False,
                                              compact_full_sparse=compact, horizons=horizons))
                self.assertFalse(campaign.exists())
