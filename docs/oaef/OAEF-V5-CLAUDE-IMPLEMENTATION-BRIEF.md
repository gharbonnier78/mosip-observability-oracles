# OAEF V5 — Claude Implementation Brief
## From engineering model to executable oracle to observable, qualified evidence
**Status:** proposed work package / implementation instructions, **not** a claim of implemented functionality  
**Date:** 2026-11-05  
**Target repository:** gharbonnier78/mosip-observability-oracles  
**Primary environment:** existing GitHub Codespace; preserve the running demo  
**Target deliverables:** specification addendum, executable synthetic demonstrator, regression suite, validation evidence, updated presentation, reproducible GitHub history.

> **Instructions to Claude:** You are the independent systems-engineering reviewer, architect, Python implementer, OTLP/Weaver integrator and technical editor. Do not merely endorse this proposal. Inspect the existing repository first, challenge the assertions, identify contradictions and gaps, design the smallest defensible incremental change, implement and test it in the currently available Codespace, and produce traceable, reproducible evidence. Never report a simulated success as MOSIP production verification. Work in reviewable pull requests. Do not rewrite the original framework or discard the prior 7-span demo.

---

## 0. Outcomes and non-negotiable rules

The new demonstration must show, on a **single coherent end-to-end scenario** based on NIN-001:

1. An approved engineering specification defines expected business states, step ordering, mandatory messages, signal schemas, metrics, non-functional thresholds and traceability obligations.
2. A deterministic synthetic generator creates **1, then 3, then 100 independently correlated transactions**, not 100 copies with the same identity. Reuse the NIN-001 scenario semantics but avoid pretending to execute MOSIP.
3. The generated traces, structured logs/events and metrics are emitted over OTLP; Grafana/Tempo/Loki/Prometheus show the observable flow as it arrives/after ingestion. A visitor can select a specific run and transaction and inspect spans, event sequence, values and anomaly links. If the intended UI called "Span Live"/"Spine Live" refers to a separate product, identify that UI precisely rather than inventing an integration.
4. An **independent, deterministic oracle** verifies exact expected business and telemetry obligations, not just "at least seven spans" or nonempty logs.
5. Controlled faults are injected **one at a time and in combinations**; each expected failure is actually caught by the corresponding oracle without changing the approved expectation. The demo visibly differentiates functional defects, non-functional defects, semantic telemetry defects, missing evidence and ingestion failures.
6. Every run writes a complete **replayable local evidence bundle** with manifest and hashes, links to Grafana, expected/actual comparisons, injected-fault provenance, verdict and reproducible seed. A hash alone is not a signature and local storage is not WORM.
7. Git and Codespace contain reproducible scripts, configuration, tests, sample evidence and the presentation/specification source updates; Git history must record precisely which evidence was actually generated and by which code/versions.
8. No LLM is present in the verification runtime. GenAI can assist the design, authoring and review of specifications; its outputs require deterministic validation and human approval.

**Definitions:** F = functional requirement; NF/NFR = non-functional requirement; OBS = observability requirement; AUD = audit requirement; EV = evidence obligation. In the verbal request "IFR" is interpreted provisionally as NFR; verify the nomenclature in the existing requirements register.

### Explicit distinction between validation modes

- **S0 / fixture replay:** show current NIN-001 OTLP example (7 spans, one log, one histogram/exemplar). Demonstrates connectivity, **not** a full scenario validator.
- **S1 / synthetic journey simulation:** the generator simulates business state and emits synthetic OTLP. Demonstrates contract/oracle consistency and the observability chain, **not** MOSIP product conformance.
- **S2 / live SUT integration (future):** the same oracle contract is applied to a genuinely instrumented system, plus independent API/DB/audit evidence. Only this mode can provide evidence about an actual delivered system, and even then only inside the specified scope.

Put this distinction on-screen, in the report, and on the presentation slides.

---

## 1. Existing baseline that MUST be inspected before any modifications

Repository files verified in the supplied snapshot and on the GitHub main branch:

- `README.md` — architecture, source-of-truth decisions, $golden workflow, known INST/VER/ENV gaps.
- `models/nin-requirements.md` — F-xx / NF-xx requirements.
- `models/nin-enrolment-activity.puml`, `models/nin-usecase.puml` and `docs/diagrams/*.drawio` — process and communication models.
- `features/nin_001_new_adult_no_hit.feature` and `catalog/TC-NIN-scenarios.md`.
- `oracles/NIN-001.oracle.yaml` — existing multi-domain oracle design.
- `oracles/examples/NIN-001.otlp-example.json` — baseline seven-span OTLP fixture.
- `observability/attribute-model.md` — official semconv reuse, `oaef.*` and `mosip.*`; inspect all attributes and events.
- `validation/replay_nin001.py` — fixture replay only.
- `validation/demo/check.sh` — a useful smoke check, not a deterministic business oracle.
- `validation/demo/docker-compose.yml` — `grafana/otel-lgtm` demo image.
- `.devcontainer/devcontainer.json` — existing Codespaces stack.
- `docs/oaef/OAEF-SPEC-001_Observability-and-Audit-Evidence-Framework-Specification.docx`, its `src` assembly files, and `OAEF-VTS-001_Validation-Test-Specification.docx`.
- `docs/wp0-shared-platform-requirements.md` and `docs/review/*`.
- Supplied `Observability-First Evidence-Based Testing_V4 (2).pptx` (36 slides) and `TraceMetricsLogs_CommunicationDiagrams (1).drawio`.

