#!/usr/bin/env python3
"""OAEF oracle engine (C1b): evaluates a compiled contract (generated/contracts/*.contract.json) against
normalised OTLP signals of one transaction. Standard library only; no LLM; deterministic.

Input per transaction:
  spans   : OTLP spans with '_svc' (resource service.name) and '_res' (resource attributes as a dict)
  logs    : OTLP log records with '_svc' and '_res'
  ctx     : variables bound before the run (env.*, run.id, rid, uin_hash, ...); $cap adds to it
Output: one result per check: {check_id, obligation_id, requirement_refs, status, expected, actual, ref}
  status PASS | FAIL | NOT_EVALUATED (reason in 'actual', never counted as PASS)

Matcher DSL (README#oracle-dsl): literal (typed; OTLP int64 strings compared as numbers), {$re}, {$cap},
{$ref}, {$in}, {$gte}, {$lte}, {$exists}, {$golden} (NOT_EVALUATED until a golden run is approved),
nested dicts = subset match. ${var} templates are substituted from ctx before matching.
"""
import re

KIND_NAMES = {'SPAN_KIND_UNSPECIFIED': 0, 'SPAN_KIND_INTERNAL': 1, 'SPAN_KIND_SERVER': 2,
              'SPAN_KIND_CLIENT': 3, 'SPAN_KIND_PRODUCER': 4, 'SPAN_KIND_CONSUMER': 5}
STATUS_NAMES = {'STATUS_CODE_UNSET': 0, 'STATUS_CODE_OK': 1, 'STATUS_CODE_ERROR': 2}
NOT_IN_C1 = {'rules': 'C2', 'api': 'C2', 'db': 'C5', 'notification': 'C5', 'audit': 'C5', 'metrics': 'C3'}


class Golden(Exception):
    pass


def attr_dict(kvs):
    out = {}
    for kv in kvs or []:
        v = kv.get('value', {})
        out[kv['key']] = next(iter(v.values())) if v else None
    return out


def kind_of(span):
    k = span.get('kind', 0)
    return KIND_NAMES.get(k, 0) if isinstance(k, str) else int(k)


def status_of(span):
    c = (span.get('status') or {}).get('code', 0)
    return STATUS_NAMES.get(c, 0) if isinstance(c, str) else int(c)


def subst(text, ctx):
    """Replace ${var} (and ${a - 1} style arithmetic on numbers) with values from ctx."""
    def one(m):
        expr = m.group(1).strip()
        mm = re.match(r'^([\w.]+)\s*([+-])\s*(\d+)$', expr)
        if mm and mm.group(1) in ctx:
            v = int(ctx[mm.group(1)])
            return str(v + int(mm.group(3)) if mm.group(2) == '+' else v - int(mm.group(3)))
        if expr in ctx:
            return re.escape(str(ctx[expr])) if getattr(subst, 'regex', False) else str(ctx[expr])
        raise KeyError(expr)
    return re.sub(r'\$\{([^}]+)\}', one, text)


