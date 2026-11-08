#!/usr/bin/env bash
# Start the OAEF demo stack (LGTM) and the evidence report server on port 8080.
# Synthetic evidence only; keep forwarded ports Private.
set -eu
cd "$(dirname "$0")/../.."
. validation/demo/env.sh
docker compose -f validation/demo/docker-compose.yml up -d
mkdir -p "$OAEF_OUT/runs"
if ! curl -sf -o /dev/null http://127.0.0.1:8080/; then
  nohup python3 -m http.server 8080 --bind 127.0.0.1 --directory "$OAEF_OUT" >/tmp/oaef-report-server.log 2>&1 &
fi
echo "Grafana : $OAEF_GRAFANA_PUBLIC_URL"
echo "Reports : $OAEF_REPORT_BASE_URL/"
