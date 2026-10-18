#!/usr/bin/env python3
# replay_nin001.py  -  usage: python3 replay_nin001.py NIN-001.otlp-example.json http://AGENT:4318
import json, os, sys, time, urllib.request
src, endpoint = sys.argv[1], sys.argv[2].rstrip('/')
doc = json.load(open(src, encoding='utf-8'))
ids = {}
def new_id(old, n):
    if not old: return old
    return ids.setdefault(old, os.urandom(n).hex())
t_min = min(int(s['startTimeUnixNano']) for rs in doc['traces']['resourceSpans']
            for ss in rs['scopeSpans'] for s in ss['spans'])
shift = time.time_ns() - t_min - 60_000_000_000          # start one minute ago
def fix(o):
    if isinstance(o, dict):
        for k, v in list(o.items()):
            if k.endswith('UnixNano') and isinstance(v, str): o[k] = str(int(v) + shift)
            elif k == 'traceId': o[k] = new_id(v, 16)
            elif k in ('spanId', 'parentSpanId'): o[k] = new_id(v, 8)
            else: fix(v)
    elif isinstance(o, list):
        for x in o: fix(x)
for block in ('traces', 'logs', 'metrics'): fix(doc[block])
for block, path in (('traces', '/v1/traces'), ('logs', '/v1/logs'), ('metrics', '/v1/metrics')):
    req = urllib.request.Request(endpoint + path, data=json.dumps(doc[block]).encode(),
                                 headers={'Content-Type': 'application/json'})
    print(block, urllib.request.urlopen(req).status)
root = ids['4bf92f3577b34da6a3ce929d0e0e4736']
print('replayed trace id:', root)