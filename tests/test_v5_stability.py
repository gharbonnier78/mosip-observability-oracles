"""Stability page: repeated runs with the same verdict and failed checks are STABLE, otherwise FLAKY."""
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
STABILITY = ROOT / 'validation/v5_stability.py'


def fake_run(path, status, failures, attempts=1):
    path.mkdir(parents=True)
    (path / 'manifest.json').write_text(json.dumps({'run_id': 's1-' + path.name, 'fault': 'duplicate'}))
    (path / 'backend-meta.json').write_text(json.dumps({'attempts': attempts, 'collect_seconds': 1.0}))
    (path / 'backend-verdict.json').write_text(json.dumps({
        'status': status, 'diagnostic_classes': ['X'], 'metric_checks': [],
        'event_span_failures': [{'check_id': c, 'transaction_id': 'TX-017'} for c in failures]}))


class StabilityTest(unittest.TestCase):
    def run_page(self, runs):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name, status, failures, attempts in runs:
                fake_run(root / name, status, failures, attempts)
            p = subprocess.run([sys.executable, str(STABILITY), str(root)], capture_output=True, text=True)
            self.assertEqual(p.returncode, 0, p.stderr)
            self.assertTrue((root / 'index.html').exists())
            return {s['case']: s for s in json.loads((root / 'stability.json').read_text())}

    def test_same_failure_every_time_is_stable(self):
        s = self.run_page([('duplicate-r1', 'FAIL', ['EVENT-EXACT-x'], 1), ('duplicate-r2', 'FAIL', ['EVENT-EXACT-x'], 1)])
        self.assertEqual(s['duplicate']['stability'], 'STABLE')

    def test_varying_verdict_with_slow_collection_is_flaky_environment(self):
        s = self.run_page([('nominal-r1', 'PASS', [], 1), ('nominal-r2', 'INCONCLUSIVE', [], 30)])
        self.assertEqual(s['nominal']['stability'], 'FLAKY')
        self.assertTrue(s['nominal']['timing_sensitive'])
        self.assertIn('environment', s['nominal']['interpretation'])

    def test_varying_failures_with_complete_evidence_points_to_product(self):
        s = self.run_page([('slow-r1', 'FAIL', ['NFR-DEMO-LATENCY'], 1), ('slow-r2', 'PASS', [], 1)])
        self.assertEqual(s['slow']['stability'], 'FLAKY')
        self.assertIn('product', s['slow']['interpretation'])


if __name__ == '__main__':
    unittest.main()
