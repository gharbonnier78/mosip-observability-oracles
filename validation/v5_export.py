#!/usr/bin/env python3
"""OAEF V5 campaign export: one self-contained zip for offline reading, plus a Cucumber JSON for Xray.

  python3 validation/v5_export.py /tmp/oaef-v5            -> /tmp/oaef-v5/exports/oaef-v5-campaign-<UTC>.zip

The zip holds the runs page (index.html), every run folder (report.html and the full evidence bundle),
the contract and scenario that were executed, xray/cucumber.json and a SHA-256 list of its own content.
Offline, every report is readable (diagrams are embedded); its Grafana links need the original stack.

Xray (Cucumber import): one scenario per run, named after the case so repeated runs update the same Test;
steps are the contract's scenario steps with their observed status; the run's report.html and verdict are
attached as evidence. INCONCLUSIVE runs (evidence gap) get a "pending" last step, never "passed".
To bind scenarios to existing Xray Tests, set OAEF_XRAY_TEST_KEYS, e.g. "none=PRJ-12,duplicate=PRJ-13".
"""
import base64
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from v5_report import step_status  # noqa: E402

FEATURE = 'features/nin_001_new_adult_no_hit.feature'
FEATURE_TAGS = ['@TC-NIN', '@NIN-001', '@regType-NEW', '@abis-NO_HIT', '@oaef-S1']
SKIP = {'runs', 'exports'}


def load(p):
    return json.loads(Path(p).read_text(encoding='utf-8'))


def run_dirs(root):
    return [d for d in sorted(root.iterdir()) if d.is_dir() and d.name not in SKIP
            and (d / 'backend-verdict.json').exists() and (d / 'manifest.json').exists()]


def scenario(d, keys):
    manifest, verdict = load(d / 'manifest.json'), load(d / 'backend-verdict.json')
    contract = load(d / 'contract.json')
    failures = verdict['event_span_failures']
    fault = manifest['fault']
    tags = [{'name': t} for t in FEATURE_TAGS + [f'@oaef-case:{fault}']]
    if keys.get(fault):
        tags.append({'name': '@' + keys[fault]})
    steps = []
    for i, st in enumerate(contract['scenario_steps']):
        hits = step_status(st, failures)
        result = {'status': 'failed' if hits else 'passed', 'duration': 0}
        if hits:
            result['error_message'] = '\n'.join(
                f'{f["check_id"]} {f.get("transaction_id") or "run"}: expected {json.dumps(f["expected"])}, '
                f'observed {json.dumps(f["actual"])}' for f in hits[:20])
        text = st['text']
        keyword, _, name = text.partition(' ')
        steps.append({'keyword': keyword + ' ', 'name': f'{name} [{st["id"]}]', 'line': 36 + i, 'result': result})
    status = verdict['status']
    metric_bad = [m for m in verdict['metric_checks'] if m['status'] != 'PASS']
    final = {'status': {'PASS': 'passed', 'FAIL': 'failed'}.get(status, 'pending'), 'duration': 0}
    if status != 'PASS':
        final['error_message'] = (f'{status} {", ".join(verdict.get("diagnostic_classes", []))}; '
                                  f'{len(failures)} event/span failures, {len(metric_bad)} metric checks not PASS. '
                                  'See the attached report.')
    report = (d / 'report.html').read_bytes() if (d / 'report.html').exists() else b''
    embeddings = [{'mime_type': 'application/json', 'name': 'backend-verdict.json',
                   'data': base64.b64encode((d / 'backend-verdict.json').read_bytes()).decode()}]
    if report:
        embeddings.insert(0, {'mime_type': 'text/html', 'name': 'report.html', 'data': base64.b64encode(report).decode()})
    steps.append({'keyword': 'Then ', 'line': 36 + len(steps),
                  'name': f'the OAEF oracle verdict of run {verdict["run_id"]} is PASS',
                  'result': final, 'embeddings': embeddings})
    return {'id': f'nin-001;{fault}', 'keyword': 'Scenario', 'type': 'scenario', 'line': 35,
            'name': f'NIN-001 [{fault}] New adult registration no hit (S1 synthetic, {manifest["transactions"]} transactions)',
            'description': f'run_id {verdict["run_id"]}, seed {manifest["seed"]}; S1 synthetic simulation observed '
                           'through Tempo/Loki/Prometheus; not a MOSIP verification.',
            'tags': tags, 'steps': steps}


