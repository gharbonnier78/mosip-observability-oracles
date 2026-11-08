# OAEF V5 — specification → scenarios and oracles compiler (design, proposed)

**Status:** design for review; nothing below is implemented yet.
**Problem.** V5 executes a hand-written contract (`contracts/NIN-001-v5-slice.json`). Its content follows the specification, but it is not derived from it: the richer specification oracle `oracles/NIN-001.oracle.yaml` (REST, DB, notification, traces, logs, events, metrics M1–M5/ENV/X1, audit, NFR, verdict mapping) is not executed, and the 44 scenarios of `catalog/TC-NIN-scenarios.md` exist only as prose. Two sources of truth can drift.
**Goal.** One source: the specification. A compiler turns it into the scenarios and frozen oracles that V5 (S1 simulation) and later S2 (instrumented MOSIP) execute, with traceability from each check back to a requirement and a model element.

## 1. Inputs and outputs

| Input (specification) | Used for |
|---|---|
| `models/nin-requirements.md` (F-xx, NF-xx) | requirement ids attached to every obligation; coverage report |
| `models/nin-enrolment-activity.puml` (activity, branches) | enumeration of paths (nominal, dedupe hit, validation reject, …) and of the step sequence |
| `catalog/TC-NIN-scenarios.md` (44 scenarios, expected end state, verdict class) | scenario identity, data variation, expected outcome |
| `oracles/NIN-001.oracle.yaml` (base oracle) + one overlay per other scenario | the expectations: rules, api, db, notification, traces, logs, events, metrics, audit, nfr, verdict |
| `observability/attribute-model.md` (`oaef.*`, `mosip.*`, semconv) | attribute names, types, privacy class |
| `data/personas/*.yaml`, `prerequisites/*.yaml` | input data and environment preconditions |

| Output (generated, versioned, reviewed) | Content |
|---|---|
| `generated/contracts/<ID>.contract.json` | compiled, frozen oracle per scenario: expected REST exchanges, span tree, events, logs, **metric assertions**, audit, NFR, verdict mapping; each check carries `obligation_id`, `requirement_refs`, `model_element_refs` |
| `generated/features/<ID>.feature` | Gherkin scenario with the same step ids as the contract (`STEP-n`), tags `@<ID>` (and the Xray Test key when known) |
| `generated/coverage.json` / `coverage.html` | requirements × scenarios × check families; uncovered requirements and model branches listed |
| `generated/sim/<ID>.behaviour.json` | what the S1 simulator must *do* for this scenario (path through the activity model, data), built from the model and persona, **not** from the oracle, so simulator and oracle stay independent |

## 2. How scenarios are generated

1. **Paths from the model.** The activity model's decisions (dedupe hit/no hit, validation OK/KO, adjudication yes/no, child/adult, …) are enumerated into paths. Each path is mapped to catalogue scenario ids; a path with no scenario, or a scenario with no path, is reported (coverage).
2. **Variants from the catalogue.** For each catalogue row: base oracle of its family (NIN-001 for nominal NEW) ⊕ an overlay that states only what changes (end state `REJECTED`, `mosip.identity.uin.assigned` expected **0** times, extra audit module, metric deltas, error spans…). Overlays are small, reviewed YAML files; the compiler merges and validates them.
3. **Cross-cutting variants.** Site (DC1/DC2, failover — NIN-080..083), pipeline faults (NIN-090..093), injected telemetry faults (the current M01–M17 matrix) are applied as generic transformations, not hand-written per scenario.
4. **Human approval.** Generated contracts are committed and reviewed like code; `$golden` values are frozen from an approved run. A contract never changes during a run (already enforced by the manifest hash).

Fully automatic derivation from prose is not claimed: the compiler composes structured specifications (model, YAML oracle, overlays, catalogue table) and checks their consistency.

## 3. Oracle families in a compiled contract

