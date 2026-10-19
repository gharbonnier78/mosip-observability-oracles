# Telemetry attribute model — environments, sites, test context

Goal: every trace, log and metric can be filtered by **test environment** and **site** (DC1, DC2/DRS…), with values coming from the **environment configuration manager** (the COTS source of truth), using **OpenTelemetry semantic conventions** wherever one exists.

> "Profiles" in OpenTelemetry is the name of the *profiling* signal (CPU/memory profiles). The standardized field names you are looking for are the **Semantic Conventions** (opentelemetry.io/docs/specs/semconv/), organised per domain/technology: *Resource* (service, deployment, k8s, host, cloud), *HTTP*, *Database*, *Messaging*, *CICD*, *Test*, … plus the **attribute naming rules** page. Many of the attributes below are still marked *Development* in semconv → **pin the semconv version** used by the agent, collector and oracles.

## 1. Principle: environment and site are *resource* attributes, not request headers

| Question | Answer |
|---|---|
| Where does "env / site" belong? | It describes **where the emitting process runs** → OTel **Resource** attributes. They are attached automatically to every span, log record and metric that process emits. |
| Must it travel in an HTTP header? | **No.** Each hop stamps its own env/site. A request DC1 → DC2 produces a parent span with `site=DC1` and a child span with `site=DC2`: the trace itself shows the crossing. A custom header would duplicate this and could be spoofed. |
| What *does* travel with the request? | Only **request-scoped** context, in standard **W3C headers**: `traceparent` (trace/span ids) and `baggage` (test run / test case). |
| Who is authoritative? | The **collector agent of each cluster** stamps env/site (an app cannot lie about where it runs). SDK / operator injection is a convenience, the collector `resource` processor enforces it. |

## 2. Attribute catalogue

### 2.1 Standard semantic conventions (use as-is)

| Attribute | Level | Example | Source | Semconv domain |
|---|---|---|---|---|
| `service.name` | resource | `regproc-pkr` | deployment name | Service |
| `service.namespace` | resource | `mosip` | platform | Service |
| `service.version` | resource | `1.2.0.1` | image tag | Service |
| `service.instance.id` | resource | pod UID | operator | Service |
| `deployment.environment.name` | resource | `test-int`, `test-perf`, `preprod`, `dr-test` | **env config manager** | Deployment |
| `k8s.cluster.name` | resource | `dc1-k8s-test` | **env config manager** | Kubernetes |
| `k8s.namespace.name`, `k8s.pod.name`, `k8s.node.name`, `k8s.deployment.name` | resource | — | k8sattributes processor | Kubernetes |
| `host.name` | resource | node name | resourcedetection | Host |
| `cloud.region` | resource | `dc1`, `dc2` (lower case, stable) | **env config manager** — physical site, see note below | Cloud |
| `cloud.availability_zone` | resource | `dc1-a`, `dc1-b` (hall / zone, optional) | env config manager | Cloud |
| `cicd.pipeline.name` | span (baggage) | `mosip-e2e-nightly` | CI | CICD |
| `cicd.pipeline.run.id` | span (baggage) | `run-20261018-001` | CI | CICD |
| `test.suite.name` | span (baggage) | `TC-NIN` | Jarvis | Test |
| `test.case.name` | span (baggage) | `NIN-001` | Jarvis | Test |
| `test.case.result.status` | ROOT span | `pass` / `fail` | Jarvis | Test |
| `test.suite.run.status` | suite span | `success`, `failure`, … | Jarvis | Test |

**Site = `cloud.region` (decision).** Semantic conventions have no "site" or "data centre" attribute. `cloud.region` is defined for cloud-provider regions; we reuse it for on-premises sites because it is standard, recognised by tools, and **indexed by default by Loki** for OTLP (no custom index label needed). Rules that keep this safe:
- Values are the **location only**: `dc1`, `dc2`. Never `drs` or `dr`: disaster recovery is a **role**, carried by `oaef.site.role` (`primary`, `dr`), which changes on failover while the location does not.
- `cloud.provider` is **not set** (its values are cloud vendors only).
- The collector site stamp is authoritative (upsert), so a cloud resource detector can never overwrite `cloud.region`.
- If a site is ever hosted by a cloud provider, this convention must be revisited.

**Migration from earlier drafts:** `oaef.site.name` → `cloud.region` (values lower-cased); `test.run.id` → `cicd.pipeline.run.id`; `test.case.id` → `test.case.name`; `test.suite` → `test.suite.name`. Never invent keys inside a namespace owned by semconv (`test.*`, `deployment.*`, `k8s.*` …): a future semconv release could define them differently.

### 2.2 No semconv exists → organisation namespace

Semconv naming rules: custom attributes must live in a namespace you own. **Decision (2026-10-18): `oaef.*`**, the namespace of the Observability and Audit Evidence Framework: neutral with respect to the organisation and the programme, so the framework can be reused. Business keys of the MOSIP domain keep `mosip.*`.

