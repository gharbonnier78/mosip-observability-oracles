#!/usr/bin/env python3
"""OAEF V5 test report: one static HTML page per run, written into the evidence bundle.

For each examined transaction (every failed one, plus the first passing one): the scenario steps
with their expected results and observed status, a sequence diagram drawn from the spans and
events actually retrieved from the backends, the input/output values carried by those signals,
and Grafana links that open the exact trace, span, logs or metric. Synthetic S1 data only.
"""
import html
from collections import Counter
import json
import os
from urllib.parse import quote

from v5_demo import KINDS, all_logs, all_spans, av, load

MAX_TX = 6
KIND_NAMES = {0: 'unspecified', 1: 'internal', 2: 'server', 3: 'client', 4: 'producer', 5: 'consumer'}
IN_KEYS = ('mosip.rid', 'messaging.destination.name', 'db.operation.name')
OUT_KEYS = ('http.response.status_code', 'oaef.response.status', 'oaef.synthetic.effect.id')
FILES = ('backend-verdict.json', 'collected-verdict.json', 'verdict.json', 'manifest.json', 'contract.json',
         'ledger.json', 'backend-meta.json', 'backend-report.md', 'evidence-sha256.json')


def public_grafana_url(fallback):
    """Grafana base URL as the reader's browser reaches it (Codespaces forwarded port, or local)."""
    if os.environ.get('OAEF_GRAFANA_PUBLIC_URL'):
        return os.environ['OAEF_GRAFANA_PUBLIC_URL'].rstrip('/')
    name, domain = os.environ.get('CODESPACE_NAME'), os.environ.get('GITHUB_CODESPACES_PORT_FORWARDING_DOMAIN')
    if name and domain:
        return f'https://{name}-3000.{domain}'
    return fallback.rstrip('/')


