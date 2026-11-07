#!/usr/bin/env python3
"""OAEF V5 stability page: compares repeated executions of the same case to separate flaky tests from defects.

  python3 validation/v5_stability.py /tmp/oaef-v5      -> writes /tmp/oaef-v5/index.html and stability.json

A case is STABLE when every repeat gives the same verdict and the same failed checks (same check ids on the
same transactions); FLAKY otherwise. Timing sensitivity (several polling attempts, timeouts) is reported
separately: a FLAKY case whose variation comes with INCONCLUSIVE or slow collection points to the test
environment, not to the product.
"""
import html
import json
import re
import sys
from pathlib import Path


def esc(x):
    return html.escape(str(x), quote=True)


def runs(root):
    for d in sorted(p for p in root.iterdir() if p.is_dir() and p.name != 'runs'):
        if (d / 'backend-verdict.json').exists() and (d / 'manifest.json').exists():
            v = json.loads((d / 'backend-verdict.json').read_text(encoding='utf-8'))
            m = json.loads((d / 'manifest.json').read_text(encoding='utf-8'))
            meta = json.loads((d / 'backend-meta.json').read_text(encoding='utf-8'))
            signature = sorted({f'{f["check_id"]}@{f.get("transaction_id") or "run"}' for f in v['event_span_failures']}
                               | {f'{c["check_id"]}@run' for c in v['metric_checks'] if c['status'] != 'PASS'})
            yield {'dir': d.name, 'case': re.sub(r'-r\d+$', '', d.name), 'run_id': m['run_id'], 'fault': m['fault'],
                   'status': v['status'], 'classes': v.get('diagnostic_classes', [v.get('classification')]),
                   'signature': signature, 'attempts': meta.get('attempts'),
                   'collect_s': meta.get('collect_seconds'), 'report': f'{d.name}/report.html'}


def assess(group):
    statuses = {r['status'] for r in group}
    signatures = {tuple(r['signature']) for r in group}
    timing = any(r['status'] == 'INCONCLUSIVE' or (r['attempts'] or 1) > 1 for r in group)
    if len(group) == 1:
        verdict = 'SINGLE RUN'
    elif len(statuses) == 1 and len(signatures) == 1:
        verdict = 'STABLE'
    else:
        verdict = 'FLAKY'
    if verdict == 'FLAKY':
        cause = ('collection/timing (environment): verdict varies with ingestion delay' if timing
                 else 'non-deterministic result with complete evidence: investigate the product or the test data')
    elif verdict == 'STABLE':
        cause = 'reproducible' + (' (needed several polling attempts: watch ingestion delay)' if timing else '')
    else:
        cause = 'repeat with OAEF_REPEAT=N to assess stability'
    return verdict, cause, timing


def main(root):
    root = Path(root)
    items = list(runs(root))
    groups = {}
    for r in items:
        groups.setdefault(r['case'], []).append(r)
    summary = []
    h = ['<!doctype html><meta charset="utf-8"><title>OAEF runs and stability</title><style>'
         'body{font:14px/1.45 system-ui,Segoe UI,Arial,sans-serif;margin:0;padding:24px;color:#1c2833;background:#fafbfc}'
         'table{border-collapse:collapse;width:100%;background:#fff;margin:6px 0}td,th{border:1px solid #dde3ea;padding:5px 8px;'
         'text-align:left;vertical-align:top}th{background:#eef2f6}.b{display:inline-block;padding:1px 8px;border-radius:10px;'
         'color:#fff;font-weight:600}.PASS,.STABLE{background:#2e7d32}.FAIL,.FLAKY{background:#c62828}'
         '.INCONCLUSIVE{background:#ef6c00}.SINGLE{background:#607d8b}code{font:12px Consolas,monospace}</style>',
         '<h1>OAEF V5 — runs and stability</h1>',
         '<p>Synthetic S1 runs observed through the real backends. STABLE = same verdict and same failed checks on every '
         'repeat; FLAKY = they vary. Expected FAIL cases (injected faults) must be STABLE FAIL.</p>',
         '<table><tr><th>Case</th><th>Repeats</th><th>Stability</th><th>Interpretation</th><th>Runs (verdict · attempts · '
         'collect time · failed checks)</th></tr>']
    for case, group in sorted(groups.items()):
        verdict, cause, timing = assess(group)
        summary.append({'case': case, 'repeats': len(group), 'stability': verdict, 'interpretation': cause,
                        'timing_sensitive': timing, 'runs': group})
        cells = '<br>'.join(f'<a href="{esc(r["report"])}">{esc(r["run_id"])}</a> <span class="b {r["status"]}">{r["status"]}'
                            f'</span> · {r["attempts"]} · {r["collect_s"]} s · <code>{esc(", ".join(r["signature"]) or "none")}</code>'
                            for r in group)
        h.append(f'<tr><td>{esc(case)}</td><td>{len(group)}</td><td><span class="b {verdict.split()[0]}">{verdict}</span></td>'
                 f'<td>{esc(cause)}</td><td>{cells}</td></tr>')
    h.append('</table>')
    (root / 'index.html').write_text('\n'.join(h) + '\n', encoding='utf-8')
    (root / 'stability.json').write_text(json.dumps(summary, indent=2) + '\n', encoding='utf-8')
    for s in summary:
        print(f'{s["case"]:<14} {s["repeats"]} run(s)  {s["stability"]:<10} {s["interpretation"]}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main(sys.argv[1] if len(sys.argv) > 1 else '/tmp/oaef-v5'))
