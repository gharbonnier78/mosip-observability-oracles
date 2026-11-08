# OAEF V5 — S1 first executable vertical slice

**Status:** implemented and unit-tested locally, **not yet deployed in a Codespace**. This is deliberately a *three-milestone synthetic* subset of NIN-001, not the full MOSIP workflow or verification against NIMS2.

## Run

From the repository root, using only Python 3 standard library:

```bash
python3 -m unittest discover -s tests -v
python3 validation/v5_demo.py run --count 1 --out /tmp/oaef-1
python3 validation/v5_demo.py run --count 3 --out /tmp/oaef-3
python3 validation/v5_demo.py run --count 100 --out /tmp/oaef-100
python3 validation/v5_demo.py run --count 100 --fault duplicate --target 17 --out /tmp/oaef-duplicate
python3 validation/v5_demo.py run --count 100 --fault missing --target 17 --out /tmp/oaef-missing
python3 validation/v5_demo.py run --count 100 --fault wrong_value --target 17 --out /tmp/oaef-value
python3 validation/v5_demo.py run --count 100 --fault slow --target 17 --out /tmp/oaef-slow
python3 validation/v5_demo.py run --count 100 --fault metric_count --target 17 --out /tmp/oaef-metric
python3 validation/v5_demo.py verify --out /tmp/oaef-duplicate
```

The nominal command exits 0 and expected mutants exit 1. `verdict.json` contains exact failures. The three mandatory events are `packet.received`, `uin.assigned`, and `identity.activated`. Tests prove that aggregate 300/300 is inadequate when one transaction is missing an event and another has a duplicate.

To send *synthetic* OTLP JSON to the existing private Codespaces LGTM collector, add `--otlp http://localhost:4318`. **This only attempts emission; it is not proof of ingestion or a backend-scoped oracle**. After sending, inspect Grafana on the Codespaces private forwarded port 3000. Backend correlation and query integrity remain the next PR.

## Contract and validity

The independent frozen contract is `contracts/NIN-001-v5-slice.json`, containing references to F-07, F-08, NF-04, NF-08 and existing UML. The **2-second threshold is DEMO-ONLY** and does not replace the 24-hour NF-04 objective. The synthetic effect value is not a valid NIN/UIN. It intentionally avoids PII or real identity data.

`ledger.json` is simulated business truth, not external proof. `observed.json` contains locally generated OTLP payloads, not queried backend observations. The offline oracle is deterministic and does not read the injection type; the test harness verifies whether an intentionally injected fault is detected. Run IDs are deterministic from count and seed: in a shared backend, use a new seed per replay to avoid cross-run ambiguity.

### Known limitations / next PR

- No actual NIMS2 component is executed. Three selected milestones do not cover the full NIN-001 path, notification, asynchronous trace links, idempotency or cross-store audit.
- No live backend queries, collector drop/sampling controls, or independent API/DB evidence yet. A missing emitted event is a simulation contract failure; in real telemetry its *cause* might be inconclusive.
- The histogram is a single synthetic isolated batch. It must not be interpreted as real Prometheus scrape accounting, nor as a production latency SLO. The non-functional verdict is based on `ledger.json` durations in simulation.
- No Weaver semconv registry or OCL runtime in this increment; avoid using the words `formal proof`.
- No cryptographic evidence manifest or WORM. The current JSON outputs are diagnostic fixtures and can be edited.
- Next: implement backend-read oracle with collection health and ingestion settle; extend full real workflow; add bundle hashes, comparison report, model traceability and slides.
