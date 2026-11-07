#!/usr/bin/env python3
"""Build the reusable OAEF Grafana dashboards (JSON) from one readable definition.

  python3 observability/dashboards/build_dashboards.py      -> oaef-test-runs.json, oaef-journey.json

Reusable outside MOSIP: data sources are dashboard variables (any Prometheus/Loki/Tempo), and the only
conventions assumed are the OAEF ones: verdict events `oaef.test.verdict` from service `oaef-jarvis`,
`oaef.run.id` on spans/logs/run-scoped metrics, OTel semantic-convention HTTP metrics, Tempo span metrics.
"""
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROM = {'type': 'prometheus', 'uid': '${ds_prom}'}
LOKI = {'type': 'loki', 'uid': '${ds_loki}'}
TEMPO = {'type': 'tempo', 'uid': '${ds_tempo}'}


def ds_var(name, kind, label):
    return {'name': name, 'type': 'datasource', 'query': kind, 'label': label, 'hide': 0, 'refresh': 1,
            'current': {}, 'options': []}


def panel(pid, kind, title, x, y, w, h, ds, targets, **extra):
    p = {'id': pid, 'type': kind, 'title': title, 'gridPos': {'x': x, 'y': y, 'w': w, 'h': h},
         'datasource': ds, 'targets': [dict(t, refId=chr(65 + i), datasource=ds) for i, t in enumerate(targets)]}
    p.update(extra)
    return p


def dashboard(uid, title, description, variables, panels, links=()):
    return {'uid': uid, 'title': title, 'description': description, 'tags': ['oaef'], 'editable': True,
            'schemaVersion': 39, 'timezone': 'browser', 'time': {'from': 'now-6h', 'to': 'now'},
            'refresh': '', 'templating': {'list': variables}, 'panels': panels, 'links': list(links)}


VERDICTS = '{service_name="oaef-jarvis"} | json'
REPORT_LINK = {'matcher': {'id': 'byName', 'options': 'report_url'},
               'properties': [{'id': 'links', 'value': [{'title': 'Open the test report', 'url': '${__value.raw}',
                                                          'targetBlank': True}]}]}
JOURNEY_LINK = {'matcher': {'id': 'byName', 'options': 'run_id'},
                'properties': [{'id': 'links', 'value': [{'title': 'Journey dashboard of this run',
                                                          'url': '/d/oaef-journey/oaef-journey?var-run_id=${__value.raw}&${__url_time_range}'}]}]}

test_runs = dashboard(
    'oaef-test-runs', 'OAEF — Test runs',
    'Verdicts published by Jarvis (oaef.test.verdict): one row per run, with its classes and a link to its report.',
    [ds_var('ds_loki', 'loki', 'Loki')],
    [
        panel(1, 'stat', 'Runs by verdict', 0, 0, 8, 6, LOKI,
              [{'expr': f'sum by (status) (count_over_time({VERDICTS} [$__range]))', 'queryType': 'instant',
                'legendFormat': '{{status}}'}],
              options={'reduceOptions': {'calcs': ['lastNotNull']}, 'colorMode': 'background', 'textMode': 'value_and_name'},
              fieldConfig={'defaults': {}, 'overrides': [
                  {'matcher': {'id': 'byName', 'options': n}, 'properties': [{'id': 'color', 'value': {'mode': 'fixed', 'fixedColor': c}}]}
                  for n, c in (('PASS', 'green'), ('FAIL', 'red'), ('INCONCLUSIVE', 'orange'))]}),
        panel(2, 'piechart', 'Failures by diagnostic class', 8, 0, 8, 6, LOKI,
              [{'expr': f'sum by (cls) (count_over_time({{service_name="oaef-jarvis"}} | json status, cls="classes[0]" '
                        f'| status != "PASS" [$__range]))', 'queryType': 'instant', 'legendFormat': '{{cls}}'}],
              options={'legend': {'displayMode': 'table', 'placement': 'right', 'values': ['value']}}),
        panel(3, 'timeseries', 'Verdicts over time', 16, 0, 8, 6, LOKI,
              [{'expr': f'sum by (status) (count_over_time({VERDICTS} [$__interval]))', 'legendFormat': '{{status}}'}],
              fieldConfig={'defaults': {'custom': {'drawStyle': 'bars', 'stacking': {'mode': 'normal'}}}, 'overrides': []}),
        panel(4, 'table', 'Runs (click run_id for its journey, report_url for its report)', 0, 6, 24, 14, LOKI,
              [{'expr': VERDICTS, 'queryType': 'range'}],
              transformations=[{'id': 'extractFields', 'options': {'source': 'labels', 'replace': False}},
                               {'id': 'organize', 'options': {'includeByName': {
                                   'Time': True, 'run_id': True, 'test_case': True, 'fault': True, 'status': True,
                                   'classes': True, 'failed_checks': True, 'transactions': True, 'report_url': True}}}],
              fieldConfig={'defaults': {}, 'overrides': [REPORT_LINK, JOURNEY_LINK,
                  {'matcher': {'id': 'byName', 'options': 'status'}, 'properties': [
                      {'id': 'custom.cellOptions', 'value': {'type': 'color-background'}},
                      {'id': 'mappings', 'value': [{'type': 'value', 'options': {
                          'PASS': {'color': 'green'}, 'FAIL': {'color': 'red'}, 'INCONCLUSIVE': {'color': 'orange'}}}]}]}]}),
    ],
    links=[{'title': 'OAEF — Journey', 'type': 'link', 'url': '/d/oaef-journey/oaef-journey'}])

