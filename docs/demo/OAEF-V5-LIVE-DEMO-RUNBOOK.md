# OAEF V5 — live demo runbook (S0 → S1 → S2-read)

**Status:** operating procedure for the demonstrator on branch `docs/oaef-v5-model-to-evidence-demo`.
**Live run status:** the expected results below are **acceptance criteria**. Until the "Live run record" table at the end is filled in from a real Codespaces run, no screenshot, count or timing in a presentation may be shown as observed.

What the demo proves, and what it does not:

| Mode | What runs | What it can show | What it cannot show |
|---|---|---|---|
| **S0** fixture replay | `replay_nin001.py` + `check.sh` | the observability chain works (7 spans, a log, an exemplar) | anything about a scenario's correctness |
| **S1** synthetic journey | `v5_demo.py`: 100 synthetic NIN-001 transactions, 3 required events each, OTLP export | the oracle is exact per transaction and catches injected faults | MOSIP/NIMS2 behaviour; backend ingestion |
| **S2-read** backend observation | `v5_backend.py collect`: queries Tempo, Loki, Prometheus for that run only | the signals really reached the backends, and the same oracle verdict holds on what was retrieved | MOSIP behaviour (the source is still the simulator) |
| S2 live SUT (future) | the same contract on an instrumented MOSIP platform plus API/DB/audit evidence | product conformance, within scope | — |

Say this table out loud at the start and at the end. Every result label in the demo is S0, S1 or S2-read, never "MOSIP verified".

---

## 1. Prerequisites

- A Codespace on this repository, **on the V5 branch** (Code → Codespaces → ⋯ → or in the terminal: `git fetch origin && git switch docs/oaef-v5-model-to-evidence-demo`). Check `git status` first; never discard local work.
- The LGTM stack running: `docker compose -f validation/demo/docker-compose.yml ps` shows `oaef-lgtm` up (started automatically by the dev container).
- Grafana password in the environment, from a **Codespaces secret** (`GF_ADMIN_PASSWORD`), not the default `change-me`. The scripts read `OAEF_GRAFANA_PASSWORD` or `GF_ADMIN_PASSWORD`.
- Ports 3000 (Grafana) and 4318 (OTLP) forwarded **Private**.
- Python 3.11+ (present in the `universal:2` image). No packages to install.

## 2. Preparation (day before, about 15 minutes)

```bash
bash validation/demo/run_v5_demo.sh tests s0 nominal duplicate missing slow
```

The last line must read `DEMO RESULT: every case behaved as expected`. Then:

1. Record the image actually used: `docker image inspect --format '{{index .RepoDigests 0}}' grafana/otel-lgtm:latest` and pin it (`LGTM_VERSION` or digest) for the session.
2. Fill in the **Live run record** table below (run IDs, counts, exit codes).
3. Keep the evidence folders `/tmp/oaef-v5/*` as the **fallback**: copy them out (`tar czf oaef-v5-evidence.tgz -C /tmp oaef-v5`) and download the archive. In the session, label fallback material "recorded on <date>", never "live".
4. Take the Grafana screenshots for the slides from this run, with the run ID visible.

## 3. Demo script (15 minutes)

Roles: presenter speaks, demo driver types. Terminal font enlarged, notifications off.

