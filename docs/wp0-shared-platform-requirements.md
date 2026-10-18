# WP0 — Shared observability, audit and evidence layer: implementation requirements

Status: **draft for review**. Scope: the shared layer that the **development, test (qualification) and in-house integration** platforms all rely on, so that every delivery of the other work packages can be developed, integrated and qualified with evidence (see the deck *Observability-First Evidence-Based Testing* and the oracles in this repository).

Conventions
- IDs: `WP0-<domain>-<nn>`. Domains: **SW** software, **INF** infrastructure, **SEC** security and privacy, **DQ** telemetry data quality, **TST** test tooling, **OPS** operations and governance.
- **Priority**: **M** must (blocks evidence-based qualification), **S** should, **C** could.
- **Acceptance**: each requirement has a verifiable criterion; most are checked automatically by the signal-contract and pipeline-health checks.
- `[brackets]` = value to agree; **[A]** = assumption. Nothing here is a measured figure.
- "Closes" refers to the gaps listed in the README (INST-01…03, VER-01/02, ENV-01) plus gaps found later (INST-04…07).

---

## 1. Platforms covered by WP0

| Platform | Purpose | Data | Telemetry sampling | Retention (traces / logs / metrics / audit / evidence) |
|---|---|---|---|---|
| **DEV** (shared) | Developer integration, early contract checks | Synthetic only | 100 % | [3 d] / [7 d] / [15 d] / [30 d] / — |
| **TEST / QUAL** | Qualification campaigns, oracles, golden runs | Synthetic only | 100 % for test traffic | [14 d] / [30 d] / [90 d] / [1 y] / [contract duration] |
| **INT** (in-house integration) | Integration with partner simulators (ABIS, SMS/email, relying parties) and real devices | Synthetic only | 100 % | as TEST |
| **PERF** [optional] | Load and soak tests | Synthetic only | tail-based, [10 %] + errors + all test-tagged | [7 d] / [14 d] / [90 d] / [90 d] / [90 d] |
| **DR-TEST** (DC1 + DC2) | Disaster recovery and multi-site tests | Synthetic only | 100 % | as TEST |

All platforms are registered in the **environment configuration manager** (COTS); it is the single source of environment and site identity (see `observability/attribute-model.md`).

---

## 2. Gap closure map

| Gap | Problem | Closed by |
|---|---|---|
| INST-01 | RID not on spans and logs | WP0-SW-02, WP0-SW-06 |
| INST-02 | Credential batch job and WebSub delivery start new traces | WP0-SW-03, WP0-SW-04 |
| INST-03 | Audit table has no trace id | WP0-SW-05 |
| INST-04 | No privacy-safe NIN key on IDA / resident / ID repo spans (journey search by NIN) | WP0-SW-02, WP0-SEC-02 |
| INST-05 | Offline registration station breaks the trace at sync | WP0-SW-08 |
| INST-06 | Web / mobile front ends do not start or propagate traces | WP0-SW-09 |
| INST-07 | Third-party partner calls (bank, telco, ABIS vendor) are opaque | WP0-SW-10, WP0-SEC-05 |
| VER-01 | DB columns, stage codes, API paths vary between MOSIP patches | WP0-SW-14, WP0-TST-04 |
| VER-02 | Span names and attributes vary with agent version and semconv | WP0-SW-01, WP0-DQ-01 |
| ENV-01 | Shared platform traffic makes metric deltas inexact | WP0-INF-09 |

---

## 3. Software requirements (MOSIP services, clients, tooling)

Principle: **extend, don't fork.** Prefer the OpenTelemetry Java agent, its extension mechanism and configuration; patch MOSIP code only where no other way exists, and propose those patches upstream.

