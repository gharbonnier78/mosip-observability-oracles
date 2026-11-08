# OAEF V5 — S2-read: Backend Observation and Evidence Reconciliation

**Status:** executable connector and offline-replay increment, with simulated Grafana API integration tests. **NOT a MOSIP integration test**, production compliance report, formal proof, or live LGTM acceptance certificate.

## 1. What changed

S1 (`validation/v5_demo.py`) generates a declared NIN-001 three-milestone synthetic slice, evaluates its emitted OTLP payload offline and optionally exports it to an OTLP/HTTP Collector. **S2-read (`validation/v5_backend.py`) is a new independent observation path**. It retrieves each emitted trace ID from Tempo, retrieves the specific run's structured log events from Loki and requests corresponding metric time series from Prometheus via Grafana's datasource proxy. A separate verdict is generated from the **retrieved** records and preserved along with the raw backend responses. Neither stage runs MOSIP or establishes NIMS2 business-system conformance.

S1 live export now chooses a fresh run ID per invocation to avoid cross-run collisions; offline S1 remains seed-deterministic. OTLP LogRecord bodies contain JSON with `run_id`, `transaction_id`, `event_name`, `synthetic_effect_id`, `trace_id` and `span_id` to enable robust LogQL run isolation without indexing high-cardinality transaction IDs. The synthetic histogram is tagged with the run ID **only for short-lived, isolated demo series**; do not transfer this practice to production without a cardinality policy. The `metric_count` defect produces an internally consistent but semantically incorrect histogram rather than invalid OTLP bucket totals.

## 2. Scope and source classification

| Material | Source | What it can establish |
| --- | --- | --- |
| `contract.json` | frozen S1 design contract | declared expected obligations for this 3-step slice |
| `ledger.json` | S1 synthetic simulator | synthetic business-level expectations; **not** a MOSIP database truth |
| `observed.json` | OTLP generated/emitted payload | source-side signal generation, not backend receipt |
| `collected-otel.json` | normalized Tempo and Loki replies | records actually returned by the queried backends (query coverage limits apply) |
| `backend-raw/*` | original datasource API replies | independent query receipts from the API; still not SUT proof |
| `backend-verdict.json` | deterministic oracle over retrieved data | scope-limited observation status |
| `backend-meta.json` | queries, scopes, limits, errors and source hashes | evidence provenance and explicit limitations |
| `evidence-sha256.json` | local SHA-256 | tamper detection on this local bundle, **not** a signature or WORM storage |

**Verdicts:** `PASS` only if all three backends yield complete, conforming observations against the simulated contract and metrics; `FAIL` for demonstrable duplicate/incorrect value/metric count; `INCONCLUSIVE` for missing backend observations or failed queries. Never conclude `PRODUCT_BUG` merely because one OTEL message was not found.

## 3. Codespaces walkthrough (existing LGTM stack)

From a clean worktree on the reviewed V5 branch (inspect `git status` first):

```bash
# Existing Codespace only; do not rebuild or replace the NIMS2 deployment
cd /workspaces/mosip-observability-oracles  # adapt to your Codespace path
python3 -m unittest discover -s tests -v

# Start LGTM if needed, preserving an existing working stack
# docker compose -f validation/demo/docker-compose.yml up -d
export OAEF_GRAFANA_PASSWORD="$GF_ADMIN_PASSWORD"  # use a Codespaces secret; no tokens in repo

# 100 distinct synthetic transactions, OTLP export, source-side S1 oracle
python3 validation/v5_demo.py run --count 100 --seed 20261107 \
    --out /tmp/oaef-v5-nominal --otlp http://localhost:4318

# Actually query Tempo/Loki/Prometheus, wait for eventual ingestion, store raw replies
python3 validation/v5_backend.py collect --out /tmp/oaef-v5-nominal \
    --grafana http://localhost:3000 --timeout 60 --poll 3

# Local evidence-integrity verification and independent offline re-evaluation
python3 validation/v5_backend.py verify-bundle --out /tmp/oaef-v5-nominal
python3 validation/v5_backend.py re-evaluate --out /tmp/oaef-v5-nominal
```

Exit codes from `collect`: `0 PASS`, `1 FAIL`, `2 INCONCLUSIVE`, `3 tooling/endpoint error`. Fault injection deliberately exits `1` from the S1 command; continue the workflow to demonstrate that the retrieved signal also violates the oracle:

```bash
python3 validation/v5_demo.py run --count 100 --seed 20261107 \
  --fault duplicate --target 17 \
  --out /tmp/oaef-v5-duplicate --otlp http://localhost:4318 || test "$?" -eq 1
python3 validation/v5_backend.py collect --out /tmp/oaef-v5-duplicate \
  --grafana http://localhost:3000 --timeout 60 --poll 3 || test "$?" -eq 1
python3 validation/v5_backend.py re-evaluate --out /tmp/oaef-v5-duplicate
```

**Expected nominal sample:** 100 trace IDs, each with 3 named spans; 300 structured events, 3 per transaction; a run-isolated histogram count of 100, sum and expected buckets. **Expected duplicate sample:** TX-017 has 2 logical `mosip.identity.uin.assigned` events instead of 1, hence 301 total and explicit failure of `EVENT-EXACT-mosip.identity.uin.assigned`. These are *acceptance criteria*, not yet a claim of observed live Codespaces results.

