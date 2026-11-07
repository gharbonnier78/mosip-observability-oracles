#!/usr/bin/env python3
"""OAEF V5 test report: one static HTML page per run, written into the evidence bundle.

For each examined transaction (every failed one, plus the first passing one): the scenario steps
with their expected results and observed status, a sequence diagram drawn from the spans and
events actually retrieved from the backends, the input/output values carried by those signals,
and Grafana links that open the exact trace, span, logs or metric. Synthetic S1 data only.
"""
import html
import json
import os
from urllib.parse import quote

from v5_demo import KINDS, all_logs, all_spans, av, load

MAX_TX = 6
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
        rows.append(f'<text x="8" y="{y + 4}" class="t">+{(t - t_first) / 1e6:.0f} ms</text>')
        remote = parent is not None and parent['_svc'] != s['_svc']
        if what == 'return':
            x0 = col[parent['_svc']]
            out = vals(attrs, OUT_KEYS)
            rows.append(f'<a href="{link}" target="_blank"><line x1="{x}" y1="{y}" x2="{x0}" y2="{y}" stroke="{color}" '
                        f'stroke-dasharray="5 3" marker-end="url(#arr)"/>'
                        f'<text x="{min(x, x0) + 6}" y="{y - 5}" class="v">return {esc(out)}</text></a>')
            y += 26
        elif k in (2, 5) and remote:
            x0 = col[parent['_svc']]
            label = s['name'] + ('  (async, Kafka)' if k == 5 else '')
            inp = vals(attrs, IN_KEYS)
            rows.append(f'<a href="{link}" target="_blank"><line x1="{x0}" y1="{y}" x2="{x}" y2="{y}" stroke="{color}" '
                        f'stroke-width="1.6" marker-end="url(#{"open" if k == 5 else "arr"})"/>'
                        f'<text x="{min(x, x0) + 6}" y="{y - 6}" fill="{color}">{esc(label)}</text>'
                        + (f'<text x="{min(x, x0) + 6}" y="{y + 13}" class="v">{esc(inp)}</text>' if inp else '')
                        + '</a>')
            y += 36 if inp else 26
        elif k == 1 and s['name'] in contract['required_events']:
            n = events_count.get(s['name'], 0)
            color = '#c62828' if bad or n != 1 else '#2e7d32'
            rows.append(f'<a href="{link}" target="_blank"><rect x="{x - 6}" y="{y - 9}" width="12" height="12" fill="{color}"/>'
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
            rows.append(f'<a href="{link}" target="_blank"><rect x="{x - 3}" y="{y - 10}" width="6" height="14" fill="{color}"/>'
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
         f'<td>{esc(", ".join(f"{m["check_id"]}: {m["status"]}" for m in backend["metric_checks"][:4]))}…</td>'
         f'<td>{a(links.metric(run_id), "histogram + exemplars")}</td></tr></table>']
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
