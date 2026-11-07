#!/usr/bin/env python3
"""Scripted screenshots of a V5 campaign (Playwright, no AI): Grafana (Tempo trace, Loki events, Prometheus histogram,
OAEF dashboards, service graph), the HTML reports, the runs page and the Allure report.

  python3 validation/demo/capture_screens.py --out /tmp/oaef-v5 [--grafana http://localhost:3000] [--reports http://localhost:8080]

Runs in the official Playwright image in CI (mcr.microsoft.com/playwright/python, pinned) or wherever
`pip install playwright && playwright install chromium` is done. Grafana password from GF_ADMIN_PASSWORD /
OAEF_GRAFANA_PASSWORD (never written anywhere). For each run folder it shoots the transaction to investigate
(first failed one, else TX-001) and writes <run>/screenshots/*.png; campaign views go to <out>/screenshots/.
Index: <out>/screenshots/index.json (file, caption, url, status). Screenshots are taken after sealing: they
illustrate the evidence, they are not part of the sealed bundle and never change a verdict.
"""
import argparse
import json
import os
from pathlib import Path
import sys
import time

HERE = Path(__file__).resolve()
sys.path.insert(0, str(HERE.parents[1]))
from v5_report import Links  # noqa: E402
from v5_demo import av  # noqa: E402

VIEW = {'width': 1600, 'height': 1000}
BROKEN = 'failed to load its application files'


def load(p):
    return json.loads(Path(p).read_text(encoding='utf-8'))


def plan(out, grafana, reports):
    """[(path, caption, url, kind)] for every run folder and the campaign."""
    shots = []
    for d in sorted(p for p in out.iterdir() if p.is_dir() and (p / 'backend-verdict.json').exists()):
        meta, verdict, manifest = load(d / 'backend-meta.json'), load(d / 'backend-verdict.json'), load(d / 'manifest.json')
        links = Links(grafana, meta['uids'], meta['query_start_ns'], meta['query_end_ns'])
        run_id, case = manifest['run_id'], d.name
        failed = [f for f in verdict.get('event_span_failures', []) if f.get('transaction_id') and not f.get('consequence_of')]
        tx = failed[0]['transaction_id'] if failed else 'TX-001'
        collected = load(d / 'collected-otel.json')
        spans = [s for g in collected['traces']['resourceSpans'] for sc in g['scopeSpans'] for s in sc['spans']
                 if av(s.get('attributes', [])).get('oaef.transaction.id') == tx]
        roots = [s for s in spans if not s.get('parentSpanId')]
        trace = (roots[0] if roots else spans[0])['traceId'] if spans else None
        aliases = load(d / 'collected-verdict.json').get('span_aliases', {})
        focus = next((s['spanId'] for s in spans if failed and aliases.get(s['spanId']) == failed[0].get('ref')), None)
        sel = meta.get('loki_selector', '{service_name=~".+"}')
        base = f'{case}/screenshots'
        if trace:
            shots.append((f'{base}/01-tempo-trace-{tx}.png', f'{case}: Tempo trace of {tx} (span tree with timings)'
                          + (f', focused on {failed[0].get("ref")}' if focus else ''), links.trace(trace, focus), 'grafana'))
        shots.append((f'{base}/02-loki-events-{tx}.png', f'{case}: business events and logs of {tx} in Loki',
                      links.logs(sel, run_id, tx), 'grafana'))
        shots.append((f'{base}/03-prometheus-histogram.png', f'{case}: journey histogram of run {run_id} with exemplars',
                      links.metric(run_id), 'grafana'))
        shots.append((f'{base}/04-dashboard-journey.png', f'{case}: OAEF Journey dashboard for run {run_id}',
                      links.journey_dashboard(run_id), 'grafana'))
        shots.append((f'{base}/05-report.png', f'{case}: OAEF HTML test report (verdict {verdict["status"]})',
                      f'{reports}/{case}/report.html', 'page'))
        last_links = links
    if shots:
        shots.append(('screenshots/10-dashboard-test-runs.png', 'OAEF Test runs dashboard (all runs of the campaign)',
                      f'{grafana}/d/oaef-test-runs/oaef-test-runs?from=now-3h&to=now', 'grafana'))
        shots.append(('screenshots/11-tempo-service-graph.png', 'Tempo service graph (derived from spans)',
                      last_links.service_graph(), 'grafana'))
        shots.append(('screenshots/12-runs-page.png', 'Runs and stability page', f'{reports}/index.html', 'page'))
        if (out / 'allure-report' / 'index.html').exists():
            shots.append(('screenshots/13-allure-overview.png', 'Allure report overview', f'{reports}/allure-report/index.html', 'page'))
            shots.append(('screenshots/14-allure-suites.png', 'Allure report: suites by case and transaction',
                          f'{reports}/allure-report/index.html#suites', 'page'))
    return shots


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--out', default=os.environ.get('OAEF_OUT', '/tmp/oaef-v5'))
    p.add_argument('--grafana', default='http://localhost:3000')
    p.add_argument('--reports', default='http://localhost:8080')
    a = p.parse_args()
    out = Path(a.out)
    password = os.environ.get('OAEF_GRAFANA_PASSWORD') or os.environ.get('GF_ADMIN_PASSWORD')
    if not password:
        print('Grafana password not set (GF_ADMIN_PASSWORD / OAEF_GRAFANA_PASSWORD)', file=sys.stderr)
        return 2
    from playwright.sync_api import sync_playwright
    shots = plan(out, a.grafana.rstrip('/'), a.reports.rstrip('/'))
    index = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        # Session login through Grafana's login API (JSON, no dependency on the form's markup): the session cookie
        # lands in the browser context. No global Authorization header (it breaks the loading of Grafana's frontend).
        context = browser.new_context(viewport=VIEW)
        r = context.request.post(f'{a.grafana}/login', data={'user': 'admin', 'password': password})
        me = context.request.get(f'{a.grafana}/api/user')
        if not r.ok or not me.ok or me.json().get('login') != 'admin':
            print(f'Grafana authentication failed (login HTTP {r.status}, api/user HTTP {me.status})', file=sys.stderr)
            return 2
        page = context.new_page()
        for rel, caption, url, kind in shots:
            target = out / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            status = 'ok'
            try:
                page.goto(url, wait_until='networkidle', timeout=60000)
                time.sleep(6 if kind == 'grafana' else 1)   # panels and trace view render after the network settles
                page.screenshot(path=str(target), full_page=(kind == 'page'))
                text = page.inner_text('body')
                if kind == 'grafana' and (BROKEN in text or 'Log in' in page.title() or '/login' in page.url):
                    status = 'error: grafana page not rendered'   # never count an error page as a screenshot
            except Exception as ex:   # one failed view must not hide the others; recorded in the index
                status = f'error: {type(ex).__name__}'
            index.append({'file': rel, 'caption': caption, 'url': url, 'status': status,
                          'taken_at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())})
            print(f'{status:<8} {rel}')
        browser.close()
    (out / 'screenshots').mkdir(exist_ok=True)
    (out / 'screenshots' / 'index.json').write_text(json.dumps(index, indent=1) + '\n', encoding='utf-8')
    ok = sum(1 for i in index if i['status'] == 'ok')
    print(f'SCREENSHOTS: {ok}/{len(index)} captured -> {out}/screenshots/index.json')
    return 0 if ok == len(index) else 1


if __name__ == '__main__':
    sys.exit(main())
