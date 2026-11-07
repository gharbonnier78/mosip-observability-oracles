#!/usr/bin/env bash
# OAEF V5 live demo orchestration (Codespaces or local LGTM stack).
# Runs each demo case end to end: S1 generation + OTLP export, S2-read backend collection,
# bundle integrity check and offline re-evaluation. Asserts the EXPECTED exit code of every step,
# so a mutant that escapes detection, or a nominal run that fails, makes this script fail.
#
# usage: bash validation/demo/run_v5_demo.sh [case ...]
#   cases: tests s0 nominal duplicate missing slow broken_link wrong_value metric_count
#          (default: tests nominal duplicate missing slow broken_link)
# env:   OAEF_OUT (default /tmp/oaef-v5)  OAEF_OTLP (http://localhost:4318)  OAEF_GRAFANA (http://localhost:3000)
#        OAEF_SEED (20261107)  OAEF_COUNT (100)  OAEF_TARGET (17)
#        OAEF_GRAFANA_PASSWORD or GF_ADMIN_PASSWORD (Codespaces secret; never committed)
set -u
cd "$(dirname "$0")/../.."
. validation/demo/env.sh   # OAEF_OUT, OAEF_GRAFANA_PUBLIC_URL, OAEF_REPORT_BASE_URL
OUT=$OAEF_OUT
OTLP=${OAEF_OTLP:-http://localhost:4318}
GRAFANA=${OAEF_GRAFANA:-http://localhost:3000}
SEED=${OAEF_SEED:-20261107}
COUNT=${OAEF_COUNT:-100}
TARGET=${OAEF_TARGET:-17}
export OAEF_GRAFANA_PASSWORD=${OAEF_GRAFANA_PASSWORD:-${GF_ADMIN_PASSWORD:-}}
TX=$(printf 'TX-%03d' "$TARGET")
SUMMARY=()
UNEXPECTED=0

expect() {  # expect <label> <expected exit> <command...>
  local label=$1 want=$2; shift 2
  "$@"; local got=$?
  if [ "$got" -eq "$want" ]; then SUMMARY+=("ok          $label (exit $got)")
  else SUMMARY+=("UNEXPECTED  $label (exit $got, expected $want)"); UNEXPECTED=1; fi
}

show_ids() {  # print the run id, the target transaction's trace id and ready-to-paste Grafana queries
  python3 - "$1" "$TX" <<'EOF'
import json, sys
out, tx = sys.argv[1], sys.argv[2]
m = json.load(open(out + '/manifest.json'))
spans = [s for g in json.load(open(out + '/observed.json'))['traces']['resourceSpans'] for s in g['scopeSpans'][0]['spans']]
tid = next(s['traceId'] for s in spans
           if any(a['key'] == 'oaef.transaction.id' and a['value'].get('stringValue') == tx for a in s['attributes']))
run = m['run_id']
print(f"  run_id    : {run}   (fault: {m['fault']}, transactions: {m['transactions']})")
print(f"  {tx} trace: {tid}")
print(f"  Tempo     : trace id {tid}")
print(f"  Loki      : {{service_name=~\"idrepo-identity|regproc-pkr\"}} |= \"{run}\" | json | transaction_id=\"{tx}\"")
print(f"  Prometheus: {{__name__=~\"oaef_synthetic_journey_duration.*\",oaef_run_id=\"{run}\"}}")
EOF
}

run_case() {  # run_case <case> <S1 exit> <collect exit>
  local c=$1 s1=$2 col=$3 dir="$OUT/$1"
  echo; echo "================ $c ================"
  rm -rf "$dir"
  local fault=(--fault none)
  [ "$c" != nominal ] && fault=(--fault "$c" --target "$TARGET")
  expect "$c: S1 generate + export + emitted-payload oracle" "$s1" \
    python3 validation/v5_demo.py run --count "$COUNT" --seed "$SEED" "${fault[@]}" --out "$dir" --otlp "$OTLP"
  [ -f "$dir/manifest.json" ] || { SUMMARY+=("UNEXPECTED  $c: no run produced"); UNEXPECTED=1; return; }
  show_ids "$dir"
  expect "$c: S2-read collect from Tempo/Loki/Prometheus" "$col" \
    python3 validation/v5_backend.py collect --out "$dir" --grafana "$GRAFANA" --timeout 90 --poll 3
  expect "$c: evidence bundle integrity" 0 python3 validation/v5_backend.py verify-bundle --out "$dir"
  expect "$c: offline re-evaluation reproduces verdict" 0 python3 validation/v5_backend.py re-evaluate --out "$dir"
  mkdir -p "$OUT/runs" && ln -sfn "../$c" "$OUT/runs/$(python3 -c "import json;print(json.load(open('$dir/manifest.json'))['run_id'])")"
  echo "  evidence  : $dir"
  echo "  REPORT    : $OAEF_REPORT_BASE_URL/$c/report.html"
}

CASES=("$@"); [ ${#CASES[@]} -eq 0 ] && CASES=(tests nominal duplicate missing slow broken_link)
[ -n "$OAEF_GRAFANA_PASSWORD" ] || echo "WARNING: OAEF_GRAFANA_PASSWORD / GF_ADMIN_PASSWORD not set; Grafana queries will fail." >&2
for c in "${CASES[@]}"; do
  case "$c" in
    tests)        echo "================ tests ================"
                  expect "unit and mutation tests (offline, fake backend)" 0 python3 -m unittest discover -s tests ;;
    s0)           expect "S0 legacy 7-span smoke (connectivity only)" 0 bash validation/demo/check.sh "$GRAFANA" "$OTLP" ;;
    nominal)      run_case nominal 0 0 ;;
    duplicate)    run_case duplicate 1 1 ;;     # FAIL: EVENT-EXACT-mosip.identity.uin.assigned, TX = 2 vs 1
    missing)      run_case missing 1 2 ;;       # INCONCLUSIVE / EVIDENCE_GAP, never PRODUCT_BUG
    slow)         run_case slow 1 1 ;;          # FAIL: NFR-DEMO-LATENCY (demo-only 2 s threshold)
    broken_link)  run_case broken_link 1 1 ;;   # FAIL: SPAN-PARENT-idrepo-server (trace context lost)
    wrong_value)  run_case wrong_value 1 1 ;;   # FAIL: EVENT-EFFECT-VALUE
    metric_count) run_case metric_count 1 1 ;;  # FAIL: PROM-MEASUREMENTS-COUNT 101 vs 100
    *) echo "unknown case: $c" >&2; exit 2 ;;
  esac
done
echo; echo "================ summary ================"
printf '%s\n' "${SUMMARY[@]}"
if [ "$UNEXPECTED" -eq 0 ]; then echo "DEMO RESULT: every case behaved as expected"; else echo "DEMO RESULT: UNEXPECTED behaviour, see above"; exit 1; fi
