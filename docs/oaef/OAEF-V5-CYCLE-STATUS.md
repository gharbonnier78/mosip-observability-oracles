# OAEF — full-cycle status against the deck (2026-11-07, branch `docs/oaef-v5-model-to-evidence-demo` @ `7436b72`)

Question: is the cycle promised by *Observability-First Evidence-Based Testing* (slides 7 "From use case to oracle", 8 "Anatomy of one step", 16 "The loop", 18–35 worked example) implemented end to end?
**Answer: not yet.** The right half of the cycle (execute → collect → verify → seal → report) runs for real against Tempo/Loki/Prometheus, in Codespaces and in GitHub Actions. The left half (use case → activity → requirements → scenarios → step detail → signal definitions → oracle) exists as reviewed documents, but is derived **by hand** and only partly executed.

Legend: **Executed** = run by V5 and checked live · **Specified** = written and reviewed, not executed · **Missing** = neither.

## 1. Derivation chain (slide 7) and step detail (slide 8)

| Deck step | Source in the repository | Status | Gap to close |
|---|---|---|---|
| 1. Use case | `models/nin-usecase.puml`, slide 19 | Specified | not machine-read |
| 1. Activity diagram (paths, decisions) | `models/nin-enrolment-activity.puml`, slide 20 | Specified | not parsed; no stable element ids; paths not enumerated (→ C4, XMI) |
| 2. Business rules (formats, checksums, states, thresholds) | `oracles/NIN-001.oracle.yaml#rules` | Specified | not executed: V5 uses synthetic `SYN-…` values, not UIN/VID/RID with Verhoeff (→ C1/C2) |
| Functional and non-functional requirements | `models/nin-requirements.md` (F-01..F-12, NF-01..NF-09), slides 21–22 | Partly executed | V5 contract cites F-07, F-08, NF-04, NF-08 only; no requirement-coverage matrix (→ C1, C4) |
| 3. Scenarios (~45: nominal, hit, no hit, rejection, failure, DR) | `catalog/TC-NIN-scenarios.md`, slide 23 | 1 of 45 executed | only NIN-001; the V5 faults (duplicate, missing, slow, …) are telemetry/oracle mutations, not catalogue scenarios (→ C4) |
| 4. Flows (sequence per component) | draw.io pages 3–4, slide 24 | Executed (expected tree hand-written) | expected 17-span tree written by hand in the contract; the observed sequence is drawn from Tempo in each report |
| 5. Step detail: state before/after | slide 8, `oracle.yaml#db` | Missing in V5 | no DB state (kernel.uin, regprc, idrepo) simulated or checked (→ C5) |
| 5. Step detail: real messages | slide 8, `oracle.yaml#api` | Missing in V5 | no REST request/response bodies; only `http.response.status_code` on spans (→ C2) |
| 5. Step detail: expected signals (span, log, metric, audit) | slide 25, draw.io page 4, `oracle.yaml#traces/logs/events/metrics/audit` | Partly executed | spans, business events, per-service HTTP metrics, journey histogram, exemplars: executed. Audit: missing. Spec metrics M1–M5 / ENV1–2 / X1 as written in the YAML: not executed (→ C3, C5) |
| 6. Oracle: executable, versioned, reviewed | `oracles/NIN-001.oracle.yaml` (spec) and `contracts/NIN-001-v5-slice.json` (executed) | Executed, but two sources | the executed contract is hand-written, not compiled from the spec oracle (→ C1) |

## 2. The loop (slide 16)

