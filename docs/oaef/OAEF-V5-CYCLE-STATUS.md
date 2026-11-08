# OAEF — full-cycle status against the deck (2026-11-07, branch `docs/oaef-v5-model-to-evidence-demo`, after C1)

Question: is the cycle promised by *Observability-First Evidence-Based Testing* (slides 7 "From use case to oracle", 8 "Anatomy of one step", 16 "The loop", 18–39 worked example) implemented end to end?
**Answer: half of it, now joined in the middle.** The right half (execute → collect → verify → seal → report) runs for real against Tempo/Loki/Prometheus in GitHub Actions and Codespaces. Since C1 the oracle that runs is **compiled from the specification** (activity model, requirement register, oracle YAML) with requirement and model-element traceability; the hand-written contract survives only as a regression baseline. Still missing on the left: scenario generation from the model (C4), and the step detail that is not signals: REST messages and business rules (C2), spec metrics (C3), DB state and audit (C5). Reference run: GitHub Actions [42420471946](https://github.com/gharbonnier78/mosip-observability-oracles/actions/runs/42420471946), deck section 6 (slides 40–59).

Legend: **Executed** = run by V5 and checked live · **Compiled, not evaluated** = in the executed contract, reported `NOT_EVALUATED` · **Specified** = written and reviewed, not executed · **Missing** = neither.

## 1. Derivation chain (slide 7) and step detail (slide 8)

| Deck step | Source in the repository | Status | Gap to close |
|---|---|---|---|
| 1. Use case | `models/nin-usecase.puml`, slide 19 | Specified | not machine-read (documentation) |
| 1. Activity diagram (paths, decisions) | `models/nin-enrolment-activity.puml`, slide 20 | **Executed for traceability** | parsed by the compiler (lanes, activities, notes, `[F-xx]` tags → `model_element_refs`); paths and decisions not enumerated, no stable XMI ids (→ C4) |
| 2. Business rules (formats, checksums, states, thresholds) | `oracles/NIN-001.oracle.yaml#rules` | Compiled, not evaluated | synthetic values; UIN/VID/RID formats and Verhoeff not checked (→ C2) |
| Functional and non-functional requirements | `models/nin-requirements.md` (F-01..F-12, NF-01..NF-09), slides 21–22 | **Executed** | every obligation cites its requirements; `generated/coverage.json` per requirement; uncovered for NIN-001: F-11, F-12, NF-02 (other scenarios) |
| 3. Scenarios (~45: nominal, hit, no hit, rejection, failure, DR) | `catalog/TC-NIN-scenarios.md`, slide 23 | 1 of ~45 executed | only NIN-001 plus 8 fault variants (telemetry/oracle mutations, not catalogue scenarios) (→ C4) |
| 4. Flows (sequence per component) | draw.io pages 3–4, slide 24 | **Executed** | expected tree compiled from the YAML: 20 span aliases, links T1→T2→T3, 42 spans over 15 services per transaction; draw.io pages are documentation, not read by scripts |
| 5. Step detail: state before/after | slide 8, `oracle.yaml#db` | Compiled, not evaluated | no DB state simulated or checked (→ C5) |
| 5. Step detail: real messages | slide 8, `oracle.yaml#api` | Compiled, not evaluated | no REST request/response bodies (→ C2) |
| 5. Step detail: expected signals (span, log, metric, audit) | slide 25, `oracle.yaml#traces/logs/events/metrics/audit` | Partly executed | spans, links, 6 ordered business events, logs (incl. forbidden PII), NF-04/NF-05 durations, span budgets, journey histogram, per-service HTTP metrics: executed. Spec metrics M1–M5 / ENV1–2 / X1: compiled, not evaluated (→ C3). Audit: compiled, not evaluated (→ C5) |
| 6. Oracle: executable, versioned, reviewed | `oracles/NIN-001.oracle.yaml` → `generated/contracts/NIN-001.contract.json` | **Executed, single source** | 60 obligations, source hashes, drift check in CI; default contract since C1d. 2000 checks per run `NOT_EVALUATED`, never counted as passed |

## 2. The loop (slide 16)

| Loop step | Status | Evidence / gap |
|---|---|---|
| 1. Instrument | Simulated | the S1 simulator emits semconv spans, events and metrics with environment, cluster, site, env id, run id; collector-side stamping not exercised |
| 2. Specify | **Executed (compiled)** | see §1; scenario generation missing (C4) |
| 3. Execute | Simulated | root span `jarvis-e2e`, `oaef.run.id`; the Gherkin feature is not executed step by step; one-command trigger (`gh workflow run`) |
| 4. Collect | Partly executed | traces (incl. link ids), logs, metrics: real backend queries, per-attempt log, truncation guard; audit, DB, infra context: missing (→ C5) |
| 5. Verify | Partly executed | per-transaction exactness, span tree and links, values, order, durations, span budgets, metric reconciliation, consequences of a root failure; 6 diagnostic classes produced; the deck's 7 verdict classes (slide 15) not all produced (→ C6) |
| 6. Seal and learn | Partly | SHA-256 bundle, offline `re-evaluate`, stability page (STABLE/FLAKY); no signature, no WORM storage; feedback to the spec is manual |

## 3. Report and RCA (slides 36–37)

| Deck promise | Status | Gap |
|---|---|---|
| Per-axis summary: functional, non-functional, signal contract %, audit, verdict | Partly | per-obligation table with requirements and evaluated / failed / not evaluated; no per-axis scores as on slide 36 (→ C6) |
| Clause → expected → actual → evidence file | **Executed** | failed checks with requirement refs, oracle versus observed, links to trace, events, sequence |
| Probable first source + where to look | Partly | root failure and its consequences, links to the exact span; no automatic first-source sentence (→ C6) |
| RCA mapping verdict → code/config to inspect (slide 37) | Missing | (→ C6) |
| Span graph filtered by business key (slide 31) | Executed per run | span tree with timings, service graph, Grafana; search by NIN hash not demonstrated |
| Evidence, test management, reuse | **Executed** | campaign zip, Xray Cucumber JSON, Allure, two dashboards as code, Playwright screenshots (35/35), live CI |

## 4. Documentation

| Item | Status |
|---|---|
| Runbook, user guide with figures, compiler design, this status | current (`docs/demo/`, `docs/oaef/`) |
| Process models: BPMN 2.0 and ArchiMate (generated) | `docs/process/` |
| Demo video script (narration and navigation) | `docs/demo/OAEF-V5-DEMO-VIDEO-SCRIPT.md`; video not recorded |
| Deck | section 6 added: real run 42420471946, process, specification, injection, validation, evidence screenshots, GenAI vs script, status; slides 18–35 remain the target design (marked illustrative where so) |
| `OAEF-SPEC-001` / `OAEF-VTS-001` (Word/PDF) | predate V5; not updated (→ C7) |
| V5 addendum `docs/oaef/OAEF-V5-MODEL-TO-EVIDENCE-ADDENDUM.md` | missing (→ C7) |
| Perspectives with NIN Registration use cases (Weaver, OATs, in-toto + Sigstore), including an executed bundle-forgery test | user guide §13, deck slides 54–57; tools not yet run |
| Signal communication diagrams (Metric, Trace, Logs) | `docs/diagrams/nin-001-signal-communication.drawio`, each element marked demonstrated / target / open; deck slides 33–35 |
| draw.io pages 3–6 generated from the contract | proposed, not done |

## 5. Plan to close the cycle

| Step | Closes | Done when | Status |
|---|---|---|---|
| **C1** compile `NIN-001.oracle.yaml` → executed contract, traceability ids | §1 rows 2, 4, 6 | every check cites requirement + model element; compiled contract is the default | **Done** (C1a–C1d), live run 42420471946 |
| **C2** REST messages + business rules in the simulator and oracle | §1 rows 3, 8 | request/response per step in the report; UIN/VID/RID formats and Verhoeff checked | next |
| **C3** spec metrics M1–M5, ENV1–2, X1 (baseline/delta) | §1 row 9, loop 1 | each metric assertion of the YAML evaluated live | to do |
| **C4** model as source (XMI from Modelio) → paths → catalogue scenarios generated | §1 rows 1, 5 | ≥ nominal, dedupe and validation families run; requirement and branch coverage published | to do (needs the XMI export) |
| **C5** state before/after (DB) and audit, simulated in S1 | §1 row 7, audit, loop 4 | DB and audit checks and faults detected; `missing` becomes decidable | to do |
| **C6** deck verdict classes, per-axis report, first source, RCA hints | loop 5, §3 | report reproduces slide 36 with real data; slide 37 hints per class | to do |
| **C7** documentation: V5 addendum, SPEC/VTS update | §4 | documents consistent with the executed system | partly (guide, runbook, deck, process models done) |
| (later) signing and WORM storage; technical user and vault; S2 on an instrumented MOSIP | loop 6, real SUT | — | to do |