class Links:
    def __init__(self, base, uids, start_ns, end_ns):
        self.base, self.uids = base, uids
        self.range = {'from': str(int(start_ns) // 1_000_000), 'to': str(int(end_ns) // 1_000_000)}

    def _explore(self, ds_type, query, extra=None):
        uid = self.uids[ds_type]
        pane = {'datasource': uid, 'queries': [dict(refId='A', datasource={'type': ds_type, 'uid': uid}, **query)],
                'range': self.range, **(extra or {})}
        return (self.base + '/explore?schemaVersion=1&orgId=1&panes='
                + quote(json.dumps({'a': pane}, separators=(',', ':'))))

    def trace(self, trace_id, span_id=None):
        extra = {'panelsState': {'trace': {'spanId': span_id}}} if span_id else None
        return self._explore('tempo', {'queryType': 'traceql', 'query': trace_id}, extra)

    def logs(self, selector, run_id, tx=None):
        expr = selector + f' |= "{run_id}"' + (f' | json | transaction_id="{tx}"' if tx else '')
        return self._explore('loki', {'expr': expr, 'queryType': 'range'})

    def service_graph(self):
        return self._explore('tempo', {'queryType': 'serviceMap'})

    def run_traces(self, run_id):
        return self._explore('tempo', {'queryType': 'traceql', 'query': f'{{ span.oaef.run.id = "{run_id}" }}',
                                       'tableType': 'traces', 'limit': 100})

    def journey_dashboard(self, run_id):
        return f'{self.base}/d/oaef-journey/oaef-journey?var-run_id={run_id}&from={self.range["from"]}&to={self.range["to"]}'

    def metric(self, run_id):
        return self._explore('prometheus', {'expr': f'oaef_synthetic_journey_duration_seconds_bucket{{oaef_run_id="{run_id}"}}',
                                            'range': True, 'exemplar': True})


def esc(x):
    return html.escape(str(x), quote=True)


def a(href, text):
    return f'<a href="{esc(href)}" target="_blank" rel="noopener">{esc(text)}</a>'


def step_status(step, failures):
    refs = set(step.get('spans', [])) | set(step.get('events', []))
    hits = [f for f in failures if f.get('ref') in refs or f['check_id'] in step.get('checks', [])]
    return hits


def sequence_svg(spans, events_count, failed_refs, contract, links):
    """Sequence diagram of one transaction, drawn from retrieved spans and events, in time order.

    Calls (client -> server) get a solid arrow with their inputs and a dashed return arrow with
    their outputs; Kafka hops (producer -> consumer) an open-headed asynchronous arrow; business
    events a square on the emitting service, coloured by how many times they were found in Loki.
    """
    expected = {(e['service'], e['name'], e['kind']): e['id'] for e in contract['journey_spans']}
    expected_by_id = {e['id']: e for e in contract['journey_spans']}
    by_id = {s['spanId']: s for s in spans}
    kind = lambda s: s['kind'] if isinstance(s['kind'], int) else KINDS.get(s['kind'], 0)
    has_remote_child = {s.get('parentSpanId') for s in spans
                        if kind(s) in (2, 5) and by_id.get(s.get('parentSpanId') or '', {}).get('_svc') not in (None, s['_svc'])}
    items = []
    for s in spans:
        k, t0, t1 = kind(s), int(s['startTimeUnixNano']), int(s['endTimeUnixNano'])
        if k in (3, 4) and s['spanId'] in has_remote_child:
            continue                               # drawn by its server/consumer counterpart
        items.append((t0, 0, 'start', s))
        if k == 2 and by_id.get(s.get('parentSpanId') or '', {}).get('_svc') not in (None, s['_svc']):
            items.append((t1, 1, 'return', s))
    items.sort(key=lambda x: (x[0], x[1]))
    if not items:
        return ''
    t_first = items[0][0]
    parts = []
    for s in sorted(spans, key=lambda s: int(s['startTimeUnixNano'])):
        if s['_svc'] not in parts:
            parts.append(s['_svc'])
    left = 170
    col = {p: left + i * 175 for i, p in enumerate(parts)}
    rows, y = [], 64

    def vals(attrs, keys):
        return ', '.join(f'{k.split(".")[-1]}={attrs[k]}' for k in keys if k in attrs)

    for t, _, what, s in items:
        k = kind(s)
        attrs = av(s['attributes'])
        sid = expected.get((s['_svc'], s['name'], k), '?')
        bad = sid in failed_refs or s['name'] in failed_refs
        color = '#c62828' if bad else '#263238'
        link = esc(links.trace(s['traceId'], s['spanId']))
        x = col[s['_svc']]
        parent = by_id.get(s.get('parentSpanId') or '')
        exp = expected_by_id.get(sid, {})
        tip = '<title>' + esc('\n'.join([
            f'{s["_svc"]} · {s["name"]} · {KIND_NAMES.get(k, k)} · {(int(s["endTimeUnixNano"]) - int(s["startTimeUnixNano"])) / 1e6:.1f} ms',
            f'span {s["spanId"]}  parent {s.get("parentSpanId") or "-"}',
            f'oracle: expected span "{sid}" under "{exp.get("parent") or "(root)"}"'
            + ('  -> FAILED CHECK' if bad else '  -> as expected'),
            *[f'{key} = {val}' for key, val in sorted(attrs.items())]])) + '</title>'
        rows.append(f'<text x="8" y="{y + 4}" class="t">+{(t - t_first) / 1e6:.0f} ms</text>')
        remote = parent is not None and parent['_svc'] != s['_svc']
        if what == 'return':
            x0 = col[parent['_svc']]
            out = vals(attrs, OUT_KEYS)
            rows.append(f'<a href="{link}" target="_blank">{tip}<line x1="{x}" y1="{y}" x2="{x0}" y2="{y}" stroke="{color}" '
                        f'stroke-dasharray="5 3" marker-end="url(#arr)"/>'
                        f'<text x="{min(x, x0) + 6}" y="{y - 5}" class="v">return {esc(out)}</text></a>')
            y += 26
        elif k in (2, 5) and remote:
            x0 = col[parent['_svc']]
            label = s['name'] + ('  (async, Kafka)' if k == 5 else '')
            inp = vals(attrs, IN_KEYS)
            rows.append(f'<a href="{link}" target="_blank">{tip}<line x1="{x0}" y1="{y}" x2="{x}" y2="{y}" stroke="{color}" '
                        f'stroke-width="1.6" marker-end="url(#{"open" if k == 5 else "arr"})"/>'
                        f'<text x="{min(x, x0) + 6}" y="{y - 6}" fill="{color}">{esc(label)}</text>'
                        + (f'<text x="{min(x, x0) + 6}" y="{y + 13}" class="v">{esc(inp)}</text>' if inp else '')
                        + '</a>')
            y += 36 if inp else 26
        elif k == 1 and s['name'] in contract['required_events']:
            n = events_count.get(s['name'], 0)
            color = '#c62828' if bad or n != 1 else '#2e7d32'
            rows.append(f'<a href="{link}" target="_blank">{tip}<rect x="{x - 6}" y="{y - 9}" width="12" height="12" fill="{color}"/>'
                        f'<text x="{x + 12}" y="{y + 1}" fill="{color}" font-weight="600">event {esc(s["name"])} '
                        f'— found x{n} in Loki (expected x1)</text>'
                        f'<text x="{x + 12}" y="{y + 15}" class="v">{esc(vals(attrs, IN_KEYS + OUT_KEYS))}</text></a>')
            y += 32
        else:
            label = s['name']
            if k == 3:
                label = f'{s["name"]}  → {attrs.get("db.system.name", "external")}'
            if s.get('parentSpanId') and parent is None:
                label += '   [parent span not found: trace context broken]'
                color = '#c62828'
            rows.append(f'<a href="{link}" target="_blank">{tip}<rect x="{x - 3}" y="{y - 10}" width="6" height="14" fill="{color}"/>'
                        f'<text x="{x + 9}" y="{y + 1}" fill="{color}">{esc(label)}</text></a>')
            y += 22
    width = left + 175 * len(parts) + 260
    heads = ''.join(f'<rect x="{col[p] - 78}" y="8" width="156" height="28" rx="5" class="p"/>'
                    f'<text x="{col[p]}" y="27" text-anchor="middle" class="pt">{esc(p)}</text>'
                    f'<line x1="{col[p]}" y1="36" x2="{col[p]}" y2="{y}" class="l"/>' for p in parts)
    return (f'<svg viewBox="0 0 {width} {y + 10}" width="{width}" height="{y + 10}" xmlns="http://www.w3.org/2000/svg">'
            '<defs><marker id="arr" markerWidth="9" markerHeight="9" refX="8" refY="4.5" orient="auto">'
            '<path d="M0,0 L9,4.5 L0,9 z" fill="#455a64"/></marker>'
            '<marker id="open" markerWidth="10" markerHeight="10" refX="9" refY="5" orient="auto">'
            '<path d="M0,0 L9,5 L0,10" fill="none" stroke="#455a64" stroke-width="1.4"/></marker></defs>'
            f'{heads}{"".join(rows)}</svg>')


SERVICE_COLORS = ['#1565c0', '#6a1b9a', '#00838f', '#ef6c00', '#2e7d32', '#ad1457', '#4e342e', '#283593']

FAMILY_TEXT = {
    'RUN-LEDGER-CARDINALITY': 'one ledger entry per transaction',
    'RUN-UNIQUE-TRANSACTIONS': 'transaction ids are unique',
    'RUN-SPAN-COUNT': 'run total = spans per transaction x transactions',
    'RUN-EVENT-COUNT': 'run total = required events x transactions',
    'SPAN-TX-COUNT': 'exactly the expected number of spans per transaction',
    'SPAN-TX-TRACE': 'one trace per transaction',
    'SPAN-PRESENT': 'each expected span (service, name, kind) exactly once',
    'SPAN-PARENT': 'each span under its expected parent span',
    'SPAN-EVENT-COUNT': 'one span per required business event',
    'EVENT-EXACT': 'each required business event exactly once in the logs',
    'EVENT-EFFECT-VALUE': 'event effect value equals the approved value',
    'EVENT-TRACE-CORRELATION': 'event trace_id/span_id point to a span of the same transaction',
    'EVENT-PARTIAL-ORDER': 'packet.received < uin.assigned < identity.activated',
    'NFR-DEMO-LATENCY': 'upload-to-assignment duration within the threshold',
    'RUN-UNKNOWN-TRANSACTIONS': 'no event from an unknown transaction',
    'RUN-UNKNOWN-SPAN-TRANSACTIONS': 'no span from an unknown transaction',
}


def _kind(s):
    return s['kind'] if isinstance(s['kind'], int) else KINDS.get(s['kind'], 0)


def waterfall_svg(spans, failed_refs, contract, links):
    """Span tree with execution times (Tempo-like trace view), drawn from retrieved spans."""
    if not spans:
        return ''
    expected = {(e['service'], e['name'], e['kind']): e['id'] for e in contract['journey_spans']}
    by_id = {s['spanId']: s for s in spans}
    children, roots = {}, []
    for s in sorted(spans, key=lambda s: int(s['startTimeUnixNano'])):
        parent = s.get('parentSpanId') or ''
        (children.setdefault(parent, []) if parent in by_id else roots).append(s)
    order = []

    def walk(s, depth):
        order.append((s, depth))
        for c in children.get(s['spanId'], []):
            walk(c, depth + 1)
    for r in roots:
        walk(r, 0)
    t0 = min(int(s['startTimeUnixNano']) for s in spans)
    total = max(max(int(s['endTimeUnixNano']) for s in spans) - t0, 1)
    services = []
    for s, _ in order:
        if s['_svc'] not in services:
            services.append(s['_svc'])
    color = {svc: SERVICE_COLORS[i % len(SERVICE_COLORS)] for i, svc in enumerate(services)}
    bar_x, bar_w, row_h = 480, 520, 20
    rows = []
    for i, (s, depth) in enumerate(order):
        y = 40 + i * row_h
        sid = expected.get((s['_svc'], s['name'], _kind(s)), '?')
        orphan = bool(s.get('parentSpanId')) and s['parentSpanId'] not in by_id
        bad = sid in failed_refs or s['name'] in failed_refs or orphan
        st, en = int(s['startTimeUnixNano']) - t0, int(s['endTimeUnixNano']) - t0
        x = bar_x + bar_w * st / total
        w = max(bar_w * (en - st) / total, 2)
        ms = (en - st) / 1e6
        name = f'{s["_svc"]}  {s["name"]}' + ('   [orphan: parent not found]' if orphan else '')
        tip = esc(f'{s["_svc"]} · {s["name"]} · {KIND_NAMES.get(_kind(s), "?")} · start +{st / 1e6:.1f} ms · {ms:.1f} ms'
                  f'\nexpected span "{sid}"' + (' -> FAILED CHECK' if bad else ''))
        fg = '#c62828' if bad else '#263238'
        bg = '#ffebee' if bad else 'transparent'
        bar = '#c62828' if bad else color[s['_svc']]
        rows.append(f'<a href="{esc(links.trace(s["traceId"], s["spanId"]))}" target="_blank"><title>{tip}</title>'
                    f'<rect x="0" y="{y - 14}" width="{bar_x + bar_w + 70}" height="{row_h}" fill="{bg}"/>'
                    f'<text x="{8 + depth * 14}" y="{y}" fill="{fg}">{esc(name[:80])}</text>'
                    f'<rect x="{x:.1f}" y="{y - 10}" width="{w:.1f}" height="12" rx="2" fill="{bar}"/>'
                    f'<text x="{min(x + w + 4, bar_x + bar_w + 4):.1f}" y="{y}" class="v">{ms:.1f} ms</text></a>')
    height = 40 + len(order) * row_h + 10
    ticks = ''.join(f'<line x1="{bar_x + bar_w * k / 4}" y1="22" x2="{bar_x + bar_w * k / 4}" y2="{height - 8}" class="l"/>'
                    f'<text x="{bar_x + bar_w * k / 4}" y="16" text-anchor="middle" class="t">{total / 1e6 * k / 4:.0f} ms</text>'
                    for k in range(5))
    legend = ''.join(f'<rect x="{8 + i * 150}" y="{height + 2}" width="10" height="10" fill="{color[svc]}"/>'
                     f'<text x="{22 + i * 150}" y="{height + 11}" class="v">{esc(svc)}</text>' for i, svc in enumerate(services))
    width = bar_x + bar_w + 80
    return (f'<svg viewBox="0 0 {width} {height + 20}" width="{width}" height="{height + 20}" xmlns="http://www.w3.org/2000/svg">'
            f'<text x="8" y="16" class="pt">Service · operation ({len(spans)} spans, {len(services)} services)</text>'
            f'{ticks}{"".join(rows)}{legend}</svg>')


def jarvis_sequence(manifest, emitted_v, meta, backend, collected_v, files_count):
    """How Jarvis produced, collected and judged the evidence: diagram plus numbered attached details."""
    parts = ['Jarvis (S1 driver)', 'OTel Collector', 'Tempo', 'Loki', 'Prometheus', 'Oracle', 'Evidence bundle']
    col = {p: 120 + i * 150 for i, p in enumerate(parts)}
    msgs, details = [], []

    def msg(dst, label, result, detail, ok=True):
        n = len(details) + 1
        details.append((n, label, result, detail))
        msgs.append((parts[0], dst, f'[{n}] {label}', result, ok, n))

    for e in manifest.get('emitted', []):
        path = '/'.join(e['url'].rsplit('/', 2)[-2:])
        msg(parts[1], f'POST /{path}', f'HTTP {e["http_status"]}, {e["bytes"]} bytes',
            f'Endpoint {e["url"]}. OTLP/JSON payload for {manifest["transactions"]} synthetic transactions '
            f'(seed {manifest["seed"]}, fault {manifest["fault"]}). Stored in observed.json.')
    if emitted_v:
        msg(parts[5], 'oracle on the emitted payload (source side)',
            f'{emitted_v["status"]}, {len(emitted_v["failures"])} failed checks',
            'The same frozen contract applied to what Jarvis sent, before any backend. Stored in verdict.json.',
            ok=emitted_v['status'] == 'PASS')
    log = meta.get('collection_log', [])
    q = meta.get('queries', {})
    lq = q.get('loki', {}) if isinstance(q.get('loki'), dict) else {}
    for idx, row in enumerate(log):
        if len(log) > 3 and 0 < idx < len(log) - 1:
            if idx == 1:
                msgs.append((parts[0], parts[0], f'... {len(log) - 2} more polling attempts, every {meta.get("poll_s")} s '
                             '(each listed in backend-meta.json collection_log)', '', True, None))
            continue
        k = row['attempt']
        msg(parts[2], f'attempt {k} (t+{row["t_s"]} s): GET /api/traces/{{id}} x{row["tempo"]["requests"]}',
            f'{row["tempo"]["returned"]}/{row["tempo"]["requests"]} traces in {row["tempo"]["ms"]} ms',
            f'{q.get("tempo", "")}. Error: {row["tempo"].get("error") or "none"}. Raw replies: backend-raw/tempo.json.',
            ok=row['tempo']['returned'] == row['tempo']['requests'])
        msg(parts[3], f'attempt {k}: query_range (events of the run)',
            f'{row["loki"]["lines"]} lines, {row["loki"]["parsed"]} parsed, {row["loki"]["ms"]} ms',
            f'LogQL {lq.get("query", "")}; window [{lq.get("start_ns", "")}, {lq.get("end_ns", "")}] ns; '
            f'limit {lq.get("limit", "")}. Error: {row["loki"].get("error") or "none"}. Raw reply: backend-raw/loki.json.',
            ok=row['loki']['parsed'] == backend['events_expected'])
        msg(parts[4], f'attempt {k}: instant query (histogram of the run)',
            f'{row["prometheus"]["series"]} series, {row["prometheus"]["ms"]} ms',
            f'PromQL {q.get("prometheus", "")}. Error: {row["prometheus"].get("error") or "none"}. '
            'Raw reply: backend-raw/prometheus.json.', ok=row['prometheus']['series'] > 0)
    total_checks = sum(v['evaluated'] for v in collected_v.get('evaluated', {}).values())
    msg(parts[5], 'oracle on the retrieved data (contract frozen before the run)',
        f'{backend["status"]}: {", ".join(backend.get("diagnostic_classes", []))}; '
        f'{total_checks} checks + {len(backend["metric_checks"])} metric checks',
        'Normalised Tempo/Loki records (collected-otel.json) evaluated against contract.json; results in '
        'collected-verdict.json and backend-verdict.json. See "Oracle versus observed".', ok=backend['status'] == 'PASS')
    msg(parts[6], 'seal the evidence (SHA-256 manifest)', f'{files_count} files hashed',
        'evidence-sha256.json holds the hash of every file of this bundle, including this report. '
        'Integrity check only: not a signature, not WORM storage.')
    y, rows = 60, []
    for src, dst, label, result, ok, n in msgs:
        x0, x1 = col[src], col[dst]
        if src == dst:
            rows.append(f'<text x="{x0 + 8}" y="{y}" class="v">{esc(label)}</text>')
            y += 24
            continue
        c = '#263238' if ok else '#c62828'
        tip = f'<title>{esc(label + chr(10) + result)}</title>'
        rows.append(f'<a href="#jdetail-{n}">{tip}<line x1="{x0}" y1="{y}" x2="{x1}" y2="{y}" stroke="{c}" '
                    f'stroke-width="1.5" marker-end="url(#jarr)"/><text x="{x0 + 6}" y="{y - 5}" fill="{c}">{esc(label)}</text>'
                    f'<line x1="{x1}" y1="{y + 14}" x2="{x0}" y2="{y + 14}" stroke="{c}" stroke-dasharray="5 3" '
                    f'marker-end="url(#jarr)"/><text x="{x0 + 6}" y="{y + 27}" class="v">{esc(result)}</text></a>')
        y += 52
    width = 120 + 150 * len(parts) + 60
    heads = ''.join(f'<rect x="{col[p] - 68}" y="8" width="136" height="28" rx="5" class="p"/>'
                    f'<text x="{col[p]}" y="27" text-anchor="middle" class="pt">{esc(p)}</text>'
                    f'<line x1="{col[p]}" y1="36" x2="{col[p]}" y2="{y}" class="l"/>' for p in parts)
    svg = (f'<svg viewBox="0 0 {width} {y + 10}" width="{width}" height="{y + 10}" xmlns="http://www.w3.org/2000/svg">'
           '<defs><marker id="jarr" markerWidth="9" markerHeight="9" refX="8" refY="4.5" orient="auto">'
           '<path d="M0,0 L9,4.5 L0,9 z" fill="#455a64"/></marker></defs>'
           f'{heads}{"".join(rows)}</svg>')
    det = ''.join(f'<details id="jdetail-{n}"><summary><b>[{n}]</b> {esc(label)} &rarr; {esc(result)}</summary>'
                  f'<p>{esc(text)}</p></details>' for n, label, result, text in details)
    return svg, det


def flakiness(manifest, meta, collected_v):
    """Indicators that the verdict could change on a rerun for reasons other than the product."""
    notes = []
    emitted = int(manifest.get('emitted_at_ns', 0) or 0)
    started = int(meta.get('collect_started_ns', 0) or 0)
    log = meta.get('collection_log', [])
    complete_at = next((r['t_s'] for r in log if r.get('complete')), None)
    rows = [('Emission to first query', f'{(started - emitted) / 1e9:.1f} s' if emitted and started else 'n/a'),
            ('Polling attempts', str(meta.get('attempts'))),
            ('Evidence complete after', f'{complete_at} s' if complete_at is not None else 'never (timeout)'),
            ('Time used / timeout', f'{meta.get("collect_seconds")} s / {meta.get("timeout_s")} s'),
            ('Loki result possibly truncated', str(meta.get('loki_truncated_possible'))),
            ('Backend errors', json.dumps(meta.get('backend_errors') or {}))]
    m = collected_v.get('margins', {})
    if m.get('threshold_ms'):
        ratio = m['max_upload_to_assignment_ms'] / m['threshold_ms']
        rows.append(('Slowest transaction / latency threshold',
                     f'{m["max_upload_to_assignment_ms"]} ms / {m["threshold_ms"]} ms ({ratio:.0%})'))
        if 0.9 <= ratio <= 1.0:
            notes.append('Latency within 10% of the threshold: the NFR verdict may flip on a rerun.')
    if complete_at is None:
        notes.append('Evidence never became complete before the timeout: the verdict is about the evidence '
                     '(INCONCLUSIVE), not the product. Rerun with a longer timeout before concluding.')
    elif (meta.get('attempts') or 1) > 1:
        notes.append(f'The backends needed {meta["attempts"]} attempts ({complete_at} s) to return every record: '
                     'this run is sensitive to ingestion delay.')
    if meta.get('loki_truncated_possible'):
        notes.append('Loki returned as many lines as the query limit: results may be truncated.')
    if meta.get('backend_errors'):
        notes.append('A backend returned errors during collection.')
    if not notes:
        notes.append('No timing or collection sensitivity observed in this run. Stability across runs: '
                     'run the case with OAEF_REPEAT=N and open the stability page (index.html).')
    return ('<table><tr><th>Indicator</th><th>Value</th></tr>'
            + ''.join(f'<tr><td>{esc(k)}</td><td>{esc(v)}</td></tr>' for k, v in rows)
            + '</table><ul>' + ''.join(f'<li>{esc(n)}</li>' for n in notes) + '</ul>')


def oracle_view(contract, collected_v, backend):
    """The oracle as executed: every check family, what it expects, how many were evaluated and failed."""
    rows = []
    for fam, v in collected_v.get('evaluated', {}).items():
        st = 'PASS' if v['failed'] == 0 else 'FAIL'
        fails = [f for f in collected_v['failures'] if f['check_id'].startswith(fam)][:3]
        diff = '<br>'.join(f'{esc(f.get("transaction_id") or "run")}: expected <code>{esc(json.dumps(f["expected"]))}</code> '
                           f'&rarr; observed <code>{esc(json.dumps(f["actual"]))}</code>' for f in fails)
        rows.append(f'<tr><td><code>{esc(fam)}</code></td><td>{esc(FAMILY_TEXT.get(fam, ""))}</td><td>{v["evaluated"]}</td>'
                    f'<td>{v["failed"]}</td><td><span class="badge {st}">{st}</span></td><td>{diff}</td></tr>')
    for mc in backend['metric_checks']:
        diff = '' if mc['status'] == 'PASS' else f'expected {esc(mc["expected"])} &rarr; observed {esc(mc["actual"])}'
        if mc['check_id'].startswith('METRIC-SVC-COUNT-'):
            text = 'per-service request metric: one measurement per transaction'
        elif mc['check_id'].startswith('METRIC-SVC-SUM-'):
            text = 'per-service request metric: sum = durations of the server spans retrieved from Tempo'
        else:
            text = 'run journey histogram reconciled with the ledger'
        rows.append(f'<tr><td><code>{esc(mc["check_id"])}</code></td><td>{text}</td>'
                    f'<td>1</td><td>{int(mc["status"] != "PASS")}</td>'
                    f'<td><span class="badge {mc["status"]}">{mc["status"]}</span></td><td>{diff}</td></tr>')
    excerpt = {k: contract[k] for k in ('schema', 'scenario', 'requirement_refs', 'required_events',
                                        'max_upload_to_assignment_ms', 'metric_name', 'metric_unit') if k in contract}
    return ('<table><tr><th>Check family</th><th>Oracle expects</th><th>Evaluated</th><th>Failed</th><th>Result</th>'
            '<th>Differences (first 3)</th></tr>' + ''.join(rows) + '</table>'
            '<details><summary>Show the oracle (contract.json, frozen before the run)</summary><pre>'
            + esc(json.dumps(excerpt, indent=2)) + '\n\njourney_spans:\n' + esc(json.dumps(contract['journey_spans'], indent=1))
            + '\n\nscenario_steps:\n' + esc(json.dumps(contract['scenario_steps'], indent=1)) + '</pre></details>')


def span_comparison(tx_spans, tx_logs, contract, entry):
    """Expected span tree and events of one transaction against what was retrieved."""
    by_key = {}
    for s in tx_spans:
        by_key.setdefault((s['_svc'], s['name'], _kind(s)), []).append(s)
    matched = {e['id']: by_key.get((e['service'], e['name'], e['kind']), []) for e in contract['journey_spans']}
    rows = []
    for e in contract['journey_spans']:
        found = matched[e['id']]
        parent_ok = None
        if len(found) == 1 and (e['parent'] is None or len(matched.get(e['parent'], [])) == 1):
            want = matched[e['parent']][0]['spanId'] if e['parent'] else ''
            parent_ok = (found[0].get('parentSpanId') or '') == want
        ok = len(found) == 1 and parent_ok is not False
        attrs = av(found[0]['attributes']) if found else {}
        shown = ', '.join(f'{k}={v}' for k, v in sorted(attrs.items())
                          if not k.startswith(('oaef.run', 'oaef.simulation', 'test.', 'oaef.transaction')))
        style = '' if ok else ' style="background:#ffebee"'
        par = 'ok' if parent_ok else '-' if parent_ok is None else 'WRONG PARENT'
        rows.append(f'<tr{style}><td>{esc(e["id"])}</td><td>{esc(e["service"])}</td><td>{esc(e["name"])}</td>'
                    f'<td>{KIND_NAMES.get(e["kind"])}</td><td>{esc(e["parent"] or "(root)")}</td>'
                    f'<td>x{len(found)}</td><td>{par}</td><td><small>{esc(shown)}</small></td></tr>')
    ev = []
    for name in contract['required_events']:
        sel = [r for r in tx_logs if r.get('eventName') == name]
        vals = sorted({str(av(r['attributes']).get('oaef.synthetic.effect.id')) for r in sel})
        ok = len(sel) == 1 and vals == [entry['synthetic_effect_id']]
        style = '' if ok else ' style="background:#ffebee"'
        ev.append(f'<tr{style}><td>{esc(name)}</td><td>x1</td><td>x{len(sel)}</td>'
                  f'<td>{esc(entry["synthetic_effect_id"])}</td><td>{esc(", ".join(vals) or "-")}</td></tr>')
    return ('<details><summary>Oracle versus observed for this transaction: '
            f'{len(contract["journey_spans"])} expected spans, {len(contract["required_events"])} required events</summary>'
            '<table><tr><th>Expected span</th><th>Service</th><th>Operation</th><th>Kind</th><th>Expected parent</th>'
            '<th>Found</th><th>Parent</th><th>Observed attributes</th></tr>' + ''.join(rows) + '</table>'
            '<table><tr><th>Required event</th><th>Expected</th><th>Found in Loki</th><th>Expected value</th>'
            '<th>Observed value(s)</th></tr>' + ''.join(ev) + '</table></details>')


def service_graph_svg(spans, links):
    """Service dependency graph of the run, counted from retrieved spans (exact for this run)."""
    by_id = {s['spanId']: s for s in spans}
    edges, nodes = {}, {}
    for s in spans:
        nodes.setdefault(s['_svc'], 0)
        p = by_id.get(s.get('parentSpanId') or '')
        if p is not None and p['_svc'] != s['_svc'] and _kind(s) in (2, 5):
            edges[(p['_svc'], s['_svc'])] = edges.get((p['_svc'], s['_svc']), 0) + 1
        if _kind(s) == 3 and any(a['key'] == 'db.system.name' for a in s['attributes']):
            db = av(s['attributes']).get('db.namespace', 'db')
            nodes.setdefault(db, 0)
            edges[(s['_svc'], db)] = edges.get((s['_svc'], db), 0) + 1
    if not nodes:
        return ''
    # layered layout: depth = longest path from a node without incoming edge
    incoming = {n: [a for (a, b) in edges if b == n] for n in nodes}
    depth = {}

    def d(n, seen=()):
        if n in depth:
            return depth[n]
        depth[n] = 0 if not incoming[n] else 1 + max(d(a, seen + (n,)) for a in incoming[n] if a not in seen)
        return depth[n]
    for n in nodes:
        d(n)
    layers = {}
    for n in sorted(nodes, key=lambda n: (depth[n], n)):
        layers.setdefault(depth[n], []).append(n)
    pos = {}
    for k, ns in layers.items():
        for i, n in enumerate(ns):
            pos[n] = (90 + k * 230, 50 + i * 90 + (len(max(layers.values(), key=len)) - len(ns)) * 45)
    height = 60 + 90 * max(len(v) for v in layers.values())
    width = 90 + 230 * len(layers) + 40
    out = []
    for (a_, b_), n in sorted(edges.items()):
        (x0, y0), (x1, y1) = pos[a_], pos[b_]
        out.append(f'<line x1="{x0 + 70}" y1="{y0}" x2="{x1 - 70}" y2="{y1}" stroke="#78909c" stroke-width="{1 + min(n, 400) / 100:.1f}" '
                   f'marker-end="url(#garr)"/><text x="{(x0 + x1) / 2}" y="{(y0 + y1) / 2 - 6}" text-anchor="middle" class="v">{n} calls</text>')
    for n, (x, y) in pos.items():
        out.append(f'<rect x="{x - 70}" y="{y - 18}" width="140" height="36" rx="18" class="p"/>'
                   f'<text x="{x}" y="{y + 4}" text-anchor="middle" class="pt">{esc(n)}</text>')
    return (f'<svg viewBox="0 0 {width} {height}" width="{width}" height="{height}" xmlns="http://www.w3.org/2000/svg">'
            '<defs><marker id="garr" markerWidth="9" markerHeight="9" refX="8" refY="4.5" orient="auto">'
            '<path d="M0,0 L9,4.5 L0,9 z" fill="#78909c"/></marker></defs>' + ''.join(out) + '</svg>')


def histogram_svg(prom_doc, emitted, links):
    """Journey duration histogram of the run as stored in Prometheus, with the emitted exemplars (click = trace)."""
    buckets = []
    for row in (prom_doc or {}).get('data', {}).get('result', []):
        m = row.get('metric', {})
        if m.get('__name__', '').endswith('_bucket'):
            le = m.get('le')
            buckets.append((float('inf') if le == '+Inf' else float(le), float(row['value'][1])))
    if not buckets:
        return '<p>No histogram retrieved from Prometheus.</p>'
    buckets.sort()
    per, prev = [], 0.0
    for le, cum in buckets:
        per.append((le, cum - prev))
        prev = cum
    exemplars = []
    for g in emitted.get('metrics', {}).get('resourceMetrics', [])[:1]:
        for mt in g['scopeMetrics'][0]['metrics']:
            for dp in mt['histogram']['dataPoints']:
                exemplars += dp.get('exemplars', [])
    top = max(n for _, n in per) or 1
    bw, gap, x0, h0 = 70, 14, 50, 170
    out = []
    labels = []
    lo = 0
    for i, (le, n) in enumerate(per):
        x = x0 + i * (bw + gap)
        hh = 140 * n / top
        out.append(f'<rect x="{x}" y="{h0 - hh:.1f}" width="{bw}" height="{hh:.1f}" fill="#1565c0" opacity="0.8"/>'
                   f'<text x="{x + bw / 2}" y="{h0 - hh - 4:.1f}" text-anchor="middle" class="v">{int(n)}</text>')
        labels.append(f'<text x="{x + bw / 2}" y="{h0 + 14}" text-anchor="middle" class="t">'
                      f'{"≤ " + format(le, "g") + " s" if le != float("inf") else "> " + format(lo, "g") + " s"}</text>')
        for e in exemplars:
            if lo < e['asDouble'] <= le or (le == float('inf') and e['asDouble'] > lo):
                tx = av(e.get('filteredAttributes', [])).get('oaef.transaction.id', '')
                out.append(f'<a href="{esc(links.trace(e["traceId"]))}" target="_blank"><title>exemplar {esc(tx)}: '
                           f'{e["asDouble"]} s, trace {esc(e["traceId"])}</title><circle cx="{x + bw / 2}" cy="{h0 - hh - 22:.1f}" '
                           f'r="6" fill="#ef6c00"/><text x="{x + bw / 2 + 9}" y="{h0 - hh - 18:.1f}" class="v">{esc(tx)}</text></a>')
        lo = le
    width = x0 + len(per) * (bw + gap) + 40
    return (f'<svg viewBox="0 0 {width} {h0 + 30}" width="{width}" height="{h0 + 30}" xmlns="http://www.w3.org/2000/svg">'
            f'<line x1="{x0 - 6}" y1="{h0}" x2="{width - 20}" y2="{h0}" class="l"/>' + ''.join(out) + ''.join(labels) + '</svg>'
            '<p class="v">Bars: measurements per bucket as stored in Prometheus. Orange dots: exemplars (slowest transaction '
            'of each bucket); click to open its trace.</p>')


def service_latency_table(spans):
    """Server latency per service and operation, from the retrieved server spans of the run."""
    rows = {}
    for s in spans:
        if _kind(s) == 2:
            rows.setdefault((s['_svc'], s['name']), []).append((int(s['endTimeUnixNano']) - int(s['startTimeUnixNano'])) / 1e6)
    out = ['<table><tr><th>Service</th><th>Operation</th><th>Calls</th><th>Min ms</th><th>Mean ms</th><th>p95 ms</th><th>Max ms</th></tr>']
    for (svc, name), v in sorted(rows.items()):
        v.sort()
        p95 = v[min(len(v) - 1, int(round(0.95 * (len(v) - 1))))]
        out.append(f'<tr><td>{esc(svc)}</td><td>{esc(name)}</td><td>{len(v)}</td><td>{v[0]:.1f}</td>'
                   f'<td>{sum(v) / len(v):.1f}</td><td>{p95:.1f}</td><td>{v[-1]:.1f}</td></tr>')
    return ''.join(out) + '</table>'


CSS = """
body{font:14px/1.45 system-ui,Segoe UI,Arial,sans-serif;margin:0;padding:24px;color:#1c2833;background:#fafbfc}
h1{font-size:22px;margin:0 0 4px} h2{font-size:17px;margin:28px 0 8px} h3{font-size:15px;margin:18px 0 6px}
.badge{display:inline-block;padding:2px 10px;border-radius:12px;color:#fff;font-weight:600}
.PASS{background:#2e7d32}.FAIL{background:#c62828}.INCONCLUSIVE{background:#ef6c00}
.scope{background:#fff8e1;border-left:4px solid #f9a825;padding:8px 12px;margin:12px 0}
table{border-collapse:collapse;width:100%;background:#fff;margin:6px 0}
td,th{border:1px solid #dde3ea;padding:5px 8px;text-align:left;vertical-align:top} th{background:#eef2f6}
code{font:12px Consolas,monospace;background:#eef2f6;padding:1px 4px;border-radius:3px}
.wrap{overflow-x:auto;background:#fff;border:1px solid #dde3ea;padding:6px}
svg text{font:12px system-ui,Arial,sans-serif} svg .v{fill:#607d8b;font-size:11px} svg .t{fill:#90a4ae;font-size:10px}
svg .p{fill:#e3f2fd;stroke:#1565c0} svg .pt{font-weight:600;fill:#0d47a1} svg .l{stroke:#b0bec5;stroke-dasharray:4 3}
svg a:hover text{text-decoration:underline}
.url{font:12px Consolas,monospace;word-break:break-all;color:#455a64;margin:4px 0 10px}
details{background:#fff;border:1px solid #dde3ea;margin:4px 0;padding:4px 8px}
details summary{cursor:pointer} pre{white-space:pre-wrap;font-size:11px}
"""


def write_report(out, grafana_public, uids):
    contract, manifest, ledger = load(out / 'contract.json'), load(out / 'manifest.json'), load(out / 'ledger.json')
    backend, collected_v = load(out / 'backend-verdict.json'), load(out / 'collected-verdict.json')
    meta, collected = load(out / 'backend-meta.json'), load(out / 'collected-otel.json')
    emitted_v = load(out / 'verdict.json') if (out / 'verdict.json').exists() else None
    run_id = manifest['run_id']
    links = Links(grafana_public, uids, meta['query_start_ns'], meta['query_end_ns'])
    selector = meta.get('loki_selector', '{service_name=~".+"}')
    spans, logs = all_spans(collected), all_logs(collected)
    failures = collected_v['failures']
    failed_tx = sorted({f['transaction_id'] for f in failures if f.get('transaction_id')})
    shown = failed_tx[:MAX_TX] or []
    first_ok = next((x['transaction_id'] for x in ledger if x['transaction_id'] not in failed_tx), None)
    if first_ok:
        shown.append(first_ok)
    tx_of = lambda o: av(o['attributes']).get('oaef.transaction.id')
    status = backend['status']
    metric_counts = Counter(m['status'] for m in backend['metric_checks'])
    metric_summary = ', '.join(f'{k}: {v}' for k, v in sorted(metric_counts.items())) + f' (of {len(backend["metric_checks"])} metric checks)'
    h = [f'<!doctype html><meta charset="utf-8"><title>OAEF report {esc(run_id)}</title><style>{CSS}</style>',
         f'<h1>NIN-001 — run <code>{esc(run_id)}</code> <span class="badge {status}">{status}</span></h1>',
         f'<div>Fault injected: <b>{esc(manifest["fault"])}</b>'
         + (f' on TX-{manifest["target"]:03d}' if manifest['fault'] != 'none' else '')
         + f' · {manifest["transactions"]} transactions · seed {manifest["seed"]} · '
           f'classes: {esc(", ".join(backend.get("diagnostic_classes", [backend.get("classification")])))}</div>',
         '<div class="scope"><b>Scope: S1 synthetic simulation, observed through the real Tempo/Loki/Prometheus backends.</b> '
         'Not a MOSIP or NIMS2 verification. Values (RID, UIN surrogate) are synthetic. The verdict comes from the '
         'deterministic oracle over retrieved evidence; Grafana is for investigation.</div>',
         '<h2>Run summary</h2><table><tr><th>Signal</th><th>Expected</th><th>Collected</th><th>Investigate</th></tr>',
         f'<tr><td>Traces (1 per transaction)</td><td>{len(ledger)}</td><td>{backend["trace_count"]}</td>'
         f'<td>{a(links.trace(next(iter(sorted({s["traceId"] for s in spans})), "")), "open one trace") if spans else ""}</td></tr>',
         f'<tr><td>Spans ({len(contract["journey_spans"])} per transaction)</td>'
         f'<td>{collected_v.get("count_expected_spans", "")}</td><td>{collected_v.get("count_observed_spans", len(spans))}</td><td></td></tr>',
         f'<tr><td>Business events ({len(contract["required_events"])} per transaction)</td>'
         f'<td>{backend["events_expected"]}</td><td>{backend["events_collected"]}</td>'
         f'<td>{a(links.logs(selector, run_id), "all events of this run")}</td></tr>',
         f'<tr><td>Journey duration histogram</td><td>count {len(ledger)}</td>'
         f'<td>{esc(metric_summary)}</td>'
         f'<td>{a(links.metric(run_id), "histogram + exemplars")}</td></tr></table>']
    prom_raw = load(out / 'backend-raw/prometheus.json') if (out / 'backend-raw/prometheus.json').exists() else None
    h.append('<h2>Run overview (from the retrieved spans and metrics)</h2>'
             '<h3>Service graph of this run</h3><div class="wrap">' + service_graph_svg(spans, links) + '</div>'
             f'<div class="url">{a(links.service_graph(), "Service graph in Grafana (Tempo, all runs)")} · '
             f'{a(links.run_traces(run_id), "the run" + chr(39) + "s traces in Tempo (TraceQL search)")} · '
             f'{a(links.metric(run_id), "journey histogram with exemplars")} · '
             f'{a(links.journey_dashboard(run_id), "OAEF Journey dashboard for this run")}</div>'
             '<h3>Journey duration histogram (Prometheus) with exemplars</h3><div class="wrap">'
             + histogram_svg(prom_raw, load(out / 'observed.json'), links) + '</div>'
             '<h3>Server latency per service (from the retrieved server spans)</h3>' + service_latency_table(spans))
    if emitted_v:
        h.append(f'<div>Oracle on the emitted payload (source side): <span class="badge {emitted_v["status"]}">'
                 f'{emitted_v["status"]}</span> · oracle on retrieved backend data: <span class="badge {status}">{status}</span></div>')
    h.append('<h2>Failed checks</h2>')
    if failures or any(m['status'] != 'PASS' for m in backend['metric_checks']):
        h.append('<table><tr><th>Check</th><th>Transaction</th><th>Expected</th><th>Observed</th><th>Investigate</th></tr>')
        traces = {tx_of(s): s['traceId'] for s in spans}
        for f in failures:
            tx = f.get('transaction_id')
            inv = (a(links.trace(traces[tx]), 'trace') + ' · ' + a(links.logs(selector, run_id, tx), 'events')
                   + ' · ' + f'<a href="#{esc(tx)}">sequence</a>') if tx in traces else ''
            h.append(f'<tr><td><code>{esc(f["check_id"])}</code></td><td>{esc(tx or "run")}</td>'
                     f'<td><code>{esc(json.dumps(f["expected"]))}</code></td><td><code>{esc(json.dumps(f["actual"]))}</code></td>'
                     f'<td>{inv}</td></tr>')
        for m in backend['metric_checks']:
            if m['status'] != 'PASS':
                h.append(f'<tr><td><code>{esc(m["check_id"])}</code> ({m["status"]})</td><td>run</td>'
                         f'<td>{esc(m["expected"])}</td><td>{esc(m["actual"])}</td><td>{a(links.metric(run_id), "metric")}</td></tr>')
        h.append('</table>')
    else:
        h.append('<p>None.</p>')
    files_now = sum(1 for p in out.rglob('*') if p.is_file()) + 1
    jsvg, jdet = jarvis_sequence(manifest, emitted_v, meta, backend, collected_v, f'{files_now}+')
    h.append('<h2>How Jarvis collected and validated this run</h2>'
             '<p>Each exchange is numbered; hover for the result, click for the attached detail '
             '(exact query, window, raw reply file).</p>'
             f'<div class="wrap">{jsvg}</div>{jdet}')
    h.append('<h2>Oracle versus observed</h2>' + oracle_view(contract, collected_v, backend))
    graph = backend.get('derived_metrics_health', [])
    if graph:
        h.append('<h2>Derived metrics health (Tempo service graph)</h2><p>Topology expected by the contract, found in the '
                 'service graph Tempo derives from spans (all runs, last 15 min). A health indicator, not part of the '
                 'verdict: derived metrics are aggregated and may drop late spans.</p><table><tr><th>Edge</th><th>Calls '
                 '(15 min)</th><th>Status</th></tr>' + ''.join(
                     f'<tr><td><code>{esc(g["check_id"][11:])}</code></td><td>{esc(g["actual"])}</td>'
                     f'<td><span class="badge {"PASS" if g["status"] == "PASS" else "INCONCLUSIVE"}">{g["status"]}</span></td></tr>'
                     for g in graph) + '</table>' + a(links.service_graph(), 'open the service graph in Grafana'))
    h.append('<h2>Stability indicators (flaky test or product?)</h2>' + flakiness(manifest, meta, collected_v))
    entries = {x['transaction_id']: x for x in ledger}
    for tx in shown:
        tx_spans = [s for s in spans if tx_of(s) == tx]
        tx_logs = [r for r in logs if tx_of(r) == tx]
        tx_fail = [f for f in failures if f.get('transaction_id') == tx]
        counts = {}
        for r in tx_logs:
            counts[r['eventName']] = counts.get(r['eventName'], 0) + 1
        refs = {f.get('ref') for f in tx_fail if f.get('ref')}
        ok = 'FAIL' if tx_fail else 'PASS'
        trace_id = tx_spans[0]['traceId'] if tx_spans else ''
        h.append(f'<h2 id="{esc(tx)}">{esc(tx)} <span class="badge {ok}">{ok}</span></h2>')
        if trace_id:
            h.append(f'<div>Trace {a(links.trace(trace_id), trace_id)} · {a(links.logs(selector, run_id, tx), "events in Loki")}</div>')
        h.append('<h3>Scenario steps</h3><table><tr><th>Step</th><th>Expected</th><th>Observed</th></tr>')
        for st in contract['scenario_steps']:
            hits = step_status(st, tx_fail)
            obs = '<span class="badge PASS">PASS</span>' if not hits else '<span class="badge FAIL">FAIL</span> ' + '<br>'.join(
                f'<code>{esc(f["check_id"])}</code> expected <code>{esc(json.dumps(f["expected"]))}</code>, '
                f'observed <code>{esc(json.dumps(f["actual"]))}</code>' for f in hits)
            h.append(f'<tr><td><b>{esc(st["id"])}</b> {esc(st["text"])}</td><td>{esc(st["expected"])}</td><td>{obs}</td></tr>')
        other = [f for f in tx_fail if not any(f in step_status(st, tx_fail) for st in contract['scenario_steps'])]
        for f in other:
            h.append(f'<tr><td>(transaction-level)</td><td><code>{esc(f["check_id"])}</code></td>'
                     f'<td><span class="badge FAIL">FAIL</span> expected {esc(json.dumps(f["expected"]))}, '
                     f'observed {esc(json.dumps(f["actual"]))}</td></tr>')
        h.append('</table><h3>Sequence (from retrieved spans and events; click any element to open it in Grafana)</h3>')
        h.append('<div class="wrap">' + (sequence_svg(tx_spans, counts, refs, contract, links) if tx_spans
                                         else 'No span retrieved for this transaction.') + '</div>')
        if tx_spans:
            url = links.trace(trace_id)
            h.append('<h3>Span tree with execution times (as in Tempo; click a row to open that span)</h3>'
                     f'<div class="wrap">{waterfall_svg(tx_spans, refs, contract, links)}</div>'
                     f'<div class="url">Tempo: <a href="{esc(url)}" target="_blank" rel="noopener">{esc(url)}</a></div>')
        h.append(span_comparison(tx_spans, tx_logs, contract, entries[tx]))
    h.append('<h2>Evidence files</h2><ul>' + ''.join(
        f'<li><a href="{f}">{f}</a></li>' for f in FILES if (out / f).exists()) + '</ul>')
    h.append(f'<p>Scenario source: <code>{esc(contract.get("scenario_source", ""))}</code> · contract '
             f'<code>{esc(contract["schema"])}</code> · integrity: local SHA-256 manifest (not a signature, not WORM).</p>')
    (out / 'report.html').write_text('\n'.join(h) + '\n', encoding='utf-8')
    md = [f'# OAEF links for {run_id}', '', f'- Report: report.html', f'- Run events: {links.logs(selector, run_id)}',
          f'- Histogram + exemplars: {links.metric(run_id)}', '']
    traces = {tx_of(s): s['traceId'] for s in spans}
    md += [f'- {tx} trace: {links.trace(traces[tx])}' for tx in shown if tx in traces]
    (out / 'links.md').write_text('\n'.join(md) + '\n', encoding='utf-8')
