"""No dependencies required: python3 -m unittest discover -s tests -v."""
import json
from http.server import BaseHTTPRequestHandler, HTTPServer
from threading import Thread
import time
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / 'validation/v5_demo.py'


class V5SyntheticSlice(unittest.TestCase):
    def run_case(self, count, fault='none', target=1):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        out = Path(tmp.name)
        p = subprocess.run([sys.executable, str(SCRIPT), 'run', '--count', str(count),
                            '--seed', '101', '--fault', fault, '--target', str(target),
                            '--out', str(out)], capture_output=True, text=True)
        verdict = json.loads((out / 'verdict.json').read_text())
        return out, p, verdict

    def test_nominal_1_3_100(self):
        for count in (1, 3, 100):
            with self.subTest(count=count):
                _, p, v = self.run_case(count)
                self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
                self.assertEqual(v['count_observed_events'], count * 3)
                self.assertEqual(v['status'], 'PASS')

    def test_mutations(self):
        for fault, check_id in (
                ('duplicate', 'EVENT-EXACT-mosip.identity.uin.assigned'),
                ('missing', 'EVENT-EXACT-mosip.identity.uin.assigned'),
                ('wrong_value', 'EVENT-EFFECT-VALUE'),
                ('slow', 'NFR-DEMO-LATENCY'),
                ('metric_count', 'METRIC-COUNT'),
                ('broken_link', 'SPAN-PARENT-idrepo-server'),
                ('missing_metric', 'METRIC-SVC-COUNT-idgenerator')):
            with self.subTest(fault=fault):
                _, p, v = self.run_case(100, fault, 17)
                self.assertEqual(p.returncode, 1, p.stdout + p.stderr)
                self.assertIn(check_id, {x['check_id'] for x in v['failures']})

    def test_aggregate_unchanged_but_each_transaction_invalid(self):
        out, _, _ = self.run_case(3)
        obj = json.loads((out / 'observed.json').read_text())
        records = next(g for g in obj['logs']['resourceLogs']
                       if any(a['value'].get('stringValue') == 'idrepo-identity'
                              for a in g['resource']['attributes']))['scopeLogs'][0]['logRecords']
        tx = lambda r: next(a['value']['stringValue'] for a in r['attributes'] if a['key'] == 'oaef.transaction.id')
        event = 'mosip.identity.uin.assigned'
        row1 = next(r for r in records if tx(r) == 'TX-001' and r['eventName'] == event)
        row2 = next(r for r in records if tx(r) == 'TX-002' and r['eventName'] == event)
        records.remove(row2)
        records.append(json.loads(json.dumps(row1)))
        (out / 'observed.json').write_text(json.dumps(obj))
        p = subprocess.run([sys.executable, str(SCRIPT), 'verify', '--out', str(out)], capture_output=True, text=True)
        v = json.loads((out / 'verdict.json').read_text())
        self.assertEqual(v['count_expected_events'], v['count_observed_events'])
        self.assertEqual(p.returncode, 1)
        fails = [c for c in v['failures'] if c['check_id'] == 'EVENT-EXACT-' + event]
        self.assertEqual({c['transaction_id'] for c in fails}, {'TX-001', 'TX-002'})

    def test_optional_otlp_http_posts_three_signals_with_recent_timestamps(self):
        received = {}

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                body = self.rfile.read(int(self.headers['Content-Length']))
                received[self.path] = json.loads(body)
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b'{}')

            def log_message(self, *args):
                pass

        server = HTTPServer(('127.0.0.1', 0), Handler)
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        with tempfile.TemporaryDirectory() as tmp:
            p = subprocess.run([sys.executable, str(SCRIPT), 'run', '--count', '3',
                                '--target', '1', '--seed', '310', '--out', tmp,
                                '--otlp', f'http://127.0.0.1:{server.server_address[1]}'],
                               capture_output=True, text=True, timeout=15)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertEqual(set(received), {'/v1/traces', '/v1/logs', '/v1/metrics'})
        spans = [s for g in received['/v1/traces']['resourceSpans'] for s in g['scopeSpans'][0]['spans']]
        self.assertEqual(len(spans), 3 * 17)
        self.assertEqual(len(received['/v1/traces']['resourceSpans']), 6)  # six services
        self.assertLess(abs(int(spans[0]['startTimeUnixNano']) - time.time_ns()), 120_000_000_000)

    def test_span_mutation_not_hidden_by_global_count(self):
        out, _, _ = self.run_case(3)
        obj = json.loads((out / 'observed.json').read_text())
        spans = [s for g in obj['traces']['resourceSpans'] for s in g['scopeSpans'][0]['spans']]
        # same total spans, but one wrong logical operation in transaction #1
        next(s for s in spans if s['name'] == 'mosip.identity.uin.assigned')['name'] = 'unknown.synthetic.operation'
        (out / 'observed.json').write_text(json.dumps(obj))
        p = subprocess.run([sys.executable, str(SCRIPT), 'verify', '--out', str(out)], capture_output=True, text=True)
        v = json.loads((out / 'verdict.json').read_text())
        self.assertEqual(p.returncode, 1)
        self.assertIn('SPAN-EVENT-COUNT', {x['check_id'] for x in v['failures']})


if __name__ == '__main__':
    unittest.main()