def main(root):
    root = Path(root)
    runs = run_dirs(root)
    if not runs:
        print('no run found in', root)
        return 1
    keys = dict(kv.split('=', 1) for kv in os.environ.get('OAEF_XRAY_TEST_KEYS', '').split(',') if '=' in kv)
    cucumber = [{'uri': FEATURE, 'id': 'nin-001', 'keyword': 'Feature', 'line': 4,
                 'name': 'NIN issuance for a new adult resident with no deduplication hit',
                 'description': 'OAEF V5 campaign export', 'tags': [{'name': t} for t in FEATURE_TAGS],
                 'elements': [scenario(d, keys) for d in runs]}]
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    out = root / 'exports' / f'oaef-v5-campaign-{stamp}.zip'
    out.parent.mkdir(exist_ok=True)
    hashes = {}
    readme = ('OAEF V5 campaign export (S1 synthetic, not a MOSIP verification)\n\n'
              'Open index.html (runs and stability), then <case>/report.html.\n'
              'Diagrams are embedded and readable offline; Grafana links need the original stack.\n'
              'Each run folder is a sealed evidence bundle: python3 validation/v5_backend.py verify-bundle --out <folder>\n'
              'xray/cucumber.json: Xray Cucumber import (one scenario per run, report attached).\n'
              'screenshots/ and screenshots/<run>/: Grafana, Tempo, Loki, Prometheus, dashboards, reports and Allure,\n'
              '  captured by validation/demo/capture_screens.py (Playwright script, after sealing; index.json lists them).\n'
              'allure-report/: open allure-report/index.html through a web server (e.g. python3 -m http.server).\n'
              'specification/: requirements, activity model, oracle spec (YAML), compiled contract and coverage.\n'
              'campaign-sha256.json: hash of every file of this zip.\n')
    with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED) as z:
        def add(arc, data):
            z.writestr(arc, data)
            hashes[arc] = hashlib.sha256(data).hexdigest()
        for f in sorted(root.iterdir()):   # campaign-level outputs only (runs page, stability, log)
            if f.is_file() and f.suffix in ('.html', '.json', '.log', '.txt'):
                add(f.name, f.read_bytes())
        for d in runs:
            for f in sorted(d.rglob('*')):
                if f.is_file():
                    add(f'{d.name}/{f.relative_to(d).as_posix()}', f.read_bytes())
        for sub in ('screenshots', 'allure-report'):   # campaign views (Playwright) and the Allure report, if produced
            for f in sorted((root / sub).rglob('*')) if (root / sub).is_dir() else []:
                if f.is_file():
                    add(f'{sub}/{f.relative_to(root / sub).as_posix()}', f.read_bytes())
        add('xray/cucumber.json', json.dumps(cucumber, indent=1).encode())
        add('scenario/' + Path(FEATURE).name, (ROOT / FEATURE).read_bytes())
        add('scenario/NIN-001-v5-slice.json', (ROOT / 'contracts/NIN-001-v5-slice.json').read_bytes())
        for rel in ('oracles/NIN-001.oracle.yaml', 'models/nin-requirements.md', 'models/nin-enrolment-activity.puml',
                    'generated/contracts/NIN-001.contract.json', 'generated/coverage.json'):
            if (ROOT / rel).exists():   # the specification sources and what the compiler made of them
                add('specification/' + rel, (ROOT / rel).read_bytes())
        add('README.txt', readme.encode())
        z.writestr('campaign-sha256.json', json.dumps({'algorithm': 'sha256', 'files': hashes}, indent=1))
    (root / 'exports' / 'cucumber.json').write_text(json.dumps(cucumber, indent=1), encoding='utf-8')
    print(f'CAMPAIGN ZIP: {out} ({out.stat().st_size // 1024} KB, {len(runs)} runs, {len(hashes) + 1} files)')
    print(f'XRAY CUCUMBER: {root / "exports" / "cucumber.json"}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main(sys.argv[1] if len(sys.argv) > 1 else '/tmp/oaef-v5'))
