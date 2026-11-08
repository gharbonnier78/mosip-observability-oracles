#!/usr/bin/env python3
"""OAEF V5 Allure export: the run's verdict as Allure 2 results, written into the evidence bundle.

Writes <run>/allure-results/ (documented Allure 2 results format: *-result.json, *-container.json,
attachments, environment.properties, categories.json), so several runs can be browsed together:

  allure generate /tmp/oaef-v5/*/allure-results --clean -o /tmp/oaef-v5/allure-report

One test result per examined transaction (the same ones as report.html: every failed one, plus the
first passing one) and one run-level result (backend counts and metric reconciliation).
Presentation only: the verdict comes from backend-verdict.json / collected-verdict.json; nothing
here recomputes or changes it. A transaction with failures is 'failed' in a FAIL run and 'broken'
in an INCONCLUSIVE run (evidence gap, not a proven defect). Synthetic S1 data only.
"""
import hashlib
import json
import shutil
import uuid

from v5_demo import all_logs, all_spans, av, load
from v5_report import CSS, MAX_TX, Links, sequence_svg, step_status

RESULTS = 'allure-results'
NAMESPACE = uuid.UUID('6f1d1b8e-0a1e-4f5c-9a51-0aef5a11e000')
STATUS = {'PASS': 'passed', 'FAIL': 'failed', 'INCONCLUSIVE': 'broken'}
SVG_STYLE = '<style>' + ' '.join(line for line in CSS.splitlines() if line.startswith('svg')) + '</style>'
CATEGORIES = [
    {'name': 'NFR violation', 'matchedStatuses': ['failed'], 'messageRegex': r'.*\[NFR_VIOLATION\].*'},
    {'name': 'Trace context broken', 'matchedStatuses': ['failed'], 'messageRegex': r'.*\[TRACE_CONTEXT_BROKEN\].*'},
    {'name': 'Metric reconciliation failure', 'matchedStatuses': ['failed'],
     'messageRegex': r'.*\[METRIC_RECONCILIATION_FAILURE\].*'},
    {'name': 'Observability violation', 'matchedStatuses': ['failed'],
     'messageRegex': r'.*\[OBSERVABILITY_VIOLATION\].*'},
    {'name': 'Evidence gap (inconclusive, not a product defect)', 'matchedStatuses': ['broken'],
     'messageRegex': r'.*\[EVIDENCE_GAP\].*'},
]


def md5(text):
    return hashlib.md5(text.encode()).hexdigest()


def check_text(f):
    return f'{f["check_id"]}: expected {json.dumps(f["expected"])}, observed {json.dumps(f["actual"])}'


def step(name, status, start, stop, expected, observed, message=None):
    out = {'name': name, 'status': status, 'stage': 'finished', 'start': start, 'stop': stop,
           'parameters': [{'name': 'Expected', 'value': str(expected)}, {'name': 'Observed', 'value': str(observed)}],
           'steps': [], 'attachments': []}
    if message:
        out['statusDetails'] = {'message': message}
    return out