def _num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def match(expected, actual, ctx, path=''):
    """Return None when it matches, else a short reason. Raises Golden for $golden expectations."""
    if isinstance(expected, dict) and any(k.startswith('$') for k in expected):
        for op, arg in expected.items():
            if op == '$golden':
                raise Golden(path)
            if op == '$exists':
                if bool(arg) != (actual is not None):
                    return f'{path}: exists={actual is not None}, expected {arg}'
            elif op == '$re':
                pattern = arg
                if '${' in pattern:
                    subst.regex = True
                    try:
                        pattern = subst(pattern, ctx)
                    finally:
                        subst.regex = False
                if actual is None or not re.fullmatch(pattern, str(actual)):
                    return f'{path}: {actual!r} !~ /{pattern}/'
            elif op == '$ref':
                if arg not in ctx:
                    return f'{path}: variable {arg} not bound'
                want = ctx[arg]
                if str(actual) != str(want):
                    return f'{path}: {actual!r} != ${{{arg}}}={want!r}'
            elif op == '$cap':
                if actual is None:
                    return f'{path}: nothing to capture into {arg}'
                ctx[arg] = actual
            elif op == '$in':
                if not any(str(actual) == str(x) for x in arg):
                    return f'{path}: {actual!r} not in {arg}'
            elif op in ('$gte', '$lte'):
                a, b = _num(actual), _num(subst(arg, ctx) if isinstance(arg, str) else arg)
                if a is None or b is None or (a < b if op == '$gte' else a > b):
                    return f'{path}: {actual!r} {"<" if op == "$gte" else ">"} {arg}'
            elif op in ('$span_of', '$descendant_ok'):
                continue   # handled by the log evaluator
            else:
                return f'{path}: unsupported matcher {op}'
        return None
    if isinstance(expected, dict):
        if not isinstance(actual, dict):
            return f'{path}: not an object'
        for k, v in expected.items():
            r = match(v, actual.get(k), ctx, f'{path}.{k}' if path else k)
            if r:
                return r
        return None
    if isinstance(expected, str) and '${' in expected:
        try:
            expected = subst(expected, ctx)
        except KeyError as ex:
            return f'{path}: variable {ex} not bound'
    if expected is None:
        return None if actual in (None, '') else f'{path}: {actual!r} != null'
    if isinstance(expected, (int, float)) and not isinstance(expected, bool):
        return None if _num(actual) == float(expected) else f'{path}: {actual!r} != {expected}'
    return None if str(actual) == str(expected) else f'{path}: {actual!r} != {expected!r}'


def count_ok(spec, n):
    if spec is None:
        return n == 1
    if isinstance(spec, int):
        return n == spec
    return match(spec, n, {}) is None


