#!/usr/bin/env python3
"""Replay the NIN-001 OTLP example with fresh ids and timestamps (OAEF-VTS-001, TP-1).

usage: python3 replay_nin001.py <example.json> <otlp-http-endpoint>

  local / Codespaces : python3 replay_nin001.py oracles/examples/NIN-001.otlp-example.json http://localhost:4318
  Grafana Cloud      : python3 replay_nin001.py oracles/examples/NIN-001.otlp-example.json https://otlp-gateway-<zone>.grafana.net/otlp

Authentication (optional) uses the standard variable OTEL_EXPORTER_OTLP_HEADERS,
comma-separated key=value pairs, values URL-encoded, for example:
  OTEL_EXPORTER_OTLP_HEADERS="Authorization=Basic%20<base64(instanceId:token)>"
Only the Python standard library is used.
"""
import json
import os
import sys
import time
import urllib.parse
import urllib.request


def otlp_headers():
    headers = {'Content-Type': 'application/json'}
    raw = os.environ.get('OTEL_EXPORTER_OTLP_HEADERS', '')
    for pair in filter(None, (p.strip() for p in raw.split(','))):
        key, _, value = pair.partition('=')
        headers[urllib.parse.unquote(key.strip())] = urllib.parse.unquote(value.strip())
    return headers


def main():
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    src, endpoint = sys.argv[1], sys.argv[2].rstrip('/')
    doc = json.load(open(src, encoding='utf-8'))
    ids = {}

    def new_id(old, n):
        if not old:
            return old
        return ids.setdefault(old, os.urandom(n).hex())

    t_min = min(int(s['startTimeUnixNano'])
                for rs in doc['traces']['resourceSpans']
                for ss in rs['scopeSpans'] for s in ss['spans'])
    shift = time.time_ns() - t_min - 60_000_000_000          # start one minute ago

    def fix(o):
        if isinstance(o, dict):
            for k, v in list(o.items()):
                if k.endswith('UnixNano') and isinstance(v, str):
                    o[k] = str(int(v) + shift)
                elif k == 'traceId':
                    o[k] = new_id(v, 16)
                elif k in ('spanId', 'parentSpanId'):
                    o[k] = new_id(v, 8)
                else:
                    fix(v)
        elif isinstance(o, list):
            for x in o:
                fix(x)

    for block in ('traces', 'logs', 'metrics'):
        fix(doc[block])
    headers = otlp_headers()
    for block, path in (('traces', '/v1/traces'), ('logs', '/v1/logs'), ('metrics', '/v1/metrics')):
        req = urllib.request.Request(endpoint + path, data=json.dumps(doc[block]).encode(), headers=headers)
        with urllib.request.urlopen(req) as resp:
            print(f'{block:8s} HTTP {resp.status}')
    print('replayed trace id:', ids['4bf92f3577b34da6a3ce929d0e0e4736'])
    print('packet-receiver span id:', ids['53995c3f42cd8ad8'])


if __name__ == '__main__':
    main()
