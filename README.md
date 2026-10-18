# mosip-observability-oracles

Evidence-based E2E testing for MOSIP / NIMS 2.0: scenarios, Gherkin, OTel signal oracles, audit evidence, observability architecture and draw.io / PlantUML models.

Human-readable test cases, executable Cucumber scenarios and **deterministic oracles** (functional + OTel signals + audit) for the Jarvis test executor.

> Status: working draft. Values marked `[A]` or in `[brackets]` are assumptions; values marked `$golden` are frozen from a reviewed reference run. API paths and DB columns follow MOSIP 1.2.x and must be verified against the deployed release.

```
mosip-observability-oracles/
├── models/                                # use case + activity (PlantUML) and tagged requirement register (F-xx, NF-xx)
├── docs/diagrams/                         # draw.io: architecture, E2E flow, NIN sequence, expected signals, evidence/verdict, observability & audit flow
├── catalog/TC-NIN-scenarios.md            # test case -> scenario catalogue (human readable, IDs)
├── features/nin_001_new_adult_no_hit.feature   # Gherkin, one file per scenario (or per family)
├── oracles/
│   ├── NIN-001.oracle.yaml                # machine-checkable expectations (API, DB, rules, traces, logs, metrics, audit, NFR, verdict)
│   └── examples/NIN-001.otlp-example.json # exact OTLP/JSON shape of the expected signals (reference for implementers)
├── data/personas/adult-nohit.persona.yaml # data contract for the fake-data generator (MOSIP ID-schema compliant)
├── prerequisites/env-nin-baseline.yaml    # environment (resolved from the env configuration manager), masterdata, keys, partners, mocks, observability settings
├── observability/
│   ├── attribute-model.md                 # env / site / test attributes on OTel semantic conventions (+ acme.* where none exists)
│   ├── env-site-injection.yaml            # env manager -> namespace annotations, OTel Operator, collector site stamp
│   └── backends-env-site.yaml             # Loki index labels, Mimir resource-attribute promotion, Tempo columns, Grafana variables
└── (to add) schemas/*.schema.json         # JSON Schemas validating persona / oracle / prerequisites files in CI
```

## Where to store test scenario definitions — recommendation

**A dedicated Git repository (this layout), versioned and reviewed like code**, with a test-management tool only as an index.

| Option | Verdict | Why |
|---|---|---|
| **Git repo, plain text (Gherkin + YAML + JSON Schema)** | **Recommended (source of truth)** | Diff/review in PRs, history, branch per MOSIP release (`release/1.2.0.x`), CI validates files against schemas, Jarvis reads them directly, oracles evolve with the code that emits the signals. |
| Test management (Xray / Zephyr / TestRail) | Index + reporting only | Link by tag (`@NIN-001` ↔ Jira key). Import results (Cucumber JSON / JUnit). Never hand-edit oracles there: no schema, weak diff. |
| Confluence / Word / Excel | No | Not executable, drifts from reality, no validation. |
| Database | No for definitions; **yes for results** | Results, verdicts and evidence index go to a results store; evidence bundles to S3 WORM. |

Rules of thumb:
- **One scenario ID** (`NIN-001`) is the join key across feature tag, oracle file, persona usage, evidence path `s3://evidence-worm/<run>/NIN-001/`, Jira key.
- **Version oracles with the platform**: an oracle declares `mosip_release` and `otel_java_agent`. Upgrading either requires re-recording the golden run (below) and a reviewed PR.
- **Secrets never in the repo**: `vault:` references only.
- Branch protection + CODEOWNERS: functional owners review `features/` + `catalog/`, SRE/observability owners review `oracles/*#traces|logs|metrics|audit`.

## Golden-run workflow (how oracles become exact without guessing)

Some values are release- or deployment-specific (audit module ids, notification subject, exact stage codes, log scope names). They are marked `{$golden: true}`:

1. Run the scenario in **record mode** on a validated environment → Jarvis stores the full evidence bundle.
2. A reviewer inspects it (Grafana trace view + DB + audit) and approves it as **golden** (PR adding the run id to `metadata.golden_run` and freezing `$golden` values).
3. From then on every run is compared to the frozen oracle: deterministic pass/fail.

Everything that is defined by a standard (OTLP data model, semantic conventions, span kinds, status codes, ID formats, MOSIP API contracts) is written explicitly in the oracle, not golden.

## Oracle DSL

The engine converts every OTLP `KeyValue[]` into a map, normalises IDs to lowercase hex and int64 JSON strings to integers, then applies:

| Matcher | Meaning |
|---|---|
| literal (`200`, `"POST"`) | typed equality |
| `{$re: "..."}` | full-match regex (variables `${x}` are substituted and regex-escaped first) |
| `{$cap: name}` | capture value into the run variables (stored in `manifest.json`) |
| `{$ref: name}` | equals a captured / persona / prerequisite variable |
| `{$in: [..]}`, `{$gte: n}`, `{$lte: n}` | set membership / numeric bounds |
| `{$exists: true\|false}` | attribute presence / absence |
| `{$golden: true}` | equals the value frozen from the approved golden run |
| `parent: ALIAS` | `span.parentSpanId == ALIAS.spanId` |
| `parent_ancestor: ALIAS` | ALIAS is an ancestor (tolerates intermediate Hibernate / framework spans) |
| `parent_kind: 4` | parent span has this kind (e.g. consumer under producer) |
| `after: ALIAS` | `startTimeUnixNano >= ALIAS.endTimeUnixNano - 50 ms` |
| `count: {...}` | number of spans/records matching the template |
| `ordered_subsequence` | expected items appear in this order (other items allowed between) |

Each check produces `{check_id, status: pass|fail|error, expected, actual, evidence_ref}` in `verdict.json`; the signal-contract coverage = passed signal checks / total signal checks.

## Known gaps to close before automation (honest list)

The implementation requirements that close these gaps (software, infrastructure, security, test tooling, operations) are specified as work package WP0 in [`docs/wp0-shared-platform-requirements.md`](docs/wp0-shared-platform-requirements.md).

| ID | Gap | Impact | Fix |
|---|---|---|---|
| INST-01 | MOSIP services don't put the RID on spans | `mosip.rid` span matchers fail | Java agent extension or small Spring filter / AOP setting `Span.current().setAttribute("mosip.rid", rid)` + `MDC.put`; for logs a collector `transform` can extract the RID from the body. |
| INST-02 | Credential batch job (T2) and WebSub delivery (T3) start new traces | not reachable from ROOT | correlate on credential `requestId` (log attribute) or add span links in an extension |
| INST-03 | `app_audit_log` has no trace_id | audit ↔ trace link is time/host based | add trace_id into audit `description` or a custom column in the test fork |
| VER-01 | Exact column names, stage codes, ID Repo RID lookup (`idvid/{rid}?idType=RID`) differ between 1.2.0.x patches | false fails | verify against `db_scripts` + Swagger of the deployed version, then freeze via golden run |
| VER-02 | Span names / messaging attributes change with the Java agent version and semconv opt-in | false fails | pin agent version; regex matchers already tolerate route/context-path variants |
| ENV-01 | Shared environment: other traffic changes metric deltas | metric asserts use `$gte`, not exact | dedicated namespace per run gives exact deltas |