class Evaluator:
    def __init__(self, contract):
        self.c = contract
        self.obl = {o['obligation_id']: o for o in contract['obligations']}
        self.results = []

    def add(self, check_id, obligation_id, ok, expected, actual, tx, ref=None, status=None):
        o = self.obl.get(obligation_id, {})
        self.results.append({'check_id': check_id, 'obligation_id': obligation_id, 'transaction_id': tx,
                             'requirement_refs': o.get('requirement_refs', []),
                             'status': status or ('PASS' if ok else 'FAIL'), 'expected': expected,
                             'actual': actual, **({'ref': ref} if ref else {})})
        return ok

    # ---------------------------------------------------------------- spans
    def span_matches(self, s, spec, ctx):
        res = spec.get('resource', {})
        for k, v in res.items():
            if match(v, s['_res'].get(k), dict(ctx)):
                return False
        if 'scope' in spec and spec['scope'].get('name') and s.get('_scope') not in (None, spec['scope']['name']):
            return False
        if match(spec.get('name'), s.get('name'), dict(ctx)) if 'name' in spec else False:
            return False
        if 'kind' in spec and match(spec['kind'], kind_of(s), {}):
            return False
        return True

    def evaluate_spans(self, spans, ctx, tx):
        by_id = {s['spanId']: s for s in spans}
        trace_root = ctx.get('trace.root')
        t1 = [s for s in spans if s['traceId'] == trace_root] if trace_root else spans
        matched = {}
        pending = list(self.c['spans'])
        progress = True
        while pending and progress:   # resolve aliases whose relations are resolved (dependency order)
            progress = False
            for spec in list(pending):
                deps = [spec.get(k) for k in ('parent', 'parent_ancestor', 'after') if spec.get(k)]
                if any(d not in matched for d in deps):
                    continue
                pending.remove(spec)
                progress = True
                self.resolve_span(spec, t1, by_id, matched, ctx, tx)
        for spec in pending:   # dependency never resolved: report, do not guess
            matched[spec['alias']] = []
            self.add(f'{self.oid(spec)}:present', self.oid(spec), False, 'resolvable relations',
                     'a span it depends on was not found', tx, spec['alias'])
        return matched

    def oid(self, spec):
        return f'OBL-TRACES-{spec["alias"]}'

    def resolve_span(self, spec, t1, by_id, matched, ctx, tx):
        """Identify the spans of one alias by every declared property (resource, name, kind, relations,
        attributes), then check count, status and duration. When spans exist but fail only the relation
        (parent, ancestor, order), a ':parent' failure is reported: the trace context is broken, not the step."""
        alias, oid = spec['alias'], self.oid(spec)
        structural = [s for s in t1 if self.span_matches(s, spec, ctx)]

        def ancestors(s):
            seen, p = [], by_id.get(s.get('parentSpanId') or '')
            while p is not None and p['spanId'] not in seen:
                seen.append(p['spanId'])
                p = by_id.get(p.get('parentSpanId') or '')
            return seen

        def attr_reasons(s):
            out = []
            for k, v in spec.get('attributes', {}).items():
                try:
                    r = match(v, attr_dict(s.get('attributes')).get(k), dict(ctx), k)
                except Golden:
                    continue
                if r:
                    out.append(r)
            return out
        by_attr = [s for s in structural if not attr_reasons(s)]
        cands = list(by_attr)
        if 'parentSpanId' in spec and spec['parentSpanId'] == '':
            cands = [s for s in cands if not s.get('parentSpanId')]
        if spec.get('parent'):
            pids = {p['spanId'] for p in matched[spec['parent']]}
            cands = [s for s in cands if s.get('parentSpanId') in pids]
        if spec.get('parent_ancestor'):
            pids = {p['spanId'] for p in matched[spec['parent_ancestor']]}
            cands = [s for s in cands if pids & set(ancestors(s))]
        if 'parent_kind' in spec:
            cands = [s for s in cands if by_id.get(s.get('parentSpanId') or '') is not None
                     and kind_of(by_id[s['parentSpanId']]) == spec['parent_kind']]
        if 'parent_kind_ancestor' in spec:
            cands = [s for s in cands if any(kind_of(by_id[a]) == spec['parent_kind_ancestor'] for a in ancestors(s))]
        if spec.get('after'):
            ref = matched[spec['after']]
            if ref:
                start = max(int(r['startTimeUnixNano']) for r in ref)
                cands = [s for s in cands if int(s['startTimeUnixNano']) >= start]
        cnt = spec.get('count')
        ok = count_ok(cnt, len(cands))
        if not ok and not cands and by_attr:
            orphan = [s['spanId'] for s in by_attr if s.get('parentSpanId') and s['parentSpanId'] not in by_id]
            self.add(f'{oid}:parent', oid, False,
                     {k: spec[k] for k in ('parent', 'parent_ancestor', 'parent_kind', 'parent_kind_ancestor', 'after') if k in spec},
                     f'{len(by_attr)} span(s) found, none in the expected position'
                     + (f'; parent span not in trace (orphan {orphan[0]})' if orphan else ''), tx, alias)
        elif not ok and structural and not by_attr:
            self.add(f'{oid}:attributes', oid, False, spec.get('attributes'), attr_reasons(structural[0])[:3], tx, alias)
        else:
            self.add(f'{oid}:count', oid, ok, cnt if cnt is not None else 1, len(cands), tx, alias)
        matched[alias] = cands
        for s in cands:
            for k, v in spec.get('attributes', {}).items():
                try:
                    match(v, attr_dict(s.get('attributes')).get(k), {}, k)
                except Golden:
                    self.add(f'{oid}:attr:{k}', oid, False, '$golden', 'golden run not approved yet', tx, alias,
                             status='NOT_EVALUATED')
            if 'status' in spec:
                r = match(spec['status'].get('code'), status_of(s), {}, 'status.code')
                if r:
                    self.add(f'{oid}:status', oid, False, spec['status'], r, tx, alias)
            if 'duration_ms' in spec:
                d = (int(s['endTimeUnixNano']) - int(s['startTimeUnixNano'])) / 1e6
                r = match(spec['duration_ms'], d, {}, 'duration_ms')
                if r:
                    self.add(f'{oid}:duration', oid, False, spec['duration_ms'], round(d, 1), tx, alias)
            for var, target in (spec.get('capture') or {}).items():
                ctx[target] = s.get(var)
            for k, v in spec.get('attributes', {}).items():   # captures ($cap) survive for later aliases
                if isinstance(v, dict) and '$cap' in v:
                    ctx[v['$cap']] = attr_dict(s.get('attributes')).get(k)

    def evaluate_common(self, spans, ctx, tx):
        rules = self.c.get('common_span_rules', {}).get('every_span', {})
        root = ctx.get('trace.root')
        bad_res, bad_attr, bad_ids = [], [], []
        for s in spans:
            if s['traceId'] != root:
                continue
            for k, v in rules.get('resource', {}).items():
                r = match(v, s['_res'].get(k), dict(ctx), k)
                if r:
                    bad_res.append(f'{s["_svc"]}/{s["name"]}: {r}')
            for k, v in rules.get('attributes', {}).items():
                r = match(v, attr_dict(s.get('attributes')).get(k), dict(ctx), k)
                if r:
                    bad_attr.append(f'{s["_svc"]}/{s["name"]}: {r}')
            if not re.fullmatch('[0-9a-f]{32}', s['traceId']) or not re.fullmatch('[0-9a-f]{16}', s['spanId']) \
                    or int(s['endTimeUnixNano']) < int(s['startTimeUnixNano']):
                bad_ids.append(s['spanId'])
        self.add('OBL-TRACES-COMMON:resource', 'OBL-TRACES-ROOT', not bad_res, rules.get('resource'), bad_res[:5], tx)
        self.add('OBL-TRACES-COMMON:attributes', 'OBL-TRACES-ROOT', not bad_attr, rules.get('attributes'), bad_attr[:5], tx)
        self.add('OBL-TRACES-COMMON:ids-and-times', 'OBL-TRACES-ROOT', not bad_ids, 'hex ids, end >= start', bad_ids[:5], tx)
        errors = [f'{s["_svc"]}/{s["name"]}' for s in spans if status_of(s) == 2]
        self.add('OBL-TRACES-FORBIDDEN:error-status', 'OBL-TRACES-ROOT', not errors, 'no span with status ERROR', errors[:5], tx)

    def evaluate_links(self, spans, matched, ctx, tx):
        for ln in self.c.get('links', []):
            oid = f'OBL-TRACES-{ln["alias"]}'
            target = matched.get(ln.get('link_to')) if ln.get('link_to') else None
            cands = []
            for s in spans:
                if s['traceId'] == ctx.get('trace.root') or match(ln.get('span', {}).get('kind'), kind_of(s), {}) \
                        or (s.get('parentSpanId') or ''):
                    continue
                links = s.get('links') or []
                if target:
                    ok = any(l_.get('traceId') == ctx.get('trace.root') and l_.get('spanId') in {t['spanId'] for t in target}
                             for l_ in links)
                else:
                    ok = any(l_.get('traceId') == ctx.get('trace.T2') for l_ in links)
                if ok:
                    cands.append(s)
            self.add(f'{oid}:present', oid, len(cands) == 1, 'one root span linked as specified', len(cands), tx, ln['alias'])
            for s in cands:
                ctx['trace.' + ln.get('trace', 'T?')] = s['traceId']
                for k, v in ln.get('attributes', {}).items():
                    r = match(v, attr_dict(s.get('attributes')).get(k), dict(ctx), k)
                    if r:
                        self.add(f'{oid}:attr:{k}', oid, False, v, r, tx, ln['alias'])

    # ---------------------------------------------------------------- events and logs
    def evaluate_events(self, logs, matched, ctx, tx):
        ev = self.c['events']
        events = [r for r in logs if r.get('eventName')]
        rules = ev.get('every_event', {})
        bad = []
        forbidden = []
        for r in events:
            for k in ('eventName', 'traceId', 'spanId'):
                if k in rules and match(rules[k], r.get(k), dict(ctx)):
                    bad.append(f'{r.get("eventName")}: {k}={r.get(k)!r}')
            if 'severityNumber' in rules and match(rules['severityNumber'], r.get('severityNumber'), {}):
                bad.append(f'{r.get("eventName")}: severity {r.get("severityNumber")}')
            vals = {str(v) for v in attr_dict(r.get('attributes')).values()}
            for f in rules.get('forbidden_attribute_values', []):
                try:
                    fv = subst(f, ctx)
                except KeyError:
                    continue
                if fv in vals:
                    forbidden.append(f'{r.get("eventName")} carries a forbidden value')
        self.add('OBL-EVENTS-COMMON:every-event', 'OBL-EVENTS-EV_PACKET_RECEIVED', not bad, rules and
                 {k: v for k, v in rules.items() if k != 'forbidden_attribute_values'}, bad[:5], tx)
        self.add('OBL-EVENTS-FORBIDDEN:pii', 'OBL-EVENTS-EV_PACKET_RECEIVED', not forbidden,
                 'no identifier or contact in clear', forbidden[:5], tx)
        times, last = {}, -1
        for spec in ev.get('expected_ordered_subsequence', []):
            oid = f'OBL-EVENTS-{spec["alias"]}'
            trace = ctx.get('trace.' + spec['trace']) if spec.get('trace') else None
            sel = [r for r in events if r.get('eventName') == spec['eventName']
                   and (trace is None or r.get('traceId') == trace)]
            sel_ok = []
            for r in sel:
                a = attr_dict(r.get('attributes'))
                reasons = [match(v, a.get(k), dict(ctx), k) for k, v in spec.get('attributes', {}).items()]
                if spec.get('span_of'):
                    if r.get('spanId') not in {s['spanId'] for s in matched.get(spec['span_of'], [])}:
                        reasons.append(f'spanId not of {spec["span_of"]}')
                reasons = [x for x in reasons if x]
                if reasons:
                    self.add(f'{oid}:values', oid, False, spec.get('attributes'), reasons[:3], tx, spec['eventName'])
                else:
                    sel_ok.append(r)
            self.add(f'{oid}:count', oid, count_ok(spec.get('count'), len(sel)),
                     spec.get('count', 1), len(sel), tx, spec['eventName'])
            if sel:
                first = min(int(r['timeUnixNano']) for r in sel)
                times[spec['alias']] = (first, max(int(r['timeUnixNano']) for r in sel))
                if first < last:
                    self.add(f'{oid}:order', oid, False, 'after the previous expected event', 'earlier', tx, spec['eventName'])
                last = max(last, first)
        for d in ev.get('durations', []):
            oid = f'OBL-EVENTS-{d["id"]}'
            if d['from'] in times and d['to'] in times:
                secs = (times[d['to']][0] - times[d['from']][0]) / 1e9
                self.add(f'{oid}:duration', oid, match(d['expect_s'], secs, {}) is None, d['expect_s'], round(secs, 3), tx)
            else:
                self.add(f'{oid}:duration', oid, False, d['expect_s'], 'event missing', tx,
                         status='NOT_EVALUATED')
        return times

    def evaluate_logs(self, logs, matched, ctx, tx):
        spec_logs = self.c.get('logs', {})
        plain = [r for r in logs if not r.get('eventName')]
        for spec in spec_logs.get('expected', []):
            oid = f'OBL-LOGS-{spec["alias"]}'
            sel = []
            for r in plain:
                if any(match(v, r['_res'].get(k), dict(ctx)) for k, v in spec.get('resource', {}).items()):
                    continue
                checks = [match(spec[k], r.get(k), dict(ctx), k) for k in ('severityNumber', 'severityText', 'traceId')
                          if k in spec]
                if 'body' in spec:
                    checks.append(match(spec['body'], (r.get('body') or {}).get('stringValue'), dict(ctx), 'body'))
                if isinstance(spec.get('spanId'), dict) and '$span_of' in spec['spanId']:
                    allowed = {s['spanId'] for a in spec['spanId']['$span_of'] for s in matched.get(a, [])}
                    if spec['spanId'].get('$descendant_ok'):
                        by_id = {}
                        for a in matched.values():
                            for s in a:
                                by_id[s['spanId']] = s
                        allowed |= {sid for sid, s in by_id.items() if s.get('parentSpanId') in allowed}
                    checks.append(None if r.get('spanId') in allowed else 'spanId')
                if not any(checks):
                    sel.append(r)
            self.add(f'{oid}:count', oid, count_ok(spec.get('count'), len(sel)), spec.get('count', 1), len(sel), tx)
        pii = []
        for r in logs:
            text = (r.get('body') or {}).get('stringValue') or ''
            vals = [str(v) for v in attr_dict(r.get('attributes')).values()] + [text]
            for var in ('uin', 'vid', 'resident.phone', 'resident.email'):
                if ctx.get(var) and any(str(ctx[var]) in v for v in vals):
                    pii.append(f'{r["_svc"]}: {var} in clear')
        self.add('OBL-LOGS-FORBIDDEN:pii', 'OBL-LOGS-LOG_PKR_RECEIVED', not pii, 'no identifier or contact in clear', pii[:5], tx)

    # ---------------------------------------------------------------- NFR and not-yet-executable sections
    def evaluate_nfr(self, matched, times, tx):
        for alias, budget in self.c['nfr'].get('span_budgets_ms', {}).items():
            oid = 'OBL-NFR-span_budgets_ms'
            spans = matched.get(alias, [])
            if not spans:
                self.add(f'{oid}:{alias}', oid, False, budget, 'span not found', tx, alias, status='NOT_EVALUATED')
                continue
            worst = max((int(s['endTimeUnixNano']) - int(s['startTimeUnixNano'])) / 1e6 for s in spans)
            self.add(f'{oid}:{alias}', oid, match(budget, worst, {}) is None, budget, round(worst, 1), tx, alias)

    def not_evaluated(self, tx):
        for o in self.c['obligations']:
            inc = NOT_IN_C1.get(o['section'])
            if inc:
                self.add(f'{o["obligation_id"]}:pending', o['obligation_id'], False, o['section'],
                         f'not executable before {inc}', tx, status='NOT_EVALUATED')
        for k in ('infra_window_checks', 'security', 'e2e_upload_to_processed_s'):
            if k in self.c['nfr']:
                self.add(f'OBL-NFR-{k}:pending', f'OBL-NFR-{k}', False, k,
                         'NOT_APPLICABLE in S1 (no infrastructure)' if k == 'infra_window_checks'
                         else 'evaluated from REST status polling in C2', tx, status='NOT_EVALUATED')

    def evaluate(self, spans, logs, ctx, tx):
        ctx = dict(ctx)
        matched = self.evaluate_spans(spans, ctx, tx)
        self.evaluate_common(spans, ctx, tx)
        self.evaluate_links(spans, matched, ctx, tx)
        times = self.evaluate_events(logs, matched, ctx, tx)
        self.evaluate_logs(logs, matched, ctx, tx)
        self.evaluate_nfr(matched, times, tx)
        self.not_evaluated(tx)
        return matched, ctx


def summarise(results):
    out = {}
    for r in results:
        s = out.setdefault(r['obligation_id'], {'PASS': 0, 'FAIL': 0, 'NOT_EVALUATED': 0})
        s[r['status']] += 1
    return out