**Current observed limits:**
- `check.sh` checks a span count of **>=7**, at least one packet-receiver log over the **last hour**, and at least one exemplar. It is not scoped precisely enough to prove per-run completeness, allows extra/missing internal steps, and prints `RESULT: CHECK` while exiting successfully in certain negative cases. Replace these as gates in V5, preserve as smoke mode.
- A replay emits predefined signals; no general-purpose engine appears to execute all sections of `NIN-001.oracle.yaml`. Do not claim such an engine exists until you execute it and demonstrate evidence.
- `grafana/otel-lgtm:latest` and the default Codespaces Grafana admin password `change-me` are unacceptable as reproducible/review-ready baselines; pin versions/digests and use Codespaces secrets or documented local development controls.
- The supplied slide archive has **two CRC-invalid embedded images**, `ppt/media/image6.png` and `ppt/media/image24.png`, in the copy inspected. Obtain a clean original or repair and visually compare before editing; never silently replace illustrations and call the deck intact.
- Existing `NIN-001.oracle.yaml` has an NFR check `e2e_upload_to_processed_s <= 600` and a separate NF-04 business duration of up to 24 h/86400 s. Define their start/end semantics and never collapse them into one threshold.
- `cloud.region=dc1/dc2` is used for private sites even though semconv `cloud.region` represents a cloud region. Assess migration to `oaef.site.id` plus appropriate source-of-truth stamping rather than hiding semantic misuse.
- The catalogue uses `event.name`, while the modern OTLP LogRecord has a distinct `EventName` field; test the real payload and backend compatibility before migration. See https://opentelemetry.io/docs/specs/otel/logs/data-model/ .

**First Claude response required:** a gap matrix listing every baseline component, whether implemented or merely specified, evidence for that status, risk, and recommended minimal change. Do not start by generating a new platform.

---

## 2. Reference standards and boundaries

Use and version-pin the official sources:

- OTel Semantic Conventions and registry: https://opentelemetry.io/docs/concepts/semantic-conventions/ and https://opentelemetry.io/docs/specs/semconv/registry/
- OTel metrics and exemplar semantics: https://opentelemetry.io/docs/specs/otel/metrics/data-model/
- OTel LogRecord and EventName: https://opentelemetry.io/docs/specs/otel/logs/data-model/
- OpenTelemetry Weaver and custom registry schema: https://github.com/open-telemetry/weaver and https://github.com/open-telemetry/weaver/blob/main/docs/define-your-own-telemetry-schema.md
- W3C Trace Context and W3C Baggage; OpenTelemetry Collector configuration/docs. Pin tested versions.
- UML / OCL only for semantically well-defined contracts on actual typed UML models; PlantUML text alone is **not** an executable OCL metamodel.
- DMN only if a scenario actually contains a decision table whose hit policy, inputs and outcomes deserve separate governance. Do not force DMN into all orchestration or observability checks.
- NFR/SLO verification is not identical to telemetry naming; time windows, populations, percentiles, confidence and observability health must be specified.

**Architecture rule:** OTel/Weaver validates signal shape and meaning; a verification-obligation registry links engineering models and requirements to checks; a separate oracle evaluates behavior, business results, temporal relations and evidence sufficiency. Do not assume Weaver proves a full functional journey.

---

## 3. Required model-to-evidence traceability

Introduce a small, versioned `verification-obligation` manifest as a **joining contract**; do not duplicate the entire original oracle.

Each obligation must have:
- `obligation_id`, `requirement_refs`, `model_element_refs` (stable identifiers, model version and optional transition guard), `oracle_check_ids`;
- `type` = functional | nonfunctional | telemetry | audit | security | infrastructure;
- human-readable intent and exact machine-checkable predicate;
- preconditions, system boundary, allowed exceptional behavior, observation window and expected cardinality;
- required evidence sources (at least one independent of the generator for claims about a real SUT);
- telemetry conventions/attributes used; definition version, change owner and risk criticality;
- explicit `on_missing_evidence` handling; do not equate absence with proof of non-execution.

Example (**proposed contract**, adapt IDs to actual file and model):
~~~yaml
apiVersion: oaef.dev/v1
kind: VerificationObligation
obligation_id: OBL-F07-ASSIGN-01
requirement_refs: [F-07]
model_element_refs:
  - model: models/nin-enrolment-activity.puml
    element_id: assign-nin             # add a stable real ID during implementation
oracle_check_ids: [FN-ASSIGN-EXACTLY-ONCE, OBS-UIN-EVENT]
type: functional
description: An eligible no-hit registration has one logical assignment.
scope: per_transaction
preconditions: [validated, dedup_no_hit]
expected:
  logical_assignments: 1
  required_event_name: mosip.identity.uin.assigned
evidence_sources: [business_state, structured_event, audit]
on_missing_evidence: inconclusive_unless_independently_proven
~~~

An event is not automatically the business truth: a faulty service could emit the event but fail to assign an identifier. In S1, model the independent **synthetic business ledger** separately from telemetry; in S2, replace that with validated API/DB/audit queries.

### Required model change-impact demonstration

Change one controlled requirement or activity ID in a branch; the traceability checker must identify dependent contracts, oracles, fixtures and tests, and fail if an obsolete reference remains. Provide a machine-readable impact report, not a screenshot.

---

## 4. Common telemetry registry

Retain `oaef.*` as the existing **framework-level extension namespace**, with `mosip.*` only for domain-specific attributes; reuse official semconv keys unchanged where they apply.

Introduce `observability/registry/manifest.yaml` and compatible Weaver registry definitions **only after confirming actual Weaver schema/version syntax**, dependency resolution and generated output. Generate human documentation from the registry rather than maintaining competing copies. Do not populate official namespaces with proprietary keys.

The registry must specify for every field and signal: name, definition, datatype, units, allowed values, scope (resource/span/log/event/metric), required/conditional status, cardinality budget, privacy class, owner, schema version, compatibility/migration note, requiredness per mode and example.

Suggested internal **low-cardinality** keys (subject to official naming review): `oaef.site.id`, `oaef.site.role`, `oaef.verification.obligation.id` (per trace/event where suitable), `oaef.simulation.mode`, `oaef.fault.code` for simulator diagnosis only, `oaef.contract.version`. Run IDs and transaction IDs may be span/event attributes, but **not unrestricted metric labels**.

