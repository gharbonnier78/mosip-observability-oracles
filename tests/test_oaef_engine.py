"""Oracle engine (C1b) on the specification simulator (C1c): the compiled NIN-001 contract passes on nominal
telemetry, and every injected fault is detected by the specification obligation that covers it, on TX-017 only."""
import json
from pathlib import Path
import random
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'validation'))
from oaef_oracle import Evaluator, attr_dict, match, Golden  # noqa: E402
from v5_sim_spec import normalise, run_context, to_otlp, transaction  # noqa: E402

CONTRACT = json.loads((ROOT / 'generated/contracts/NIN-001.contract.json').read_text(encoding='utf-8'))
EXPECTED = {
    'duplicate': {'OBL-EVENTS-EV_UIN_ASSIGNED:count'},
    'missing': {'OBL-EVENTS-EV_UIN_ASSIGNED:count'},
    'wrong_value': {'OBL-EVENTS-EV_IDENTITY_ACTIVATED:values'},
    'slow': {'OBL-NFR-span_budgets_ms:IDREPO_CREATE_SERVER'},
    'broken_link': {'OBL-TRACES-IDREPO_CREATE_SERVER:parent'},
}


def run(fault, n=20):
    rng, run_id = random.Random(7), 's1-test'
    ctx0 = run_context(run_id)
    spans, records, truths = [], [], []
    for tx in range(1, n + 1):
        sp, rec, tr = transaction(7, run_id, tx, 1_800_000_000_000_000_000 + tx * 5_000_000_000,
                                  rng.randint(75, 180), fault, 17, ctx0)
        spans += sp
        records += rec
        truths.append(tr)
    s, r = normalise(*to_otlp(spans, records, ctx0))
    ev = Evaluator(CONTRACT)
    for t in truths:
        tid = t['transaction_id']
        ev.evaluate([x for x in s if attr_dict(x['attributes']).get('oaef.transaction.id') == tid],
                    [x for x in r if attr_dict(x['attributes']).get('oaef.transaction.id') == tid],
                    dict(ctx0, rid=t['rid'], uin=t['uin'], uin_hash=t['uin_hash']), tid)
    return ev.results


class EngineTest(unittest.TestCase):
    def test_nominal_passes_every_evaluated_check(self):
        res = run('none')
        self.assertEqual([x for x in res if x['status'] == 'FAIL'], [])
        self.assertGreater(sum(x['status'] == 'PASS' for x in res), 800)
        pending = {x['obligation_id'] for x in res if x['status'] == 'NOT_EVALUATED'}
        self.assertTrue(any(o.startswith('OBL-API-') for o in pending))   # REST: C2, never counted as PASS

    def test_each_fault_detected_by_its_obligation_on_the_target_only(self):
        for fault, ids in EXPECTED.items():
            with self.subTest(fault=fault):
                fails = [x for x in run(fault) if x['status'] == 'FAIL']
                self.assertTrue(ids <= {x['check_id'] for x in fails}, fails)
                self.assertEqual({x['transaction_id'] for x in fails}, {'TX-017'})
                self.assertTrue(all(x['requirement_refs'] for x in fails))   # every failure traces to a requirement

    def test_matcher_dsl(self):
        ctx = {'rid': '123', 'n': '11'}
        self.assertIsNone(match({'$re': '^1${rid}$'}, '1123', ctx))
        self.assertIsNotNone(match({'$ref': 'rid'}, '124', ctx))
        self.assertIsNone(match(200, '200', ctx))                         # OTLP int64 as string
        self.assertIsNone(match({'$gte': 1, '$lte': 60}, 3, ctx))
        self.assertIsNone(match({'$cap': 'topic'}, 'bus-out', ctx))
        self.assertEqual(ctx['topic'], 'bus-out')
        self.assertIsNone(match({'a': {'$in': ['x', 'y']}}, {'a': 'y', 'b': 1}, ctx))   # subset match
        with self.assertRaises(Golden):
            match({'$golden': True}, 'anything', ctx)


if __name__ == '__main__':
    unittest.main()
