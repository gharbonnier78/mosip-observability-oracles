#!/usr/bin/env python3
"""OAEF V5 S2-read: retrieve *backend* signals for a synthetic S1 run and evaluate.

No MOSIP product verification. Pure Python 3.11+, no extra packages.
The bundle contains emitted, collected and query provenance as DIFFERENT sources.

  python3 validation/v5_backend.py collect --out /tmp/v5run --grafana http://localhost:3000
  python3 validation/v5_backend.py verify-bundle --out /tmp/v5run

Use OAEF_GRAFANA_USER / OAEF_GRAFANA_PASSWORD or OAEF_GRAFANA_TOKEN for auth.
"""
import argparse
import base64
import binascii
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen

from v5_demo import KINDS, av, attrs, dump, load, verify
from v5_report import public_grafana_url, write_report

HASH_FILE = 'evidence-sha256.json'
METRIC_PREFIX = 'oaef_synthetic_journey_duration'  # S1 baseline; validated against contract below


class BackendProblem(Exception):
    pass


class Grafana:
    def __init__(self, base, timeout=12):
        parsed = urlsplit(base)
        if parsed.scheme not in ('http', 'https') or not parsed.netloc or parsed.username or parsed.password:
            raise BackendProblem('Expected a Grafana http(s) URL without embedded credentials')
        if parsed.scheme == 'http' and parsed.hostname not in ('localhost', '127.0.0.1', '::1'):
            raise BackendProblem('Nonlocal Grafana endpoint requires HTTPS')
        self.base = base.rstrip('/')
        self.timeout = timeout
        self.user = os.environ.get('OAEF_GRAFANA_USER', 'admin')
        self.password = os.environ.get('OAEF_GRAFANA_PASSWORD', os.environ.get('GF_ADMIN_PASSWORD'))
        self.token = os.environ.get('OAEF_GRAFANA_TOKEN')

    def get(self, path, params=None):
        if params:
            path += ('&' if '?' in path else '?') + urlencode(params)
        url = self.base + path
        req = Request(url, headers={'Accept': 'application/json'})
        if self.token:
            req.add_header('Authorization', 'Bearer ' + self.token)
        elif self.password is not None:
            import base64
            encoded = base64.b64encode((self.user + ':' + self.password).encode()).decode()
            req.add_header('Authorization', 'Basic ' + encoded)
        try:
            with urlopen(req, timeout=self.timeout) as response:
                return json.load(response)
        except HTTPError as ex:
            # 404 means no trace yet. Other HTTP failures must NOT be hidden.
            if ex.code == 404:
                return None
            raise BackendProblem(f'Grafana HTTP {ex.code} at {path.split("?")[0]}') from ex
        except (URLError, TimeoutError, json.JSONDecodeError) as ex:
            raise BackendProblem(f'Grafana query failed: {type(ex).__name__}') from ex

    def uids(self):
        obj = self.get('/api/datasources')
        if not isinstance(obj, list):
            raise BackendProblem('Grafana datasource discovery did not return a list')
        output = {}
        for t in ('tempo', 'loki', 'prometheus'):
            matches = [x.get('uid') for x in obj if x.get('type') == t and x.get('uid')]
            if not matches:
                raise BackendProblem(f'Missing {t} datasource in Grafana')
            output[t] = matches[0]
        return output

    def proxy(self, uid, endpoint, params=None):
        return self.get('/api/datasources/proxy/uid/' + uid + endpoint, params)


def hex_id(value, width):
    """Tempo's JSON API returns OTLP bytes fields base64-encoded; OTLP/JSON input uses hex."""
    value = value or ''
    if re.fullmatch('[0-9a-fA-F]{%d}' % width, value):
        return value.lower()
    try:
        raw = base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError):
        return value
    return raw.hex() if len(raw) * 2 == width else value