Clarify `service.namespace` (service grouping) versus custom attribute namespaces (`oaef.*`). Configure canonical `deployment.environment.name` mapping across Bronze, Silver and Gold. Preserve local site identity across primary/DR role switch.

Events: prefer actual OTLP `LogRecord.EventName` for event identity, with structured attributes; support documented legacy decoding only when necessary. Do not rely on regexes over free-text log bodies. Define schema and producer operation for each business event. Mask/suppress sensitive identifiers in public synthetic demos.

CI gate: schema lint + Weaver registry check + a small controlled `live-check` smoke test. **Do not** claim live-check checks causal ordering or missing transactions; implement those in the oracle.

---

## 5. Complete simulated journey, not just disconnected signals

For NIN-001, derive a **canonical journey contract** from real model/requirement/oracle files. Include all genuinely required stages and alternate branches, with stable step IDs, predecessor relationships, allowed fan-out, correlation boundary and an explicit per-step event/log/span expectation.

For a manageable first vertical slice define, at minimum, these conceptual steps, mapping them to **actual** existing aliases and event names:
1. packet accepted;
2. validation completed;
3. deduplication no-hit decision;
4. unique NIN/UIN assignment;
5. identity activation;
6. credential issuance;
7. notification outcome;
8. durable audit/verification outcome.

**Do not imply that these eight conceptual milestones equal eight spans.** One step can have zero, one or multiple instrumentation spans. The authoritative cardinalities must be specified per span/event type and per logical transaction, with conditions when a step is optional.

Generate 100 independent logical transactions (synthetic RID, synthetic pseudonymous business ID, a transaction identity, fresh trace/span IDs, stable `run_id` and deterministic seed). Each has internally consistent values, timestamps, parent/child relationships and span links for truly asynchronous boundaries (T2/T3); avoid forging one artificial parent-child tree across unrelated traces.

The generator must create:
- a **pre-fault expected-state/ground-truth ledger** (simulation truth) and model-derived expected obligations;
- an **actual simulated business ledger**, independently mutable in the functional fault mode;
- traces, structured event/log records, audit-like records and honest metrics generated from the actual simulated activities;
- injectors acting either on the business model, on produced telemetry, or on the transport/collection side;
- a run manifest with seed, scenario/version, fault IDs, transaction count, timestamps, OTLP export endpoints and image/tool digests.

Never generate `expected` from the already-mutated `actual`. Keep generator internals separate from the oracle module and test that they can disagree. When comparing against a real SUT, do not treat the simulator's truth ledger as evidence about that SUT.

### Replay identity and counting semantics

A repeated full test run gets a **new run ID**; 100 transactions each get a unique transaction ID. Distinguish:
1. duplicating the **same OTLP record** (transport/export retry);
2. emitting two different events about the **same logical business transition**;
3. executing the **same business command twice** with one or two effects;
4. repeating an entire 100-transaction test campaign.

The oracle must not mistake (1) for two successful business transitions. The business exactly-once property applies to logical effects under stated idempotency assumptions, not to an unqualified "OTel exactly once delivery" guarantee.

---

## 6. Oracle contract: exactness, completeness and falsifiability

Use the following layered checks on every executed transaction:
- **Presence:** expected record exists.
- **Type/schema:** attributes, typed values, required fields, recognized event names, privacy.
- **Value:** status codes, declared outcomes, synthetic business ID and cross-step value consistency.
- **Cardinality:** exactly N required logical events/steps; minimum and maximum for ancillary spans; no unexpected duplicates.
- **Causality:** permitted transition ordering (a partial order, not falsely assuming all distributed events totally ordered).
- **Correlation:** valid trace/span identifiers, W3C propagation, link existence where applicable, join keys, no cross-transaction contamination.
- **Temporal:** duration boundaries based on defined start/stop milestones, clock tolerance, asynchronous settling.
- **Functional:** actual business ledger and API-like response vs independently approved requirements.
- **Non-functional:** individual latency limits, overall journey budget, population-based thresholds, error rate under the correct denominator.
- **Evidence quality:** collection health, requested vs observed records, redaction, integrity of persisted records and completeness of query scope.

Pseudocode (illustrative, not a substitute for implemented semantics):
~~~python
expected = contract.expected_multiset(transaction_id)  # defined BEFORE injection
observed = normalize(collected_telemetry.for_transaction(transaction_id))
missing = expected - observed
unexpected = observed - expected
duplicates = count_logical_business_events(observed, key=(transaction_id, event_name, effect_id))
assert not missing and not unexpected
assert duplicates == {}
assert graph_respects_required_edges(observed, contract.partial_order)
assert all_values_match_contract(observed, contract)
~~~

**Never silently allow extra records just because the required subset is present.** Extra instrumented spans may be allowed by policy; extra business assignments, notifications and audit events often are not. Encode this difference explicitly.

### Numerical acceptance demonstrations

- 1 transaction × 3 obligatory events => exactly 3 logical events, no unexpected event;
- 3 transactions × 3 obligatory events => exactly 9, also exactly three for EACH transaction;
- 100 transactions × 3 obligatory events => exactly 300 and complete per-transaction coverage. Overall 300 alone is insufficient: 299 + 1 duplicate can fool aggregate counts;
- 100 transactions × 1 assignment => 100 unique successful assignments if the scenario is fully nominal;
- no cross-run matching even if another run is concurrently present in the same Grafana store;
- a duplicated required logical event => at least one affected obligation FAIL, even if `count >= 3` remains true.

The 3-event case is a **focused cardinality example**, not a claim that the complete NIN flow needs only three events.

### Pipeline health and epistemic limits