| ID | Requirement | Pri | Acceptance | Closes |
|---|---|---|---|---|
| WP0-SW-01 | All MOSIP Java services run the **OpenTelemetry Java agent**, injected by the OTel Operator, **one pinned version per platform release**, with `OTEL_SEMCONV_STABILITY_OPT_IN=database`, propagators `tracecontext,baggage`, logs exported over OTLP, exemplars `trace_based`. | M | Every component in the inventory emits spans, metrics and logs with `service.name` = deployment name; the agent version is recorded in the evidence manifest. | VER-02 |
| WP0-SW-02 | A **MOSIP OTel agent extension** (one jar, versioned) sets business keys on the current span and in the logging MDC: `mosip.rid`, `mosip.uin_hash`, `mosip.vid_hash`, `mosip.request_id` (credential), `mosip.partner_id`, `mosip.reg_type`, `mosip.stage`. Keys are read from known request fields and from the regproc `MessageDTO`. **Never the UIN, VID or other PII in clear.** | M | Contract check: every regproc, ID repo, IDA, resident and credential span of a test journey carries the expected key; PII scan finds no clear identifier. | INST-01, INST-04 |
| WP0-SW-03 | **Context propagation through the regproc event bus** (Vert.x / Kafka) and ActiveMQ (ABIS) is verified; where the agent does not propagate, the extension injects and extracts `traceparent` / `baggage` in message headers. | M | For NIN-001, every stage consumer span is a descendant of the packet-receiver span (same trace). | INST-02 |
| WP0-SW-04 | **Span links for asynchronous breaks**: the credential request stores the originating `traceparent` (e.g. in its additional-info field) and the batch job starts its span with a **link** to it; WebSub callbacks carry the publisher's context in a header and IDA links to it. | S | Trace T2 / T3 of NIN-001 each have a span link resolvable to trace T1. | INST-02 |
| WP0-SW-05 | **Audit ↔ trace correlation**: the audit client library adds `trace_id` and `span_id` to each audit event (new nullable columns in `app_audit_log` or a structured field), and each audit event is also emitted as an OTLP log to the **audit tenant**. | M | For every audit row of a test journey, the oracle finds the producing span by id (no time/host heuristic). Audit counts in DB and audit tenant are equal. | INST-03 |
| WP0-SW-06 | **Structured JSON logs** (logback encoder) on all services: timestamp UTC, level, logger, message key, `trace_id`, `span_id`, MDC business keys; message bodies keep stable keys for oracle matching. | M | 100 % of log records emitted inside a span carry `trace_id` and `span_id`. | INST-01 |
| WP0-SW-07 | **Business metrics** with OTel naming and units: stage processed / failed / reprocessed per stage, UIN and VID pool levels, ABIS round-trip time, credential issuance time, notifications sent / failed, packets queued at stations. | S | Metrics exist with the agreed names and labels; dashboards and alert rules use them. | — |
| WP0-SW-08 | **Registration client (station)** instrumented with the OTel Java SDK: capture, quality, approval and sync spans; the `traceparent` of the enrolment is **stored with the encrypted packet** and restored by the packet receiver, so the journey survives offline periods; local telemetry buffer bounded to [N MB] and flushed on reconnect; station clock synchronised. | M | Offline variant of NIN-001: station spans and central spans share one trace id after a [72 h] offline window. | INST-05 |
| WP0-SW-09 | **Web and mobile front ends** (resident portal, admin portal, mobile apps): OTel browser / mobile SDK, user-action spans, `traceparent` on every API call (CORS allows `traceparent`, `tracestate`, `baggage`), consent-aware, no PII in attributes. | S | A resident-portal update journey (NIN-042) shows the browser span as root of the backend trace. | INST-06 |
| WP0-SW-10 | **Partner and gateway edge**: the ingress / API gateway creates a server span for every partner call, records `mosip.partner_id` and accepts an inbound `traceparent` from authorised partners only (remote parent); partner simulators in INT are instrumented. | S | Bank-auth scenario (NIN-050/051) shows partner id and remote parent on the first IDA span. | INST-07 |
| WP0-SW-11 | **Version and build manifest**: each service exposes build info (version, git commit, image digest) via actuator and resource attributes `service.version`, `vcs.ref.head.revision`. | M | Evidence manifest lists every component's version and digest for each run. | VER-01 |

## 4. Test tooling requirements (shared by all work packages)

| ID | Requirement | Pri | Acceptance |
|---|---|---|---|
| WP0-TST-01 | **Jarvis test executor**: OTel SDK, ROOT span per scenario, baggage `cicd.pipeline.run.id`, `test.suite.name`, `test.case.name`, step spans, results on the ROOT span (`test.case.result.status`, `acme.test.verdict`). | M | Every scenario run has exactly one ROOT span with these attributes. |
| WP0-TST-02 | **Evidence collector**: settle-window logic, queries to Tempo / Loki (app and audit tenants) / Mimir / read-only DB / business APIs / Kubernetes, manifest with exact queries, SHA-256 per file, signature, upload to the evidence bucket. | M | A verdict can be recomputed from the bundle alone (replay test). |
| WP0-TST-03 | **Oracle engine**: matcher language, JSON Schemas for oracle, persona and prerequisite files validated in CI, golden-run **record → review → freeze** workflow, verdict classification (7 classes). | M | CI rejects an invalid oracle; a golden run needs an approving review before use. |
| WP0-TST-04 | **Release-aware oracles**: oracles declare `mosip_release` and `otel_java_agent`; a platform upgrade triggers re-recording of golden runs and a reviewed diff. | M | Running an oracle against a non-matching release fails fast with ENV_NOT_READY. |
| WP0-TST-05 | **Synthetic data generator** compliant with the live ID schema and persona contracts (demographics, documents, ISO 19794 biometrics through mock MDS), deterministic by seed, uniqueness guaranteed against the gallery. | M | 1 000 generated residents validate against the ID schema; no ABIS hit unless requested. |
| WP0-TST-06 | **Mocks and simulators**, all instrumented: ABIS (NO_HIT, HIT, TIMEOUT, FAILURE), SMTP / SMS with a read API, relying-party simulator, WebSub subscriber. | M | Each mode is selectable per scenario through an API and visible in traces. |
| WP0-TST-07 | **Reporting**: Allure (or equivalent) with per-clause expected / actual / evidence file, probable first source, Grafana deep link; results pushed to the test-management tool by scenario tag. | S | Every failed check in the report links to an evidence file and a Grafana URL. |

