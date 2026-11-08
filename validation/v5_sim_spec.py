#!/usr/bin/env python3
"""S1 simulator, specification edition (C1c): emits, for one NIN-001 transaction, the telemetry an instrumented
MOSIP 1.2 platform is expected to produce, following the *behaviour* of the activity model (upload, validation
stages, dedupe no hit, UIN generation, identity creation, credential, notification).

It is written from the MOSIP flow, not from the oracle: the oracle (generated/contracts/NIN-001.contract.json)
checks it independently, so the two can disagree. Synthetic values only (RID shape, UIN surrogate, hashes).

Faults act on what the platform does or emits:
  duplicate    uin.assigned event emitted twice          missing      uin.assigned event not emitted
  wrong_value  identity.activated carries a wrong hash    slow         identity creation takes 3150 ms
  broken_link  idrepo server span loses its parent        (metric faults are handled by v5_demo.py)
"""
import hashlib

STAGES = ['packet-uploader', 'packet-validator', 'packet-classifier', 'cmd-validator', 'operator-validator',
          'demo-dedupe', 'bio-dedupe', 'uin-generator', 'finalization']
STAGE_CODES = ['UPLOAD_PACKET', 'VALIDATE_PACKET', 'PACKET_CLASSIFICATION', 'CMD_VALIDATION', 'OPERATOR_VALIDATION',
               'DEMOGRAPHIC_VERIFICATION', 'BIOGRAPHIC_VERIFICATION', 'UIN_GENERATOR', 'FINALIZATION']
API = 'https://api.test-int.nims.example'


def h(*parts, width=16):
    return hashlib.sha256('|'.join(map(str, parts)).encode()).hexdigest()[:width]


def run_context(run_id):
    """Environment and run variables, as Jarvis gets them from the environment manager (not from telemetry)."""
    return {'env.name': 'test-int', 'env.site': 'dc1', 'env.cluster': 'dc1-k8s-test', 'env.id': 'ENV-000123',
            'env.site_role': 'primary', 'run.id': run_id, 'ci.pipeline.name': 'oaef-v5-demo'}


def resource(service, ctx):
    return {'service.name': service, 'service.namespace': 'jarvis' if service == 'jarvis-e2e' else 'mosip',
            'deployment.environment.name': ctx['env.name'], 'cloud.region': ctx['env.site'],
            'k8s.cluster.name': ctx['env.cluster'], 'oaef.site.role': ctx['env.site_role'], 'oaef.env.id': ctx['env.id'],
            'oaef.simulation.mode': 'S1'}