| Loop step | Status | Evidence / gap |
|---|---|---|
| 1. Instrument (signal contract in every layer; env and site stamped) | Simulated | the S1 simulator emits semconv spans, events and metrics with `deployment.environment.name`, `cloud.region`; collector-side stamping (`observability/env-site-injection.yaml`) not exercised |
| 2. Specify | Partly | see §1 |
| 3. Execute (executor opens the root span, journey tagged) | Simulated | root span `jarvis-e2e` and `oaef.run.id`; the Gherkin feature is not executed step by step |
| 4. Collect (traces, logs, metrics, audit, DB state, infra context) | Partly executed | traces, logs, metrics: real backend queries, per-attempt log; audit, DB, infra context: missing |
| 5. Verify (functional, non-functional, completeness; verdict class) | Partly executed | per-transaction exactness, span tree, values, order, latency, metric reconciliation; diagnostic classes (`OBSERVABILITY_VIOLATION`, `NFR_VIOLATION`, `TRACE_CONTEXT_BROKEN`, `METRIC_RECONCILIATION_FAILURE`, `EVIDENCE_GAP`); the deck's seven classes (slide 15: PASS, PASS_OBSERVABILITY_DEFECT, INCONCLUSIVE, INFRA, SILENT_FAILURE, TEST_DATA_CONFIG, PRODUCT_BUG) are not all produced (→ C6) |
| 6. Seal and learn (hash, sign, write-once; gaps feed back) | Partly | SHA-256 bundle + offline re-evaluation + stability page; no signature, no WORM storage; feedback to the spec is manual |

## 3. Report and RCA (slides 33–34)

| Deck promise | Status | Gap |
|---|---|---|
| Per-axis summary: functional x/y, non-functional x/y, signal contract %, audit x/y, verdict | Partly | report shows per check family and verdict; no per-axis scores grouped as in slide 33 (→ C6) |
| Clause → expected → actual → evidence file | Executed | failed checks and "Oracle versus observed" with evidence links |
| Probable first source + where to look | Partly | links to the exact trace/span/logs; no automatic "first source" synthesis (→ C6) |
| RCA mapping verdict → code/config to inspect (slide 34) | Missing | (→ C6) |
| Span graph filtered by business key (slide 31) | Executed (per run) | report service graph, span tree with timings, Grafana links; search by NIN hash not demonstrated |
| Evidence, test management, reuse | Executed | campaign zip, Xray Cucumber JSON, reusable dashboards, live CI |

## 4. Documentation

| Item | Status |
|---|---|
| Runbook, design notes, this status | Markdown, current (`docs/demo/`, `docs/oaef/`) |
| `OAEF-SPEC-001` / `OAEF-VTS-001` (Word/PDF) | predate V5; not updated |
| V5 addendum `docs/oaef/OAEF-V5-MODEL-TO-EVIDENCE-ADDENDUM.md` (asked by the V5 brief) | missing |
| Deck | predates V5 (slides 30, 33 still illustrative); not updated with real run IDs |

## 5. Plan to close the cycle

| Step | Closes | Done when |
|---|---|---|
| **C1** compile `NIN-001.oracle.yaml` → executed contract, traceability ids | §1 rows 2, 6; requirement refs | hand-written contract removed; every check cites requirement + model element |
| **C2** REST messages + business rules in the simulator and oracle | §1 rows 2, 5b | request/response per step in the report; UIN/VID/RID formats and Verhoeff checked |
| **C3** spec metrics M1–M5, ENV1–2, X1 (baseline/delta) | §1 row 5c, loop 1 | each metric assertion of the YAML evaluated live |
| **C4** model as source (XMI from Modelio) → paths → catalogue scenarios generated | §1 rows 1, 3, 4 | ≥ nominal, dedupe and validation families run; coverage of requirements and branches published |
| **C5** state before/after (DB) and audit, simulated in S1 | §1 row 5a, audit, loop 4 | DB and audit checks and faults detected |
| **C6** deck verdict classes, per-axis report, first source, RCA hints | §2 loop 5, §3 | report reproduces slide 33 with real data; slide 34 hints per class |
| **C7** documentation: V5 addendum, SPEC/VTS update, deck slides with real run IDs | §4 | documents consistent with the executed system |
| (later) signing and WORM storage; S2 on an instrumented MOSIP | loop 6, real SUT | — |
