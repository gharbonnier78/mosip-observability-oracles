#!/usr/bin/env python3
"""OAEF specification compiler (C1): spec oracle YAML + requirements + activity model -> frozen contract JSON.

  python3 tools/oaef_compile.py                 # (re)generate generated/contracts/*.contract.json + coverage
  python3 tools/oaef_compile.py --check         # exit 1 if the committed generated files differ (drift)

Design-time tool: needs PyYAML (requirements-compiler.txt, pinned and hash-locked). The runtime (simulator,
collector, oracle engine, reports) reads only the generated JSON and stays standard-library only.

Every obligation of the compiled contract carries:
  obligation_id       stable id  OBL-<section>-<alias or key>
  requirement_refs    from the traceability table of models/nin-requirements.md (requirement -> oracle sections)
  model_element_refs  activities of models/nin-enrolment-activity.puml tagged with those requirements
The YAML content is kept as written (matcher DSL, ${...} templates, $golden); the compiler only normalises,
validates references and adds traceability. It never invents an expectation.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import sys

import yaml

ROOT = Path(__file__).resolve().parents[1]
SPECS = [('NIN-001', 'oracles/NIN-001.oracle.yaml')]
REQUIREMENTS = 'models/nin-requirements.md'
ACTIVITY = 'models/nin-enrolment-activity.puml'
OUT = ROOT / 'generated'
SECTIONS = ('rules', 'api', 'db', 'notification', 'traces', 'logs', 'events', 'metrics', 'audit', 'nfr', 'verdict')


class SpecError(Exception):
    pass


def read_requirements():
    """{req_id: {'text', 'scenarios', 'sections': [section paths]}} from the markdown traceability table."""
    out = {}
    for line in (ROOT / REQUIREMENTS).read_text(encoding='utf-8').splitlines():
        m = re.match(r'^\|\s*((?:F|NF)-\d+)\s*\|([^|]*)\|([^|]*)\|([^|]*)\|', line)
        if m:
            sections = re.findall(r'`([a-z_]+(?:\.[A-Za-z0-9_\[\]]+)*)', m.group(4))
            if not sections and m.group(4).strip() not in ('—', '-', ''):
                sections = [w for w in SECTIONS if w in m.group(4)]
            out[m.group(1)] = {'text': m.group(2).strip(), 'scenarios': m.group(3).strip(), 'sections': sections}
    if not out:
        raise SpecError(f'no requirement found in {REQUIREMENTS}')
    return out


def read_activities():
    """Activities of the PlantUML activity diagram: [{'line', 'lane', 'text', 'requirements'}].

    Handles multi-line activities (":...;" over several lines), swimlanes ("|Lane|") and notes, whose
    requirement tags are attached to the activity they follow. Ids are line-based until the model moves to XMI (C4).
    """
    acts, lane, buf, start, in_note, note_reqs = [], None, None, 0, False, []
    for n, line in enumerate((ROOT / ACTIVITY).read_text(encoding='utf-8').splitlines(), 1):
        t = line.strip()
        if in_note:
            if t.startswith('end note'):
                in_note = False
                if acts:
                    acts[-1]['requirements'] = sorted(set(acts[-1]['requirements']) | set(note_reqs))
            else:
                note_reqs += re.findall(r'\[((?:F|NF)-\d+)\]', t)
            continue
        if t.startswith('note'):
            in_note, note_reqs = True, []
            continue
        m = re.match(r'^\|([^|]+)\|$', t)
        if m:
            lane = m.group(1)
            continue
        if buf is None and t.startswith(':'):
            buf, start = t[1:], n
        elif buf is not None:
            buf += ' ' + t
        if buf is not None and buf.endswith(';'):
            reqs = re.findall(r'\[((?:F|NF)-\d+)\]', buf)
            text = re.sub(r'\s*\[[^\]]*\]', '', buf[:-1]).strip()
            acts.append({'line': start, 'lane': lane, 'text': text, 'requirements': reqs})
            buf = None
    return acts


def refs_for(path, requirements, activities):
    """Requirements whose traceability names this section path (or a parent of it), and their activities."""
    reqs = sorted((r for r, v in requirements.items()
                   if any(path == s or path.startswith(s + '.') or s.startswith(path + '.') for s in v['sections'])),
                  key=lambda r: (r.split('-')[0], int(r.split('-')[1])))
    model = [{'model': ACTIVITY, 'line': a['line'], 'lane': a['lane'], 'activity': a['text']}
             for a in activities if set(a['requirements']) & set(reqs)]
    return reqs, model


def variables(node, acc):
    """Collect ${...} templates and {$ref: x} / {$cap: x} names used by the spec."""
    if isinstance(node, dict):
        for k, v in node.items():
            if k in ('$ref', '$cap') and isinstance(v, str):
                acc.add(v)
            variables(v, acc)
    elif isinstance(node, list):
        for v in node:
            variables(v, acc)
    elif isinstance(node, str):
        acc.update(x.split(' ')[0] for x in re.findall(r'\$\{([^}]+)\}', node))
    return acc


def compile_spec(scenario, rel, requirements, activities):
    src = ROOT / rel
    raw = src.read_bytes()
    spec = yaml.safe_load(raw)
    if spec.get('kind') != 'Oracle' or spec.get('metadata', {}).get('scenario') != scenario:
        raise SpecError(f'{rel}: not the Oracle of {scenario}')
    missing = [s for s in ('settle', 'traces', 'events', 'nfr', 'verdict') if s not in spec]
    if missing:
        raise SpecError(f'{rel}: missing sections {missing}')
    spans = spec['traces'].get('spans', [])
    aliases = [s['alias'] for s in spans]
    dup = sorted({a for a in aliases if aliases.count(a) > 1})
    if dup:
        raise SpecError(f'{rel}: duplicate span aliases {dup}')
    known = set(aliases)
    for s in spans:
        for rel_key in ('parent', 'parent_ancestor', 'after'):
            if rel_key in s and s[rel_key] not in known:
                raise SpecError(f'{rel}: span {s["alias"]} {rel_key} -> unknown alias {s[rel_key]}')
    for ln in spec['traces'].get('links', []):
        if 'link_to' in ln and ln['link_to'] not in known:
            raise SpecError(f'{rel}: link {ln["alias"]} -> unknown alias {ln["link_to"]}')
    events = spec['events'].get('expected_ordered_subsequence', [])
    for ev in events:
        if ev.get('span_of') and ev['span_of'] not in known:
            raise SpecError(f'{rel}: event {ev["alias"]} span_of unknown alias {ev["span_of"]}')
    ev_aliases = {e['alias'] for e in events}
    for d in spec['events'].get('durations', []):
        for k in ('from', 'to'):
            if d[k] not in ev_aliases:
                raise SpecError(f'{rel}: duration {d["id"]} {k} -> unknown event {d[k]}')

    obligations = []

    cross_cutting = {r for r, v in requirements.items() if v['scenarios'].lower().startswith('all')}

    def obligation(section, key, body, path=None):
        reqs, model = refs_for(path or section, requirements, activities)
        if isinstance(body, dict) and body.get('requirements'):
            # element-level traceability wins; section-level refs keep only the cross-cutting requirements
            own = [r for r in body['requirements'] if r in requirements]
            unknown = [r for r in body['requirements'] if r not in requirements]
            if unknown:
                raise SpecError(f'{section} {key}: unknown requirements {unknown}')
            reqs = sorted(set(own) | (set(reqs) & cross_cutting), key=lambda r: (r.split('-')[0], int(r.split('-')[1])))
            model = [{'model': ACTIVITY, 'line': a['line'], 'lane': a['lane'], 'activity': a['text']}
                     for a in activities if set(a['requirements']) & set(own)]
        # NF-xx ids used as obligation keys (e.g. event durations) are requirements themselves
        if re.match(r'^(F|NF)-\d+$', str(key)) and key not in reqs:
            reqs = sorted(set(reqs) | {key})
            model = [m for m in model] + [{'model': ACTIVITY, 'line': a['line'], 'lane': a['lane'], 'activity': a['text']}
                                          for a in activities if key in a['requirements']]
        obligations.append({'obligation_id': f'OBL-{section.upper()}-{key}', 'section': section, 'key': key,
                            'requirement_refs': reqs, 'model_element_refs': model, 'expect': body})

    for k, v in spec.get('rules', {}).items():
        obligation('rules', k, v, f'rules.{k}')
    for k, v in spec.get('api', {}).items():
        obligation('api', k, v, f'api.{k}')
    for k, v in spec.get('db', {}).items():
        obligation('db', k, v, f'db.{k}')
    for k, v in spec.get('notification', {}).items():
        obligation('notification', k, v, f'notification.{k}')
    for s in spans:
        obligation('traces', s['alias'], s, 'traces')
    for ln in spec['traces'].get('links', []):
        obligation('traces', ln['alias'], ln, 'traces')
    for lg in spec.get('logs', {}).get('expected', []):
        obligation('logs', lg['alias'], lg, 'logs')
    for ev in events:
        obligation('events', ev['alias'], ev, 'events')
    for d in spec['events'].get('durations', []):
        obligation('events', d['id'], d, 'events')
    metrics = spec.get('metrics', {})
    for a in metrics.get('assertions', []):
        base = next((b for b in metrics.get('baseline', []) if b['id'] == a['id']), {})
        obligation('metrics', a['id'], {**base, **a}, 'metrics')
    if spec.get('audit'):
        obligation('audit', 'app_audit_log', spec['audit'], 'audit')
    for k, v in spec.get('nfr', {}).items():
        obligation('nfr', k, v, f'nfr.{k}')

    contract = {
        'schema': 'oaef.contract/v3',
        'scenario': scenario,
        'generated_by': 'tools/oaef_compile.py',
        'sources': {rel: hashlib.sha256(raw).hexdigest(),
                    REQUIREMENTS: hashlib.sha256((ROOT / REQUIREMENTS).read_bytes()).hexdigest(),
                    ACTIVITY: hashlib.sha256((ROOT / ACTIVITY).read_bytes()).hexdigest()},
        'metadata': spec.get('metadata', {}),
        'settle': spec['settle'],
        'variables': sorted(variables(spec, set())),
        'trace_set': spec['traces'].get('trace_set', {}),
        'common_span_rules': spec['traces'].get('common_span_rules', {}),
        'spans': spans,
        'links': spec['traces'].get('links', []),
        'span_forbidden': spec['traces'].get('forbidden', []),
        'logs': spec.get('logs', {}),
        'events': spec['events'],
        'metrics': metrics,
        'nfr': spec['nfr'],
        'verdict': spec['verdict'],
        'functional': {k: spec.get(k, {}) for k in ('rules', 'api', 'db', 'notification', 'audit')},
        'obligations': obligations,
    }
    return contract


def coverage(contracts, requirements):
    rows = []
    for rid, r in requirements.items():
        obs = [o['obligation_id'] for c in contracts for o in c['obligations'] if rid in o['requirement_refs']]
        rows.append({'requirement': rid, 'text': r['text'], 'scenarios': r['scenarios'], 'oracle_sections': r['sections'],
                     'obligations': len(obs), 'covered': bool(obs)})
    return {'requirements': rows, 'uncovered': [r['requirement'] for r in rows if not r['covered']]}


def render(obj):
    return json.dumps(obj, indent=1, sort_keys=False, ensure_ascii=False) + '\n'


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--check', action='store_true', help='fail if generated files are not up to date')
    a = p.parse_args(argv)
    requirements, activities = read_requirements(), read_activities()
    outputs = {}
    contracts = []
    for scenario, rel in SPECS:
        c = compile_spec(scenario, rel, requirements, activities)
        contracts.append(c)
        outputs[OUT / 'contracts' / f'{scenario}.contract.json'] = render(c)
    outputs[OUT / 'coverage.json'] = render(coverage(contracts, requirements))
    stale = [str(f.relative_to(ROOT)) for f, text in outputs.items()
             if not f.exists() or f.read_text(encoding='utf-8') != text]
    if a.check:
        if stale:
            print('DRIFT: regenerate with python3 tools/oaef_compile.py ->', ', '.join(stale))
            return 1
        print('generated files up to date')
        return 0
    for f, text in outputs.items():
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(text, encoding='utf-8', newline='\n')
    cov = json.loads(outputs[OUT / 'coverage.json'])
    for c in contracts:
        print(f'{c["scenario"]}: {len(c["obligations"])} obligations, {len(c["spans"])} spans, '
              f'{len(c["events"].get("expected_ordered_subsequence", []))} events, variables {len(c["variables"])}')
    print('requirements without obligation:', ', '.join(cov['uncovered']) or 'none')
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except SpecError as ex:
        print('SPEC ERROR:', ex, file=sys.stderr)
        sys.exit(2)