An expected event not found is a **telemetry contract failure / evidence gap** when the test conclusively measured the producer and collector boundaries; otherwise mark `INCONCLUSIVE` / `NOT_DEMONSTRATED` if collection completeness is unknown. Do not conclude that business activity never occurred solely from a missing span. Track collector/export drop counters, sampling policies, receiver availability, known emitted counts, settle/poll progress and query time range.

Do not call synthetic replay coverage "100% production completeness". The demo can prove that **this generated fixture** was completely emitted/received and checked, subject to its measurement assumptions.

---

## 7. Metric/NFR oracle — strict distinction from events and logs

Create an explicit metric contract table for each measurement:
- instrument and metric name, type (counter/gauge/histogram), unit, aggregation temporality, resource and data-point attributes;
- expected relationship to scenario activities, label dimensions and cardinality budget;
- baseline/end time, scrape/export interval, warm-up/settle interval, permitted reset;
- exact versus statistical assertion, uncertainty and sample population.

For a **controlled dedicated instance** with one metric series and stable counters, 100 successful requests should produce an expected aggregate increment of 100 **provided** the instrument increments once per transaction and there is no reset or outside traffic. The generated business/event ledger is the exact reference; PromQL `increase()` can extrapolate with scrape timing and must **not** be mistaken for exact transaction accounting.

For histogram metrics:
- count difference = number of recorded measurements under isolation assumptions;
- unit and bucket boundaries must match registered semconv/producer configuration;
- histogram p95 is approximate, and 100 samples make tail quantiles unstable; compare with the 100 exact synthetic durations when showing exact per-run NFR outcomes, and label dashboard histogram quantiles as estimates;
- an exemplar is **optional/sampled** and is a navigation aid, not required for each transaction or proof of count completeness.

Create both a clean nominal run (e.g. well within a configured service latency budget) and a violating run (deterministically > declared threshold); show the corresponding individual NFR check failure, not just a red dashboard.

Retain distinctions between `NF-04 <= 86400s` for business RID-to-NIN and `nfr.e2e_upload_to_processed_s <= 600s` from existing files, after agreeing their exact endpoints. Validate whether existing metrics named "http.server.request.duration" truly use seconds and the matching standard/version; avoid guessing.

---

## 8. Mandatory controlled mutation/fault matrix

Seed all injections; run one-at-a-time plus at least two compound cases. Fault injection must be configured by manifest, not hand-edited JSON files, and must preserve an immutable nominal baseline. Implement at distinct fault layers.

| ID | Layer | Injected defect | Expected machine-detected violation |
|---|---|---|---|
| M00 | none | Nominal 1/3/100 transactions | all applicable obligations PASS |
| M01 | telemetry | Delete one mandatory business event from transaction #17 | missing mandatory event, OBS FAIL or evidence INCONCLUSIVE depending health |
| M02 | telemetry | Duplicate a logical `identity.uin.assigned` event in #17 | unexpected duplicate, cardinality FAIL |
| M03 | business | Execute assignment twice for same logical enrolment | functional idempotency/uniqueness FAIL; telemetry may honestly show both |
| M04 | telemetry | Wrong outcome/status for an event | typed value or semantic mismatch |
| M05 | telemetry | Remove required attribute or change its type | schema/semconv FAIL |
| M06 | telemetry | Break trace/span link or cross-transaction correlation | causality/correlation FAIL |
| M07 | telemetry | Reorder a forbidden transition with valid-looking timestamps | forbidden temporal/transition relation FAIL |
| M08 | business | Mark identity ACTIVE without approved decision | state invariant / functional FAIL |
| M09 | NFR | Make designated stage exceed its latency budget | NFR FAIL with exact duration |
| M10 | metrics | Under-/over-count isolated metric stream (99/101 for 100 calls) | metrics-to-ledger reconciliation FAIL |
| M11 | telemetry | Wrong unit, metric type or resource attributes | semconv/metric contract FAIL |
| M12 | audit | Missing audit effect or mismatch between two stores | audit completeness FAIL or NOT_DEMONSTRATED |
| M13 | pipeline | Drop OTLP export / disable receiver / simulate sampling loss | pipeline health FAIL, business conclusion INCONCLUSIVE |
| M14 | security | Forbidden synthetic sensitive value in log | privacy FAIL with redacted report |
| M15 | replay | Re-send the same exact OTLP record | distinguish duplicated transport data from duplicate business effect; document normalization policy |
| M16 | compound | M02 + M09 | both independent failures reported; no masking by single overall verdict |
| M17 | compound | M01 + M13 | explicit ambiguity and evidence insufficiency, not false PRODUCT_BUG |

The matrix is a minimum. Where an injection cannot be observed in a given mode, explicitly mark it `NOT_APPLICABLE` and explain why. A fault "killed" by oracle must have a check ID, evidence reference and verified expected failure class; test-only comparison against injection metadata is **not** a valid oracle.

### Fault injector design contract

Each fault record contains `fault_id`, `fault_layer`, `target_transaction`, `target_step`, `seed`, `before/after fixture hash`, `expected_detection_ids` and `expected_outcome`. The oracle may **not** read the fault metadata to decide whether a run passes; the test harness may use it to check oracle sensitivity after the verdict is independently produced.

---

## 9. Verdict and coverage model

Avoid treating a verdict as a single cause label. Persist:
- `functional_status`, `nonfunctional_status`, `telemetry_status`, `audit_status`, `collection_health_status` ∈ PASS / FAIL / INCONCLUSIVE / NOT_APPLICABLE;
- an independent `evidence_sufficiency` status;
- ordered `diagnostic_causes` (OBS_GAP, PRODUCT_DEFECT, INFRA, TEST_DATA_CONFIG, etc.), with confidence and scope clearly labeled;
- one **overall demonstration result**: PASS only if all required axes pass and evidence sufficiency meets policy; FAIL for proven violations; INCONCLUSIVE when required evidence is not evaluable.

