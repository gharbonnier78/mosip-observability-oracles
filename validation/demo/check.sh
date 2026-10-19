#!/usr/bin/env bash
# Rehearsal check for the OAEF live demo (local Docker or Codespaces).
# Replays NIN-001, then verifies trace, logs, metrics and exemplars through the Grafana API.
# usage: bash validation/demo/check.sh [grafana_url] [otlp_http_url]
set -u
cd "$(dirname "$0")/../.."
GRAFANA=${1:-http://localhost:3000}
OTLP=${2:-http://localhost:4318}
AUTH="admin:${GF_ADMIN_PASSWORD:-change-me}"
G() { curl -s -u "$AUTH" "$GRAFANA$1" "${@:2}"; }

echo "== containers"; docker ps --format '{{.Names}} {{.Status}} {{.Image}}' 2>/dev/null || echo "(docker not available here)"
for i in $(seq 1 60); do curl -sf -o /dev/null "$GRAFANA/api/health" && break; sleep 2; done
echo "== grafana health: $(curl -s "$GRAFANA/api/health" | tr -d '\n ')"

echo "== replay"
OUT=$(python3 validation/replay_nin001.py oracles/examples/NIN-001.otlp-example.json "$OTLP" 2>&1); echo "$OUT"
TID=$(echo "$OUT" | awk '/replayed trace id/{print $4}')
[ -n "$TID" ] || { echo "RESULT: FAIL replay"; exit 1; }
echo "== waiting 30 s for ingestion"; sleep 30

DS=$(G /api/datasources)
echo "== datasources"; echo "$DS" | jq -r '.[]|"\(.uid) \(.type) \(.name)"'
uid_of() { echo "$DS" | jq -r --arg t "$1" '[.[]|select(.type==$t)][0].uid // empty'; }
TEMPO=$(uid_of tempo); LOKI=$(uid_of loki); PROM=$(uid_of prometheus)

echo "== trace $TID"
SPANS=$(G "/api/datasources/proxy/uid/$TEMPO/api/traces/$TID" | jq -c '[(.batches // .resourceSpans)[]?.scopeSpans[]?.spans[]?.name]')
echo "$SPANS"
N_SPANS=$(echo "$SPANS" | jq 'length' 2>/dev/null || echo 0)

echo "== logs (regproc-pkr, last hour)"
LOGS=$(G "/api/datasources/proxy/uid/$LOKI/loki/api/v1/query_range" --get \
  --data-urlencode 'query={service_name="regproc-pkr"}' --data-urlencode 'since=1h' \
  | jq -c '[.data.result[]?.values[]?[1]]')
echo "$LOGS" | cut -c1-400
N_LOGS=$(echo "$LOGS" | jq 'length' 2>/dev/null || echo 0)

echo "== metric series"
G "/api/datasources/proxy/uid/$PROM/api/v1/series" --get \
  --data-urlencode 'match[]={__name__=~"http_server_request_duration.*"}' \
  | jq -c '[.data[]?|{n:.__name__, job:.job, service_name:.service_name}]|unique'
echo "== exemplars"
EX=$(G "/api/datasources/proxy/uid/$PROM/api/v1/query_exemplars" --get \
  --data-urlencode 'query={__name__=~"http_server_request_duration.*bucket"}' \
  --data-urlencode "start=$(( $(date +%s) - 3600 ))" --data-urlencode "end=$(date +%s)" \
  | jq -c '[.data[]?.exemplars[]?.labels]')
echo "$EX"
EX_MATCH=$(echo "$EX" | jq --arg t "$TID" '[.[]?|select(.trace_id==$t or .traceID==$t)]|length' 2>/dev/null || echo 0)

echo "== summary"
echo "spans in trace      : $N_SPANS (expected 7)"
echo "pkr log records     : $N_LOGS (expected >= 1)"
echo "exemplar -> trace   : $EX_MATCH (expected >= 1)"
if [ "$N_SPANS" -ge 7 ] && [ "$N_LOGS" -ge 1 ] && [ "$EX_MATCH" -ge 1 ]; then echo "RESULT: PASS"; else echo "RESULT: CHECK (see details above)"; fi
