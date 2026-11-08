#!/usr/bin/env python3
"""OAEF V5 S1 vertical slice: simulated OTel flow + independent offline oracle.

No external libraries.  Does NOT demonstrate real MOSIP conformance or backend ingestion.
Examples:
  python3 validation/v5_demo.py run --count 100 --seed 12 --out /tmp/v5good
  python3 validation/v5_demo.py run --count 100 --seed 12 --fault duplicate --target 17 --out /tmp/v5dup
  python3 validation/v5_demo.py verify --out /tmp/v5dup
Optional: --otlp http://localhost:4318 (existing LGTM Codespaces instance).
"""
import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import random
import sys
import time
import urllib.request
import uuid
from collections import Counter

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / 'contracts' / 'NIN-001-v5-slice.json'
EVENTS = ("mosip.registration.packet.received", "mosip.identity.uin.assigned", "mosip.identity.activated")
BOUNDS = [0.1, 0.25, 0.5, 1, 2, 5, 10]
KINDS = {'SPAN_KIND_UNSPECIFIED': 0, 'SPAN_KIND_INTERNAL': 1, 'SPAN_KIND_SERVER': 2,
         'SPAN_KIND_CLIENT': 3, 'SPAN_KIND_PRODUCER': 4, 'SPAN_KIND_CONSUMER': 5}

# Simulated SUT topology for one NIN-001 transaction. Built here, independently of the
# contract's expected `journey_spans`, so that the two can disagree.
# (id, service, name, kind, parent id, start ms, end ms); d = upload-to-assignment duration in ms.
PKR_PATH = 'POST /registrationprocessor/v1/packetreceiver/registrationpackets'


def journey(d):
    return [
        ('root', 'jarvis-e2e', 'NIN-001 New adult registration no hit', 1, None, 0, d + 60),
        ('upload', 'jarvis-e2e', PKR_PATH, 3, 'root', 1, 8),
        ('pkr', 'regproc-pkr', PKR_PATH, 2, 'upload', 2, 7),
        ('received', 'regproc-pkr', EVENTS[0], 1, 'pkr', 3, 4),
        ('publish', 'regproc-pkr', 'packet-receiver-bus-out publish', 4, 'pkr', 5, 6),
        ('process', 'regproc-group1', 'packet-receiver-bus-out process', 5, 'publish', 10, d + 40),
        ('validate', 'regproc-group1', 'packet validation', 1, 'process', 11, 15),
        ('dedupe', 'regproc-group1', 'bio-dedupe decision', 1, 'process', 16, 20),
        ('uin-client', 'regproc-group1', 'GET /v1/idgenerator/uin', 3, 'process', 21, 26),
        ('uin-server', 'idgenerator', 'GET /v1/idgenerator/uin', 2, 'uin-client', 22, 25),
        ('idrepo-client', 'regproc-group1', 'POST /idrepository/v1/identity/', 3, 'process', 27, d + 20),
        ('idrepo-server', 'idrepo-identity', 'POST /idrepository/v1/identity/', 2, 'idrepo-client', 28, d + 19),
        ('insert', 'idrepo-identity', 'INSERT mosip_idrepo.uin', 3, 'idrepo-server', 29, 31),
        ('assigned', 'idrepo-identity', EVENTS[1], 1, 'idrepo-server', d + 3, d + 4),
        ('activated', 'idrepo-identity', EVENTS[2], 1, 'idrepo-server', d + 5, d + 6),
        ('notify-client', 'regproc-group1', 'POST /v1/notifier/email/send', 3, 'process', d + 21, d + 30),
        ('notify-server', 'kernel-notification', 'POST /v1/notifier/email/send', 2, 'notify-client', d + 22, d + 29),
    ]


def span_detail(sid, name, kind):
    """Semantic-convention attributes per span type (synthetic values)."""
    if kind in (2, 3) and ' /' in name:
        method, route = name.split(' ', 1)
        out = {'http.request.method': method, 'http.response.status_code': 200}
        out['http.route' if kind == 2 else 'url.path'] = route
        return out
    if sid == 'insert':
        return {'db.system.name': 'postgresql', 'db.namespace': 'mosip_idrepo', 'db.operation.name': 'INSERT'}
    if kind in (4, 5):
        return {'messaging.system': 'kafka', 'messaging.destination.name': 'packet-receiver-bus-out',
                'messaging.operation.type': 'send' if kind == 4 else 'process'}
    return {}