## 5. Infrastructure requirements

| ID | Requirement | Pri | Acceptance |
|---|---|---|---|
| WP0-INF-01 | **Observability stack per site** (DC1, DC2): OTel Operator; collector **agent** (DaemonSet) and **gateway** (≥ 2 replicas, load-balancing exporter keyed on trace id for tail sampling); Tempo; Loki with tenants per platform class + **audit tenant**; Mimir; Grafana; Alertmanager. | M | Canary signal from every node retrievable in < [60 s] on each site. |
| WP0-INF-02 | **Object storage with object lock** (WORM) for audit tenant chunks and the **evidence bucket**, replicated DC1 → DC2. | M | Delete / overwrite attempts on locked objects fail; replica present on DC2. |
| WP0-INF-03 | **Tenancy and isolation**: tenants per platform class (dev, test, int, perf) plus audit; every signal carries `deployment.environment.name`, `k8s.cluster.name`, `acme.site.name`, stamped by the cluster collector. | M | ENV-02 / ENV-03 checks pass on every platform. |
| WP0-INF-04 | **Capacity**: ingest sized for [X] spans/s, [Y] log lines/s, [Z] active series per platform; load-tested before first campaign. | M | Collector refused / failed counters stay 0 at [1.5×] nominal load. |
| WP0-INF-05 | **Time synchronisation**: NTP / chrony on all nodes, stations and simulators, offset ≤ [50 ms]. | M | Offset metric alert below threshold; oracle skew tolerance never exceeded. |
| WP0-INF-06 | **Network**: OTLP endpoints internal only; dedicated ports and network policies; DC1 ↔ DC2 links monitored (latency, loss); synthetic probes. | M | Network policies tested; site-to-site probe metrics in Mimir. |
| WP0-INF-07 | **Environment configuration manager integration**: sync job from the COTS API to GitOps (namespace annotations, Instrumentation CR, collector stamp, Jarvis prerequisite files) with drift detection. | M | ENV-02 drift check runs before every campaign and on every change. |
| WP0-INF-08 | **Everything as code** (GitOps): collector configs, dashboards, alert rules, retention, tenants, oracles; changes by reviewed pull request. | M | No manual change in the cluster survives a sync. |
| WP0-INF-09 | **Ephemeral test namespaces** on demand: a MOSIP slice with pre-seeded masterdata, SoftHSM keys and partners, isolated from shared traffic, so metric deltas can be asserted exactly. | S | NIN-001 in an ephemeral namespace passes with exact (`==`) metric assertions. |
| WP0-INF-10 | **CI runners** for Jarvis on each platform with access to MOSIP endpoints, observability APIs and the evidence bucket only. | M | Runner network policy allows only these destinations. |
| WP0-INF-11 | **Backup and DR** of observability stores and evidence; DR test included in NIN-080…082. | S | Restore test documented; evidence readable from DC2 after DC1 loss. |

## 6. Security and privacy requirements

| ID | Requirement | Pri | Acceptance |
|---|---|---|---|
| WP0-SEC-01 | **No PII in telemetry**: deny-list (UIN, VID, names, phone, email, address, biometrics, document numbers) enforced at source (extension) **and** at the gateway (redaction / transform processors); continuous automated PII scan of traces and logs. | M | PII scan (oracle `logs.forbidden`, `nfr.security`) returns 0 on every run; a seeded PII string is caught by the scan (negative test). |
| WP0-SEC-02 | **Privacy-safe search keys**: `mosip.uin_hash` uses MOSIP's salted hash; the investigator query helper that hashes a typed NIN runs as a restricted service, and every lookup is itself audited (who, when, which hash). | M | Lookup audit records exist for each search; the salt is never exposed to browsers or test code. |
| WP0-SEC-03 | **Access control**: Grafana and observability APIs behind SSO (OIDC, e.g. Keycloak) with RBAC per platform and tenant; audit tenant readable by auditors only; Jarvis and evidence collector use read-only service accounts; DB access through read-only replicas and roles. | M | Access matrix tested; denied queries logged. |
| WP0-SEC-04 | **Transport and secrets**: TLS (mTLS inside the mesh) for OTLP and backend APIs; all credentials in a vault; nothing secret in repositories. | M | TLS enforced (plain-text connection refused); secret scan of repositories clean. |
| WP0-SEC-05 | **Baggage and context hygiene**: strip `baggage` (and optionally `traceparent`) on egress to third parties; accept inbound `traceparent` only from authorised partners; cap baggage size [8 KB]; never put PII or secrets in baggage. | M | Egress capture shows no baggage header to partner simulators. |
| WP0-SEC-06 | **Evidence integrity**: SHA-256 per file, bundle signature (Keymanager `jwtSign` or KMS / cosign), optional RFC 3161 timestamp, object lock for the retention period. | M | Tampering with one file makes the bundle verification fail. |
| WP0-SEC-07 | **Data protection compliance** (Nigeria Data Protection Act 2023 [A]): synthetic data only on DEV / TEST / INT / PERF; no production copy; DPIA of the observability platform; retention limits enforced. | M | DPIA approved; retention policies visible in configuration. |
| WP0-SEC-08 | **Supply chain**: pinned and signed images for agent, collector and backends; SBOM per release; vulnerability scanning in CI. | S | Unsigned image rejected by admission policy. |
| WP0-SEC-09 | **Classification and publication**: artefacts carry their classification; public repositories contain no environment URLs, hostnames, keys or real identifiers. | M | Pre-push scan on public repositories; manual review before making a repository public. |