| Time | Step | Command (driver) | Show | Say |
|---|---|---|---|---|
| 0:00 | **Specification** | open `contracts/NIN-001-v5-slice.json`, `models/nin-requirements.md` (F-07, F-08, NF-04, NF-08) | the 3 required events, the requirement references | "The expectation is frozen before the run; faults never change it. The 2 s threshold is demo-only, not NF-04's 24 h." |
| 1:30 | **S0 baseline** | `bash validation/demo/run_v5_demo.sh s0` | `RESULT: PASS`, the 7-span trace in Grafana | "This proves the pipeline works. It would also pass with a missing step: it counts ≥ 7 spans and ≥ 1 log." |
| 3:00 | **S1 + S2-read nominal, 100 transactions** | `bash validation/demo/run_v5_demo.sh nominal` | `PASS: 100 tx; expected events 300; observed 300`, then `BACKEND PASS | traces 100 / 100 | structured events 300 / 300` | "300 is not the check. Each transaction must have exactly its 3 events, with the right value, trace and order." |
| 5:30 | **Investigate in Grafana** | paste the printed queries in Explore | Tempo: the TX-017 trace (3 spans). Loki: the run's 3 events for TX-017. Prometheus: the run's histogram, count 100 | "Grafana is for investigation. The verdict comes from the oracle, offline." |
| 7:00 | **Duplicate on TX-017** | `bash validation/demo/run_v5_demo.sh duplicate` | `FAIL … EVENT-EXACT-mosip.identity.uin.assigned TX-017 expected 1 actual 2`, 301 events collected; in Loki, two `uin.assigned` lines for TX-017 | "Aggregate ≥ 300 would pass. Per-transaction exactness catches it." |
| 9:00 | **Missing event on TX-017** | `bash validation/demo/run_v5_demo.sh missing` | S1 `FAIL` on the emitted payload; backend `INCONCLUSIVE`, classification `EVIDENCE_GAP` | "A missing signal is not proof the business step did not happen. Without an independent source, the honest verdict is inconclusive." |
| 10:30 | **Latency breach on TX-017** | `bash validation/demo/run_v5_demo.sh slow` | `NFR-DEMO-LATENCY TX-017` FAIL with the exact duration (2150 ms > 2000 ms); in Tempo, the longer TX-017 trace | "The NFR verdict uses exact per-transaction durations. The histogram p95 is only an estimate." |
| 12:00 | **Evidence and replay** | `cat /tmp/oaef-v5/duplicate/backend-verdict.json`; `python3 validation/v5_backend.py verify-bundle --out /tmp/oaef-v5/duplicate`; then change one byte in `backend-raw/loki.json` and run it again | `BUNDLE INTEGRITY: PASS`, then `FAIL` after tampering; `re-evaluate` prints `MATCH` | "Anyone can re-check the verdict from the stored evidence. A hash is an integrity check, not a signature and not WORM storage." |
| 14:00 | **Scope and next step** | back to the table at the top | S0/S1/S2-read vs S2 live | "Next: the same contract on an instrumented MOSIP platform, with API/DB/audit evidence." |

Each `run_v5_demo.sh <case>` prints the run ID, the TX-017 trace ID and ready-to-paste Tempo, Loki and Prometheus queries. Nothing has to be copied by hand from JSON files.

Expected exit codes (asserted by the script):

| Case | S1 `v5_demo.py run` | S2-read `collect` | `verify-bundle` | `re-evaluate` |
|---|---|---|---|---|
| nominal | 0 PASS | 0 PASS | 0 | 0 MATCH |
| duplicate | 1 FAIL | 1 FAIL | 0 | 0 MATCH |
| missing | 1 FAIL | 2 INCONCLUSIVE | 0 | 0 MATCH |
| slow | 1 FAIL | 1 FAIL | 0 | 0 MATCH |
| wrong_value (optional) | 1 FAIL | 1 FAIL | 0 | 0 MATCH |
| metric_count (optional) | 1 FAIL | 1 FAIL | 0 | 0 MATCH |

## 4. Recovery during the session

| Symptom | Likely cause | Action |
|---|---|---|
| `collect` exit 3, `Grafana HTTP 401` | password not in the environment | `export OAEF_GRAFANA_PASSWORD=…` from the secret; rerun the case |
| `collect` exit 2 on nominal, traces < 100 | ingestion still in progress | rerun only `collect` for the same folder (`python3 validation/v5_backend.py collect --out /tmp/oaef-v5/nominal --timeout 120`) |
| Prometheus checks `INCONCLUSIVE` | metric name or label mapping differs in this LGTM version, or the sample is older than 5 minutes | look at `backend-raw/prometheus.json`; do not edit the adapter live; say it and move on |
| Grafana unreachable | Codespace stopped or port closed | restart the Codespace (stack restarts by itself); otherwise switch to the fallback evidence, labelled "recorded" |
| A case prints `UNEXPECTED` | real defect in the demonstrator | stop that case, show the recorded run, open an issue after the session |

## 5. After the session

- Stop the Codespace (github.com/codespaces → ⋯ → Stop) to save the free quota.
- Keep the evidence archive with the session recording; link the run IDs in the review issues.

## 6. Known limits (say them, do not hide them)

- Three selected milestones, not the full NIN-001 flow (no notification, asynchronous links, idempotency or cross-store audit yet).
- The source is a simulator. `ledger.json` is simulated truth, not a MOSIP database.
- The metric series carries `oaef_run_id` as a label only for this short-lived demo; not a production practice.
- Tempo's JSON API returns trace and span IDs base64-encoded; the collector normalises them to hex before the oracle runs (covered by `test_tempo_base64_ids`).
- Pending from the V5 brief: verification-obligation manifest, Weaver registry, image pinning by digest, the full M01–M17 matrix, slides V5.

## 7. Live run record (fill in from the real run)

| Date | Codespace image / LGTM digest | Case | run_id | S1 exit | collect exit | traces | events | Notes |
|---|---|---|---|---|---|---|---|---|
| | | nominal | | | | / 100 | / 300 | |
| | | duplicate | | | | / 100 | / 300 | |
| | | missing | | | | / 100 | / 300 | |
| | | slow | | | | / 100 | / 300 | |