def histogram_point(calls, start_ns, time_ns, attributes):
    """Cumulative OTLP histogram point of the given calls, with the slowest call of each bucket as exemplar."""
    durs = [c[0] for c in calls]
    cum = [sum(1 for d in durs if d <= b) for b in BOUNDS]
    buckets = [str(n - p) for n, p in zip(cum, [0] + cum[:-1])] + [str(len(durs) - cum[-1])]
    exemplars, seen = [], set()
    for d, trace_id, span_id, t, tx_id, *_ in sorted(calls, reverse=True):
        b = next((i for i, x in enumerate(BOUNDS) if d <= x), len(BOUNDS))
        if b not in seen:
            seen.add(b)
            exemplars.append({'timeUnixNano': str(t), 'asDouble': d, 'traceId': trace_id, 'spanId': span_id,
                              'filteredAttributes': attrs({'oaef.transaction.id': tx_id})})
    return {'attributes': attrs(attributes), 'startTimeUnixNano': str(start_ns), 'timeUnixNano': str(time_ns),
            'count': str(len(durs)), 'sum': round(sum(durs), 6), 'explicitBounds': BOUNDS,
            'bucketCounts': buckets, 'exemplars': exemplars}


def service_metric_checks(contract, ledger, spans, observed):
    """Per-service request metrics of the run: count = transactions, sum = durations of the server spans.

    observed: {(service, route): (count, sum)}; a missing entry gives INCONCLUSIVE at the caller's choice.
    """
    out = []
    for m in contract.get('service_metrics', []):
        key = (m['service'], m['route'])
        server = [s for s in spans if s.get('_svc') == m['service'] and span_kind(s) == 2
                  and s['name'] == f'{m["method"]} {m["route"]}']
        span_sum = round(sum(int(s['endTimeUnixNano']) - int(s['startTimeUnixNano']) for s in server) / 1e9, 6)
        got = observed.get(key)
        tag = m['service']
        out.append({'check_id': f'METRIC-SVC-COUNT-{tag}', 'expected': len(ledger) * m['per_transaction'],
                    'actual': None if got is None else got[0]})
        out.append({'check_id': f'METRIC-SVC-SUM-{tag}', 'expected': span_sum,
                    'actual': None if got is None else round(got[1], 6)})
    return out


def kv(k, v):
    typ = 'boolValue' if isinstance(v, bool) else 'intValue' if isinstance(v, int) else 'stringValue'
    return {'key': k, 'value': {typ: str(v) if typ == 'intValue' else v}}


def attrs(obj):
    return [kv(k, v) for k, v in sorted(obj.items())]


def av(records):
    out = {}
    for obj in records:
        v = obj['value']
        out[obj['key']] = next(iter(v.values()))
    return out


def resource(service):
    return {'attributes': attrs({'service.name': service,
                                 'service.namespace': 'jarvis' if service == 'jarvis-e2e' else 'mosip',
                                 'deployment.environment.name': 'test-int', 'cloud.region': 'dc1',
                                 'oaef.simulation.mode': 'S1'})}


def span_kind(span):
    k = span.get('kind', 0)
    return KINDS.get(k, 0) if isinstance(k, str) else int(k)


def all_spans(otlp):
    """Spans with their resource's service.name attached as '_svc'."""
    out = []
    for group in otlp['traces']['resourceSpans']:
        svc = av(group.get('resource', {}).get('attributes', [])).get('service.name')
        for scope in group['scopeSpans']:
            out += [dict(s, _svc=svc) for s in scope['spans']]
    return out


def all_logs(otlp):
    return [r for group in otlp['logs']['resourceLogs'] for scope in group['scopeLogs']
            for r in scope['logRecords']]


def dump(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + '\n', encoding='utf-8')


def load(path):
    return json.loads(path.read_text(encoding='utf-8'))


