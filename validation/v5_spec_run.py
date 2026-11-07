#!/usr/bin/env python3
"""V5 run on the compiled specification contract (C1): generation, oracle evaluation, metric reconciliation.

Called by v5_demo.py when the contract is oaef.contract/v3 (generated/contracts/NIN-001.contract.json).
The legacy hand-written contract path stays available (--contract legacy) until C7.
"""
import hashlib
import json
from pathlib import Path
import random
import re
import time
import uuid

from oaef_oracle import Evaluator, attr_dict
from v5_sim_spec import kv, normalise, run_context, to_otlp, transaction

ROOT = Path(__file__).resolve().parents[1]
SPEC_CONTRACT = ROOT / 'generated' / 'contracts' / 'NIN-001.contract.json'
AGENT_BOUNDS = [0.005, 0.01, 0.025, 0.05, 0.075, 0.1, 0.25, 0.5, 0.75, 1, 2.5, 5, 7.5, 10]   # OTel agent defaults


def dump(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + '\n', encoding='utf-8')


def load(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def histogram(values, bounds, start_ns, time_ns, attrs, exemplar_rows=()):
    """Cumulative OTLP histogram point; exemplars = slowest row of each bucket (navigation aid only)."""
    cum = [sum(1 for v in values if v <= b) for b in bounds]
    buckets = [str(n - p) for n, p in zip(cum, [0] + cum[:-1])] + [str(len(values) - (cum[-1] if cum else 0))]
    ex, seen = [], set()
    for v, trace_id, span_id, t, tx in sorted(exemplar_rows, reverse=True):
        b = next((i for i, x in enumerate(bounds) if v <= x), len(bounds))
        if b not in seen:
            seen.add(b)
            ex.append({'timeUnixNano': str(t), 'asDouble': v, 'traceId': trace_id, 'spanId': span_id,
                       'filteredAttributes': [kv('oaef.transaction.id', tx)]})
    return {'attributes': [kv(k, v) for k, v in sorted(attrs.items())], 'startTimeUnixNano': str(start_ns),
            'timeUnixNano': str(time_ns), 'count': str(len(values)), 'sum': round(sum(values), 6),
            'explicitBounds': bounds, 'bucketCounts': buckets, 'exemplars': ex}


def generate_spec(count, seed, fault, target, out, otlp_url, emit):
    if count < 1 or target < 1 or target > count:
        raise ValueError('count must be positive, target must be within count')
    contract = load(SPEC_CONTRACT)
    rng = random.Random(seed)
    run_id = 's1-' + (uuid.uuid4().hex[:12] if otlp_url else hashlib.sha256(f'{seed}|{count}|spec'.encode()).hexdigest()[:12])
    base = time.time_ns() - 8_000_000_000 if otlp_url else 1_800_000_000_000_000_000
    spacing = 50_000_000 if otlp_url else 5_000_000_000
    ctx = run_context(run_id)
    all_spans, all_records, ledger, journey = [], [], [], []
    for tx in range(1, count + 1):
        started = base + tx * spacing
        spans, records, truth = transaction(seed, run_id, tx, started, rng.randint(75, 180), fault, target, ctx)
        all_spans += spans
        all_records += records
        t_rec = {r['eventName']: int(r['timeUnixNano']) for _, r in records if r['eventName']}
        root = next(s for _, s in spans if not s.get('parentSpanId') and s['traceId'] == truth['trace_root'])
        if 'mosip.registration.packet.received' in t_rec and 'mosip.identity.uin.assigned' in t_rec:
            secs = (t_rec['mosip.identity.uin.assigned'] - t_rec['mosip.registration.packet.received']) / 1e9
        else:   # the business step happened (simulator truth) even when its event was not emitted
            secs = None
        truth['upload_to_assignment_s'] = secs
        ledger.append(truth)
        if secs is not None:
            journey.append((round(secs, 6), truth['trace_root'], root['spanId'], started, truth['transaction_id']))
    # metrics: journey histogram (run-isolated) + http.server.request.duration per server span, like an OTel agent
    t_end = base + (count + 1) * spacing
    jh = contract['run_isolated_metrics']['journey_histogram']
    values = [j[0] for j in journey]
    if fault == 'metric_count':
        values.append(0.12)   # one measurement too many, histogram stays internally consistent
    metrics = [{'resource': {'attributes': [kv('service.name', 'oaef-s1-simulator'), kv('service.namespace', 'oaef'),
                                            kv('deployment.environment.name', ctx['env.name']), kv('oaef.simulation.mode', 'S1')]},
                'scopeMetrics': [{'scope': {'name': 'oaef.v5.s1'}, 'metrics': [{'name': jh['name'], 'unit': jh['unit'],
                    'histogram': {'aggregationTemporality': 2, 'dataPoints': [histogram(
                        values, jh['explicitBounds'], base, t_end, {'oaef.simulation.mode': 'S1', 'oaef.run.id': run_id},
                        journey)]}}]}]}]
    servers = {}
    for svc, s in all_spans:
        if s['kind'] == 2 and ' ' in s['name']:
            method, route = s['name'].split(' ', 1)
            d = (int(s['endTimeUnixNano']) - int(s['startTimeUnixNano'])) / 1e9
            servers.setdefault((svc, method, route), []).append(
                (round(d, 6), s['traceId'], s['spanId'], int(s['startTimeUnixNano']), s['attributes']['oaef.transaction.id']))
    from v5_sim_spec import resource
    for (svc, method, route), rows in sorted(servers.items()):
        if fault == 'missing_metric' and svc == 'idgenerator':
            continue   # the service is not instrumented for metrics: traces exist, the metric does not
        metrics.append({'resource': {'attributes': [kv(k, v) for k, v in sorted(resource(svc, ctx).items())]},
                        'scopeMetrics': [{'scope': {'name': 'io.opentelemetry.http'}, 'metrics': [{
                            'name': 'http.server.request.duration', 'unit': 's', 'histogram': {
                                'aggregationTemporality': 2, 'dataPoints': [histogram(
                                    [r[0] for r in rows], AGENT_BOUNDS, base, t_end,
                                    {'http.request.method': method, 'http.route': route, 'http.response.status_code': 200,
                                     'oaef.run.id': run_id}, rows)]}}]}]})
    traces, logs = to_otlp(all_spans, all_records, ctx)
    otlp = {'traces': traces, 'logs': logs, 'metrics': {'resourceMetrics': metrics}}
    dump(out / 'contract.json', contract)
    dump(out / 'ledger.json', ledger)
    dump(out / 'observed.json', otlp)
    dump(out / 'manifest.json', {'run_id': run_id, 'mode': 'S1', 'seed': seed, 'transactions': count, 'fault': fault,
                                  'target': target, 'contract_kind': 'spec', 'context': ctx,
                                  'scope': 'S1 simulation of the NIN-001 specification; not MOSIP verification',
                                  'contract_sha256': hashlib.sha256(SPEC_CONTRACT.read_bytes()).hexdigest(),
                                  'contract_snapshot_sha256': hashlib.sha256((out / 'contract.json').read_bytes()).hexdigest(),
                                  'otlp_status': 'not_requested' if not otlp_url else 'attempted'})
    print('run id:', run_id, '| contract: specification (compiled) | example trace id:', ledger[0]['trace_root'])
    if otlp_url:
        sent = emit(otlp_url, otlp)
        m = load(out / 'manifest.json')
        m.update({'emitted_at_ns': str(time.time_ns()), 'emitted': sent})
        dump(out / 'manifest.json', m)
    return verify_spec(out)


def series_from_otlp(otlp):
    """[{service, method, route, count, sum}] for http.server.request.duration in an OTLP metrics payload."""
    out = []
    for g in otlp.get('metrics', {}).get('resourceMetrics', []):
        svc = attr_dict(g.get('resource', {}).get('attributes')).get('service.name')
        for sc in g.get('scopeMetrics', []):
            for m in sc.get('metrics', []):
                if m.get('name') != 'http.server.request.duration':
                    continue
                for dp in m['histogram']['dataPoints']:
                    a = attr_dict(dp['attributes'])
                    out.append({'service': svc, 'method': a.get('http.request.method'), 'route': a.get('http.route'),
                                'count': int(dp['count']), 'sum': float(dp['sum'])})
    return out


def metric_checks_spec(contract, ledger, spans, series):
    """Run-isolated metrics: count = transactions x per_transaction (ledger); sum = durations of the retrieved
    server spans with the same service, method and route (traces). Missing series -> actual None."""
    out = []
    for m in contract['run_isolated_metrics'].get('service_metrics', []):
        route_re = re.compile(m['route_re'])
        rows = [x for x in series if x['service'] == m['service'] and x['method'] == m['method']
                and x['route'] and route_re.match(x['route'])]
        sp = [s for s in spans if s['_svc'] == m['service'] and (s.get('kind') in (2, 'SPAN_KIND_SERVER'))
              and s['name'].startswith(m['method'] + ' ') and route_re.match(s['name'].split(' ', 1)[1])]
        span_sum = round(sum(int(s['endTimeUnixNano']) - int(s['startTimeUnixNano']) for s in sp) / 1e9, 6)
        tag = f'{m["service"]}.{m["alias"]}'
        out.append({'check_id': f'METRIC-SVC-COUNT-{tag}', 'obligation_id': f'OBL-METRICS-service.{m["alias"]}',
                    'expected': len(ledger) * m['per_transaction'], 'actual': sum(r['count'] for r in rows) if rows else None,
                    'ref': m['alias'], 'requirement_refs': m.get('requirements', [])})
        out.append({'check_id': f'METRIC-SVC-SUM-{tag}', 'obligation_id': f'OBL-METRICS-service.{m["alias"]}',
                    'expected': span_sum, 'actual': round(sum(r['sum'] for r in rows), 6) if rows else None,
                    'ref': m['alias'], 'requirement_refs': m.get('requirements', [])})
    for c in out:
        if c['actual'] is None:
            c['status'] = 'INCONCLUSIVE'
        elif c['check_id'].startswith('METRIC-SVC-SUM-'):
            c['status'] = 'PASS' if abs(c['actual'] - c['expected']) <= 1e-3 else 'FAIL'
        else:
            c['status'] = 'PASS' if c['actual'] == c['expected'] else 'FAIL'
    return out


def journey_checks(contract, ledger, otlp):
    """Journey histogram of the run against the simulated business truth (S1 source side)."""
    jh = contract['run_isolated_metrics']['journey_histogram']
    point = None
    for g in otlp['metrics']['resourceMetrics']:
        for sc in g['scopeMetrics']:
            for m in sc['metrics']:
                if m['name'] == jh['name']:
                    point, unit = m['histogram']['dataPoints'][0], m.get('unit')
    if point is None:
        return [{'check_id': 'METRIC-COUNT', 'expected': len(ledger), 'actual': None, 'status': 'FAIL'}]
    measured = [x['upload_to_assignment_s'] for x in ledger if x['upload_to_assignment_s'] is not None]
    rows = [('METRIC-UNIT', jh['unit'], unit), ('METRIC-COUNT', len(measured), int(point['count'])),
            ('METRIC-BUCKET-TOTAL', len(measured), sum(map(int, point['bucketCounts']))),
            ('METRIC-SUM', round(sum(measured), 6), round(point['sum'], 6))]
    return [{'check_id': c, 'obligation_id': 'OBL-METRICS-journey_histogram', 'expected': e, 'actual': a,
             'status': 'PASS' if e == a else 'FAIL', 'requirement_refs': jh.get('requirements', [])} for c, e, a in rows]


def evaluate_transactions(contract, ledger, manifest, spans, records):
    ev = Evaluator(contract)
    by_tx_s, by_tx_r = {}, {}
    for s in spans:
        by_tx_s.setdefault(attr_dict(s.get('attributes')).get('oaef.transaction.id'), []).append(s)
    for r in records:
        by_tx_r.setdefault(attr_dict(r.get('attributes')).get('oaef.transaction.id'), []).append(r)
    aliases = {}
    ctx0 = manifest.get('context') or run_context(manifest['run_id'])
    for t in ledger:
        tid = t['transaction_id']
        matched, _ = ev.evaluate(by_tx_s.get(tid, []), by_tx_r.get(tid, []),
                                 dict(ctx0, rid=t['rid'], uin=t['uin'], uin_hash=t['uin_hash']), tid)
        for alias, ss in matched.items():
            for s in ss:
                aliases[s['spanId']] = alias
    known = {t['transaction_id'] for t in ledger}
    unknown = sorted((set(by_tx_s) | set(by_tx_r)) - known - {None})
    ev.results.append({'check_id': 'RUN-UNKNOWN-TRANSACTIONS', 'obligation_id': 'RUN', 'transaction_id': None,
                       'requirement_refs': ['NF-08'], 'status': 'PASS' if not unknown else 'FAIL',
                       'expected': [], 'actual': unknown})
    return ev.results, aliases


def verify_spec(out, observed_name='observed.json', verdict_name='verdict.json', check_metrics=True, source=None):
    contract, ledger, manifest = load(out / 'contract.json'), load(out / 'ledger.json'), load(out / 'manifest.json')
    otlp = load(out / observed_name)
    spans, records = normalise(otlp['traces'], otlp['logs'])
    results, aliases = evaluate_transactions(contract, ledger, manifest, spans, records)
    metric = (journey_checks(contract, ledger, otlp) + metric_checks_spec(contract, ledger, spans, series_from_otlp(otlp))
              if check_metrics else [])
    failures = [dict(r) for r in results if r['status'] == 'FAIL']
    failures += [dict(m, status='FAIL') for m in metric if m['status'] != 'PASS']
    evaluated = {}
    for r in results + metric:
        e = evaluated.setdefault(r.get('obligation_id') or r['check_id'], {'evaluated': 0, 'failed': 0, 'not_evaluated': 0})
        if r['status'] == 'NOT_EVALUATED':
            e['not_evaluated'] += 1
        else:
            e['evaluated'] += 1
            e['failed'] += r['status'] != 'PASS'
    idrepo = [int(s['endTimeUnixNano']) - int(s['startTimeUnixNano']) for s in spans if aliases.get(s['spanId']) == 'IDREPO_CREATE_SERVER']
    budget = contract['nfr'].get('span_budgets_ms', {}).get('IDREPO_CREATE_SERVER', {}).get('$lte')
    status = 'FAIL' if failures else 'PASS'
    verdict = {'run_id': manifest['run_id'], 'mode': 'S1', 'contract': contract['schema'],
               'source': source or 'stored synthetic emitted payload only', 'backend_ingestion_verified': False,
               'count_expected_transactions': len(ledger), 'count_observed_events': sum(1 for r in records if r.get('eventName')),
               'count_observed_records': len(records), 'count_observed_spans': len(spans),
               'checks_evaluated': sum(1 for r in results + metric if r['status'] != 'NOT_EVALUATED'),
               'checks_not_evaluated': sum(1 for r in results if r['status'] == 'NOT_EVALUATED'),
               'status': status, 'failures': failures, 'metric_checks': metric, 'evaluated': evaluated,
               'margins': {'max_identity_creation_ms': round(max(idrepo) / 1e6, 1) if idrepo else None, 'budget_ms': budget},
               'span_aliases': aliases}
    dump(out / verdict_name, verdict)
    print(f"{status}: {len(ledger)} tx; {verdict['checks_evaluated']} checks evaluated, {len(failures)} failed, "
          f"{verdict['checks_not_evaluated']} not evaluated (later increments); spans {len(spans)}, records {len(records)}")
    for x in failures[:8]:
        print('  ', x['check_id'], x.get('transaction_id'), 'expected', x['expected'], 'actual', x['actual'],
              f"(consequence of {x['consequence_of']})" if x.get('consequence_of') else '')
    return status == 'PASS'


# ---------------------------------------------------------------------------- S2-read (backend) helpers
def records_from_loki_body(data, ts):
    """Rebuild an OTLP-like record from the JSON body the spec simulator writes (service, severity, ids, attributes)."""
    rec = {'timeUnixNano': str(int(ts)), 'severityNumber': data['severity_number'], 'severityText': data['severity_text'],
           'traceId': data['trace_id'], 'spanId': data['span_id'], 'body': {'stringValue': data.get('message') or ''},
           'attributes': [kv(k, v) for k, v in sorted((data.get('attributes') or {}).items())]}
    if data.get('event_name'):
        rec['eventName'] = data['event_name']
    return data['service'], rec


def series_from_prometheus(doc, run_id):
    """[{service, method, route, count, sum}] from an instant query on http_server_request_duration_seconds_(count|sum)."""
    rows = {}
    for row in (doc or {}).get('data', {}).get('result', []):
        m = row.get('metric', {})
        if m.get('oaef_run_id') != run_id:
            continue
        key = (m.get('service_name'), m.get('http_request_method'), m.get('http_route'))
        r = rows.setdefault(key, {'service': key[0], 'method': key[1], 'route': key[2], 'count': None, 'sum': None})
        v = float(row['value'][1])
        if m.get('__name__', '').endswith('_count'):
            r['count'] = int(v)
        elif m.get('__name__', '').endswith('_sum'):
            r['sum'] = v
    return [r for r in rows.values() if r['count'] is not None and r['sum'] is not None]


def journey_prom_checks(contract, ledger, series):
    """Journey histogram as stored in Prometheus ({(name, le): value}) against the simulated truth."""
    jh = contract['run_isolated_metrics']['journey_histogram']
    prefix = jh['name'].replace('.', '_')
    measured = [x['upload_to_assignment_s'] for x in ledger if x['upload_to_assignment_s'] is not None]
    out = []

    def ck(cid, expected, actual, tol=0):
        st = 'INCONCLUSIVE' if actual is None else ('PASS' if abs(actual - expected) <= tol else 'FAIL')
        out.append({'check_id': cid, 'obligation_id': 'OBL-METRICS-journey_histogram', 'expected': expected,
                    'actual': actual, 'status': st, 'requirement_refs': jh.get('requirements', [])})
    counts = [v for (n, le), v in series.items() if n.startswith(prefix) and n.endswith('_count')]
    sums = [v for (n, le), v in series.items() if n.startswith(prefix) and n.endswith('_sum')]
    ck('PROM-MEASUREMENTS-COUNT', len(measured), counts[0] if len(counts) == 1 else None)
    ck('PROM-MEASUREMENTS-SUM-S', round(sum(measured), 6), sums[0] if len(sums) == 1 else None, tol=1e-4)
    for b in jh['explicitBounds'] + ['+Inf']:
        vals = [v for (n, le), v in series.items() if n.startswith(prefix) and n.endswith('_bucket')
                and le and (le == '+Inf' if b == '+Inf' else le != '+Inf' and abs(float(le) - b) < 1e-9)]
        exp = len(measured) if b == '+Inf' else sum(m <= b for m in measured)
        ck(f'PROM-BUCKET-{b if b == "+Inf" else format(b, "g")}', exp, vals[0] if len(vals) == 1 else None)
    return out


def classify_spec(failures, metric_checks, backend_errors, trace_count, expected_traces, record_count,
                  expected_records, bad_logs, truncated):
    """PASS / FAIL / INCONCLUSIVE for the spec path, and the diagnostic classes.

    FAIL needs a proven violation (wrong value, broken relation, extra occurrence, NFR or duration breach,
    forbidden content, metric mismatch). A missing item is an evidence gap (INCONCLUSIVE) unless it is the
    consequence of a proven violation. Inconsistent Tempo replies void trace-based checks."""
    tempo_bad = 'tempo-consistency' in (backend_errors or {})
    root = [f for f in failures if not f.get('consequence_of')]
    if tempo_bad:
        root = [f for f in root if not f['check_id'].startswith('OBL-TRACES-')
                and not (f['check_id'].startswith('OBL-EVENTS-') and f['check_id'].endswith(':values'))]
        metric_checks = [m for m in metric_checks if not m['check_id'].startswith('METRIC-SVC-SUM-')]

    def proven(f):
        cid = f['check_id']
        if cid.startswith('OBL-NFR-') or cid.endswith((':values', ':parent', ':attributes', ':order', ':status',
                                                       ':duration', ':pii', ':error-status', ':every-event')):
            return True
        if cid.endswith(':count') or cid.endswith(':present'):
            try:
                return int(f['actual']) > int(f['expected'] if not isinstance(f['expected'], dict) else f['expected'].get('$lte', 10**9))
            except (TypeError, ValueError):
                return False
        return cid.startswith(('OBL-TRACES-COMMON', 'RUN-UNKNOWN')) and bool(f.get('actual'))
    hard = [f for f in root if proven(f)] + [m for m in metric_checks if m['status'] == 'FAIL']
    missing = (bool(backend_errors or truncated) or trace_count < expected_traces or record_count < expected_records
               or any(m['status'] == 'INCONCLUSIVE' for m in metric_checks)
               or any(not proven(f) for f in root) or bool(bad_logs))
    if hard:
        status = 'FAIL'
    elif missing:
        status = 'INCONCLUSIVE'
    else:
        status = 'PASS'
    if status == 'PASS':
        classes = ['S1_TELEMETRY_CONFORMANT']
    elif status == 'INCONCLUSIVE':
        classes = ['EVIDENCE_GAP']
    else:
        ids = [f['check_id'] for f in hard]
        classes = []
        if any(i.startswith('OBL-NFR-') or i.endswith(':duration') for i in ids):
            classes.append('NFR_VIOLATION')
        if any(i.endswith(':parent') for i in ids):
            classes.append('TRACE_CONTEXT_BROKEN')
        if any(i.startswith(('METRIC-', 'PROM-')) for i in ids):
            classes.append('METRIC_RECONCILIATION_FAILURE')
        if any(i.startswith(('OBL-EVENTS-', 'OBL-LOGS-', 'OBL-TRACES-', 'RUN-')) and not i.endswith(':parent')
               and not i.startswith('OBL-NFR-') and not i.endswith(':duration') for i in ids):
            classes.append('OBSERVABILITY_VIOLATION')
        classes = classes or ['OBSERVABILITY_VIOLATION']
    return status, classes
