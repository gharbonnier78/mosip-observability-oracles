# OAEF review guide (v0.2)

**Review window:** [start] – [end] · **Feedback:** issues on this repository (templates provided) or comments in the Word documents · **Contact:** [name]

## What OAEF is, in three lines
Build observability and audit **before** the tests, with a signal contract every component meets. Derive **exact oracles** from use cases and business rules. Verify every run automatically against the oracle, seal the evidence, and classify each result into one of seven verdicts with its probable first source.

## What to read, by role (about 30–60 min)
| If you are… | Read | Look at closely |
|---|---|---|
| Test lead / tester | Deck slides 2–17, 27–33 | Verdict classes, oracle YAML, Cucumber scenario |
| Test automation / CI owner | Spec ch. 7, VTS ch. 5–6 | Execution lifecycle, evidence bundle, reporting, test-management export |
| Platform / DevOps | Spec ch. 3, 6; `observability/` | Collector configuration, tenancy, GitOps, capacity |
| Security / audit / DPO | Spec ch. 4.4, 9; requirements SEC-xx | PII controls, hashed NIN search, audit trail, evidence integrity |
| Project outside MOSIP | Deck 2–17; spec ch. 3–5 | What is generic and what is MOSIP-specific |

## Questions where your view matters most
1. **Verdicts.** Do the seven classes cover the test failures you see today? Which real failure would not fit?
2. **Oracle format.** Could a tester read and maintain `oracles/NIN-001.oracle.yaml`? What would make it easier (tooling, recording, templates)?
3. **Golden runs.** Is "record, review, freeze" acceptable for values that only a deployment can tell (audit codes, message texts)?
4. **Signal contract as Definition of Done** (DQ-02). Acceptable for your projects? What would it cost?
5. **Tooling.** Which existing tools must OAEF integrate with (test management, reporting, CI, observability stack already in place)?
6. **Naming.** Site = `cloud.region` (`dc1`, `dc2`), DR role = `oaef.site.role`, framework namespace `oaef.*`. Any conflict with existing conventions?
7. **Security.** Is a restricted, audited NIN-hash lookup acceptable for investigators? Anything missing for audit-trail integrity?
8. **Scope and phasing.** Is the WP0 split (foundation, instrumentation, test tooling, edges and multi-site) realistic? What should come first?
9. **Reuse.** What would prevent you from applying OAEF to a non-MOSIP project?

## How to give feedback
- One issue per point, using a template: **Review feedback**, **Requirement change**, or **Scenario proposal**.
- Reference the document and section (for example `OAEF-SPEC-001 §5.4, SEC-02`).
- Say what you would change, not only what is wrong.
- Severity: **blocking** (cannot accept as is), **important**, **minor**.

## Out of scope for this review
- MOSIP functional design itself.
- Exact capacity figures and retention durations (bracketed values, decided later — D5).
- Tool brand choices beyond the reference stack, unless they block adoption.

## What happens next
Feedback is triaged weekly; a synthesis and the decisions taken are shared at the end of the window, and the documents move to v0.3.