def flatten_traces(trace_docs):
    groups_out = []
    for trace_id, doc in trace_docs.items():
        if not doc:
            continue
        groups = doc.get('resourceSpans', doc.get('batches', []))
        if not isinstance(groups, list):
            raise BackendProblem('Unrecognized Tempo trace response')
        for group in groups:
            spans = []
            for scope in group.get('scopeSpans', []):
                for span in scope.get('spans', []):
                    span = dict(span, traceId=hex_id(span.get('traceId'), 32),
                                spanId=hex_id(span.get('spanId'), 16))
                    if isinstance(span.get('kind'), str):  # Tempo JSON uses enum names
                        span['kind'] = KINDS.get(span['kind'], 0)
                    if span.get('parentSpanId'):
                        span['parentSpanId'] = hex_id(span['parentSpanId'], 16)
                    if span['traceId'] != trace_id.lower():
                        raise BackendProblem('Tempo trace result contained another trace ID')
                    spans.append(span)
            groups_out.append({'resource': group.get('resource', {}), 'scopeSpans': [{'spans': spans}]})
    return {'resourceSpans': groups_out}


def normalize_loki(doc, run_id):
    if not isinstance(doc, dict) or doc.get('status') != 'success' or doc.get('data', {}).get('resultType') != 'streams':
        raise BackendProblem('Loki did not return a successful stream query')
    records, malformed, seen = [], [], 0
    for stream in doc['data'].get('result', []):
        for entry in stream.get('values', []):
            seen += 1
            if len(entry) < 2:
                malformed.append('entry_without_timestamp_or_body')
                continue
            ts, body = entry[:2]
            try:
                data = json.loads(body)
                if data.get('run_id') != run_id:
                    malformed.append('foreign_run_or_missing_run_id')
                    continue
                must = ('transaction_id', 'event_name', 'trace_id', 'span_id', 'synthetic_effect_id')
                if any(not data.get(k) for k in must):
                    raise ValueError('missing structured business event fields')
                if not re.fullmatch('[0-9a-f]{32}', data['trace_id']) or not re.fullmatch('[0-9a-f]{16}', data['span_id']):
                    raise ValueError('invalid trace/span identifier')
                records.append({'timeUnixNano': str(int(ts)), 'eventName': data['event_name'],
                                'traceId': data['trace_id'], 'spanId': data['span_id'],
                                'attributes': attrs({'oaef.run.id': run_id,
                                    'oaef.transaction.id': data['transaction_id'],
                                    'oaef.synthetic.effect.id': data['synthetic_effect_id']})})
            except (TypeError, ValueError, KeyError, json.JSONDecodeError) as ex:
                malformed.append(f'malformed_structured_event:{type(ex).__name__}')
    return ({'resourceLogs': [{'resource': {'attributes': attrs({'service.name': 'oaef-s1-simulator'})},
                                'scopeLogs': [{'logRecords': records}]}]}, malformed, seen)


def parse_prometheus(doc, run_id):
    if not isinstance(doc, dict) or doc.get('status') != 'success' or doc.get('data', {}).get('resultType') != 'vector':
        raise BackendProblem('Prometheus did not return a successful instant vector query')
    series = {}
    for row in doc['data']['result']:
        labels = row.get('metric', {})
        if labels.get('oaef_run_id') != run_id:
            raise BackendProblem('Prometheus returned a metric from a foreign run')
        key = (labels.get('__name__', ''), labels.get('le', ''))
        if key in series:
            raise BackendProblem('Ambiguous duplicate Prometheus metric series')
        try:
            value = float(row['value'][1])
            if not math.isfinite(value):
                raise ValueError('non-finite metric')
            series[key] = value
        except (KeyError, ValueError, TypeError) as ex:
            raise BackendProblem('Malformed Prometheus metric value') from ex
    return series


