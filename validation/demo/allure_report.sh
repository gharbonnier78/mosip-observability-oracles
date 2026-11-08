#!/usr/bin/env bash
# Build one Allure report over every OAEF V5 run in $OAEF_OUT (each run's allure-results/, written by
# `v5_backend.py collect`). Output: $OAEF_OUT/allure-report/, served by the existing report server on
# port 8080 (no extra port, no secret). Needs Node (npx) and Java 8+; both are in the Codespace image.
# Repeated runs of the same case share a history id: Allure shows the latest and lists the others as retries.
#
# usage: bash validation/demo/allure_report.sh
# env:   OAEF_OUT (default /tmp/oaef-v5)  ALLURE_VERSION (pinned below)
set -eu
cd "$(dirname "$0")/../.."
. validation/demo/env.sh   # OAEF_OUT, OAEF_REPORT_BASE_URL
ALLURE_VERSION=${ALLURE_VERSION:-2.39.0}   # allure-commandline on npm / Maven Central, released 2026-05-06
shopt -s nullglob
RESULTS=("$OAEF_OUT"/*/allure-results)
[ ${#RESULTS[@]} -gt 0 ] || { echo "No allure-results under $OAEF_OUT; run validation/demo/run_v5_demo.sh first." >&2; exit 2; }
npx --yes "allure-commandline@$ALLURE_VERSION" generate "${RESULTS[@]}" --clean -o "$OAEF_OUT/allure-report"
echo "  runs      : ${#RESULTS[@]}"
echo "  ALLURE    : $OAEF_REPORT_BASE_URL/allure-report/"