Preserve/migrate existing categories (`PASS_OBSERVABILITY_DEFECT`, `INFRA`, `PRODUCT_BUG`, `SILENT_FAILURE`, etc.) as diagnostic classifications, not mutually exclusive truths when multiple defects coexist.

For each check, produce exactly:
~~~json
{
  "check_id": "OBS-F07-ASSIGN-COUNT",
  "obligation_id": "OBL-F07-ASSIGN-01",
  "transaction_id": "TX-017",
  "status": "FAIL",
  "expected": {"logical_count": 1},
  "actual": {"logical_count": 2},
  "evidence_refs": ["events.ndjson#..."],
  "reason_code": "UNEXPECTED_DUPLICATE"
}
~~~

Report separately:
1. **specification coverage** = obligations with executable checks / approved obligations (by risk weight as an additional indicator);
2. **execution coverage** = executed applicable checks / available applicable checks;
3. **conformance** = passed / conclusively evaluated applicable checks; show missing/inconclusive separately;
4. **mutation detection** = killed detectable mutations / applied detectable mutations, by fault layer and class.

Never report “100% coverage” without the denominator, mode and excluded obligations.

---

## 10. Demonstrator services and separation of responsibilities

Proposed minimum modules (adapt names to existing conventions and avoid unnecessarily many containers):

~~~text
validation/
  demo/
    docker-compose.yml
    README.md
    check.sh                   # legacy smoke, corrected exit codes
    run_demo.sh                # reproducible orchestration
    demo-config.yaml
  simulation/
    scenario.yaml             # scenario settings and expected contract refs
    generate.py               # seeded truth + synthetic journey + OTLP
    inject.py                 # controlled mutations
    export_otlp.py            # OTLP HTTP exporter with retry/backoff
  oracle/
    load_contracts.py
    normalize.py              # OTLP KeyValue normalization, types, timestamps
    graph.py                  # parent/link and partial-order checks
    evaluate.py               # check engine
    collect.py                # backend query adapters / raw receiver option
    report.py                 # verdict + evidence indexes
  evidence/
    verify_bundle.py
  tests/
    test_contracts.py
    test_nominal_1_3_100.py
    test_mutants.py
    test_isolation.py
    test_metrics.py
    test_evidence_integrity.py
contracts/
  verification-obligations.yaml
observability/
  registry/
    manifest.yaml
    ... definitions ...
reports/
  demo/                        # disposable local outputs, selected fixtures versioned
~~~

Do not introduce Kafka, Kubernetes or real MOSIP services solely for this demonstrator. A Python stdlib or minimal locked dependencies implementation may suffice. Reuse Grafana LGTM local stack but pin an available version/digest. Use an OTLP receiver/raw-signal capture or stored emitted payload to prove exporter data, and cross-check backend retrieval separately; the captured emission file alone is not proof the backend ingested it.

**Demo UX:** provide a single deterministic `run_demo.sh --transactions 100 --seed 20261105 --fault none` and `run_demo.sh --transactions 100 --seed 20261105 --fault M02 --target TX-017` entry point (illustrative interface). The script should print `run_id`, truth counts, observed counts, expected/actual per step, failures, Grafana deep links, evidence directory and a machine-readable summary. UI may be a static HTML report or rendered Markdown; do not add a web app if it adds maintenance without verification value.

**Pipeline path:** generator → pre-fault expected reference + actual business state → fault injector → telemetry encoder → OTLP Collector/LGTM → backend query/capture → normalization → deterministic oracle → bundle → report/UI. Keep external observations separate from expected reference and from simulated SUT state.

---

## 11. Query isolation and backend behavior

Never query `all logs in last hour` or assume that seven spans in one trace mean full journey completeness.

Use `run_id`, `scenario_id`, `transaction_id`, trace IDs and bounded timestamps; trust only canonical structured, privacy-safe attributes and documented mappings to actual Loki/Tempo query syntax. For multi-trace journeys query each trace by ID or follow valid span links, not a fabricated all-in-one trace.

Use settle/poll until stable within bounded timeout, accounting for backend eventual consistency. Capture query response, query text, timestamp, errors and collection health. No passing a run solely because one dashboard has a visible span.

**For live demonstrations:** let the operator see the span/event stream appear in Grafana/Tempo, with realistic ingestion latency; show a separately refreshed oracle report. Do not claim native instantaneous "live spans" when the actual viewer is an indexed-query UI.

**Shared stores:** a per-run business counter is safest in the exact synthetic ledger or instrumented isolated series. Avoid `run_id` as an unbounded metric label in long-lived deployments. Isolate the demo's metric writer, then reconcile with OTLP metric points and selected PromQL counters using explicit reset/scrape assumptions.

---

## 12. Evidence bundle, reproducibility and integrity

Output for each run:
~~~text
evidence/demo/<run_id>/
  manifest.json                 # contract/model/code refs, seed, mode, environment,
                                # exporter/backends, time window, faults, hashes
  reference/expected.json       # approved expected obligations; NOT mutated
  truth/business-ledger.json    # simulator truth (S1 only; NEVER SUT ground truth)
  injected/faults.json          # mutation provenance, separate from oracle inputs
  emitted/traces.json
  emitted/logs.json
  emitted/metrics.json
  collected/traces.json         # backend retrieval; may differ from emitted
  collected/logs.ndjson
  collected/metrics.json
  audit.json
  verdict.json                  # every check: exact expected/actual + evidence ref
  coverage.json
  links.md                      # Grafana links, run-scoped
  environment.json              # image digests, CLI/tool versions, collection health
  sha256sums.txt                # integrity check
  report.md                     # concise human-readable investigation
~~~

Ensure files are valid JSON/YAML, stable and diffable, with deterministic ordering; timestamps are dynamic but reproducible relative to seed/clock configuration. Do not place secret tokens, actual identities or raw PII in evidence, manifests, logs or Git history.

