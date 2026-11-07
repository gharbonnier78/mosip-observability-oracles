# OAEF V5 — live demo runbook (S0 → S1 → S2-read)

**Status:** operating procedure for the demonstrator on branch `docs/oaef-v5-model-to-evidence-demo`.
**Live run status:** executed end to end in GitHub Codespaces on 2026-11-07 (commit `e7531ec`): S0 and all 7 cases behaved as expected, HTML reports and Grafana links verified in the browser. See section 7 and `examples/evidence/v5-live-20261107-e7531ec/`. Screenshots and figures shown in a presentation must come from a recorded run like this one, with its run ID.

What the demo proves, and what it does not:

| Mode | What runs | What it can show | What it cannot show |
|---|---|---|---|
| **S0** fixture replay | `replay_nin001.py` + `check.sh` | the observability chain works (7 spans, a log, an exemplar) | anything about a scenario's correctness |
| **S1** synthetic journey | `v5_demo.py`: 100 synthetic NIN-001 transactions; per transaction 17 spans over 6 services and 3 required business events; OTLP export | the oracle is exact per transaction (events, values, span tree, order, latency) and catches injected faults | MOSIP/NIMS2 behaviour; backend ingestion |
| **S2-read** backend observation | `v5_backend.py collect`: queries Tempo, Loki, Prometheus for that run only; writes `report.html` | the signals really reached the backends, and the same oracle verdict holds on what was retrieved | MOSIP behaviour (the source is still the simulator) |
| S2 live SUT (future) | the same contract on an instrumented MOSIP platform plus API/DB/audit evidence | product conformance, within scope | — |

Say this table out loud at the start and at the end. Every result label in the demo is S0, S1 or S2-read, never "MOSIP verified".

---

## 1. Prerequisites

- A Codespace on this repository, **on the V5 branch**: `git fetch origin && git switch docs/oaef-v5-model-to-evidence-demo` (then `git merge --ff-only origin/docs/oaef-v5-model-to-evidence-demo` to update). Check `git status` first; never discard local work.
- The stack and the report server running: `bash validation/demo/start_stack.sh` (run automatically when the Codespace starts). It prints the two browser URLs:
  - **Grafana** `https://<codespace>-3000.app.github.dev` (user `admin`);
  - **Reports** `https://<codespace>-8080.app.github.dev/` (one folder per case, `runs/<run_id>/` aliases).
- Grafana password from a **Codespaces secret** `GF_ADMIN_PASSWORD`, not the default `change-me`. The scripts read `OAEF_GRAFANA_PASSWORD` or `GF_ADMIN_PASSWORD`.
- Ports 3000 (Grafana), 4318 (OTLP) and 8080 (reports) forwarded **Private**. Sign in to Grafana in the demo browser before the session.
- The image is pinned by digest in `validation/demo/docker-compose.yml` (the one used in the recorded run).
- For the Allure view across runs (optional): Node (`npx`) and Java 8+, both in the Codespace image (`node -v`, `java -version`). The Allure CLI is fetched by `npx` at a pinned version (`allure-commandline@2.39.0`); no secret, no extra port.

## 2. Preparation (day before, about 15 minutes)

```bash
bash validation/demo/start_stack.sh
bash validation/demo/run_v5_demo.sh tests s0 nominal duplicate missing slow broken_link
```

The last line must read `DEMO RESULT: every case behaved as expected`. Optionally build the Allure report over all these runs:

```bash
bash validation/demo/allure_report.sh
```

It prints the **ALLURE** URL (`$OAEF_REPORT_BASE_URL/allure-report/`, served by the same port 8080). Then:

1. Open each printed `REPORT` URL once (Codespaces asks for GitHub sign-in on port 8080 the first time).
2. Fill in the **Live run record** (section 7) with run IDs, counts and exit codes.
3. Keep the evidence as the **fallback**: `tar czf oaef-v5-evidence.tgz -C /tmp oaef-v5`, download it. In the session, label fallback material "recorded on <date>", never "live".
4. Take the Grafana screenshots for the slides from this run, with the run ID visible.

## 3. Demo script (15 minutes)

Roles: presenter speaks, demo driver types and clicks. Terminal font enlarged, notifications off. Grafana and the report server open in two browser tabs.