def deterministic_id(seed, run, tx, stage, width):
    return hashlib.sha256(f'{seed}|{run}|{tx}|{stage}'.encode()).hexdigest()[:width]


def emit(endpoint, otlp):
    sent = []
    for name, suffix in [('traces', '/v1/traces'), ('logs', '/v1/logs'), ('metrics', '/v1/metrics')]:
        headers = {'Content-Type': 'application/json'}
        for item in os.environ.get('OTEL_EXPORTER_OTLP_HEADERS', '').split(','):
            if item.strip():
                k, _, v = item.partition('=')
                from urllib.parse import unquote
                headers[unquote(k.strip())] = unquote(v.strip())
        request = urllib.request.Request(endpoint.rstrip('/') + suffix,
                                         data=json.dumps(otlp[name]).encode('utf-8'),
                                         headers=headers, method='POST')
        with urllib.request.urlopen(request, timeout=30) as res:
            if res.status not in (200, 202):
                raise RuntimeError(f'{name} OTLP HTTP {res.status}')
            print('OTLP', name, res.status)
            sent.append({'signal': name, 'url': endpoint.rstrip('/') + suffix, 'http_status': res.status,
                         'bytes': len(request.data)})
    return sent


def generate(count, seed, fault, target, out, otlp_url):
    if count < 1 or target < 1 or target > count:
        raise ValueError('count must be positive, target must be within count')
    contract = load(CONTRACT)
    rng = random.Random(seed)
    run_id = 's1-' + (uuid.uuid4().hex[:12] if otlp_url else deterministic_id(seed, count, 'run', 'id', 12))
    # Live export must use recent timestamps so traces/logs are discoverable in Grafana.
    # Offline runs stay byte-for-byte deterministic for a fixed seed and count.
    # Live: every span ends 2-8 s before export, inside the window Tempo's metrics generator accepts (30 s).
    base = time.time_ns() - 8_000_000_000 if otlp_url else 1_800_000_000_000_000_000
    tx_spacing = 50_000_000 if otlp_url else 5_000_000_000
    spans_by_svc, logs, ledger = {}, [], []
    durations, roots = [], []
    server_calls = {}   # service -> [(duration s, trace id, span id, start ns, tx id, method, route)]
    for tx in range(1, count + 1):
        tx_id = f'TX-{tx:03d}'
        trace_id = deterministic_id(seed, run_id, tx_id, 'trace', 32)
        value = f'SYN-{seed:06d}-{tx:06d}'
        rid = f'1000110001{tx:05d}{seed % 10**14:014d}'  # synthetic 29-digit RID shape, not a real RID
        duration_ms = rng.randint(75, 180)
        if fault == 'slow' and tx == target:
            duration_ms = contract['max_upload_to_assignment_ms'] + 150
        durations.append(duration_ms / 1000)
        started = base + tx * tx_spacing
        ids = {}
        for sid, svc, name, kind, parent, t0, t1 in journey(duration_ms):
            ids[sid] = deterministic_id(seed, run_id, tx_id, sid, 16)
            common = {'oaef.run.id': run_id, 'oaef.transaction.id': tx_id,
                      'oaef.simulation.mode': 'S1', 'test.case.name': 'NIN-001'}
            if name in EVENTS or sid in ('uin-server', 'idrepo-server'):
                common['oaef.synthetic.effect.id'] = value   # synthetic UIN surrogate (output value)
            if sid in ('root', 'upload', 'pkr', 'received', 'publish', 'process', 'idrepo-client'):
                common['mosip.rid'] = rid                      # synthetic RID (input value)
            if sid == 'pkr':
                common['oaef.response.status'] = 'PACKET_RECEIVED'
            span = {'traceId': trace_id, 'spanId': ids[sid], 'name': name, 'kind': kind,
                    'startTimeUnixNano': str(started + t0 * 1_000_000),
                    'endTimeUnixNano': str(started + t1 * 1_000_000),
                    'attributes': attrs({**common, **span_detail(sid, name, kind)})}
            if parent:
                span['parentSpanId'] = ids[parent]
                if fault == 'broken_link' and tx == target and sid == 'idrepo-server':
                    # Lost context propagation: the server span no longer points to its caller.
                    span['parentSpanId'] = deterministic_id(seed, run_id, tx_id, 'lost-parent', 16)
            spans_by_svc.setdefault(svc, []).append(span)
            if sid == 'root':
                roots.append((duration_ms / 1000, trace_id, ids[sid], started, tx_id))
            if kind == 2:
                method, route = name.split(' ', 1)
                server_calls.setdefault(svc, []).append(((t1 - t0) / 1000, trace_id, ids[sid],
                                                          started + t0 * 1_000_000, tx_id, method, route))
            if name in EVENTS:
                t = str(started + t0 * 1_000_000)
                logs.append({'_svc': svc, 'timeUnixNano': t, 'observedTimeUnixNano': t,
                             'severityNumber': 9, 'severityText': 'INFO', 'eventName': name,
                             'traceId': trace_id, 'spanId': ids[sid],
                             'body': {'stringValue': json.dumps({'event_name': name, 'run_id': run_id,
                                   'transaction_id': tx_id, 'synthetic_effect_id': value,
                                   'trace_id': trace_id, 'span_id': ids[sid],
                                   'result': 'success'}, sort_keys=True, separators=(',', ':'))},
                             'attributes': attrs({'oaef.run.id': run_id, 'oaef.transaction.id': tx_id,
                                                  'oaef.synthetic.effect.id': value, 'oaef.result': 'success'})})
        ledger.append({'transaction_id': tx_id, 'synthetic_effect_id': value,
                       'outcome': 'activated', 'upload_to_assignment_ms': duration_ms})
    if fault in ('missing', 'duplicate', 'wrong_value'):
        event_name = EVENTS[1]
        matching = [r for r in logs if av(r['attributes']).get('oaef.transaction.id') == f'TX-{target:03d}'
                    and r['eventName'] == event_name]
        if len(matching) != 1:
            raise RuntimeError('expected single mutation target')
        original = matching[0]
        if fault == 'missing':
            logs.remove(original)
        elif fault == 'duplicate':
            duplicate = copy.deepcopy(original)
            # Distinct log emission, SAME logical business effect. Loki may deduplicate
            # identical timestamp/body records; this is not an OTLP transport retry.
            duplicate['timeUnixNano'] = str(int(original['timeUnixNano']) + 1000)
            duplicate['observedTimeUnixNano'] = duplicate['timeUnixNano']
            logs.append(duplicate)
        elif fault == 'wrong_value':
            for a in original['attributes']:
                if a['key'] == 'oaef.synthetic.effect.id':
                    a['value']['stringValue'] = 'CORRUPTED'
            body = json.loads(original['body']['stringValue'])
            body['synthetic_effect_id'] = 'CORRUPTED'
            original['body']['stringValue'] = json.dumps(body, sort_keys=True, separators=(',', ':'))
    histogram_counts = [sum(1 for d in durations if d <= b) for b in BOUNDS]
    bucket_counts = []
    previous = 0
    for n in histogram_counts:
        bucket_counts.append(str(n - previous))
        previous = n
    bucket_counts.append(str(count - previous))
    actual_count = count + (1 if fault == 'metric_count' else 0)
    if fault == 'metric_count':
        # Corrupt the business-to-metric count without constructing an invalid
        # histogram: an extra 0.12s measurement is counted in the first bucket.
        bucket_counts[1] = str(int(bucket_counts[1]) + 1)
    # Exemplars: the slowest transaction of each non-empty bucket, as a navigation aid to its trace.
    # Not evidence of count completeness.
    exemplars, seen_buckets = [], set()
    for d, trace_id, span_id, started, tx_id in sorted(roots, reverse=True):
        bucket = next((i for i, b in enumerate(BOUNDS) if d <= b), len(BOUNDS))
        if bucket not in seen_buckets:
            seen_buckets.add(bucket)
            exemplars.append({'timeUnixNano': str(started), 'asDouble': d, 'traceId': trace_id, 'spanId': span_id,
                              'filteredAttributes': attrs({'oaef.transaction.id': tx_id})})
    metric = {'name': contract['metric_name'], 'unit': contract['metric_unit'],
              'histogram': {'aggregationTemporality': 2, 'dataPoints': [{
                  'attributes': attrs({'oaef.simulation.mode': 'S1', 'oaef.run.id': run_id}),
                  'startTimeUnixNano': str(base),
                  'timeUnixNano': str(base + (count + 1) * tx_spacing),
                  'count': str(actual_count), 'sum': sum(durations) + (0.12 if fault == 'metric_count' else 0),
                  'explicitBounds': BOUNDS, 'bucketCounts': bucket_counts, 'exemplars': exemplars}]}}
    service_metrics = []
    for svc, calls in sorted(server_calls.items()):
        if fault == 'missing_metric' and svc == 'idgenerator':
            continue   # the service is not instrumented for metrics: traces exist, the metric does not
        for method, route in sorted({(c[5], c[6]) for c in calls}):
            rows = [c for c in calls if (c[5], c[6]) == (method, route)]
            service_metrics.append({'resource': resource(svc), 'scopeMetrics': [{'scope': {'name': 'oaef.v5.s1'},
                'metrics': [{'name': 'http.server.request.duration', 'unit': 's', 'histogram': {
                    'aggregationTemporality': 2, 'dataPoints': [histogram_point(
                        rows, base, base + (count + 1) * tx_spacing,
                        {'http.request.method': method, 'http.route': route, 'http.response.status_code': 200,
                         'oaef.run.id': run_id})]}}]}]})
    logs_by_svc = {}
    for r in logs:
        logs_by_svc.setdefault(r.pop('_svc'), []).append(r)
    otlp = {'traces': {'resourceSpans': [{'resource': resource(svc),
                                         'scopeSpans': [{'scope': {'name': 'oaef.v5.s1'}, 'spans': spans}]}
                                        for svc, spans in spans_by_svc.items()]},
            'logs': {'resourceLogs': [{'resource': resource(svc),
                                      'scopeLogs': [{'scope': {'name': 'oaef.v5.s1'}, 'logRecords': rows}]}
                                     for svc, rows in sorted(logs_by_svc.items())]},
            'metrics': {'resourceMetrics': [{'resource': {'attributes': attrs({
                            'service.name': 'oaef-s1-simulator', 'service.namespace': 'oaef',
                            'deployment.environment.name': 'test-int', 'oaef.simulation.mode': 'S1'})},
                                            'scopeMetrics': [{'scope': {'name': 'oaef.v5.s1'}, 'metrics': [metric]}]}]
                                            + service_metrics}}
    dump(out / 'contract.json', contract)
    dump(out / 'ledger.json', ledger)
    dump(out / 'observed.json', otlp)
    dump(out / 'manifest.json', {'run_id': run_id, 'mode': 'S1', 'seed': seed,
                                  'transactions': count, 'fault': fault, 'target': target,
                                  'scope': contract['scope'], 'contract_sha256': hashlib.sha256(CONTRACT.read_bytes()).hexdigest(),
                                  'contract_snapshot_sha256': hashlib.sha256((out / 'contract.json').read_bytes()).hexdigest(),
                                  'otlp_status': 'not_requested' if not otlp_url else 'attempted'})
    print('run id:', run_id, '| example trace id:', roots[0][1])
    if otlp_url:
        sent = emit(otlp_url, otlp)  # offline verdict below does not prove remote ingestion
        manifest = load(out / 'manifest.json')
        manifest.update({'emitted_at_ns': str(time.time_ns()), 'emitted': sent})
        dump(out / 'manifest.json', manifest)
    return verify(out)