**Signing and WORM:** Only label the evidence "signed" when a real signature has been produced and verified with a configured key; only label it "WORM" when backed by enforced object retention. For this Codespace demonstrator hashes + independent offline verification are sufficient and must be called **integrity checks**, not legal/audit-grade immutable retention.

Provide `python -m ... verify-bundle evidence/demo/RUN` which fails when any evidence file or manifest reference is altered. Also provide `re-evaluate --offline` to demonstrate identical verdict from the stored evidence and frozen contract.

---

## 13. Deterministic regression tests and acceptance gates

Required local + GitHub Actions CI:
- Registry/schema/JSON/YAML lint; stable model reference resolver; broken links and missing obligation IDs rejected.
- S0 7-span legacy replay must still work.
- S1 nominal test for 1, 3 and 100 journeys with **exact** counts per transaction, correct values, correlation, expected metrics and NFRs.
- Parallel runs do not cross-contaminate results.
- All M01–M17 faults are reproducible and detected or classified as INCONCLUSIVE for justified pipeline degradation.
- An intentionally incorrect oracle is rejected by positive/negative controls (self-test).
- Exact aggregate event count cannot hide a per-transaction missing/duplicate pair.
- An unsampled/unsent span is NOT silently classified as business non-execution.
- A failed check exits nonzero at CLI and marks GitHub Actions red. `RESULT: CHECK` with process exit 0 is forbidden for a failing gate.
- CI forbids secrets / actual PII in synthetic payload and report. A privacy fault report must redact the injected value.
- Evidence tampering test modifies one byte → bundle verifier detects corruption.
- Offline replay reproduces verdict without querying live Grafana.
- Performance: 100 journeys must run within the Codespace's documented resource limits; record actual benchmark, do not invent a time target.
- Versions pinned; dependencies auditable; synthetic fixtures and CI reproducible after Codespace restart.

For each test record: intended falsification target, oracle check IDs, expected verdict, actual verdict, evidence path and independent review result.

**Definition of Done:** a human reviewer can reproduce baseline, one 100-journey run, a duplicate injection and a latency violation by invoking documented commands in a clean Codespace branch; open Grafana, inspect TX-017, inspect the exact failed check and rerun offline verification. No manual copying of invisible IDs needed.

---

## 14. Demonstration script (12–15 minutes, with fallback)

1. **00:00–01:30 — Specification:** Show F-07 + NF requirement; activity diagram, the two or three critical verification obligations and telemetry contract. Make traceability IDs visible.
2. **01:30–03:00 — Baseline:** Show existing 7-span S0 fixture and explicitly explain what it does NOT validate.
3. **03:00–05:30 — Nominal S1:** Generate 100 synthetic transactions with fixed seed. Show truth 100, expected/observed per-step counts, example `3 required events × 100 = 300`, all check IDs, functional and NFR statuses.
4. **05:30–07:00 — Live telemetry:** Open one selected transaction in Grafana/Tempo; inspect span tree/links, structured events/logs, correct resource attributes, correlation; show histogram metrics and optional exemplar. State ingestion delay and optional sampling clearly.
5. **07:00–09:00 — Duplicate mutation:** Duplicate a logical assignment event on TX-017 while keeping immutable approved expected reference. Show 101 logical assignment events for 100 transactions, and **TX-017=2 while expected=1**, violated obligation and precise evidence reference. Show that aggregate event count alone is insufficient.
6. **09:00–10:30 — Missing signal:** Delete a mandatory event. Show OBS/evidence classification and explain why missing telemetry alone does not prove the business step never ran.
7. **10:30–12:00 — NFR mutation:** Inject a late stage over the configured latency budget; show exact synthetic timing and the NFR verdict, plus metric estimate clearly labeled.
8. **12:00–14:00 — Evidence and replay:** Inspect `verdict.json`, `coverage.json`, hashes, Grafana deep links. Re-evaluate offline and demonstrate the same check IDs/verdict.
9. **14:00–15:00 — Scope/next step:** S1 proves verification pipeline and oracle sensitivity under simulation; S2 requires actual MOSIP instrumentation, independently collected API/DB/audit evidence and deployment constraints.

Prepare cached baseline and failure evidence in case Codespaces/Grafana is temporarily unavailable; label archival demos as prerecorded, never "live".

---

## 15. Presentation changes (keep the existing 36-slide story)

Review original `Observability-First Evidence-Based Testing V4` (36 slides). Do not delete its purpose or undermine its architecture. Explicit edits:

- **Slide 1:** make version V5, subtitle "Model → obligation → oracle → observable evidence" and realistic simulation scope.
- **Slides 6–10:** distinguish semantic registry from behavioral verification contracts, annotate which statements are normatively guaranteed and which remain targets.
- **Slide 7:** add stable IDs and `verification obligations` between use case/activity and oracle, including UML/OCL option; DMN only where decision tables apply.
- **Slides 13 and 16:** distinguish specification validation, execution/evidence collection, oracle evaluation, qualified proof; do not suggest no manual review in every context.
- **Slides 24–28:** update model/sequence/signal examples with actual contract IDs, version and observed-vs-expected representation.
- **Slide 30:** keep legacy 7-span demonstration but identify as S0.
- **Slide 32:** add where semantic Weaver live-check is placed and where actual oracle logic runs.
- **Slide 33:** replace or clearly relabel illustrative numbers; introduce per-axis verdict/coverage and evidence sufficiency.
- **Slides 35–36:** show common enterprise `oaef.*` registry and graduated scope S0/S1/S2.
- **Add 5–7 slides AFTER slide 36**:
  A. Architecture V5 (source model/requirements → registry/obligation → generator → OTel → oracle → report);
  B. 1/3/100 nominal: exact event counts, per-transaction validation and representative screenshot;
  C. Fault matrix and the explicit three fault layers;
  D. Nominal vs duplicate: expected 100 vs observed 101, TX-017 1 vs 2, violated contract;
  E. NFR and metrics: ledger vs metric stream, latency breach, exemplar only if sampled;
  F. Evidence/coverage/INCONCLUSIVE taxonomy and honest simulation boundary;
  G. Codespace reproducibility (commands, repo link, environment version, next S2 milestone).