def transaction(seed, run_id, tx, started_ns, d_ms, fault, target, ctx):
    """Spans (list of (service, span dict with python-native attributes)), records (logs and events), truth."""
    tx_id = f'TX-{tx:03d}'
    rid = f'1000110001{tx:05d}20261107{seed % 1000000:06d}'
    uin = str(2 + (int(h(seed, tx, 'uin', width=12), 16) % 7)) + str(int(h(seed, tx, 'uin2', width=12), 16))[:10]
    uin_hash = f'{tx}_' + hashlib.sha256(uin.encode()).hexdigest().upper()
    t1 = h(seed, run_id, tx_id, 'T1', width=32)
    t2 = h(seed, run_id, tx_id, 'T2', width=32)
    t3 = h(seed, run_id, tx_id, 'T3', width=32)
    is_target = tx == target
    idrepo_ms = 3150 if fault == 'slow' and is_target else 60 + d_ms // 3
    spans, records = [], []
    clock = [started_ns]

    def ms(x):
        return int(x * 1_000_000)

    def span(service, name, kind, parent, t0, dur, attrs=None, trace=t1, sid=None, links=None, status=0, scope=None):
        sid = sid or h(seed, run_id, tx_id, service, name, t0, len(spans))
        a = {'oaef.run.id': run_id, 'oaef.transaction.id': tx_id}
        if trace == t1:
            a.update({'cicd.pipeline.run.id': ctx['run.id'], 'test.case.name': 'NIN-001'})
        a.update(attrs or {})
        sp = {'traceId': trace, 'spanId': sid, 'name': name, 'kind': kind,
              'startTimeUnixNano': str(started_ns + ms(t0)), 'endTimeUnixNano': str(started_ns + ms(t0 + dur)),
              'attributes': a, 'status': {'code': status}, '_scope': scope or 'io.opentelemetry'}
        if parent:
            sp['parentSpanId'] = parent
        if links:
            sp['links'] = links
        spans.append((service, sp))
        return sid

    def record(service, t, trace, span_id, message=None, event=None, attrs=None, severity=9):
        a = {'oaef.run.id': run_id, 'oaef.transaction.id': tx_id}
        a.update(attrs or {})
        records.append((service, {'timeUnixNano': str(started_ns + ms(t)), 'severityNumber': severity,
                                  'severityText': 'INFO' if severity == 9 else 'ERROR', 'traceId': trace,
                                  'spanId': span_id, 'eventName': event, 'message': message, 'attributes': a}))

    # Jarvis: root, step, upload client; MOSIP packet receiver
    root = span('jarvis-e2e', 'NIN-001 New adult registration no hit', 1, None, 0, d_ms + 400,
                {'test.suite.name': 'TC-NIN', 'oaef.test.persona': 'adult-nohit', 'oaef.test.verdict': 'PASS',
                 'test.case.result.status': 'pass', 'cicd.pipeline.name': ctx['ci.pipeline.name']}, status=1, scope='jarvis')
    step = span('jarvis-e2e', f'step: Jarvis uploads "{rid}.zip" with "POST /registrationprocessor/v1/packetreceiver/registrationpackets"',
                1, root, 1, 12, scope='jarvis')
    up = span('jarvis-e2e', 'POST', 3, step, 2, 10, {'http.request.method': 'POST', 'server.address': 'api.test-int.nims.example',
              'url.full': f'{API}/registrationprocessor/v1/packetreceiver/registrationpackets', 'http.response.status_code': 200})
    route = '/registrationprocessor/v1/packetreceiver/registrationpackets'
    pkr = span('regproc-pkr', f'POST {route}', 2, up, 3, 8, {'http.request.method': 'POST', 'url.path': route, 'url.scheme': 'https',
               'http.route': route, 'http.response.status_code': 200, 'network.protocol.version': '1.1', 'mosip.rid': rid})
    span('regproc-pkr', 'INSERT mosip_regprc.registration', 3, pkr, 4, 1, {'db.system.name': 'postgresql',
         'db.namespace': 'mosip_regprc', 'db.operation.name': 'INSERT', 'db.collection.name': 'registration'})
    ac = span('regproc-pkr', 'POST', 3, pkr, 5, 2, {'http.request.method': 'POST',
              'url.full': 'http://auditmanager.mosip/v1/auditmanager/audits', 'http.response.status_code': 200})
    asv = span('auditmanager', 'POST /v1/auditmanager/audits', 2, ac, 5.2, 1.5, {'http.response.status_code': 200})
    span('auditmanager', 'INSERT mosip_audit.app_audit_log', 3, asv, 5.4, 0.8, {'db.system.name': 'postgresql',
         'db.namespace': 'mosip_audit', 'db.operation.name': 'INSERT', 'db.collection.name': 'app_audit_log'})
    topic = 'packet-receiver-bus-out'
    pub = span('regproc-pkr', f'{topic} publish', 4, pkr, 7, 0.5, {'messaging.system': 'kafka',
               'messaging.operation': 'publish', 'messaging.destination.name': topic})
    record('regproc-pkr', 3.5, t1, pkr, message=f'SESSIONID - REGISTRATIONID - {rid} - PacketReceiverServiceImpl::storePacket()::exit')
    record('regproc-pkr', 3.6, t1, pkr, event='mosip.registration.packet.received', attrs={'mosip.rid': rid, 'mosip.reg_type': 'NEW'})

    # Stage chain over Kafka: each stage consumes the previous publish, then publishes to the next topic
    t, parent_pub, group = 10, pub, 1
    stage_spans = {}
    for i, stage in enumerate(STAGES):
        group = 1 + i % 7
        svc = f'regproc-group{group}'
        dest = topic if i == 0 else f'{STAGES[i - 1]}-bus-out'
        dur = 6 if stage != 'uin-generator' else idrepo_ms + 40
        proc = span(svc, f'{dest} process', 5, parent_pub, t, dur, {'messaging.system': 'kafka', 'messaging.operation': 'process',
                    'messaging.destination.name': dest, 'messaging.kafka.consumer.group': f'{stage}-group', 'mosip.rid': rid})
        stage_spans[stage] = (svc, proc, t)
        if stage == 'packet-uploader':
            span(svc, 'POST', 3, proc, t + 0.5, 2, {'http.request.method': 'POST', 'url.full': 'http://keymanager.mosip/v1/keymanager/decrypt',
                 'http.response.status_code': 200})
            span(svc, 'S3.PutObject', 3, proc, t + 3, 1.5, {'rpc.system': 'aws-api', 'rpc.service': 'S3', 'rpc.method': 'PutObject'})
        if stage == 'uin-generator':
            g = span(svc, 'GET', 3, proc, t + 1, 4, {'http.request.method': 'GET', 'url.full': 'http://idgenerator.mosip/v1/idgenerator/uin',
                     'http.response.status_code': 200})
            span('idgenerator', 'GET /v1/idgenerator/uin', 2, g, t + 1.5, 3, {'http.route': '/v1/idgenerator/uin',
                 'http.response.status_code': 200})
            c = span(svc, 'POST', 3, proc, t + 6, idrepo_ms + 4, {'http.request.method': 'POST',
                     'url.full': 'http://idrepo-identity.mosip/idrepository/v1/identity/', 'http.response.status_code': 200})
            parent = h(seed, 'lost', tx_id) if fault == 'broken_link' and is_target else c
            irs = span('idrepo-identity', 'POST /idrepository/v1/identity/', 2, parent, t + 7, idrepo_ms,
                       {'http.route': '/idrepository/v1/identity/', 'http.response.status_code': 200})
            span('idrepo-identity', 'POST', 3, irs, t + 8, 3, {'http.request.method': 'POST',
                 'url.full': 'http://keymanager.mosip/v1/keymanager/encrypt', 'http.response.status_code': 200})
            span('idrepo-identity', 'INSERT mosip_idrepo.uin', 3, irs, t + 12, 2, {'db.system.name': 'postgresql',
                 'db.namespace': 'mosip_idrepo', 'db.operation.name': 'INSERT', 'db.collection.name': 'uin'})
            assigned_at = t + 6.5
            if not (fault == 'missing' and is_target):
                record(svc, assigned_at, t1, proc, event='mosip.identity.uin.assigned', attrs={'mosip.rid': rid})
            if fault == 'duplicate' and is_target:
                record(svc, assigned_at + 0.001, t1, proc, event='mosip.identity.uin.assigned', attrs={'mosip.rid': rid})
            act_hash = 'CORRUPTED_HASH' if fault == 'wrong_value' and is_target else uin_hash
            record('idrepo-identity', t + 7 + idrepo_ms - 1, t1, irs, event='mosip.identity.activated',
                   attrs={'mosip.uin_hash': act_hash})
            record('idrepo-identity', t + 7 + idrepo_ms - 0.5, t1, irs, message=f'identity created for registration {rid}')
            span(svc, 'PUT', 3, proc, t + 8 + idrepo_ms, 3, {'http.request.method': 'PUT',
                 'url.full': 'http://idgenerator.mosip/v1/idgenerator/uin', 'http.response.status_code': 200})
            span('idgenerator', 'PUT /v1/idgenerator/uin', 2, spans[-1][1]['spanId'], t + 8.5 + idrepo_ms, 2,
                 {'http.route': '/v1/idgenerator/uin', 'http.response.status_code': 200})
            idrepo_span, idrepo_end = irs, t + 7 + idrepo_ms
        record(svc, t + dur - 0.5, t1, proc, message=f'{STAGE_CODES[i]} SUCCESS for registration {rid}')
        record(svc, t + dur - 0.4, t1, proc, event='mosip.registration.stage.completed',
               attrs={'mosip.rid': rid, 'mosip.stage': STAGE_CODES[i], 'mosip.stage.status': 'SUCCESS'})
        t += dur + 2
        if i < len(STAGES) - 1:
            parent_pub = span(svc, f'{stage}-bus-out publish', 4, proc, t - 1.5, 0.5, {'messaging.system': 'kafka',
                              'messaging.operation': 'publish', 'messaging.destination.name': f'{stage}-bus-out'})
    # notification after finalization (event attached to the finalization stage span)
    fin_svc, fin_span, fin_t = stage_spans['finalization']
    record(fin_svc, idrepo_end + 90, t1, fin_span, event='mosip.notification.sent',
           attrs={'mosip.rid': rid, 'mosip.notification.channel': 'email'})
    # Jarvis polls the registration status until PROCESSED
    for k in range(3):
        span('jarvis-e2e', 'POST', 3, root, 20 + k * 100, 4, {'http.request.method': 'POST',
             'url.full': f'{API}/registrationprocessor/v1/registrationstatus/search', 'http.response.status_code': 200})

    # T2: credential request batch job (new trace, linked to the identity creation span)
    batch = span('credential-request-generator', 'credential-request batch', 1, None, idrepo_end + 50, 30,
                 {'mosip.rid': rid, 'test.case.name': 'NIN-001'}, trace=t2,
                 links=[{'traceId': t1, 'spanId': idrepo_span}])
    pubc = span('credential-service', 'POST /v1/credentialservice/issue', 2, batch, idrepo_end + 55, 20,
                {'http.response.status_code': 200}, trace=t2)
    record('credential-service', idrepo_end + 70, t2, pubc, event='mosip.credential.issued', attrs={'mosip.uin_hash': uin_hash})
    # T3: WebSub delivery to the IDA callback (new trace, linked to T2)
    span('ida-internal', 'POST /idauthentication/v1/internal/callback/idchange', 2, None, idrepo_end + 120, 15,
         {'mosip.uin_hash': uin_hash}, trace=t3, links=[{'traceId': t2, 'spanId': pubc}])
    truth = {'transaction_id': tx_id, 'rid': rid, 'uin': uin, 'uin_hash': uin_hash, 'trace_root': t1,
             'identity_creation_ms': idrepo_ms, 'upload_to_assignment_ms': d_ms}
    return spans, records, truth


