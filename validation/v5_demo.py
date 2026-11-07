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


def dump(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + '\n', encoding='utf-8')


def load(path):
    return json.loads(path.read_text(encoding='utf-8'))


def deterministic_id(seed, run, tx, stage, width):
    return hashlib.sha256(f'{seed}|{run}|{tx}|{stage}'.encode()).hexdigest()[:width]


def emit(endpoint, otlp):
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


def generate(count, seed, fault, target, out, otlp_url):
    if count < 1 or target < 1 or target > count:
        raise ValueError('count must be positive, target must be within count')
    contract = load(CONTRACT)
    rng = random.Random(seed)
    run_id = 's1-' + (uuid.uuid4().hex[:12] if otlp_url else deterministic_id(seed, count, 'run', 'id', 12))
    # Live export must use recent timestamps so traces/logs are discoverable in Grafana.
    # Offline runs stay byte-for-byte deterministic for a fixed seed and count.
    base = time.time_ns() - 30_000_000_000 if otlp_url else 1_800_000_000_000_000_000
    tx_spacing = 200_000_000 if otlp_url else 5_000_000_000
    source = attrs({'service.name': 'oaef-s1-simulator', 'service.namespace': 'oaef',
                    'deployment.environment.name': 'test-int', 'oaef.simulation.mode': 'S1'})
    spans, logs, ledger = [], [], []
    durations = []
    for tx in range(1, count + 1):
        tx_id = f'TX-{tx:03d}'
        trace_id = deterministic_id(seed, run_id, tx_id, 'trace', 32)
        value = f'SYN-{seed:06d}-{tx:06d}'
        duration_ms = rng.randint(75, 180)
        if fault == 'slow' and tx == target:
            duration_ms = contract['max_upload_to_assignment_ms'] + 150
        durations.append(duration_ms / 1000)
        started = base + tx * tx_spacing
        prev = ''
        for i, event in enumerate(EVENTS):
            span_id = deterministic_id(seed, run_id, tx_id, str(i), 16)
            t = started + (duration_ms * 1_000_000 * i // 2)
            span = {'traceId': trace_id, 'spanId': span_id,
                    'name': event, 'kind': 1,
                    'startTimeUnixNano': str(t), 'endTimeUnixNano': str(t + 1_000_000),
                    'attributes': attrs({'oaef.run.id': run_id, 'oaef.transaction.id': tx_id,
                                         'oaef.simulation.mode': 'S1', 'oaef.synthetic.effect.id': value,
                                         'test.case.name': 'NIN-001'})}
            if prev:
                span['parentSpanId'] = prev
            spans.append(span)
            record = {'timeUnixNano': str(t), 'observedTimeUnixNano': str(t),
                      'severityNumber': 9, 'severityText': 'INFO', 'eventName': event,
                      'traceId': trace_id, 'spanId': span_id,
                      'body': {'stringValue': json.dumps({'event_name': event, 'run_id': run_id,
                            'transaction_id': tx_id, 'synthetic_effect_id': value,
                            'trace_id': trace_id, 'span_id': span_id,
                            'result': 'success'}, sort_keys=True, separators=(',', ':'))},
                      'attributes': attrs({'oaef.run.id': run_id, 'oaef.transaction.id': tx_id,
                                           'oaef.synthetic.effect.id': value, 'oaef.result': 'success'})}
            logs.append(record)
            prev = span_id
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
    metric = {'name': contract['metric_name'], 'unit': contract['metric_unit'],
              'histogram': {'aggregationTemporality': 2, 'dataPoints': [{
                  'attributes': attrs({'oaef.simulation.mode': 'S1', 'oaef.run.id': run_id}),
                  'startTimeUnixNano': str(base),
                  'timeUnixNano': str(base + (count + 1) * tx_spacing),
                  'count': str(actual_count), 'sum': sum(durations) + (0.12 if fault == 'metric_count' else 0),
                  'explicitBounds': BOUNDS, 'bucketCounts': bucket_counts}]}}
    otlp = {'traces': {'resourceSpans': [{'resource': {'attributes': source},
                                        'scopeSpans': [{'scope': {'name': 'oaef.v5.s1'}, 'spans': spans}]}]},
            'logs': {'resourceLogs': [{'resource': {'attributes': source},
                                      'scopeLogs': [{'scope': {'name': 'oaef.v5.s1'}, 'logRecords': logs}]}]},
            'metrics': {'resourceMetrics': [{'resource': {'attributes': source},
                                            'scopeMetrics': [{'scope': {'name': 'oaef.v5.s1'}, 'metrics': [metric]}]}]}}
    dump(out / 'contract.json', contract)
    dump(out / 'ledger.json', ledger)
    dump(out / 'observed.json', otlp)
    dump(out / 'manifest.json', {'run_id': run_id, 'mode': 'S1', 'seed': seed,
                                  'transactions': count, 'fault': fault, 'target': target,
                                  'scope': contract['scope'], 'contract_sha256': hashlib.sha256(CONTRACT.read_bytes()).hexdigest(),
                                  'contract_snapshot_sha256': hashlib.sha256((out / 'contract.json').read_bytes()).hexdigest(),
                                  'otlp_status': 'not_requested' if not otlp_url else 'attempted'})
    print('run id:', run_id, '| example trace id:', spans[0]['traceId'])
    if otlp_url:
        emit(otlp_url, otlp)  # offline verdict below does not prove remote ingestion
    return verify(out)


def verify(out, observed_name='observed.json', verdict_name='verdict.json', check_metrics=True, source=None):
    contract = load(out / 'contract.json')
    ledger = load(out / 'ledger.json')
    otlp = load(out / observed_name)
    manifest = load(out / 'manifest.json')
    checks = []

    def check(code, actual, expected, tx=None):
        ok = actual == expected
        if not ok:
            checks.append({'check_id': code, 'transaction_id': tx, 'expected': expected,
                           'actual': actual, 'status': 'FAIL'})
        return ok

    records = [r for group in otlp['logs']['resourceLogs'] for scope in group['scopeLogs']
               for r in scope['logRecords']]
    spans = [s for group in otlp['traces']['resourceSpans'] for scope in group['scopeSpans']
             for s in scope['spans']]
    all_ids = [x['transaction_id'] for x in ledger]
    check('RUN-LEDGER-CARDINALITY', len(ledger), manifest['transactions'])
    check('RUN-UNIQUE-TRANSACTIONS', len(set(all_ids)), manifest['transactions'])
    check('RUN-SPAN-COUNT', len(spans), len(ledger) * len(contract['required_events']))
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
        check('SPAN-TX-COUNT', len(tx_spans), len(contract['required_events']), tx)
        check('SPAN-TX-TRACE', len({s['traceId'] for s in tx_spans}), 1, tx)
        for name in contract['required_events']:
            check('SPAN-EVENT-COUNT', len([s for s in tx_spans if s['name'] == name]), 1, tx)
            selected = [r for r in rows if r.get('eventName') == name]
            check('EVENT-EXACT-' + name, len(selected), 1, tx)
            for r in selected:
                a = av(r['attributes'])
                check('EVENT-EFFECT-VALUE', a.get('oaef.synthetic.effect.id'),
                      entry['synthetic_effect_id'], tx)
                check('EVENT-TRACE-CORRELATION',
                      any(s['traceId'] == r['traceId'] and s['spanId'] == r['spanId']
                          and av(s['attributes']).get('oaef.transaction.id') == tx for s in spans), True, tx)
        starts = {r['eventName']: int(r['timeUnixNano']) for r in rows
                  if r.get('eventName') in contract['required_events']}
        if len(starts) == len(contract['required_events']):
            check('EVENT-PARTIAL-ORDER', [starts[x] for x in contract['required_events']] ==
                  sorted(starts.values()), True, tx)
        check('NFR-DEMO-LATENCY', entry['upload_to_assignment_ms'] <=
              contract['max_upload_to_assignment_ms'], True, tx)
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
    status = 'FAIL' if checks else 'PASS'
    verdict = {'run_id': manifest['run_id'], 'mode': 'S1', 'source': source or 'stored synthetic emitted payload only',
               'backend_ingestion_verified': False,
               'count_expected_transactions': len(ledger),
               'count_observed_events': len(records),
               'count_expected_events': len(ledger) * len(contract['required_events']),
               'status': status, 'failures': checks}
    dump(out / verdict_name, verdict)
    print(f"{status}: {len(ledger)} tx; expected events {verdict['count_expected_events']}; "
          f"observed {len(records)}; failed checks {len(checks)}")
    for x in checks[:8]:
        print('  ', x['check_id'], x.get('transaction_id'), 'expected', x['expected'], 'actual', x['actual'])
    return status == 'PASS'


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest='command', required=True)
    run = sub.add_parser('run')
    run.add_argument('--count', type=int, default=100)
    run.add_argument('--seed', type=int, default=20261105)
    run.add_argument('--fault', choices=['none', 'duplicate', 'missing', 'wrong_value', 'slow', 'metric_count'], default='none')
    run.add_argument('--target', type=int, default=1)
    run.add_argument('--out', type=Path, required=True)
    run.add_argument('--otlp', help='Optional OTLP/HTTP collector base URL')
    verify_cmd = sub.add_parser('verify')
    verify_cmd.add_argument('--out', type=Path, required=True)
    args = p.parse_args(argv)
    try:
        valid = generate(args.count, args.seed, args.fault, args.target, args.out, args.otlp) if args.command == 'run' else verify(args.out)
    except (ValueError, OSError, KeyError, RuntimeError) as e:
        print('ERROR:', e, file=sys.stderr)
        return 2
    return 0 if valid else 1


if __name__ == '__main__':
    raise SystemExit(main())