def write_allure(out, grafana_public, uids):
    contract, manifest, ledger = load(out / 'contract.json'), load(out / 'manifest.json'), load(out / 'ledger.json')
    backend, collected_v = load(out / 'backend-verdict.json'), load(out / 'collected-verdict.json')
    meta, collected = load(out / 'backend-meta.json'), load(out / 'collected-otel.json')
    run_id, fault, run_status = manifest['run_id'], manifest['fault'], backend['status']
    classes = backend.get('diagnostic_classes', [backend.get('classification')])
    links = Links(grafana_public, uids, meta['query_start_ns'], meta['query_end_ns'])
    selector = meta.get('loki_selector', '{service_name=~".+"}')
    spans, logs = all_spans(collected), all_logs(collected)
    failures = collected_v['failures']
    failed_tx = sorted({f['transaction_id'] for f in failures if f.get('transaction_id')})
    shown = failed_tx[:MAX_TX]
    first_ok = next((x['transaction_id'] for x in ledger if x['transaction_id'] not in failed_tx), None)
    if first_ok:
        shown.append(first_ok)
    tx_of = lambda o: av(o['attributes']).get('oaef.transaction.id')
    bad = 'failed' if run_status == 'FAIL' else 'broken'
    if spans:  # time range of the retrieved spans; the query window is padded
        run_start = min(int(s['startTimeUnixNano']) for s in spans) // 1_000_000
        run_stop = max(int(s['endTimeUnixNano']) for s in spans) // 1_000_000
    else:
        run_start, run_stop = int(meta['query_start_ns']) // 1_000_000, int(meta['query_end_ns']) // 1_000_000

    res = out / RESULTS
    if res.exists():
        shutil.rmtree(res)
    res.mkdir(parents=True)
    report_src = None
    if (out / 'report.html').exists():
        report_src = str(uuid.uuid5(NAMESPACE, run_id + '|report.html')) + '-attachment.html'
        shutil.copyfile(out / 'report.html', res / report_src)

    def labels(story, *extra):
        rows = [('suite', contract['scenario']), ('subSuite', fault), ('epic', 'OAEF V5 S2-read (synthetic S1)'),
                ('feature', contract['scenario']), ('story', story), ('run_id', run_id), ('fault', fault),
                ('tag', fault), ('framework', 'oaef-v5'), ('language', 'python')]
        rows += [('diagnostic_class', c) for c in classes] + [('tag', c) for c in classes] + list(extra)
        return [{'name': n, 'value': v} for n, v in rows]

    def params():
        return [{'name': 'run_id', 'value': run_id}, {'name': 'fault', 'value': fault},
                {'name': 'seed', 'value': str(manifest['seed'])}, {'name': 'run verdict', 'value': run_status}]

    children = []
    for tx in shown:
        tx_spans = [s for s in spans if tx_of(s) == tx]
        tx_logs = [r for r in logs if tx_of(r) == tx]
        tx_fail = [f for f in failures if f.get('transaction_id') == tx]
        counts = {}
        for r in tx_logs:
            if r.get('eventName'):   # business events only; plain logs have none
                counts[r['eventName']] = counts.get(r['eventName'], 0) + 1
        refs = {f.get('ref') for f in tx_fail if f.get('ref')}
        if tx_spans:
            start = min(int(s['startTimeUnixNano']) for s in tx_spans) // 1_000_000
            stop = max(int(s['endTimeUnixNano']) for s in tx_spans) // 1_000_000
        else:
            start, stop = run_start, run_stop
        steps = []
        for st in contract['scenario_steps']:
            hits = step_status(st, tx_fail)
            observed = '; '.join(check_text(f) for f in hits) or 'as expected'
            steps.append(step(f'{st["id"]} {st["text"]}', bad if hits else 'passed', start, stop,
                              st['expected'], observed, observed if hits else None))
        other = [f for f in tx_fail if not any(f in step_status(st, tx_fail) for st in contract['scenario_steps'])]
        if other:
            observed = '; '.join(check_text(f) for f in other)
            steps.append(step('Transaction-level checks', bad, start, stop,
                              ', '.join(f['check_id'] for f in other), observed, observed))
        uid = str(uuid.uuid5(NAMESPACE, run_id + '|' + tx))
        trace_id = tx_spans[0]['traceId'] if tx_spans else ''
        result = {
            'uuid': uid, 'historyId': md5(f'{contract["scenario"]}|{fault}|{tx}'),
            'testCaseId': md5(f'{contract["scenario"]}|{tx}'),
            'fullName': f'{contract["scenario"]}.{fault}.{tx}', 'name': f'{contract["scenario"]} {tx} ({fault})',
            'description': (f'Synthetic S1 transaction {tx} of run {run_id}, observed through Tempo/Loki/Prometheus '
                            f'(S2-read). Not a MOSIP verification. Scenario source: {contract.get("scenario_source", "")}.'),
            'status': bad if tx_fail else 'passed', 'stage': 'finished', 'start': start, 'stop': stop,
            'labels': labels(tx, ('transaction_id', tx)), 'parameters': params(), 'steps': steps,
            'links': ([{'name': f'Tempo trace {trace_id}', 'url': links.trace(trace_id), 'type': 'link'}] if trace_id else [])
                     + [{'name': f'Loki events of {tx}', 'url': links.logs(selector, run_id, tx), 'type': 'link'},
                        {'name': 'Journey duration histogram (exemplars)', 'url': links.metric(run_id), 'type': 'link'}],
            'attachments': []}
        if tx_fail:
            result['statusDetails'] = {'message': f'[{classes[0]}] ' + '; '.join(check_text(f) for f in tx_fail),
                                       'trace': json.dumps(tx_fail, indent=2)}
        if tx_spans:
            for s_ in tx_spans:   # specification contract: aliases resolved by the oracle engine
                s_.setdefault('_alias', collected_v.get('span_aliases', {}).get(s_['spanId']))
            svg = sequence_svg(tx_spans, counts, refs, contract, links).replace('<defs>', SVG_STYLE + '<defs>', 1)
            src = uid + '-sequence-attachment.svg'
            (res / src).write_text(svg, encoding='utf-8')
            result['attachments'].append({'name': f'Sequence of {tx} (retrieved spans and events)',
                                          'source': src, 'type': 'image/svg+xml'})
        if report_src:
            result['attachments'].append({'name': 'OAEF run report (report.html)', 'source': report_src,
                                          'type': 'text/html'})
        (res / f'{uid}-result.json').write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
        children.append(uid)

    # Run-level result: backend counts, metric reconciliation and checks not tied to one transaction.
    uid = str(uuid.uuid5(NAMESPACE, run_id + '|run'))
    steps = [step('Traces retrieved from Tempo', 'passed' if backend['trace_count'] == len(ledger) else 'broken',
                  run_start, run_stop, len(ledger), backend['trace_count']),
             step('Business events retrieved from Loki',
                  'passed' if backend['events_collected'] == backend['events_expected'] else bad,
                  run_start, run_stop, backend['events_expected'], backend['events_collected'])]
    for m in backend['metric_checks']:
        steps.append(step(m['check_id'], STATUS[m['status']], run_start, run_stop, m['expected'], m['actual'],
                          None if m['status'] == 'PASS' else f'{m["check_id"]}: {m["status"]}'))
    for f in failures:
        if not f.get('transaction_id'):
            steps.append(step(f['check_id'], bad, run_start, run_stop, f['expected'], f['actual'], check_text(f)))
    result = {
        'uuid': uid, 'historyId': md5(f'{contract["scenario"]}|{fault}|run'), 'testCaseId': md5(f'{contract["scenario"]}|run'),
        'fullName': f'{contract["scenario"]}.{fault}.run', 'name': f'{contract["scenario"]} run verdict ({fault})',
        'description': (f'Backend observation verdict of run {run_id}: {run_status}, classes {", ".join(classes)}. '
                        f'{len(ledger)} transactions; examined transactions are the other results of this run.'),
        'status': STATUS[run_status], 'stage': 'finished', 'start': run_start, 'stop': run_stop,
        'labels': labels('run verdict'), 'parameters': params(), 'steps': steps,
        'links': [{'name': 'All events of this run (Loki)', 'url': links.logs(selector, run_id), 'type': 'link'},
                  {'name': 'Journey duration histogram (exemplars)', 'url': links.metric(run_id), 'type': 'link'}],
        'attachments': []}
    if run_status != 'PASS':
        result['statusDetails'] = {'message': f'[{classes[0]}] run {run_status}: ' + ', '.join(classes)}
    for name in ('backend-verdict.json', 'backend-meta.json'):
        src = f'{uid}-{name.removesuffix(".json")}-attachment.json'
        shutil.copyfile(out / name, res / src)
        result['attachments'].append({'name': name, 'source': src, 'type': 'application/json'})
    if report_src:
        result['attachments'].append({'name': 'OAEF run report (report.html)', 'source': report_src, 'type': 'text/html'})
    (res / f'{uid}-result.json').write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    children.append(uid)

    collect_ok = not meta['backend_errors'] and not meta['loki_truncated_possible']
    container = {
        'uuid': str(uuid.uuid5(NAMESPACE, run_id + '|container')), 'name': f'OAEF run {run_id} ({fault})',
        'children': children, 'start': run_start, 'stop': run_stop, 'afters': [],
        'befores': [{'name': 'S2-read collect from Tempo/Loki/Prometheus via Grafana',
                     'status': 'passed' if collect_ok else 'broken', 'stage': 'finished',
                     'start': run_start, 'stop': run_stop, 'steps': [], 'attachments': [],
                     'parameters': [{'name': 'attempts', 'value': str(meta['attempts'])},
                                    {'name': 'backend errors', 'value': json.dumps(meta['backend_errors'])},
                                    {'name': 'Loki truncation possible', 'value': str(meta['loki_truncated_possible'])}]}]}
    (res / f'{container["uuid"]}-container.json').write_text(json.dumps(container, indent=2) + '\n', encoding='utf-8')
    env = {'run_id': run_id, 'fault': fault, 'seed': manifest['seed'], 'transactions': len(ledger),
           'contract': contract['schema'], 'scope': 'S1 synthetic, S2-read backend observation; not MOSIP verification'}
    (res / 'environment.properties').write_text(
        ''.join(f'{k}={v}\n' for k, v in env.items()), encoding='utf-8')
    (res / 'categories.json').write_text(json.dumps(CATEGORIES, indent=2) + '\n', encoding='utf-8')
    return res