def verify(out, observed_name='observed.json', verdict_name='verdict.json', check_metrics=True, source=None):
    if load(out / 'contract.json').get('schema', '').startswith('oaef.contract/v3'):
        from v5_spec_run import verify_spec   # compiled specification contract (C1)
        return verify_spec(out, observed_name, verdict_name, check_metrics, source)
    contract = load(out / 'contract.json')
    ledger = load(out / 'ledger.json')
    otlp = load(out / observed_name)
    manifest = load(out / 'manifest.json')
    expected_spans = contract['journey_spans']
    checks = []
    evaluated = Counter()

    def family(code):
        for prefix in ('SPAN-PRESENT', 'SPAN-PARENT', 'EVENT-EXACT'):
            if code.startswith(prefix):
                return prefix
        return code

    def check(code, actual, expected, tx=None, ref=None):
        ok = actual == expected
        evaluated[family(code)] += 1
        if not ok:
            checks.append({'check_id': code, 'transaction_id': tx, 'expected': expected,
                           'actual': actual, 'status': 'FAIL', **({'ref': ref} if ref else {})})
        return ok

    records = all_logs(otlp)
    spans = all_spans(otlp)
    all_ids = [x['transaction_id'] for x in ledger]
    check('RUN-LEDGER-CARDINALITY', len(ledger), manifest['transactions'])
    check('RUN-UNIQUE-TRANSACTIONS', len(set(all_ids)), manifest['transactions'])
    check('RUN-SPAN-COUNT', len(spans), len(ledger) * len(expected_spans))
    check('RUN-EVENT-COUNT', len(records), len(ledger) * len(contract['required_events']))
    by_tx = {}
    span_by_tx = {}
    for s in spans:
        span_by_tx.setdefault(av(s['attributes']).get('oaef.transaction.id'), []).append(s)
    for r in records:
        by_tx.setdefault(av(r['attributes']).get('oaef.transaction.id'), []).append(r)
    for entry in ledger:
        tx = entry['transaction_id']
        rows = by_tx.get(tx, [])
        tx_spans = span_by_tx.get(tx, [])
        check('SPAN-TX-COUNT', len(tx_spans), len(expected_spans), tx)
        check('SPAN-TX-TRACE', len({s['traceId'] for s in tx_spans}), 1, tx)
        # Span tree: each expected span exactly once (service, name, kind), under the expected parent.
        by_key = {}
        for s in tx_spans:
            by_key.setdefault((s['_svc'], s['name'], span_kind(s)), []).append(s)
        matched = {}
        for e in expected_spans:
            found = by_key.get((e['service'], e['name'], e['kind']), [])
            if check('SPAN-PRESENT-' + e['id'], len(found), 1, tx, e['id']):
                matched[e['id']] = found[0]
        for e in expected_spans:
            if e['id'] in matched and (e['parent'] is None or e['parent'] in matched):
                want = matched[e['parent']]['spanId'] if e['parent'] else ''
                check('SPAN-PARENT-' + e['id'], matched[e['id']].get('parentSpanId') or '', want, tx, e['id'])
        for name in contract['required_events']:
            check('SPAN-EVENT-COUNT', len([s for s in tx_spans if s['name'] == name]), 1, tx, name)
            selected = [r for r in rows if r.get('eventName') == name]
            check('EVENT-EXACT-' + name, len(selected), 1, tx, name)
            for r in selected:
                a = av(r['attributes'])
                check('EVENT-EFFECT-VALUE', a.get('oaef.synthetic.effect.id'),
                      entry['synthetic_effect_id'], tx, name)
                check('EVENT-TRACE-CORRELATION',
                      any(s['traceId'] == r['traceId'] and s['spanId'] == r['spanId']
                          and av(s['attributes']).get('oaef.transaction.id') == tx for s in spans), True, tx, name)
        starts = {r['eventName']: int(r['timeUnixNano']) for r in rows
                  if r.get('eventName') in contract['required_events']}
        if len(starts) == len(contract['required_events']):
            check('EVENT-PARTIAL-ORDER', [starts[x] for x in contract['required_events']] ==
                  sorted(starts.values()), True, tx)
        evaluated['NFR-DEMO-LATENCY'] += 1
        if entry['upload_to_assignment_ms'] > contract['max_upload_to_assignment_ms']:
            check('NFR-DEMO-LATENCY', {'upload_to_assignment_ms': entry['upload_to_assignment_ms']},
                  {'max_upload_to_assignment_ms': contract['max_upload_to_assignment_ms']}, tx)
    check('RUN-UNKNOWN-TRANSACTIONS', sorted(set(by_tx) - set(all_ids)), [])
    check('RUN-UNKNOWN-SPAN-TRANSACTIONS', sorted(set(span_by_tx) - set(all_ids)), [])
    if check_metrics:
        metric = otlp['metrics']['resourceMetrics'][0]['scopeMetrics'][0]['metrics'][0]
        point = metric['histogram']['dataPoints'][0]
        check('METRIC-NAME', metric['name'], contract['metric_name'])
        check('METRIC-UNIT', metric['unit'], contract['metric_unit'])
        check('METRIC-COUNT', int(point['count']), len(ledger))
        check('METRIC-BUCKET-TOTAL', sum(map(int, point['bucketCounts'])), len(ledger))
        check('METRIC-SUM', round(point['sum'], 6),
              round(sum(x['upload_to_assignment_ms'] / 1000 for x in ledger), 6))
        emitted = {}
        for group in otlp['metrics']['resourceMetrics'][1:]:
            svc = av(group['resource']['attributes']).get('service.name')
            for mt in group['scopeMetrics'][0]['metrics']:
                for dp in mt['histogram']['dataPoints']:
                    emitted[(svc, av(dp['attributes']).get('http.route'))] = (int(dp['count']), dp['sum'])
        for mc in service_metric_checks(contract, ledger, spans, emitted):
            check(mc['check_id'], mc['actual'], mc['expected'], None, mc['check_id'].split('-', 3)[-1])
    status = 'FAIL' if checks else 'PASS'
    verdict = {'run_id': manifest['run_id'], 'mode': 'S1', 'source': source or 'stored synthetic emitted payload only',
               'backend_ingestion_verified': False,
               'count_expected_transactions': len(ledger),
               'count_observed_events': len(records),
               'count_expected_events': len(ledger) * len(contract['required_events']),
               'count_observed_spans': len(spans),
               'count_expected_spans': len(ledger) * len(expected_spans),
               'status': status, 'failures': checks,
               'evaluated': {f: {'evaluated': n, 'failed': sum(1 for c in checks if family(c['check_id']) == f)}
                             for f, n in sorted(evaluated.items())},
               'margins': {'max_upload_to_assignment_ms': max((x['upload_to_assignment_ms'] for x in ledger), default=0),
                           'threshold_ms': contract['max_upload_to_assignment_ms']}}
    dump(out / verdict_name, verdict)
    print(f"{status}: {len(ledger)} tx; expected events {verdict['count_expected_events']}; "
          f"observed {len(records)}; spans {len(spans)}/{verdict['count_expected_spans']}; failed checks {len(checks)}")
    for x in checks[:8]:
        print('  ', x['check_id'], x.get('transaction_id'), 'expected', x['expected'], 'actual', x['actual'])
    return status == 'PASS'


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest='command', required=True)
    run = sub.add_parser('run')
    run.add_argument('--count', type=int, default=100)
    run.add_argument('--seed', type=int, default=20261105)
    run.add_argument('--fault', choices=['none', 'duplicate', 'missing', 'wrong_value', 'slow', 'metric_count', 'broken_link',
                                           'missing_metric'], default='none')
    run.add_argument('--target', type=int, default=1)
    run.add_argument('--out', type=Path, required=True)
    run.add_argument('--otlp', help='Optional OTLP/HTTP collector base URL')
    run.add_argument('--contract', choices=['legacy', 'spec'], default=os.environ.get('OAEF_CONTRACT', 'spec'),
                     help='spec (default): compiled specification (generated/contracts); '
                          'legacy: hand-written V5 slice, kept for the regression baseline')
    verify_cmd = sub.add_parser('verify')
    verify_cmd.add_argument('--out', type=Path, required=True)
    args = p.parse_args(argv)
    try:
        if args.command == 'run' and args.contract == 'spec':
            from v5_spec_run import generate_spec
            valid = generate_spec(args.count, args.seed, args.fault, args.target, args.out, args.otlp, emit)
        else:
            valid = generate(args.count, args.seed, args.fault, args.target, args.out, args.otlp) if args.command == 'run' else verify(args.out)
    except (ValueError, OSError, KeyError, RuntimeError) as e:
        print('ERROR:', e, file=sys.stderr)
        return 2
    return 0 if valid else 1


if __name__ == '__main__':
    raise SystemExit(main())
