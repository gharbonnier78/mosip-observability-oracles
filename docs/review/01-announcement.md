# Announcement (test community channel)

Two versions: short for chat channels, longer for email or newsletter. Replace every `[placeholder]`.

---

## Short version (Teams / Slack)

**🧪 Request for review: OAEF — Observability and Audit Evidence Framework (v0.2 draft)**

A red test in a distributed system has three possible causes: a product bug, the infrastructure, or missing evidence. Today we find out which by hand.

OAEF proposes to build observability and audit **before** the tests, and to verify every scenario against an **exact oracle**: expected API responses, data, business rules, traces, logs, metrics and audit events. Each run produces sealed evidence and an automatic verdict that names the probable first source of a failure.

Worked example: NIN issuance on MOSIP (NIMS 2.0).

📅 **Walkthrough + live demo:** [date, time, 45 min, link]
📝 **Review window:** [start] to [end] — comments as issues on [repository link]
📂 Deck, specification and validation plan: [links]

We especially want challenge from people who own CI pipelines, test reporting, security/audit, or projects outside MOSIP.

---

## Longer version (email / newsletter)

**Subject:** Request for review — Observability and Audit Evidence Framework (OAEF), walkthrough on [date]

Hello all,

When a test fails on a distributed platform, we usually spend the next day finding out whose problem it is: the product, the infrastructure, or simply missing evidence. As our systems grow (web and mobile front ends, offline stations, gateways, message brokers, two data centres), this gets worse.

**OAEF** is a proposal to change the order of work:

1. **Build the observability and audit layer first**, with a signal contract every component must meet (trace context, business keys, structured logs, audit events, metrics with exemplars, environment and site attributes based on OpenTelemetry semantic conventions).
2. **Derive exact oracles from use cases and business rules**: for each scenario step, the state before and after, the real messages exchanged, and the expected signals.
3. **Verify every run automatically**: sealed evidence bundle, seven verdict classes (pass, evidence gap, inconclusive, infrastructure, silent failure, test data/config, product bug), and a direct link to the trace for investigation.

The same specification also supports early report design (missing data shows up before delivery) and drift detection across releases.

The draft includes a complete worked example on MOSIP: NIN issuance for NIMS 2.0, from use case to Cucumber scenario, oracle, evidence and test report.

**What we are asking for**
- Join the 45-minute walkthrough and demo on **[date, time, link]**.
- Review the material between **[start]** and **[end]** and raise comments as issues on **[repository link]** (templates provided). A one-page review guide lists the questions where your view matters most.

**Material**
- Presentation: [link]
- OAEF-SPEC-001 — Framework specification (v0.2): [link]
- OAEF-VTS-001 — Validation test specification (v0.2): [link]
- Review guide: [link]

Status: working draft. Bracketed values are assumptions; nothing is decided that cannot be changed by good arguments.

Thanks in advance,
[Name]
[Role, team]