## 7. Telemetry data-quality requirements

| ID | Requirement | Pri | Acceptance |
|---|---|---|---|
| WP0-DQ-01 | **Pinned semantic conventions** version and a published **attribute registry** (`observability/attribute-model.md`), including the organisation namespace (`acme.*` placeholder to be replaced). | M | Registry versioned; CI lint rejects unknown custom attributes. |
| WP0-DQ-02 | **Signal contract per component** checked in CI and in each platform: a delivery is not "done" until its contract passes. | M | Contract job part of every work package's Definition of Done. |
| WP0-DQ-03 | **Cardinality budget**: metric label whitelist (env, site, cluster, service, route, status); no IDs as metric labels. | M | Active series per service under [budget]. |
| WP0-DQ-04 | **Sampling policy** per platform (section 1), with test-tagged traffic always kept. | M | No test-tagged trace missing in Tempo (pipeline-health check). |

## 8. Operations and governance requirements

| ID | Requirement | Pri | Acceptance |
|---|---|---|---|
| WP0-OPS-01 | **Pipeline health SLOs**: collector receive / export failures, ingestion lag, canary freshness; a run during a breach is marked INCONCLUSIVE automatically. | M | Breach injected (NIN-090) → INCONCLUSIVE. |
| WP0-OPS-02 | **Provisioned dashboards and alerts**: platform health, MOSIP journey (per run), stage RED metrics, audit completeness, PII scan, DR. | S | Dashboards loaded from Git; alerts routed to the platform team. |
| WP0-OPS-03 | **Governance**: owners for the attribute registry, oracles (functional + observability review), golden-run approval, and the WP0 platform itself; change advisory for agent / semconv upgrades. | M | RACI published; upgrade checklist used. |
| WP0-OPS-04 | **Runbooks and support** during qualification campaigns: platform on-call, triage of INCONCLUSIVE and INFRA verdicts. | S | Runbooks in Git; support rota during campaigns. |
| WP0-OPS-05 | **Onboarding**: guide and training for work-package teams (how to instrument, how to write an oracle, how to read evidence). | S | Each team has run one scenario end to end. |

---

## 9. WP0 deliverables and phasing

| Phase | Content | Exit criterion |
|---|---|---|
| **WP0.1 Foundation** | INF-01…08, SEC-03/04, DQ-01, OPS-01 | Canary from every site and platform; drift check green |
| **WP0.2 Instrumentation** | SW-01…07, SW-11, SEC-01/02, DQ-02/03 | NIN-001 signal contract ≥ [95 %] on TEST |
| **WP0.3 Test tooling** | TST-01…07, SEC-06 | NIN-001 PASS with sealed, replayable evidence |
| **WP0.4 Edges and multi-site** | SW-08…10, SEC-05, INF-09…11, DR scenarios | Offline station, bank auth and DR scenarios (NIN-080…082) pass |

Dependency for other work packages: **passing the signal contract (WP0-DQ-02) is part of each delivery's Definition of Done** from WP0.2 onward.

## 10. Open decisions

1. Which environment configuration manager product, and who owns its records.
2. Tenant model: one shared stack with tenants per platform class (proposed) or one stack per platform.
3. MOSIP changes that cannot be done by extension (audit trace id columns, credential traceparent): local patch, fork policy, upstream contribution.
4. ABIS vendor: can it propagate `traceparent` through its queues, or is the boundary a span link only?
5. Organisation attribute namespace replacing `acme.*`.
6. Retention durations and capacity figures (all bracketed values).
7. Whether this repository stays public (see WP0-SEC-09).