def classify(base_verdict, trace_count, expected_count, log_count, expected_logs,
             backend_errors, bad_logs, truncated, metrics_checks):
    failures = base_verdict['failures']
    hard_fail = bool(bad_logs) or any(
        # NFR-DEMO-LATENCY is a proven violation of a declared threshold, not an evidence gap.
        f['check_id'] in ('EVENT-EFFECT-VALUE', 'EVENT-TRACE-CORRELATION', 'EVENT-PARTIAL-ORDER',
                          'NFR-DEMO-LATENCY') or
        (f['check_id'].startswith('EVENT-EXACT-') and f['actual'] > f['expected']) or
        f['check_id'].startswith('SPAN-PARENT-') or
        ((f['check_id'] in ('SPAN-EVENT-COUNT', 'SPAN-TX-COUNT', 'RUN-EVENT-COUNT', 'RUN-SPAN-COUNT')
          or f['check_id'].startswith('SPAN-PRESENT-')) and f['actual'] > f['expected']) or
        (f['check_id'] in ('RUN-UNKNOWN-TRANSACTIONS', 'RUN-UNKNOWN-SPAN-TRANSACTIONS')
            and bool(f['actual']))
        for f in failures)
    hard_fail |= any(m['status'] == 'FAIL' for m in metrics_checks)
    missing = bool(backend_errors or truncated) or trace_count < expected_count or log_count < expected_logs
    missing |= any(m['status'] == 'INCONCLUSIVE' for m in metrics_checks)
    if hard_fail:
        overall = 'FAIL'
    elif missing or failures:
        overall = 'INCONCLUSIVE'
    else:
        overall = 'PASS'
    return overall


def diagnostic_classes(status, failures, metric_checks):
    """Every applicable diagnostic class, most specific first; several defects can coexist."""
    if status == 'PASS':
        return ['S1_TELEMETRY_CONFORMANT']
    if status == 'INCONCLUSIVE':
        return ['EVIDENCE_GAP']
    ids = [f['check_id'] for f in failures]
    out = []
    if any(i.startswith('NFR-') for i in ids):
        out.append('NFR_VIOLATION')
    if any(i.startswith('SPAN-PARENT-') for i in ids):
        out.append('TRACE_CONTEXT_BROKEN')
    if any(m['status'] == 'FAIL' for m in metric_checks):
        out.append('METRIC_RECONCILIATION_FAILURE')
    if any(i.startswith(('EVENT-', 'SPAN-PRESENT-', 'SPAN-EVENT-', 'RUN-')) for i in ids):
        out.append('OBSERVABILITY_VIOLATION')
    return out or ['OBSERVABILITY_VIOLATION']


def observed_metric_checks(series, contract, ledger):
    result = []

    def ck(name, expected, actual, tolerance=0):
        if actual is None:
            st = 'INCONCLUSIVE'
        elif abs(actual - expected) <= tolerance:
            st = 'PASS'
        else:
            st = 'FAIL'
        result.append({'check_id': name, 'expected': expected, 'actual': actual, 'status': st})

    count_names = [k for k in series if k[0].startswith(METRIC_PREFIX) and k[0].endswith('_count')]
    sum_names = [k for k in series if k[0].startswith(METRIC_PREFIX) and k[0].endswith('_sum')]
    # Empty/ambiguous series cannot be treated as an observed PASS.
    ck('PROM-SERIES-COUNT-UNIQUE', 1, len(count_names) if count_names else None)
    ck('PROM-SERIES-SUM-UNIQUE', 1, len(sum_names) if sum_names else None)
    ck('PROM-MEASUREMENTS-COUNT', len(ledger), series.get(count_names[0]) if len(count_names) == 1 else None)
    expected_sum = sum(x['upload_to_assignment_ms'] for x in ledger) / 1000
    ck('PROM-MEASUREMENTS-SUM-S', expected_sum,
       series.get(sum_names[0]) if len(sum_names) == 1 else None, tolerance=1e-4)
    bucket_names = [k for k in series if k[0].startswith(METRIC_PREFIX) and k[0].endswith('_bucket')]
    if not bucket_names:
        result.append({'check_id': 'PROM-HISTOGRAM-BUCKETS', 'expected': 'present',
                       'actual': None, 'status': 'INCONCLUSIVE'})
    else:
        for bound in (0.1, 0.25, 0.5, 1, 2, 5, 10):
            matches = [series[k] for k in bucket_names if k[1] and k[1] != '+Inf' and
                       abs(float(k[1]) - bound) <= 1e-9]
            actual = matches[0] if len(matches) == 1 else None
            expected = sum(x['upload_to_assignment_ms'] / 1000 <= bound for x in ledger)
            ck('PROM-BUCKET-' + str(bound), expected, actual)
        inf = [series[k] for k in bucket_names if k[1] == '+Inf']
        ck('PROM-BUCKET-INF', len(ledger), inf[0] if len(inf) == 1 else None)
    return result