def kv(k, v):
    if isinstance(v, bool):
        return {'key': k, 'value': {'boolValue': v}}
    if isinstance(v, int):
        return {'key': k, 'value': {'intValue': str(v)}}
    if isinstance(v, float):
        return {'key': k, 'value': {'doubleValue': v}}
    return {'key': k, 'value': {'stringValue': str(v)}}


def to_otlp(all_spans, all_records, ctx):
    """OTLP/JSON traces and logs (one resource per service). Logs carry a JSON body with the fields the
    backend collector needs to rebuild them from Loki (service, severity, event name, ids, attributes)."""
    import json
    by_svc = {}
    for svc, sp in all_spans:
        sp = {k: v for k, v in sp.items() if not k.startswith('_')}
        sp['attributes'] = [kv(k, v) for k, v in sorted(sp['attributes'].items())]
        by_svc.setdefault(svc, []).append(sp)
    traces = {'resourceSpans': [{'resource': {'attributes': [kv(k, v) for k, v in sorted(resource(svc, ctx).items())]},
                                 'scopeSpans': [{'scope': {'name': 'oaef.v5.s1'}, 'spans': rows}]}
                                for svc, rows in sorted(by_svc.items())]}
    logs_by = {}
    for svc, r in all_records:
        body = {'service': svc, 'severity_number': r['severityNumber'], 'severity_text': r['severityText'],
                'event_name': r['eventName'], 'trace_id': r['traceId'], 'span_id': r['spanId'],
                'message': r['message'], 'attributes': r['attributes'],
                'run_id': r['attributes']['oaef.run.id'], 'transaction_id': r['attributes']['oaef.transaction.id']}
        rec = {'timeUnixNano': r['timeUnixNano'], 'observedTimeUnixNano': r['timeUnixNano'],
               'severityNumber': r['severityNumber'], 'severityText': r['severityText'],
               'traceId': r['traceId'], 'spanId': r['spanId'],
               'body': {'stringValue': json.dumps(body, sort_keys=True, separators=(',', ':'))},
               'attributes': [kv(k, v) for k, v in sorted(r['attributes'].items())]}
        if r['eventName']:
            rec['eventName'] = r['eventName']
        logs_by.setdefault(svc, []).append(rec)
    logs = {'resourceLogs': [{'resource': {'attributes': [kv(k, v) for k, v in sorted(resource(svc, ctx).items())]},
                              'scopeLogs': [{'scope': {'name': 'oaef.v5.s1'}, 'logRecords': rows}]}
                             for svc, rows in sorted(logs_by.items())]}
    return traces, logs


def normalise(traces, logs):
    """OTLP/JSON -> engine input: spans and records with '_svc' and '_res' (resource attributes as a dict)."""
    from oaef_oracle import attr_dict
    spans, records = [], []
    for g in traces.get('resourceSpans', []):
        res = attr_dict(g.get('resource', {}).get('attributes'))
        for sc in g.get('scopeSpans', []):
            for sp in sc.get('spans', []):
                spans.append(dict(sp, _svc=res.get('service.name'), _res=res))
    for g in logs.get('resourceLogs', []):
        res = attr_dict(g.get('resource', {}).get('attributes'))
        for sc in g.get('scopeLogs', []):
            for r in sc.get('logRecords', []):
                records.append(dict(r, _svc=res.get('service.name'), _res=res))
    return spans, records