| Family | From spec section | Evaluated in S1 (simulation) | Evaluated in S2 (MOSIP) |
|---|---|---|---|
| Functional rules (UIN/VID/RID format, Verhoeff) | `rules` | on simulated values | on real values |
| **REST** (request, status, body by matcher DSL `$re/$ref/$cap/$in`) | `api`, feature `Then` steps | simulator exposes the REST exchanges (recorded as spans + payload evidence) | real HTTP responses captured by Jarvis |
| DB / audit / notification | `db`, `audit`, `notification` | simulated stores | read-only SQL, Loki audit tenant, mock SMTP |
| Span tree, links, attributes | `traces` | yes (today: 17-span slice) | yes |
| Logs, business events, durations NF-04/NF-05 | `logs`, `events` | yes | yes |
| **Metrics**: per-service HTTP request metrics (M1–M3), span metrics (M4 audit calls, M5 errors), environment/site labels (ENV1/ENV2), exemplar link (X1), business counters | `metrics` | run-isolated series (as today) + baseline/delta semantics of the spec | baseline at t0 and t_end, deltas on shared or dedicated environments |
| NFR budgets, infra window checks | `nfr` | span budgets; infra checks NOT_APPLICABLE | yes |
| Verdict mapping (PASS, PASS_OBSERVABILITY_DEFECT, INCONCLUSIVE, INFRA, SILENT_FAILURE, TEST_DATA_CONFIG, PRODUCT_BUG) | `verdict` | yes, alongside today's diagnostic classes | yes |

Metrics therefore stay **specification-driven**: the contract says which metric must exist, with which labels, and by how much it must change for this scenario; the simulator (or MOSIP) only produces observations that are checked against it.

## 4. Increments

| Step | Content | Done when |
|---|---|---|
| **C1** | Compiler for NIN-001: `oracles/NIN-001.oracle.yaml` → `generated/contracts/NIN-001.contract.json` covering the families V5 already evaluates (span tree, events, metrics per service, NFR) + traceability ids; V5 runs on the compiled contract instead of the hand-written one | same verdicts as today on all fault cases; hand-written contract removed; a model/requirement change shows up as a contract diff |
| **C2** | REST layer: simulator records request/response for each exchange (synthetic bodies following MOSIP 1.2 API shapes); oracle evaluates `api` + `Then` steps with the matcher DSL | wrong status, wrong body field, missing response field each detected by a named check; report shows request/response per step |
| **C3** | Metrics section of the spec: baseline/delta (M1–M5), ENV1/ENV2 site labels, X1 exemplar | each assertion evaluated live; site mislabel fault detected |
| **C4** | Scenario generation: activity-model paths + catalogue + overlays → contracts and features for the nominal and dedupe families (NIN-001..005, 010..014) and validation rejects (020..029); coverage report | `coverage.html` lists requirements/branches without scenario; S1 runs all generated scenarios |
| **C5** | DB, audit and notification families (simulated stores in S1; real queries in S2) | audit/DB faults detected; ready for S2 |

## 5. Decisions needed

1. **YAML parsing.** The Python standard library has no YAML parser. Proposal: the compiler (a design-time tool) uses **PyYAML, pinned and hash-locked** in `requirements-compiler.txt`; the runtime (simulator, collector, oracle, reports) stays standard-library only and reads the compiled JSON. Alternative: keep the specification oracles in JSON (less readable for reviewers).
2. **Where generated files live.** Proposal: committed under `generated/` and reviewed in pull requests (diffs show every change of expectation), rather than produced at run time.
3. **Overlay format.** Proposal: YAML documents with the same section names as the base oracle, merged with explicit `$replace` / `$remove` markers, so a reviewer reads only the differences.
4. **Xray binding.** Generated features carry the scenario id tag (`@NIN-010`); once Xray Test keys exist, a mapping file adds the key tag (same mechanism as `OAEF_XRAY_TEST_KEYS`).