def hashes(root):
    entries = {}
    for path in sorted(root.rglob('*')):
        if path.is_file() and path.name != HASH_FILE:
            rel = path.relative_to(root).as_posix()
            if rel.startswith('.') or any(x == '..' for x in Path(rel).parts):
                continue
            entries[rel] = hashlib.sha256(path.read_bytes()).hexdigest()
    return {'algorithm': 'sha256', 'scope': 'local integrity, NOT signature or WORM', 'files': entries}


def seal(root):
    dump(root / HASH_FILE, hashes(root))


def verify_bundle(root):
    manifest = load(root / HASH_FILE)
    current = hashes(root)
    return manifest.get('algorithm') == 'sha256' and manifest.get('files') == current['files']


def re_evaluate(out):
    """Re-run oracle offline against *stored backend data*, without modifying the sealed bundle."""
    if not verify_bundle(out):
        raise BackendProblem('Bundle integrity verification failed')
    meta = load(out / 'backend-meta.json')
    expected = load(out / 'backend-verdict.json')
    contract = load(out / 'contract.json')
    ledger = load(out / 'ledger.json')
    manifest = load(out / 'manifest.json')
    checksums = meta.get('verifier_code_sha256', {})
    for name, path in [('v5_backend.py', Path(__file__)),
                       ('v5_demo.py', Path(__file__).with_name('v5_demo.py'))]:
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if checksums.get(name) != digest:
            raise BackendProblem(f'Verifier version mismatch for {name}; cannot claim identical replay')
    with tempfile.TemporaryDirectory() as folder:
        tmp = Path(folder)
        for name in ('contract.json', 'ledger.json', 'manifest.json'):
            shutil.copyfile(out / name, tmp / name)
        shutil.copyfile(out / 'collected-otel.json', tmp / 'collected-otel.json')
        verify(tmp, observed_name='collected-otel.json', verdict_name='collected-verdict.json',
               check_metrics=False, source='offline replay of stored backend observations')
        base = load(tmp / 'collected-verdict.json')
    prom_file = out / 'backend-raw/prometheus.json'
    series = parse_prometheus(load(prom_file), manifest['run_id']) if prom_file.exists() else {}
    metric_checks = observed_metric_checks(series, contract, ledger)
    result = classify(base, meta['returned_trace_count'], len(ledger),
                      meta['parsed_log_records'], len(ledger) * len(contract['required_events']),
                      meta['backend_errors'], meta['parse_errors'],
                      meta['loki_truncated_possible'], metric_checks)
    same = (result == expected['status'] and
            metric_checks == expected['metric_checks'] and
            base['failures'] == expected['event_span_failures'])
    print('OFFLINE RE-EVALUATION:', 'MATCH' if same else 'MISMATCH',
          '| original', expected['status'], '| recalculated', result)
    return same


