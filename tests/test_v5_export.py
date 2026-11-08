"""Campaign export: offline zip with the runs, hashes, scenario, and an Xray Cucumber JSON."""
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_v5_backend  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]


class ExportTest(unittest.TestCase):
    run_sample = test_v5_backend.V5BackendTest.run_sample   # fake Grafana backend helper only
    def test_campaign_zip_and_cucumber(self):
        with tempfile.TemporaryDirectory() as tmp:
            campaign = Path(tmp)
            for fault in ('none', 'duplicate'):
                out, _, _, _, _ = self.run_sample(fault=fault)
                shutil.copytree(out, campaign / fault)
            subprocess.run([sys.executable, str(ROOT / 'validation/v5_stability.py'), str(campaign)], check=True,
                           capture_output=True)
            p = subprocess.run([sys.executable, str(ROOT / 'validation/v5_export.py'), str(campaign)],
                               capture_output=True, text=True, env={**__import__('os').environ,
                                                                    'OAEF_XRAY_TEST_KEYS': 'duplicate=PRJ-13'})
            self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
            zpath = next((campaign / 'exports').glob('oaef-v5-campaign-*.zip'))
            with zipfile.ZipFile(zpath) as z:
                names = set(z.namelist())
                self.assertTrue({'index.html', 'README.txt', 'campaign-sha256.json', 'xray/cucumber.json',
                                 'none/report.html', 'duplicate/evidence-sha256.json',
                                 'scenario/nin_001_new_adult_no_hit.feature'} <= names)
                hashes = json.loads(z.read('campaign-sha256.json'))['files']
                self.assertEqual(set(hashes), names - {'campaign-sha256.json'})
                feature = json.loads(z.read('xray/cucumber.json'))[0]
            by_case = {e['id']: e for e in feature['elements']}
            self.assertEqual({s['result']['status'] for s in by_case['nin-001;none']['steps']}, {'passed'})
            dup = by_case['nin-001;duplicate']
            self.assertIn({'name': '@PRJ-13'}, dup['tags'])
            self.assertEqual(dup['steps'][2]['result']['status'], 'failed')          # STEP-3
            self.assertIn('EVENT-EXACT-mosip.identity.uin.assigned', dup['steps'][2]['result']['error_message'])
            self.assertEqual(dup['steps'][-1]['embeddings'][0]['name'], 'report.html')


if __name__ == '__main__':
    unittest.main()
