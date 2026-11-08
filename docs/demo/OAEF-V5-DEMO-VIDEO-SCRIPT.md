# OAEF V5 — demo video script (narration and navigation)

**Purpose:** a 9-minute recorded walkthrough of one real campaign, from specification to sealed evidence. The video may be produced by a GenAI screen agent (e.g. Claude Cowork) or by a person; either way it follows **this script**, which is versioned here. The video illustrates; it is not evidence. Verdicts come from the sealed bundles.
**Audience:** programme stakeholders and test leads. **Language:** English, plain, no jargon without its meaning.
**Source of truth for figures:** the campaign recorded for the video (fill the run id below); reference values from run 42420471946 are given in brackets.

## 0. Preparation (not recorded)

| Item | Value |
|---|---|
| Environment | a Codespace on branch `docs/oaef-v5-model-to-evidence-demo` with the stack running (`bash validation/demo/start_stack.sh`), so Grafana links are live. Fallback: the CI campaign zip served locally (`python3 -m http.server` in the unzipped folder) plus the CI screenshots; then say "recorded run" and skip live Grafana scenes |
| Campaign | `bash validation/demo/run_v5_demo.sh tests s0 nominal duplicate missing slow broken_link missing_metric`, then `bash validation/demo/allure_report.sh`; note the run ids. Or CI: `gh workflow run oaef-v5-live.yml ... -f contract=spec` |
| Run id for the video | `[run id]` (reference: 42420471946) |
| Sign-in | the presenter signs in to GitHub and Grafana **before** recording. The agent never types a password; no password, token or Codespace URL secret appears on screen |
| Screen | 1600 × 1000 browser window, zoom 100 %, dark Grafana theme, notifications off |
| Tabs, in order | 1 GitHub repo (branch), 2 `oracles/NIN-001.oracle.yaml`, 3 `generated/contracts/NIN-001.contract.json`, 4 GitHub Actions run, 5 runs page `index.html`, 6 `duplicate/report.html`, 7 Grafana (signed in), 8 Allure |
| Rules for the narrator | say "synthetic S1 journey observed through real backends", never "MOSIP verified"; say the numbers on screen, not from memory |

## 1. Scenes

| # | Time | Screen and navigation | Narration (say) |
|---|---|---|---|
| 1 | 0:00–0:40 | Deck slide 40 (live run divider), then slide 41 (process) | "This is one real run of the OAEF demonstrator. A synthetic NIN-001 journey, a new adult with no deduplication hit, is observed through real Tempo, Loki and Prometheus. People write and review the specification; scripts do everything else, with no AI in the run path." |
| 2 | 0:40–1:40 | Tab 1 → `models/nin-requirements.md` (scroll the table), `models/nin-enrolment-activity.puml` | "The inputs are owned by people: the requirement register, functional F and non-functional NF, and the activity diagram with its lanes. Each activity carries the requirements it realises." |
| 3 | 1:40–2:30 | Tab 2 `oracles/NIN-001.oracle.yaml`: show `spans:` (one alias with parent, attributes, `requirements:`), then `events:` | "The oracle specification says exactly which spans, links, events and logs every transaction must leave, and which requirement each one proves." |
| 4 | 2:30–3:10 | Tab 3 compiled contract: search `"obligation_id"`, show one with `requirement_refs` and `model_element_refs`; then `generated/coverage.json` → `uncovered` | "A script compiles this into the executed contract: 60 obligations, each traced to its requirement and model element. CI fails if anyone edits the specification and forgets to recompile. Coverage shows three requirements without obligations for this scenario: F-11, F-12 and NF-02." |
| 5 | 3:10–3:50 | Tab 4 GitHub Actions run: steps list, expand "Run the demo cases" to the line `DEMO RESULT`; artifacts list | "The campaign runs in GitHub Actions with one command. Eight cases: nominal, and seven with one defect injected on transaction 17. Every case behaved as expected. Artifacts: reports, evidence and an offline zip." |
| 6 | 3:50–4:30 | Tab 5 runs page | "One line per case. Nominal passes. Duplicate, slow and broken link fail. Missing event and missing metric are inconclusive: an absent signal is an evidence gap, not proof of a product failure." |
| 7 | 4:30–5:40 | Tab 6 `duplicate/report.html`: summary counts; failed check; scroll to *Oracle versus observed*, row `OBL-EVENTS-EV_UIN_ASSIGNED` | "The duplicate run. 300 traces and 2,501 records were read back from the backends. The oracle evaluated 4,401 checks; one failed: transaction 17, the NIN-assigned event, expected once, observed twice. Requirement F-07, exactly one NIN. A test on totals would have passed." |
| 8 | 5:40–6:20 | Same report: click `events` on the failed check → Grafana Loki (tab 7) | "One click from the failed check to the business events of that transaction in Loki: 26 lines where the contract expects 25." |
| 9 | 6:20–7:00 | Back to the report: span tree with execution times; click the identity-creation row → Tempo | "The same transaction in Tempo: 42 spans over 15 services, with timings. The oracle checked every parent, kind, attribute and duration." |
| 10 | 7:00–7:40 | Grafana → Dashboards → OAEF → *Test runs*, then click a run id → *Journey* | "The verdicts are published back into Grafana. Operations and testers look at the same dashboards: runs by verdict, failures by class, and the journey of each run." |
| 11 | 7:40–8:10 | Tab 8 Allure overview → Categories | "Allure gives the campaign view; categories are the diagnostic classes. The same results can be imported into Xray." |
| 12 | 8:10–8:40 | Terminal (pre-typed): `python3 validation/v5_backend.py verify-bundle --out <duplicate>` then `re-evaluate` | "Every run is sealed with SHA-256. Anyone can verify the bundle and recompute the verdict offline. It must match." |
| 13 | 8:40–9:00 | Deck slide 52 (done / remains) | "What remains: REST messages and business rules, specification metrics, scenarios generated from the model, database and audit evidence, the full verdict classes, signed write-once storage, and finally the same oracle on an instrumented MOSIP platform." |

## 2. Recording rules for a GenAI screen agent

- Follow the scenes in order; do not improvise navigation or narration beyond small wording changes.
- Do not sign in, type credentials or accept prompts; stop and ask the presenter if a sign-in page appears.
- Do not open links outside this repository, its Actions run, the Codespace ports and the local report server.
- Pause 2 seconds on each figure the narrator quotes; zoom only with the browser's zoom, never by editing pages.
- If a number on screen differs from the bracketed reference, say the number on screen.
- Keep the raw recording and this script's commit id together; publish only after the presenter's review.