def collect(out, grafana_url, timeout, poll, limit):
    if not (out / 'observed.json').exists() or not (out / 'ledger.json').exists():
        raise BackendProblem('Run directory missing S1 emitted/ledger artifacts')
    emitted = load(out / 'observed.json')
    ledger = load(out / 'ledger.json')
    contract = load(out / 'contract.json')
    manifest = load(out / 'manifest.json')
    if manifest.get('mode') != 'S1' or manifest.get('otlp_status') != 'attempted':
        raise BackendProblem('Collect requires an S1 run generated with --otlp')
    snapshot_hash = hashlib.sha256((out / 'contract.json').read_bytes()).hexdigest()
    if snapshot_hash != manifest.get('contract_snapshot_sha256'):
        raise BackendProblem('Frozen contract snapshot hash differs from the run manifest')
    if contract['metric_name'].replace('.', '_') != METRIC_PREFIX or contract['metric_unit'] != 's':
        raise BackendProblem('S1 metrics adapter does not support this contract metric/version')
    run_id = manifest['run_id']
    source_spans = [s for g in emitted['traces']['resourceSpans'] for sc in g['scopeSpans'] for s in sc['spans']]
    log_services = sorted({av(g['resource']['attributes'])['service.name'] for g in emitted['logs']['resourceLogs']})
    selector = '{service_name=~"' + '|'.join(log_services) + '"}'
    trace_ids = sorted({s['traceId'] for s in source_spans})
    if len(trace_ids) != len(ledger):
        raise BackendProblem('One source trace per transaction required for this slice')
    starts = [int(s['startTimeUnixNano']) for s in source_spans]
    ends = [int(s['endTimeUnixNano']) for s in source_spans]
    start_ns = min(starts) - 10_000_000_000
    end_ns = max(ends) + 60_000_000_000
    client = Grafana(grafana_url)
    uid = client.uids()
    trace_docs, errors, loki_doc, prom_doc = {}, {}, None, None
    deadline = time.monotonic() + timeout
    attempts = 0
    while True:
        attempts += 1
        errors = {}
        # Fetch each exact trace ID; never query only a global last-hour window.
        def one(tid):
            return tid, client.proxy(uid['tempo'], '/api/traces/' + tid)
        trace_docs = {}
        with ThreadPoolExecutor(max_workers=8) as pool:
            futures = [pool.submit(one, tid) for tid in trace_ids]
            for future in as_completed(futures):
                try:
                    tid, doc = future.result()
                    trace_docs[tid] = doc
                except BackendProblem as ex:
                    errors['tempo'] = str(ex)
        try:
            # Run id is in the structured JSON log body, NOT a cardinality-heavy index label.
            loki_doc = client.proxy(uid['loki'], '/loki/api/v1/query_range', {
                'query': selector + ' |= "' + run_id + '"', 'start': str(start_ns), 'end': str(end_ns),
                'limit': str(limit), 'direction': 'forward'})
            log_otlp, malformed, seen = normalize_loki(loki_doc, run_id)
            log_count = len(log_otlp['resourceLogs'][0]['scopeLogs'][0]['logRecords'])
        except BackendProblem as ex:
            errors['loki'] = str(ex)
            loki_doc, log_otlp, malformed, seen, log_count = None, None, ['loki_unavailable'], 0, 0
        try:
            expression = '{__name__=~"' + METRIC_PREFIX + '.*",oaef_run_id="' + run_id + '"}'
            prom_doc = client.proxy(uid['prometheus'], '/api/v1/query', {
                'query': expression, 'time': str(time.time())})
            series = parse_prometheus(prom_doc, run_id)
        except BackendProblem as ex:
            errors['prometheus'] = str(ex)
            prom_doc, series = None, {}
        trace_count = sum(bool(doc) for doc in trace_docs.values())
        metric_checks = observed_metric_checks(series, contract, ledger)
        ready = (not errors and trace_count == len(trace_ids) and
                 log_count >= len(ledger) * len(contract['required_events']) and
                 all(c['status'] != 'INCONCLUSIVE' for c in metric_checks))
        if ready or time.monotonic() >= deadline:
            break
        time.sleep(min(poll, max(0, deadline - time.monotonic())))

    collected = {'traces': flatten_traces(trace_docs),
                 'logs': log_otlp or {'resourceLogs': [{'scopeLogs': [{'logRecords': []}]}]},
                 'metrics': {'resourceMetrics': []}}
    dump(out / 'collected-otel.json', collected)
    meta = {'source': 'Grafana proxy Tempo/Loki/Prometheus API', 'queried_base': client.base,
            'uids': uid, 'query_start_ns': str(start_ns), 'query_end_ns': str(end_ns),
            'attempts': attempts, 'queried_trace_count': len(trace_ids),
            'returned_trace_count': trace_count, 'queried_log_records': seen,
            'parsed_log_records': log_count, 'loki_limit': limit,
            'loki_truncated_possible': seen >= limit, 'parse_errors': malformed,
            'backend_errors': errors, 'metric_series': len(series),
            'verifier_code_sha256': {name: hashlib.sha256(path.read_bytes()).hexdigest()
                  for name, path in [('v5_backend.py', Path(__file__)),
                                     ('v5_demo.py', Path(__file__).with_name('v5_demo.py'))]},
            'loki_selector': selector,
            'scope': 'synthetic S1 observation only; no actual MOSIP SUT'}
    dump(out / 'backend-meta.json', meta)
    dump(out / 'backend-raw/tempo.json', trace_docs)
    if loki_doc is not None:
        dump(out / 'backend-raw/loki.json', loki_doc)
    if prom_doc is not None:
        dump(out / 'backend-raw/prometheus.json', prom_doc)
    verify(out, observed_name='collected-otel.json', verdict_name='collected-verdict.json',
           check_metrics=False, source='actually queried Grafana/Tempo/Loki records, synthetic S1')
    base = load(out / 'collected-verdict.json')
    status = classify(base, trace_count, len(trace_ids), log_count,
                      len(ledger) * len(contract['required_events']), errors, malformed,
                      seen >= limit, metric_checks)
    verdict = {'run_id': run_id, 'mode': 'S1_BACKEND_OBSERVATION', 'status': status,
               'business_sut_verified': False, 'backend_ingestion_verified': status == 'PASS',
               'transaction_count': len(ledger), 'trace_count': trace_count,
               'events_expected': len(ledger) * len(contract['required_events']),
               'events_collected': log_count, 'event_span_failures': base['failures'],
               'metric_checks': metric_checks,
               'evidence_sufficiency': 'SUFFICIENT_FOR_S1' if status != 'INCONCLUSIVE' else 'INSUFFICIENT',
               'classification': diagnostic_classes(status, base['failures'], metric_checks)[0],
               'diagnostic_classes': diagnostic_classes(status, base['failures'], metric_checks),
               'collected_artifact': 'collected-otel.json', 'backend_query_provenance': 'backend-meta.json'}
    dump(out / 'backend-verdict.json', verdict)
    report = [f'# OAEF V5 — backend observation for {run_id}', '',
              f'**Result: {status}** — S1 synthetic only; not MOSIP qualification.', '',
              f'- Traces returned: {trace_count}/{len(trace_ids)}',
              f'- Structured business logs: {log_count}/{verdict["events_expected"]}',
              f'- Metric checks: {Counter(x["status"] for x in metric_checks)}',
              f'- Event/span failures: {len(base["failures"])}',
              f'- Query attempts: {attempts}; truncated Loki query: {seen >= limit}',
              f'- Collection errors: {errors}; malformed log entries: {malformed[:5]}', '',
              'Important: A missing telemetry record is not proof the business activity did not occur.',
              'Manifest hashes are local integrity checks; not signatures or WORM.']
    (out / 'backend-report.md').write_text('\n'.join(report) + '\n', encoding='utf-8')
    write_report(out, public_grafana_url(grafana_url), uid)
    seal(out)
    print('Report:', out / 'report.html')
    print('BACKEND', status, '| traces', trace_count, '/', len(trace_ids),
          '| structured events', log_count, '/', verdict['events_expected'],
          '| metrics', Counter(x['status'] for x in metric_checks), '| attempts', attempts)
    print('Evidence:', out, '| local integrity:', verify_bundle(out))
    return status


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest='command', required=True)
    c = sub.add_parser('collect')
    c.add_argument('--out', type=Path, required=True)
    c.add_argument('--grafana', default='http://localhost:3000')
    c.add_argument('--timeout', type=float, default=45)
    c.add_argument('--poll', type=float, default=2)
    c.add_argument('--limit', type=int, default=2500)
    v = sub.add_parser('verify-bundle')
    v.add_argument('--out', type=Path, required=True)
    offline = sub.add_parser('re-evaluate')
    offline.add_argument('--out', type=Path, required=True)
    a = p.parse_args(argv)
    try:
        if a.command == 'verify-bundle':
            ok = verify_bundle(a.out)
            print('BUNDLE INTEGRITY:', 'PASS' if ok else 'FAIL')
            return 0 if ok else 1
        if a.command == 're-evaluate':
            return 0 if re_evaluate(a.out) else 1
        if a.timeout < 0 or a.poll <= 0 or a.limit < 10:
            raise BackendProblem('Invalid timeout/poll/limit')
        status = collect(a.out, a.grafana, a.timeout, a.poll, a.limit)
        return {'PASS': 0, 'FAIL': 1, 'INCONCLUSIVE': 2}[status]
    except (BackendProblem, OSError, KeyError, ValueError) as ex:
        print('BACKEND ERROR:', str(ex), file=sys.stderr)
        return 3


if __name__ == '__main__':
    raise SystemExit(main())