### Examine in Grafana

- Open forwarded **private** port 3000. Grafana → Explore → Tempo → choose one `traceId` from the S1 emitted JSON; inspect its three-span trace.
- Loki → `{service_name=~"idrepo-identity|regproc-pkr"} |= "<actual run_id>" | json | transaction_id="TX-017"`; check the duplicate business event. (Since `e7531ec` the simulator emits from the MOSIP service names; the run script and `report.html` print these links ready to click, see `OAEF-V5-LIVE-DEMO-RUNBOOK.md`.)
- Prometheus → `{__name__=~"oaef_synthetic_journey_duration.*",oaef_run_id="<actual run_id>"}`; query only within the short-lived demo. The histogram count is not an independent business record count.
- Compare the visible records with `backend-verdict.json`, `collected-verdict.json` and `backend-raw/`. **Grafana's display is not the oracle.**

### Why run isolation matters

Each live replay uses a fresh `run_id`; the same 100 transactions therefore cannot accidentally be confused with a previous run using the same seed. Loki uses the JSON body, not a high-cardinality indexed label. Tempo queries the **explicit 100 trace IDs**. Prometheus uses a deliberately short-lived demo label on one histogram series. These choices are demonstration-specific; the production OAEF needs a governed aggregation and collection policy.

## 4. Acceptance and observability caveats

- The adapter tests use a **fake HTTP Grafana server**, verifying strict parsing, missing-signal behavior, deliberate duplicates, metric mismatch, 100-trace retrieval and tamper detection. They do **not** prove real Tempo/Loki/Prometheus ingestion, API compatibility with your pinned LGTM image or asynchronous NIMS2 flows.
- Tempo `GET /api/traces/{trace_id}` returns a trace document; the adapter accepts `resourceSpans` and `batches` response shapes. Querying a specific emitted trace cannot discover unrelated unknown traces.
- Loki `query_range` with `start/end` must stay within the intended run's timestamps. Records are selected by the structured JSON body. If the response reaches the configured `--limit`, the run is **INCONCLUSIVE** rather than silently accepting a truncated query. For a larger campaign, implement proper server-backed pagination, rather than merely increasing the limit without bounds.
- Structured Loki metadata and OTLP `EventName` mappings differ across deployed versions. This short slice chooses a well-defined JSON LogRecord body as a version-tolerant retrieval contract; keep `eventName` at OTLP source and retain raw receipts for checking the actual backend mapping.
- Prometheus metric names and label normalization depend on OTel exporter and Prometheus settings. The initial adapter supports the concrete S1 histogram `oaef.synthetic.journey.duration` (seconds) with `_count`, `_sum`, `_bucket`; unknown or absent series do not pass. The Prometheus query is at **query time**, not at the original event timestamp, accounting for delayed ingestion. If actual LGTM mapping differs, **inspect the raw backend response and explicitly version/adjust the adapter; do not fabricate metrics**.
- Histogram buckets and sums are cross-checked against the synthetic ledger, **not** used to assert business truth. Per-transaction performance requires actual per-transaction measured durations, which this 3-stage demonstration does not yet obtain from independent backend signals.
- An absent log can mean absent instrumentation, sampling, collector loss, indexing delay or product behavior. `INCONCLUSIVE` is intentional unless a separate independent source closes the gap.
- A hash protects integrity only against accidental or uncoordinated changes to this local bundle. For audit-grade retention, a separate immutable storage and signing process is required.
- No hard-coded credentials are needed in this increment. `OAEF_GRAFANA_USER`, `OAEF_GRAFANA_PASSWORD` / `GF_ADMIN_PASSWORD`, or `OAEF_GRAFANA_TOKEN` are read from environment. Do not expose Grafana or OTLP Codespaces forwarded ports publicly.

## 5. Next decision after the real Codespace dry run

1. Capture the **actual** LGTM version and sample outputs in one sanitized evidence package and GitHub Actions artifact; confirm that Tempo, Loki and Prometheus mapping is exactly as assumed or document the actual divergence.
2. Introduce `verification-obligations.yaml` with stable model/activity and F/NF requirement IDs, real S2 query contracts, a reusable `oaef.*` registry and model-change impact checks; do not duplicate an existing YAML oracle or presume OCL executable on plain PlantUML files.
3. Extend the 3-milestone slice to the complete NIN-001 model including asynchronous boundaries and explicit independent API/DB/audit evidence. Treat this as a **separate increment**, not as functionality silently completed here.
4. Update V5 slides only with real screenshot/run IDs after this deployed Codespaces check.

## 6. Standards/API references

- [Tempo HTTP trace API](https://grafana.com/docs/tempo/latest/api_docs/)
- [Loki HTTP API](https://grafana.com/docs/loki/latest/reference/loki-http-api/)
- [Loki OpenTelemetry ingestion and structured metadata](https://grafana.com/docs/loki/latest/send-data/otel/)
- [Prometheus HTTP API](https://prometheus.io/docs/prometheus/latest/querying/api/)
- [OTLP metrics data model](https://opentelemetry.io/docs/specs/otel/metrics/data-model/)
