#!/usr/bin/env python3
"""Check that every panel of the OAEF dashboards returns data, through Grafana's query API.

  python3 validation/demo/check_dashboards.py --run-id s1-xxxx [--grafana http://localhost:3000]

Variables are substituted (data sources by uid, run_id, service=.+); each panel query is sent to
/api/ds/query and the number of frames/rows returned is printed. Panels answered by the browser only
(Tempo service map) are listed as SKIPPED. Exit 1 if a panel returns an error or no data.
"""
import argparse
import base64
import json
import os
from pathlib import Path
import sys
from urllib.error import HTTPError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[2]
DS = {'${ds_prom}': 'prometheus', '${ds_loki}': 'loki', '${ds_tempo}': 'tempo'}


def post(base, path, body):
    req = Request(base + path, data=json.dumps(body).encode(), method='POST', headers={'Content-Type': 'application/json'})
    pw = os.environ.get('OAEF_GRAFANA_PASSWORD') or os.environ.get('GF_ADMIN_PASSWORD', '')
    req.add_header('Authorization', 'Basic ' + base64.b64encode(f'admin:{pw}'.encode()).decode())
    try:
        with urlopen(req, timeout=30) as r:
            return json.load(r)
    except HTTPError as ex:
        return {'error': f'HTTP {ex.code}: {ex.read()[:200]!r}'}


def subst(text, run_id):
    for k, v in {'$run_id': run_id, '$service': '.+', '$__range': '1h', '$__interval': '1m',
                 '$__rate_interval': '2m'}.items():
        text = text.replace(k, v)
    return text


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--run-id', required=True)
    p.add_argument('--grafana', default='http://localhost:3000')
    a = p.parse_args()
    bad = 0
    for f in sorted((ROOT / 'observability/dashboards').glob('*.json')):
        d = json.loads(f.read_text(encoding='utf-8'))
        print(f'== {d["title"]}')
        for panel in d['panels']:
            ds_type = panel['datasource']['type']
            uid = DS[panel['datasource']['uid']]
            if any(t.get('queryType') == 'serviceMap' for t in panel['targets']):
                print(f'  SKIPPED  {panel["title"]} (service map is assembled by the browser)')
                continue
            queries = []
            for t in panel['targets']:
                q = {k: (subst(v, a.run_id) if isinstance(v, str) else v) for k, v in t.items()}
                q['datasource'] = {'type': ds_type, 'uid': uid}
                q.setdefault('intervalMs', 60000)
                q.setdefault('maxDataPoints', 200)
                queries.append(q)
            res = post(a.grafana, '/api/ds/query', {'queries': queries, 'from': 'now-1h', 'to': 'now'})
            if 'error' in res:
                print(f'  ERROR    {panel["title"]}: {res["error"]}')
                bad += 1
                continue
            frames = rows = 0
            errors = []
            for ref, r in res.get('results', {}).items():
                if r.get('error'):
                    errors.append(r['error'][:160])
                for fr in r.get('frames', []):
                    frames += 1
                    vals = fr.get('data', {}).get('values', [])
                    rows += len(vals[0]) if vals else 0
            status = 'ERROR' if errors else ('OK' if rows else 'EMPTY')
            bad += status != 'OK'
            print(f'  {status:<8} {panel["title"]}: {frames} frame(s), {rows} row(s)' + (f' {errors}' if errors else ''))
    print('DASHBOARDS:', 'PASS' if not bad else f'{bad} panel(s) without data or in error')
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