RUN = 'oaef_run_id="$run_id"'
journey = dashboard(
    'oaef-journey', 'OAEF — Journey',
    'One test run: service graph, per-service requests and latency (run-scoped), journey histogram with exemplars, '
    'span-metrics RED, the run\'s traces, business events and verdict.',
    [ds_var('ds_prom', 'prometheus', 'Prometheus'), ds_var('ds_tempo', 'tempo', 'Tempo'), ds_var('ds_loki', 'loki', 'Loki'),
     {'name': 'run_id', 'type': 'query', 'label': 'Run', 'datasource': PROM, 'refresh': 2, 'sort': 0,
      'query': {'query': 'label_values(oaef_synthetic_journey_duration_seconds_count, oaef_run_id)', 'refId': 'run'},
      'current': {}, 'options': []},
     {'name': 'service', 'type': 'query', 'label': 'Service', 'datasource': PROM, 'refresh': 2, 'multi': True,
      'includeAll': True, 'allValue': '.+',
      'query': {'query': 'label_values(http_server_request_duration_seconds_count{' + RUN + '}, service_name)', 'refId': 'svc'},
      'current': {}, 'options': []}],
    [
        panel(1, 'nodeGraph', 'Service graph (Tempo, all runs in the time range)', 0, 0, 12, 10, TEMPO,
              [{'queryType': 'serviceMap'}]),
        panel(2, 'stat', 'Transactions in this run', 12, 0, 4, 5, PROM,
              [{'expr': f'sum(oaef_synthetic_journey_duration_seconds_count{{{RUN}}})', 'instant': True}]),
        panel(3, 'stat', 'Verdict of this run', 16, 0, 8, 5, LOKI,
              [{'expr': f'sum by (status) (count_over_time({{service_name="oaef-jarvis"}} |= "$run_id" | json status [$__range]))',
                'queryType': 'instant', 'legendFormat': '{{status}}'}],
              options={'reduceOptions': {'calcs': ['lastNotNull']}, 'textMode': 'name', 'colorMode': 'background'}),
        panel(4, 'bargauge', 'Requests per service (this run)', 12, 5, 6, 5, PROM,
              [{'expr': f'sum by (service_name) (http_server_request_duration_seconds_count{{{RUN}, service_name=~"$service"}})',
                'instant': True, 'legendFormat': '{{service_name}}'}],
              options={'orientation': 'horizontal', 'displayMode': 'basic'}),
        panel(5, 'bargauge', 'Mean server latency per service (this run)', 18, 5, 6, 5, PROM,
              [{'expr': f'sum by (service_name) (http_server_request_duration_seconds_sum{{{RUN}, service_name=~"$service"}}) / '
                        f'sum by (service_name) (http_server_request_duration_seconds_count{{{RUN}, service_name=~"$service"}})',
                'instant': True, 'legendFormat': '{{service_name}}'}],
              options={'orientation': 'horizontal', 'displayMode': 'basic'},
              fieldConfig={'defaults': {'unit': 's'}, 'overrides': []}),
        panel(6, 'timeseries', 'Journey duration buckets of this run (exemplars open the trace)', 0, 10, 12, 8, PROM,
              [{'expr': f'sum by (le) (oaef_synthetic_journey_duration_seconds_bucket{{{RUN}}})', 'exemplar': True,
                'legendFormat': 'le {{le}}'}],
              fieldConfig={'defaults': {'custom': {'drawStyle': 'points', 'pointSize': 8}}, 'overrides': []}),
        panel(7, 'timeseries', 'RED from span metrics: request rate per service', 12, 10, 12, 8, PROM,
              [{'expr': 'sum by (service) (rate(traces_spanmetrics_calls_total{service=~"$service", span_kind="SPAN_KIND_SERVER"}[$__rate_interval]))',
                'legendFormat': '{{service}}'},
               {'expr': 'sum by (service) (rate(traces_spanmetrics_calls_total{service=~"$service", status_code="STATUS_CODE_ERROR"}[$__rate_interval]))',
                'legendFormat': 'errors {{service}}'}],
              fieldConfig={'defaults': {'unit': 'reqps'}, 'overrides': []}),
        panel(8, 'table', 'Traces of this run (click a trace id)', 0, 18, 12, 10, TEMPO,
              [{'queryType': 'traceql', 'query': '{ span.oaef.run.id = "$run_id" }', 'tableType': 'traces', 'limit': 100}]),
        panel(9, 'timeseries', 'p95 latency per service (span metrics)', 12, 18, 12, 10, PROM,
              [{'expr': 'histogram_quantile(0.95, sum by (service, le) (rate(traces_spanmetrics_latency_bucket{service=~"$service", span_kind="SPAN_KIND_SERVER"}[$__rate_interval])))',
                'legendFormat': '{{service}}'}],
              fieldConfig={'defaults': {'unit': 's'}, 'overrides': []}),
        panel(10, 'logs', 'Business events of this run', 0, 28, 24, 10, LOKI,
              [{'expr': '{service_name=~".+"} |= "$run_id" | json | event_name =~ ".+"', 'queryType': 'range'}],
              options={'showTime': True, 'wrapLogMessage': True, 'prettifyLogMessage': True}),
    ],
    links=[{'title': 'OAEF — Test runs', 'type': 'link', 'url': '/d/oaef-test-runs/oaef-test-runs'}])

if __name__ == '__main__':
    for name, d in (('oaef-test-runs.json', test_runs), ('oaef-journey.json', journey)):
        (HERE / name).write_text(json.dumps(d, indent=2) + '\n', encoding='utf-8')
        print('wrote', HERE / name)