**Every slide with empirical claims must link to a real run ID/evidence path** or show a prominent "illustrative" label. No invented screenshots or timings. Provide editable PowerPoint in addition to diagrams/text if the original deck can be repaired; use its layout and colors. Source to repository and document which slides were regenerated.

---

## 16. Specification and VTS changes

Produce a reviewed addendum `docs/oaef/OAEF-V5-MODEL-TO-EVIDENCE-ADDENDUM.md` **as the immediate text source**, mapping requested changes to:
- `OAEF-SPEC-001`: scope and modes S0/S1/S2; model element IDs and obligation contract; semconv registry governance; synthetic simulation & separation of truth; exact count semantics; OTLP normalization; joins and causality; evidence sufficiency; metric interpretation; multi-axis verdict and independent offline replay; security.
- `OAEF-VTS-001`: TP-1 remains legacy S0; expand TP-3 mutation framework; include V5 tests for 1/3/100, per-transaction exactness, duplicate, missing event, wrong value, break correlation, NFR, metrics, lost pipeline, privacy, concurrency, artifact integrity and reproducibility.
- `docs/wp0-shared-platform-requirements.md`: identify incremental WP dependencies only; do not claim all future WP0 requirements are implemented.
- `observability/attribute-model.md`: derive from Weaver registry where practical; keep migration notes.
- UML/PlantUML/draw.io: minimally add IDs, semantic mapping and genuinely required expected events; no unsupported "formal proof" claim.

If regenerating DOCX/PDF through PowerShell/HTML is feasible, modify canonical sources under `docs/oaef/src/` and regenerate; if not, retain existing binary documents and clearly label the V5 addendum as **proposed, not yet merged into the official spec**. Do not edit a PDF screenshot and call the source synchronized.

---

## 17. Implementation milestones — small, reviewable PRs

**PR-0 baseline assessment and preservation**
- Inventory repo/current Codespace, verify stack, versions, exact existing behavior. Archive S0 healthy evidence (no secrets). Pin tool versions, fix dangerous credentials/exit codes without breaking S0.
- Gate: clean restart + existing replay/check executable; baseline report with known gaps.

**PR-1 traceability and registry**
- Define obligation IDs, version and schema validation, missing-reference checking, `oaef.*` semconv registry and selected conformance checks.
- Gate: references resolve, Weaver syntax genuinely runs in CI, intentional schema violation fails.

**PR-2 synthetic generator and 1/3/100 nominal**
- Independent contract/reference and actual ledgers, flow/state machine, deterministic seed, OTLP exported, run ID isolation, time boundaries, 100 journeys and a meaningful diagram.
- Gate: exact per-transaction and aggregate counts, correct link/correlation/schema, 100 reproducible runs, no oracle yet claimed beyond implemented checks.

**PR-3 oracle engine, evidence collection and reports**
- Normalization, actual matching engine, expected/actual, per-axis verdict, Grafana deep links, offline evidence bundle and SHA256 verifier.
- Gate: deliberately incorrect collected payload fails with nonzero exit; stored bundle reproduces verdict.

**PR-4 mutation suite and NFR**
- M01–M17 (or a clearly identified documented subset first), exact metrics/NFR reconciliation, collection-health ambiguity, mutation sensitivity.
- Gate: minimum duplicate, missing, bad value, broken link, slow stage, metric mismatch and pipeline failure all demonstrate expected verdicts; then expand matrix before calling V5 complete.

**PR-5 documentation, presentation, Codespaces**
- Update runbook, V5 addendum, VTS, slides, screenshots from real runs, CI badge and quickstart.
- Gate: an independent reviewer follows only the README in a fresh Codespace and reproduces three negative examples.

**No automatic merge to main:** changes to a shared demo/specification should go through reviewable PRs with actual output, code diffs and limitations.

---

## 18. Codespaces: use existing instance; do not assume remote access

Do NOT claim direct access to a user's already-running Codespace unless such access is verified. GitHub commits do **not** automatically propagate into an open Codespace working tree.

In the **existing Codespace**, first run:
~~~bash
pwd
git status --short --branch
git remote -v
docker compose -f validation/demo/docker-compose.yml ps
docker compose -f validation/demo/docker-compose.yml config --images
python3 --version
~~~
Save outputs to the run evidence (redact credentials). **Never reset/discard uncommitted local work.**

Then, if the user or Claude has confirmed the correct branch and a clean tree:
~~~bash
git fetch origin
git switch docs/oaef-v5-model-to-evidence-demo
# later, on reviewed implementation branches:
# git pull --ff-only
~~~
If there are local changes, stash/commit on a separate work branch only after inspection. The Codespace is a development machine, **not** an archival store; Git history and selected sanitized evidence must be pushed to GitHub; large/high-cardinality evidence should be a versioned CI artifact or managed object store rather than committed as giant JSON files.

Port 3000 (Grafana) and OTLP 4318 forwarded **Private**; no secrets in Git, terminal logs, screenshots or public artifacts. Use a secret for Grafana admin credentials and pin a known-working image/digest. Confirm Codespaces resource quota before a 100-transaction demo.

---

## 19. CI evidence and GitHub archiving