| Attribute | Level | Example | Source |
|---|---|---|---|
| `oaef.site.role` | resource | `primary`, `dr` | env config manager (changes on failover) |
| `oaef.env.id` | resource | CMDB CI id `ENV-000123` | env config manager |
| `oaef.env.config.version` | resource | snapshot id / hash of the env definition | env config sync job |
| `oaef.test.verdict` | ROOT span | `PASS`, `INFRA`, `PRODUCT_BUG`, … (richer than `test.case.result.status`) | Jarvis |
| `oaef.test.persona` | ROOT span | `adult-nohit` | Jarvis |
| `mosip.rid` | span + log | 29-digit RID | INST-01 extension |

### 2.3 Business event catalogue (WP0-SW-12)

OTel **Events** are log records with an `event.name` and typed attributes; they give the oracle a business timeline that does not depend on free-text log bodies. Rules: emitted **inside the producing span** (so `trace_id` / `span_id` are set), severity INFO, business keys only (`mosip.rid`, `mosip.uin_hash`), **never the UIN, VID or other PII**. The catalogue is versioned with this registry; CI lint rejects an unknown `event.name` (WP0-DQ-01).

| `event.name` | Emitted by (span) | Step | Attributes |
|---|---|---|---|
| `mosip.registration.packet.received` | regproc-pkr (`PKR_SERVER`) | B3 | `mosip.rid`, `mosip.reg_type` |
| `mosip.registration.stage.completed` | regproc stage (`STAGE_PROCESS`) | C1–C8 | `mosip.rid`, `mosip.stage`, `mosip.stage.status` (`SUCCESS`, `FAILED`, `REPROCESS`) |
| `mosip.identity.uin.assigned` | UIN generator stage | D1 | `mosip.rid` |
| `mosip.identity.activated` | idrepo-identity (`IDREPO_CREATE_SERVER`) | D2 | `mosip.rid`, `mosip.uin_hash` |
| `mosip.credential.issued` | credential batch job (trace T2) | E1–E5 | `mosip.uin_hash`, `mosip.request_id` |
| `mosip.notification.sent` | message sender | E7 | `mosip.rid`, `mosip.notification.channel` (`email`, `sms`) |

Audit events (WP0-SW-05) reuse these names, so one audit row ↔ one event ↔ one span. Durations between events give the business KPIs across traces (NF-04 RID → NIN, NF-05 notification delay).

### 2.4 Profiles (WP0-SW-13)

*Profiles* is the OTel profiling signal (CPU / memory samples per stack frame); it is not yet stable. Profiles carry the same resource attributes as the other signals (env, site, service) and `span_id` on samples, so the profile of a slow span can be opened from the trace. In OAEF they are **informative evidence** attached to the report when a span exceeds its budget; they never decide a verdict.

## 3. Flow of values: environment configuration manager → telemetry

```
Env configuration manager (COTS, source of truth: env, site, role, cluster, URLs)
        │  API export (on change + nightly)
        ▼
env-config-sync job ──► Git (GitOps repo) ──► Argo CD / Helm
        │                    ├─ namespace labels + annotations  resource.opentelemetry.io/<attr>
        │                    ├─ OTel Operator Instrumentation CR (spec.resource.resourceAttributes)
        │                    └─ collector agent config (resource processor, per cluster)  ◄─ authoritative stamp
        └──► nin-test-specs/prerequisites/<env>.yaml  (Jarvis: target env, site, endpoints)
```

## 4. What appears where (and how to filter)

| Backend | How env/site arrive | Filter example |
|---|---|---|
| Tempo | resource attributes on every span | TraceQL `{ resource.deployment.environment.name = "test-int" && resource.cloud.region = "dc2" }` |
| Loki | resource attributes → **index labels** for the default list (incl. `deployment.environment.name`, `k8s.cluster.name`, `cloud.region`, `service.name`, `k8s.namespace.name`); only the custom `oaef.site.role` must be added as index label (low cardinality) | `{deployment_environment_name="test-int", cloud_region="dc2", service_name="regproc-pkr"}` |
| Mimir / Prometheus | resource attributes go to `target_info` only, **unless promoted** to series labels | `http_server_request_duration_seconds_count{deployment_environment_name="test-int", cloud_region="dc1"}` |
| Grafana | dashboard variables `$env`, `$site` from label values; data links keep them | — |

Cardinality: env, site, role, cluster are low-cardinality (< 50 values) → safe as labels. `oaef.env.config.version` stays a resource attribute only (not a metric label).

## 5. DR / multi-site specifics

- Same `service.name` on both sites; the site is told apart by `cloud.region` + `k8s.cluster.name`.
- `oaef.site.role` flips on failover (`cloud.region=dc2`: `dr → primary`): the env config manager is updated by the failover runbook, the sync job re-stamps the collectors → evidence shows which site was primary at test time.
- Cross-site calls (replication, DR routing) appear as parent/child spans with different `cloud.region` — this is what DR test oracles assert (see NIN-080…082).