| Time | Step | Action (driver) | Show | Say |
|---|---|---|---|---|
| 0:00 | **Specification** | open `contracts/NIN-001-v5-slice.json` (`required_events`, `journey_spans`, `scenario_steps`) and `models/nin-requirements.md` | 3 required events, the 17-span expected tree, 5 scenario steps with expected results | "The expectation is frozen before the run; faults never change it. The 2 s threshold is demo-only, not NF-04's 24 h." |
| 1:30 | **S0 baseline** | `bash validation/demo/run_v5_demo.sh s0` | `RESULT: PASS` | "This proves the pipeline works. It would also pass with a missing step: it counts ≥ 7 spans and ≥ 1 log." |
| 2:30 | **Nominal, 100 transactions** | `bash validation/demo/run_v5_demo.sh nominal` | `spans 1700/1700`, `BACKEND PASS | traces 100 / 100 | structured events 300 / 300`, then open the printed **REPORT** URL | "300 is not the check. Each transaction must have exactly its 3 events and its 17 spans under the right parents, with the right values." |
| 4:30 | **The span tree** | in the report, TX-001: scroll the sequence diagram; click any arrow | Grafana opens the trace: Jarvis → packet receiver → Kafka → stage group → ID generator → ID repository → notification, 6 services | "One business transaction, end to end, across six services, from one click in the test report." |
| 6:00 | **Duplicate on TX-017** | `bash validation/demo/run_v5_demo.sh duplicate`, open its REPORT | Failed checks: `EVENT-EXACT-mosip.identity.uin.assigned TX-017 expected 1 observed 2`; STEP-3 red; in the sequence, `uin.assigned — found x2 in Loki`; click it → Tempo on that span → **Related logs** shows the two events | "The trace looks normal. The defect is in the business events. Aggregate ≥ 300 would pass; per-transaction exactness catches it." |
| 8:00 | **Broken trace context on TX-017** | `bash validation/demo/run_v5_demo.sh broken_link`, open its REPORT | `SPAN-PARENT-idrepo-server`, class `TRACE_CONTEXT_BROKEN`; in the sequence, the call from regproc-group1 ends at "external" and idrepo-identity is red "parent span not found" | "Every span is there; the chain is broken. Without the tree check this passes." |
| 9:30 | **Latency breach on TX-017** | `bash validation/demo/run_v5_demo.sh slow`, open its REPORT | `NFR-DEMO-LATENCY` expected `max 2000 ms`, observed `2150 ms`, class `NFR_VIOLATION`; in Tempo, span → **Journey duration of this run** → histogram; the exemplar in the 5 s bucket opens TX-017's trace | "The verdict uses the exact per-transaction duration. The histogram is for navigation; its quantiles are estimates." |
| 11:00 | **Missing event on TX-017** | `bash validation/demo/run_v5_demo.sh missing` (about 90 s: the collector polls until its timeout; talk meanwhile) | backend `INCONCLUSIVE | 299 / 300`, class `EVIDENCE_GAP`; in the report, `found x0 in Loki` | "A missing signal is not proof the business step did not happen. Without an independent source, the honest verdict is inconclusive." |
| 12:30 | **Back from a log to the test** | in Grafana Loki, any event line of the run → field `oaef_run_id` → link **OAEF test report** | the report of that run opens (another application) | "From any signal back to the test that produced it, and from the test to every signal." |
| 13:00 | **Evidence and replay** | `python3 validation/v5_backend.py verify-bundle --out /tmp/oaef-v5/duplicate`; change one byte in `backend-raw/loki.json`; run it again; `re-evaluate` | `BUNDLE INTEGRITY: PASS`, then `FAIL` after tampering; `re-evaluate` prints `MATCH` | "Anyone can re-check the verdict from the stored evidence. A hash is an integrity check, not a signature and not WORM storage." |
| 14:00 | **Scope and next step** | back to the table at the top | S0/S1/S2-read vs S2 live | "Next: the same contract on an instrumented MOSIP platform, with API/DB/audit evidence." |

### Navigation map (what links to what)

| From | Click | Opens |
|---|---|---|
| Test report, failed check | `trace` · `events` · `sequence` | Tempo trace of that transaction · Loki events of that transaction · the diagram below |
| Test report, sequence diagram | any arrow, event or span | Tempo on that exact span |
| Tempo span | **Related logs** | Loki: logs of that trace and service |
| Tempo span | **Journey duration of this run (exemplars on)** | Prometheus: the run's histogram; an exemplar opens the trace it points to |
| Loki event line | `trace_id` field | Tempo trace |
| Loki event line | `oaef_run_id` field → **OAEF test report** | the run's HTML report on port 8080 |
| Prometheus exemplar | `trace_id` | Tempo trace |
| Allure report (`/allure-report/`) | **Suites** → `NIN-001` → case (`none`, `duplicate`, …) → test | one examined transaction of one run (or the run verdict): scenario steps with Expected / Observed, labels `run_id`, `fault`, `diagnostic_class` |
| Allure test | **Links** | Tempo trace · Loki events of that transaction · histogram with exemplars (same links as `report.html`) |
| Allure test | attachments | the transaction's sequence diagram (SVG, not clickable) · the run's `report.html` |
| Allure | **Categories** | tests grouped by diagnostic class; `EVIDENCE_GAP` results are *broken*, not *failed* |
| Allure test | **Retries** | the same case and transaction in the other runs of `$OAEF_OUT` (repeated runs of a case share a history id, so the latest is shown and the others are its retries) |

