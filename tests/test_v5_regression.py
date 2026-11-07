"""Regression baseline for the V5 demonstrator, frozen before C1 (spec compiler) at commit 4685910.

For every fault case: S1 exit code, S2-read collect exit code, verdict, diagnostic classes, and the business
facts the oracle must detect. Facts are (check family regex, keyword) pairs matched case-insensitively
against the failed check ids, so renaming checks (C1 aliases) does not break the baseline, while losing a
detection or gaining an unexpected one does.
"""
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import json
import re

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_v5_backend  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
S1 = ROOT / 'validation/v5_demo.py'

# case: (S1 exit, collect exit, verdict, classes, must-detect facts, allowed extra families)
BASELINE = {
    'none':           (0, 0, 'PASS', ['S1_TELEMETRY_CONFORMANT'], [], []),
    'duplicate':      (1, 1, 'FAIL', ['OBSERVABILITY_VIOLATION'],
                       [('EVENT-EXACT', 'uin.assigned')], ['RUN-EVENT-COUNT']),
    'missing':        (1, 2, 'INCONCLUSIVE', ['EVIDENCE_GAP'],
                       [('EVENT-EXACT', 'uin.assigned')], ['RUN-EVENT-COUNT']),
    'wrong_value':    (1, 1, 'FAIL', ['OBSERVABILITY_VIOLATION'], [('EVENT-EFFECT-VALUE', '')], []),
    'slow':           (1, 1, 'FAIL', ['NFR_VIOLATION'], [('NFR', '')], []),
    'broken_link':    (1, 1, 'FAIL', ['TRACE_CONTEXT_BROKEN'], [('SPAN-PARENT', 'idrepo')], []),
    'metric_count':   (1, 1, 'FAIL', ['METRIC_RECONCILIATION_FAILURE'], [(r'(METRIC|PROM-MEASUREMENTS)-COUNT', '')],
                       ['METRIC-BUCKET-TOTAL', 'METRIC-SUM', 'PROM-']),
    'missing_metric': (1, 2, 'INCONCLUSIVE', ['EVIDENCE_GAP'], [('METRIC-SVC', 'idgenerator')], []),
}


def failed_ids(verdict):
    ids = [f['check_id'] for f in verdict.get('event_span_failures', verdict.get('failures', []))]
    ids += [m['check_id'] for m in verdict.get('metric_checks', []) if m['status'] != 'PASS']
    return ids


class RegressionTest(unittest.TestCase):
    run_sample = test_v5_backend.V5BackendTest.run_sample

    def check_facts(self, case, ids, facts, allowed):
        for family, keyword in facts:
            self.assertTrue(any(re.match(family, i.upper()) and keyword.lower() in i.lower() for i in ids),
                            f'{case}: lost detection {family}/{keyword}; failed checks {ids}')
        known = [f for f, _ in facts] + allowed
        unexpected = [i for i in ids if not any(re.match(k, i.upper()) for k in known)]
        self.assertEqual(unexpected, [], f'{case}: unexpected failed checks')

    def test_offline_s1_baseline(self):
        for case, (s1_exit, _, _, _, facts, allowed) in BASELINE.items():
            with self.subTest(case=case), tempfile.TemporaryDirectory() as tmp:
                p = subprocess.run([sys.executable, str(S1), 'run', '--count', '20', '--seed', '101',
                                    '--fault', case, '--target', '17', '--out', tmp], capture_output=True, text=True)
                self.assertEqual(p.returncode, s1_exit, p.stdout + p.stderr)
                v = json.loads((Path(tmp) / 'verdict.json').read_text())
                self.check_facts(case, failed_ids(v), facts, allowed + ['PROM-'])

    def test_backend_baseline(self):
        for case, (s1_exit, col_exit, status, classes, facts, allowed) in BASELINE.items():
            with self.subTest(case=case):
                kwargs = {'fault': case}
                if case == 'missing':      # backend view of a missing event: the record never reaches Loki
                    kwargs = {'drop_event': True}
                _, run, proc, v, _ = self.run_sample(**kwargs)
                if case != 'missing':
                    self.assertEqual(run.returncode, s1_exit)
                self.assertEqual(proc.returncode, col_exit, proc.stdout + proc.stderr)
                self.assertEqual(v['status'], status)
                self.assertEqual(v['diagnostic_classes'], classes)
                self.check_facts(case, failed_ids(v), facts, allowed)


if __name__ == '__main__':
    unittest.main()
