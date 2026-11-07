"""Contract tests for real Grafana HTTP adapters using a deterministic fake HTTP backend.

The fake backend establishes parser/oracle sensitivity, NOT real LGTM integration.
"""
import base64
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import subprocess
import sys
import tempfile
from threading import Thread
import unittest
from urllib.parse import parse_qs, urlsplit

ROOT = Path(__file__).resolve().parents[1]
S1 = ROOT / 'validation/v5_demo.py'
BACKEND = ROOT / 'validation/v5_backend.py'


class MemoryGrafana:
    def __init__(self, posted, drop_event=False, metric_missing=False, tempo_base64=False, foreign_span=False):
        self.posted = posted
        self.drop_event = drop_event
        self.metric_missing = metric_missing
        self.tempo_base64 = tempo_base64
        self.foreign_span = foreign_span
        self.paths = []

    def query(self, path, query):
        self.paths.append(path)
        if path == '/api/datasources':
            return 200, [{'type': t, 'uid': t + '-demo'} for t in ('tempo', 'loki', 'prometheus')]
        prefix = '/api/datasources/proxy/uid/tempo-demo/api/traces/'
        if path.startswith(prefix):
            wanted = path.removeprefix(prefix)
            groups = []
            for src in self.posted['/v1/traces']['resourceSpans']:
                spans = [s for s in src['scopeSpans'][0]['spans'] if s['traceId'] == wanted]
                if self.tempo_base64:  # real Tempo JSON: base64 bytes fields, enum names for kind
                    b64 = lambda h: base64.b64encode(bytes.fromhex(h)).decode()
                    kinds = ['SPAN_KIND_UNSPECIFIED', 'SPAN_KIND_INTERNAL', 'SPAN_KIND_SERVER',
                             'SPAN_KIND_CLIENT', 'SPAN_KIND_PRODUCER', 'SPAN_KIND_CONSUMER']
                    spans = [dict(s, kind=kinds[s['kind']],
                                  **{k: b64(s[k]) for k in ('traceId', 'spanId', 'parentSpanId') if s.get(k)})
                             for s in spans]
                if self.foreign_span and spans and any(a['value'].get('stringValue') == 'TX-002'
                                                       for a in spans[0]['attributes']):
                    spans = [dict(spans[0], traceId='f' * 32)] + spans[1:]   # inconsistent Tempo reply
                if spans:
                    groups.append({'resource': src['resource'], 'scopeSpans': [{'spans': spans}]})
            return (200, {'batches': groups}) if groups else (404, {})
        if path == '/api/datasources/proxy/uid/loki-demo/loki/api/v1/query_range':
            logs = [r for g in self.posted['/v1/logs']['resourceLogs'] for r in g['scopeLogs'][0]['logRecords']]
            sel = query.get('query', [''])[0]
            rows = []
            for log in logs:
                body = log['body']['stringValue']
                if self.drop_event and 'TX-002' in body and 'identity.uin.assigned' in body:
                    continue
                if 'regproc-pkr' in sel and 'idrepo-identity' in sel and json.loads(body)['run_id'] in sel:
                    rows.append([log['timeUnixNano'], body, {}])
            rows.sort(key=lambda r: int(r[0]))
            limit = int(query.get('limit', [2500])[0])
            return 200, {'status': 'success', 'data': {'resultType': 'streams',
                                  'result': [{'stream': {'service_name': 'oaef-s1-simulator'},
                                              'values': rows[:limit]}]}}
        if path == '/api/datasources/proxy/uid/prometheus-demo/api/v1/query':
            q = query.get('query', [''])[0]
            if 'traces_service_graph' in q:   # Tempo-derived service graph: every expected edge present
                contract = json.loads((ROOT / 'contracts/NIN-001-v5-slice.json').read_text())
                return 200, {'status': 'success', 'data': {'resultType': 'vector', 'result': [
                    {'metric': {'client': c, 'server': s}, 'value': [1800000000, '100']}
                    for c, s in contract['service_graph_edges']]}}
            if 'http_server_request_duration' in q:   # per-service request metrics of the run
                rows = []
                for g in self.posted['/v1/metrics']['resourceMetrics'][1:]:
                    svc = next(a['value']['stringValue'] for a in g['resource']['attributes'] if a['key'] == 'service.name')
                    for dp in g['scopeMetrics'][0]['metrics'][0]['histogram']['dataPoints']:
                        lab = {a['key']: next(iter(a['value'].values())) for a in dp['attributes']}
                        base = {'service_name': svc, 'http_route': lab['http.route'], 'oaef_run_id': lab['oaef.run.id'],
                                'http_request_method': lab.get('http.request.method', '')}
                        rows.append({'metric': dict(base, __name__='http_server_request_duration_seconds_count'),
                                     'value': [1800000000, str(dp['count'])]})
                        rows.append({'metric': dict(base, __name__='http_server_request_duration_seconds_sum'),
                                     'value': [1800000000, str(dp['sum'])]})
                return 200, {'status': 'success', 'data': {'resultType': 'vector', 'result': rows}}
            if self.metric_missing:
                return 200, {'status': 'success', 'data': {'resultType': 'vector', 'result': []}}
            met = self.posted['/v1/metrics']['resourceMetrics'][0]['scopeMetrics'][0]['metrics'][0]
            point = met['histogram']['dataPoints'][0]
            run_id = next(a['value']['stringValue'] for a in point['attributes'] if a['key'] == 'oaef.run.id')
            name = 'oaef_synthetic_journey_duration_seconds'
            rows = []
            def add(metric, value, **labels):
                rows.append({'metric': {'__name__': metric, 'oaef_run_id': run_id, **labels},
                             'value': [1800000000, str(value)]})
            add(name + '_count', point['count'])
            add(name + '_sum', point['sum'])
            cum = 0
            for bound, bucket in zip(point['explicitBounds'], point['bucketCounts']):
                cum += int(bucket)
                add(name + '_bucket', cum, le=str(bound))
            add(name + '_bucket', point['count'], le='+Inf')
            return 200, {'status': 'success', 'data': {'resultType': 'vector', 'result': rows}}
        return 404, {'error': 'unexpected route'}