Add a workflow such as `.github/workflows/oaef-demo-validation.yml` with:
1. checkout and dependency/tool versions pinned;
2. model/registry/oracle validation;
3. quick nominal 1/3 and complete 100 synthetic run, with timeout and cleanup;
4. mutation regression suite;
5. evidence integrity check;
6. upload selected scrubbed baseline/mutant verdicts and small, complete sample bundle as build artifacts;
7. summary containing run IDs, coverage denominators, detected mutant counts and links;
8. failure on unexpected PASS of a mutant or unexpected failure of nominal.

Commit small contract, test code, documentation and deterministic fixtures. Store sampled evidence with hashes in `examples/evidence/` only when size/privacy permit. Do not commit ephemeral Grafana stores, full 100-run heavy span dump by default, access tokens, real RID/NIN or actual operator personal information.

Use pull requests for review and explicit milestone labels. Add a machine-readable `implementation-status.md` detailing what was actually run (vs planned), environment, output and GitHub Actions checks.

---

## 20. Independent challenge questions — Claude must answer with evidence

**Challenge C1 — Model fidelity.** Does the synthetic NIN journey preserve the real modeled business semantics, or does it just emit pleasing spans? Where can a business defect be observed independently of telemetry?

**C2 — Exactly-once.** What identity defines a unique business effect, a unique event and a unique transport record? Is the demo correctly treating retries/idempotency, not falsely assuming exactly-once OTLP?

**C3 — Semantic truth.** Does `oaef.*` reuse OTel official definitions without misleading labels like `cloud.region=dc1`? Are EventName/semconv version differences pinned?

**C4 — Completeness.** How can the oracle prove a run is complete if sampling, packet loss, delayed export or unknown upstream work exists? Which failures must remain INCONCLUSIVE?

**C5 — Metric validity.** Are increments tied to isolated measurements, not extrapolated PromQL samples? Can p95 assertions be meaningfully demonstrated on 100 synthetic observations?

**C6 — Sensitivity & false positives.** Do all injected mutants get caught by the right checks, without changing the expected reference or relying on fault metadata? Does the nominal run stay PASS with one or multiple test executions?

**C7 — Time & ordering.** Are comparisons using consistent clocks, partial-order constraints and allowed skew? Are asynchronous spans correctly linked?

**C8 — Evidence chain.** Can an unrelated reviewer independently re-evaluate from the sealed local bundle? Is the signature/WORM claim restrained to actual implemented controls?

**C9 — Cost & maintainability.** Does the new OCL/DMN/Weaver layer simplify verification enough to justify overhead? Are data and rules single-sourced? Which generated artifacts replace manually duplicated prose?

**C10 — Security.** Does the new public GitHub/Codespace demonstration contain only synthetic data, with private ports, secret-free fixtures and controlled cardinality?

**C11 — Generality.** Can another IN Groupe solution reuse `oaef.*` and obligation/oracle formats without importing MOSIP-specific state names?

**C12 — Acceptance.** Show a failed test that would previously have passed under `>=7 spans / >=1 log`. Give its check ID, actual evidence and repaired outcome.

Claude must issue an **ADR** for every material trade-off (e.g. OCL vs YAML DSL, OPA/Rego vs Python matcher, raw OTLP vs backend query, event identity) and record rejected alternatives.

---

## 21. Outputs and reporting format to the requester

Deliver all of the following, with links to real paths:
1. `docs/oaef/OAEF-V5-MODEL-TO-EVIDENCE-ADDENDUM.md` — spec delta and normative terms.
2. `docs/oaef/OAEF-V5-REVIEW-AND-DECISIONS.md` — challenges, contradictions, ADRs, assumptions and residual risks.
3. Executable generator, fault injectors, oracle, collector adapters, CI tests and pinned runbook.
4. `docs/demo/OAEF-V5-LIVE-DEMO-RUNBOOK.md` — exact commands, sample outputs, Grafana links and failure recovery.
5. One **real** S1 nominal-100 bundle plus M02 duplicate and M09 NFR bundles; each has explicit run IDs, manifest, verdict and coverage. If execution is blocked, state blockers, do not fabricate.
6. Updated slide deck V5 (preserve editable visuals) and slide-to-evidence mapping.
7. GitHub branch/PR URL, CI status, actual CodeSpace instructions and clear distinction between code pushed and code running.
8. A concise table: **implemented / tested / demonstrated / only specified / blocked**.
9. A five-minute stakeholder summary and a technical appendix with commands, model mappings and coverage equations.

**Required Claude working rhythm:** (a) inspect and review, (b) list decisions and minimal architecture, (c) implement incrementally, (d) execute negative and positive tests, (e) capture evidence, (f) update slides/spec, (g) open PR. Do not declare completion before the gates pass. If blocked, deliver tested partial results, exact blocker and next action.

---

## 22. Success criteria for the sponsor

The demonstrator is ready for a serious architecture review when a stakeholder can observe and independently verify all of these claims:

- The same approved specification drives a nominal and an intentionally faulty run, without moving the acceptance criteria.
- Running 100 journeys produces traceable expected logical effects, not merely a dramatic graph of 100x copied OTLP payloads.
- Exact counts are checked per transaction, not just overall; a duplicate of one of three required events is detected and explained.
- NFRs are checked as actual declared constraints; metrics are cross-checked with reference measurements rather than assumed to prove individual transactions.
- Grafana makes investigation intuitive, but deterministic offline oracle reports determine pass/fail.
- A missing signal may indicate a product defect, instrumentation defect or insufficient evidence; the classification does not overclaim.
- The evidence is reproducible, integrity-checkable and traceable back to models, requirements, versions and injected faults.
- The same design is positioned for eventual use on a genuinely instrumented MOSIP/NIMS2 platform and reusable on other industrial solutions.

**Final guiding statement:** We are not demonstrating that OpenTelemetry can draw attractive traces. We are demonstrating that an engineering contract can be translated into falsifiable verification obligations, evaluated against observable execution, challenged by deliberate faults, and supported by reproducible evidence—with explicit epistemic limits.
