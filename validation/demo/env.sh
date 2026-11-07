# Sourced by start_stack.sh and run_v5_demo.sh: where evidence is written and how a browser reaches
# Grafana and the report server (Codespaces forwarded ports, or localhost).
export OAEF_OUT=${OAEF_OUT:-/tmp/oaef-v5}
if [ -n "${CODESPACE_NAME:-}" ]; then
  _d=${GITHUB_CODESPACES_PORT_FORWARDING_DOMAIN:-app.github.dev}
  export OAEF_GRAFANA_PUBLIC_URL=${OAEF_GRAFANA_PUBLIC_URL:-https://$CODESPACE_NAME-3000.$_d}
  export OAEF_REPORT_BASE_URL=${OAEF_REPORT_BASE_URL:-https://$CODESPACE_NAME-8080.$_d}
else
  export OAEF_GRAFANA_PUBLIC_URL=${OAEF_GRAFANA_PUBLIC_URL:-http://localhost:3000}
  export OAEF_REPORT_BASE_URL=${OAEF_REPORT_BASE_URL:-http://localhost:8080}
fi