class V5BackendTest(unittest.TestCase):
    def run_sample(self, fault='none', drop_event=False, metric_missing=False, count=3, tempo_base64=False,
                   foreign_span=False):
        work = tempfile.TemporaryDirectory()
        self.addCleanup(work.cleanup)
        root = Path(work.name)
        posted = {}

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                posted[self.path] = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                self.reply(200, {})

            def do_GET(self):
                url = urlsplit(self.path)
                code, obj = backend.query(url.path, parse_qs(url.query))
                self.reply(code, obj)

            def reply(self, code, obj):
                body = json.dumps(obj).encode()
                self.send_response(code)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                pass

        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        url = f'http://127.0.0.1:{server.server_address[1]}'
        out = root / 'run'
        cmd = [sys.executable, str(S1), 'run', '--count', str(count), '--seed', '502',
               '--target', '2', '--fault', fault, '--out', str(out), '--otlp', url]
        run = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        self.assertEqual(set(posted), {'/v1/traces', '/v1/logs', '/v1/metrics'})
        backend = MemoryGrafana(posted, drop_event=drop_event, metric_missing=metric_missing,
                                tempo_base64=tempo_base64, foreign_span=foreign_span)
        result = subprocess.run([sys.executable, str(BACKEND), 'collect', '--out', str(out),
                                 '--grafana', url, '--timeout', '0', '--poll', '0.01'],
                                capture_output=True, text=True, timeout=30)
        bundle = json.loads((out / 'backend-verdict.json').read_text())
        return out, run, result, bundle, backend

    def test_nominal_3(self):
        out, run, proc, verdict, server = self.run_sample()
        self.assertEqual((run.returncode, proc.returncode), (0, 0), proc.stdout + proc.stderr)
        self.assertEqual(verdict['status'], 'PASS')
        self.assertEqual(verdict['events_collected'], 9)
        self.assertEqual(verdict['trace_count'], 3)
        self.assertTrue(any('/api/traces/' in s for s in server.paths))
        report = (out / 'report.html').read_text(encoding='utf-8')
        self.assertIn('<svg', report)                       # sequence diagram from retrieved spans
        self.assertIn('/explore?schemaVersion=1', report)  # Grafana deep links
        self.assertIn('STEP-3', report)                     # scenario steps with expected results
        ok = subprocess.run([sys.executable, str(BACKEND), 'verify-bundle', '--out', str(out)],
                            capture_output=True, text=True)
        self.assertEqual(ok.returncode, 0, ok.stdout + ok.stderr)
        replay = subprocess.run([sys.executable, str(BACKEND), 're-evaluate', '--out', str(out)],
                                capture_output=True, text=True)
        self.assertEqual(replay.returncode, 0, replay.stdout + replay.stderr)
        self.assertIn('MATCH', replay.stdout)
        # Altering a backend response in evidence MUST be detected.
        with (out / 'backend-raw/loki.json').open('a') as handle:
            handle.write('tamper')
        bad = subprocess.run([sys.executable, str(BACKEND), 'verify-bundle', '--out', str(out)],
                             capture_output=True, text=True)
        self.assertEqual(bad.returncode, 1)

    def test_nominal_100(self):
        _, run, proc, v, _ = self.run_sample(count=100)
        self.assertEqual(run.returncode, 0)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertEqual(v['trace_count'], 100)
        self.assertEqual(v['events_collected'], 300)

    def test_duplicate_seen_by_backend(self):
        _, run, proc, v, _ = self.run_sample(fault='duplicate')
        self.assertEqual(run.returncode, 1)
        self.assertEqual(proc.returncode, 1, proc.stdout + proc.stderr)
        self.assertEqual(v['status'], 'FAIL')
        self.assertEqual(v['events_collected'], 10)
        self.assertIn('EVENT-EXACT-mosip.identity.uin.assigned',
                      {x['check_id'] for x in v['event_span_failures']})

    def test_missing_backend_log_is_not_product_bug(self):
        _, run, proc, v, _ = self.run_sample(drop_event=True)
        self.assertEqual(run.returncode, 0)
        self.assertEqual(proc.returncode, 2, proc.stdout + proc.stderr)
        self.assertEqual(v['status'], 'INCONCLUSIVE')
        self.assertEqual(v['classification'], 'EVIDENCE_GAP')
        self.assertEqual(v['events_collected'], 8)

    def test_absent_metric_is_inconclusive(self):
        _, _, proc, v, _ = self.run_sample(metric_missing=True)
        self.assertEqual(proc.returncode, 2, proc.stdout + proc.stderr)
        self.assertEqual(v['status'], 'INCONCLUSIVE')

    def test_metric_count_disagreement(self):
        _, run, proc, v, _ = self.run_sample(fault='metric_count')
        self.assertEqual(run.returncode, 1)
        self.assertEqual(proc.returncode, 1, proc.stdout + proc.stderr)
        self.assertEqual(v['status'], 'FAIL')
        self.assertIn('PROM-MEASUREMENTS-COUNT',
                      {x['check_id'] for x in v['metric_checks'] if x['status'] == 'FAIL'})

    def test_tempo_base64_ids(self):
        _, run, proc, v, _ = self.run_sample(tempo_base64=True)
        self.assertEqual((run.returncode, proc.returncode), (0, 0), proc.stdout + proc.stderr)
        self.assertEqual(v['status'], 'PASS')
        self.assertEqual(v['trace_count'], 3)

    def test_broken_trace_context_is_fail(self):
        _, run, proc, v, _ = self.run_sample(fault='broken_link', tempo_base64=True)
        self.assertEqual((run.returncode, proc.returncode), (1, 1), proc.stdout + proc.stderr)
        self.assertEqual(v['classification'], 'TRACE_CONTEXT_BROKEN')
        self.assertIn('SPAN-PARENT-idrepo-server', {x['check_id'] for x in v['event_span_failures']})

    def allure_results(self, out):
        res = out / 'allure-results'
        results = [json.loads(p.read_text(encoding='utf-8')) for p in sorted(res.glob('*-result.json'))]
        containers = [json.loads(p.read_text(encoding='utf-8')) for p in res.glob('*-container.json')]
        for r in results:  # basic Allure 2 result schema
            for key in ('uuid', 'historyId', 'fullName', 'name', 'status', 'stage', 'start', 'stop',
                        'labels', 'links', 'steps', 'attachments'):
                self.assertIn(key, r)
            self.assertIn(r['status'], ('passed', 'failed', 'broken', 'skipped', 'unknown'))
            self.assertLessEqual(r['start'], r['stop'])
            for att in r['attachments']:
                self.assertTrue((res / att['source']).is_file(), att['source'])
            for s in r['steps']:
                self.assertEqual({p['name'] for p in s['parameters']}, {'Expected', 'Observed'})
        self.assertEqual(len(containers), 1)
        self.assertEqual(set(containers[0]['children']), {r['uuid'] for r in results})
        self.assertTrue((res / 'environment.properties').is_file())
        return {r['fullName']: r for r in results}

    def test_allure_results_nominal(self):
        out, _, proc, _, _ = self.run_sample()
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        results = self.allure_results(out)
        self.assertEqual(set(results), {'NIN-001.none.TX-001', 'NIN-001.none.run'})
        tx = results['NIN-001.none.TX-001']
        self.assertEqual(tx['status'], 'passed')
        self.assertEqual([s['name'].split()[0] for s in tx['steps']],
                         ['STEP-1', 'STEP-2', 'STEP-3', 'STEP-4', 'STEP-5'])
        labels = {(l['name'], l['value']) for l in tx['labels']}
        self.assertTrue({('suite', 'NIN-001'), ('fault', 'none'),
                         ('diagnostic_class', 'S1_TELEMETRY_CONFORMANT')} <= labels)
        self.assertIn(('run_id', json.loads((out / 'manifest.json').read_text())['run_id']), labels)
        self.assertTrue(all('/explore?schemaVersion=1' in l['url'] for l in tx['links']))
        self.assertEqual({a['type'] for a in tx['attachments']}, {'image/svg+xml', 'text/html'})
        # allure-results is part of the sealed bundle
        sealed = json.loads((out / 'evidence-sha256.json').read_text())['files']
        self.assertTrue(any(k.startswith('allure-results/') for k in sealed))

    def test_allure_results_duplicate(self):
        out, _, proc, _, _ = self.run_sample(fault='duplicate')
        self.assertEqual(proc.returncode, 1, proc.stdout + proc.stderr)
        results = self.allure_results(out)
        self.assertEqual(set(results), {'NIN-001.duplicate.TX-002', 'NIN-001.duplicate.TX-001',
                                        'NIN-001.duplicate.run'})
        bad = results['NIN-001.duplicate.TX-002']
        self.assertEqual(bad['status'], 'failed')
        self.assertIn('[OBSERVABILITY_VIOLATION]', bad['statusDetails']['message'])
        step3 = next(s for s in bad['steps'] if s['name'].startswith('STEP-3'))
        self.assertEqual(step3['status'], 'failed')
        self.assertIn('EVENT-EXACT-mosip.identity.uin.assigned',
                      next(p['value'] for p in step3['parameters'] if p['name'] == 'Observed'))
        self.assertEqual(results['NIN-001.duplicate.TX-001']['status'], 'passed')
        self.assertEqual(results['NIN-001.duplicate.run']['status'], 'failed')

    def test_allure_missing_event_is_broken(self):
        out, _, proc, _, _ = self.run_sample(drop_event=True)
        self.assertEqual(proc.returncode, 2, proc.stdout + proc.stderr)
        results = self.allure_results(out)
        self.assertEqual(results['NIN-001.none.TX-002']['status'], 'broken')
        self.assertIn('[EVIDENCE_GAP]', results['NIN-001.none.TX-002']['statusDetails']['message'])

    def test_service_without_metrics_is_detected(self):
        out, run, proc, v, _ = self.run_sample(fault='missing_metric')
        self.assertEqual(run.returncode, 1)                     # source side: the service emitted no metric
        self.assertEqual(proc.returncode, 2, proc.stdout + proc.stderr)   # backend: absent series = evidence gap
        bad = {m['check_id']: m['status'] for m in v['metric_checks'] if m['status'] != 'PASS'}
        self.assertEqual(bad, {'METRIC-SVC-COUNT-idgenerator': 'INCONCLUSIVE', 'METRIC-SVC-SUM-idgenerator': 'INCONCLUSIVE'})
        self.assertTrue(all(g['status'] == 'PASS' for g in v['derived_metrics_health']))

    def test_service_metrics_reconciled_with_traces(self):
        _, _, proc, v, _ = self.run_sample()
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        svc = [m for m in v['metric_checks'] if m['check_id'].startswith('METRIC-SVC-')]
        self.assertEqual(len(svc), 8)                           # 4 services x (count, sum)
        self.assertTrue(all(m['status'] == 'PASS' for m in svc))

    def test_inconsistent_tempo_reply_is_evidence_gap_not_crash(self):
        out, run, proc, v, _ = self.run_sample(foreign_span=True)
        self.assertEqual(proc.returncode, 2, proc.stdout + proc.stderr)   # INCONCLUSIVE, not exit 3
        self.assertEqual(v['classification'], 'EVIDENCE_GAP')
        meta = json.loads((out / 'backend-meta.json').read_text())
        self.assertIn('tempo-consistency', meta['backend_errors'])
        self.assertIn('f' * 32, meta['backend_errors']['tempo-consistency'][0])
        ok = subprocess.run([sys.executable, str(BACKEND), 'verify-bundle', '--out', str(out)], capture_output=True, text=True)
        self.assertEqual(ok.returncode, 0, ok.stdout + ok.stderr)

    def test_latency_breach_is_fail_not_inconclusive(self):
        _, run, proc, v, _ = self.run_sample(fault='slow')
        self.assertEqual(run.returncode, 1)
        self.assertEqual(proc.returncode, 1, proc.stdout + proc.stderr)
        self.assertEqual(v['status'], 'FAIL')
        self.assertIn('NFR-DEMO-LATENCY', {x['check_id'] for x in v['event_span_failures']})
        self.assertEqual(v['diagnostic_classes'], ['NFR_VIOLATION'])


if __name__ == '__main__':
    unittest.main()