The links are versioned: `validation/demo/grafana-datasources.yaml` (Grafana provisioning, replaces the image's file), `validation/v5_report.py` (report) and `validation/v5_allure.py` (Allure export).

**Allure export.** `collect` also writes `allure-results/` into each run folder (Allure 2 results format: one `*-result.json` per examined transaction, i.e. every failed one plus the first passing one, one run-verdict result with the backend counts and metric checks, a `*-container.json` for the collection step, `environment.properties`, `categories.json`, attachments). It is part of the sealed bundle and is presentation only: it reads the verdict files and never recomputes them. Status mapping: transaction with failed checks → *failed* in a FAIL run, *broken* in an INCONCLUSIVE run; run verdict PASS/FAIL/INCONCLUSIVE → passed/failed/broken. To view without the report server: `npx --yes allure-commandline@2.39.0 serve /tmp/oaef-v5/*/allure-results` (opens a local web server on a random port). For S2, the same provisioning has a commented template linking a log to the SUT's own UI by business key (e.g. MOSIP admin packet status by RID).

Expected exit codes (asserted by the script):

| Case | S1 `v5_demo.py run` | S2-read `collect` | Class | `verify-bundle` | `re-evaluate` |
|---|---|---|---|---|---|
| nominal | 0 PASS | 0 PASS | `S1_TELEMETRY_CONFORMANT` | 0 | 0 MATCH |
| duplicate | 1 FAIL | 1 FAIL | `OBSERVABILITY_VIOLATION` | 0 | 0 MATCH |
| missing | 1 FAIL | 2 INCONCLUSIVE | `EVIDENCE_GAP` | 0 | 0 MATCH |
| slow | 1 FAIL | 1 FAIL | `NFR_VIOLATION` | 0 | 0 MATCH |
| broken_link | 1 FAIL | 1 FAIL | `TRACE_CONTEXT_BROKEN` | 0 | 0 MATCH |
| wrong_value (optional) | 1 FAIL | 1 FAIL | `OBSERVABILITY_VIOLATION` | 0 | 0 MATCH |
| metric_count (optional) | 1 FAIL | 1 FAIL | `METRIC_RECONCILIATION_FAILURE` | 0 | 0 MATCH |

## 4. Recovery during the session

| Symptom | Likely cause | Action |
|---|---|---|
| `collect` exit 3, `Grafana HTTP 401` | password not in the environment | `export OAEF_GRAFANA_PASSWORD=…` from the secret; rerun the case |
| `collect` exit 2 on nominal, traces < 100 | ingestion still in progress | rerun only `collect` for the same folder (`python3 validation/v5_backend.py collect --out /tmp/oaef-v5/nominal --timeout 120`) |
| Prometheus checks `INCONCLUSIVE` | label mapping differs, or the sample is older than 5 minutes | look at `backend-raw/prometheus.json`; do not edit the adapter live; say it and move on |
| `allure_report.sh` fails: `java: not found` or `npx: not found` | Allure CLI needs Java 8+ and Node | skip it; `report.html` per run is the primary view |
| REPORT URL does not open | report server not running, or port 8080 not signed in | `bash validation/demo/start_stack.sh`; open the Reports URL once and sign in |
| Grafana link opens the login page | Grafana session expired | sign in, then click the link again |
| Grafana unreachable | Codespace stopped or port closed | restart the Codespace (stack restarts by itself); otherwise switch to the fallback evidence, labelled "recorded" |
| A case prints `UNEXPECTED` | real defect in the demonstrator | stop that case, show the recorded run, open an issue after the session |

## 5. After the session

- Stop the Codespace (VS Code command palette → *Codespaces: Stop Current Codespace*, or github.com/codespaces → ⋯ → Stop) to save the free quota.
- Keep the evidence archive with the session recording; link the run IDs in the review issues.

## 6. Known limits (say them, do not hide them)

- The journey is simulated: 17 spans and 3 required events per transaction; no real MOSIP call, no idempotency or cross-store audit yet. The span tree is one trace per transaction (the Kafka hop is a parent-child link, not a span link).
- `ledger.json` is simulated truth, not a MOSIP database. RID and UIN values are synthetic.
- The metric series carries `oaef_run_id` as a label only for this short-lived demo; not a production practice. Exemplars are navigation aids (one per bucket), not evidence of completeness.
- Report links point to the Codespace's forwarded URLs; they work while the Codespace runs and Tempo/Loki keep the data.
- Tempo's JSON API returns trace and span IDs base64-encoded and kinds as enum names; the collector normalises both (covered by tests).
- Pending from the V5 brief: verification-obligation manifest, Weaver registry, the full M01–M17 matrix, slides V5. `report.html` is the single-run view; the Allure report (`allure_report.sh`) is the cross-run view built from the same verdicts. Allure's own trend graphs need its `history/` folder carried between `generate` calls; not set up here.

## 7. Live run records

### Run 2 — commit `e7531ec` (current procedure)

`bash validation/demo/run_v5_demo.sh tests s0 nominal duplicate missing slow broken_link wrong_value metric_count`, GitHub Codespaces (2 CPU, 7 GiB, universal:2, Python 3.12.1), image `grafana/otel-lgtm@sha256:57b5ab1ca6619beb180174e2fccce04762470750669d043f544b4726d0582d07` (Grafana 13.2.3), finished 2026-11-07 17:09 UTC. Tests 14/14 OK. S0 smoke PASS.

| Case | run_id | S1 exit | collect exit | Verdict / class | Traces | Spans | Events | Attempts |
|---|---|---|---|---|---|---|---|---|
| nominal | `s1-9245a5c06458` | 0 | 0 | PASS | 100/100 | 1700/1700 | 300/300 | 1 |
| duplicate | `s1-1cdc48f2d24f` | 1 | 1 | FAIL `OBSERVABILITY_VIOLATION` | 100/100 | 1700/1700 | 301/300 | 1 |
| missing | `s1-0259e09626d6` | 1 | 2 | INCONCLUSIVE `EVIDENCE_GAP` | 100/100 | 1700/1700 | 299/300 | 22 (timeout) |
| slow | `s1-b3b33a1edad6` | 1 | 1 | FAIL `NFR_VIOLATION` (2150 ms > 2000 ms) | 100/100 | 1700/1700 | 300/300 | 1 |
| broken_link | `s1-d976596a56ae` | 1 | 1 | FAIL `TRACE_CONTEXT_BROKEN` | 100/100 | 1700/1700 | 300/300 | 1 |
| wrong_value | `s1-91ca4dbfe43a` | 1 | 1 | FAIL `OBSERVABILITY_VIOLATION` | 100/100 | 1700/1700 | 300/300 | 1 |
| metric_count | `s1-c592df2df64a` | 1 | 1 | FAIL `METRIC_RECONCILIATION_FAILURE` (9/12 metric checks) | 100/100 | 1700/1700 | 300/300 | 1 |

For every case, `verify-bundle` returned PASS and `re-evaluate` returned MATCH.

Checked in the browser during this run:
- The duplicate REPORT URL opened from port 8080; its link on `uin.assigned — found x2 in Loki` opened Grafana on the TX-017 trace (17 spans, 6 services) with the span selectable.
- On that span: **Related logs** and **Journey duration of this run (exemplars on)** present; the latter opened Prometheus on `oaef_run_id="s1-1cdc48f2d24f"`.
- The slow run's histogram had 3 exemplars; the 2.15 s one carries TX-017's trace id.
- Loki's `oaef_run_id` link resolved to `https://<codespace>-8080.app.github.dev/runs/<run_id>/report.html` (HTTP 200).

Evidence: `examples/evidence/v5-live-20261107-e7531ec/` (log, environment, per case: manifest, verdicts, query metadata, `report.html`, `links.md`, hashes; `full-bundles.tgz` with raw backend replies). Report links inside point to that Codespace and work only while it runs and holds the data.

### Run 1 — commit `ceec0cb` (3-span slice, before the report)

6 cases plus S0 as expected; first observation that Tempo returns base64 IDs. Record and evidence: `examples/evidence/v5-live-20261107/` (re-evaluate it with the code of `ceec0cb`: `re-evaluate` refuses a replay when `v5_backend.py` or `v5_demo.py` changed).

To re-check a verdict offline (either run, with its commit checked out):

```bash
mkdir -p /tmp/replay && tar xzf examples/evidence/v5-live-20261107-e7531ec/full-bundles.tgz -C /tmp/replay
python3 validation/v5_backend.py verify-bundle --out /tmp/replay/oaef-v5/duplicate
python3 validation/v5_backend.py re-evaluate --out /tmp/replay/oaef-v5/duplicate
```
