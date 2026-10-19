# OAEF live demo — runbook

Goal of the demo (10 min, see `docs/review/02-session-agenda.md`): replay the NIN-001 signals, then show in Grafana the span tree, the log of a span, the metric exemplar pointing to the same span, and match one span against the oracle. **No MOSIP needed.** Only synthetic data is used.

Choose one of three ways to run the stack. Free-tier conditions change: check the provider's current terms before relying on them.

| Variant | Where | Cost | Best for |
|---|---|---|---|
| A | Your laptop (Docker) | none | rehearsal |
| B | GitHub Codespaces (this repository) | free monthly quota on a personal account | reviewers replaying the demo |
| C | Grafana Cloud free tier | free tier | the live session (nothing to host) |

---

## A. Local (Docker Desktop or Docker Engine)

```bash
docker compose -f validation/demo/docker-compose.yml up -d      # first start can take 1-2 minutes
python3 validation/replay_nin001.py oracles/examples/NIN-001.otlp-example.json http://localhost:4318
```
Open http://localhost:3000 (user `admin`, password from `GF_ADMIN_PASSWORD`, default `change-me` — change it).

## B. GitHub Codespaces

1. On the repository page: **Code → Codespaces → Create codespace on main**. The dev container starts the stack automatically (`.devcontainer/devcontainer.json`).
2. In the codespace terminal:
   ```bash
   python3 validation/replay_nin001.py oracles/examples/NIN-001.otlp-example.json http://localhost:4318
   ```
3. Open the forwarded port **3000 (Grafana)** from the *Ports* tab. Keep the port visibility **Private**.
4. Stop the codespace after use to save the free quota; it also stops itself after inactivity.

## C. Grafana Cloud (free tier)

1. Create a free Grafana Cloud account and stack.
2. In the stack, open the **OpenTelemetry (OTLP)** connection page and note: the OTLP endpoint (`https://otlp-gateway-<zone>.grafana.net/otlp`), the **instance ID**, and create an **access token** with write scopes for metrics, logs and traces.
3. Replay with authentication (never commit the token):
   ```bash
   export OTEL_EXPORTER_OTLP_HEADERS="Authorization=Basic%20$(printf '%s:%s' '<instanceId>' '<token>' | base64 -w0)"
   python3 validation/replay_nin001.py oracles/examples/NIN-001.otlp-example.json https://otlp-gateway-<zone>.grafana.net/otlp
   ```
   PowerShell: `$env:OTEL_EXPORTER_OTLP_HEADERS = "Authorization=Basic%20" + [Convert]::ToBase64String([Text.Encoding]::ASCII.GetBytes("<instanceId>:<token>"))`
4. Open your stack's Grafana (Explore).

---

## Demo steps (all variants)

The script prints the **replayed trace id** and the **packet-receiver span id**. Copy both.

1. **Trace** — Explore → Tempo → query the trace id. Expected: 7 spans, root `NIN-001 New adult registration no hit` (service `jarvis-e2e`) → step → `POST` client → `POST /registrationprocessor/v1/packetreceiver/registrationpackets` (service `regproc-pkr`) → `INSERT mosip_regprc.registration` and `packet-receiver-bus-out publish` → `packet-receiver-bus-out process` (service `regproc-group1`). Show resource attributes `cloud.region=dc1`, `deployment.environment.name=test-int`, span attributes `test.case.name`, `mosip.rid`.
2. **Log** — from the packet-receiver span, *Logs for this span* (or Explore → Loki: `{service_name="regproc-pkr"} | trace_id="<trace id>"`). Expected: one INFO record with the RID in the body.
3. **Metric and exemplar** — Explore → Prometheus/Mimir: `http_server_request_duration_seconds_bucket{service_name="regproc-pkr"}` (label may be `job="mosip/regproc-pkr"` depending on the backend) with *Exemplars* on. Expected: an exemplar whose trace id is the replayed one.
4. **Oracle** — open `oracles/NIN-001.oracle.yaml` beside the trace; match `PKR_SERVER` (name, kind 2, parent = Jarvis client span, `http.response.status_code` 200, `mosip.rid`). Say clearly: the evidence collector and oracle engine are not built yet (WP0.3).

## Automated check

`bash validation/demo/check.sh` replays NIN-001 and verifies, through the Grafana API, that the trace has 7 spans, the packet-receiver log record exists and a metric exemplar points to the replayed trace. It ends with `RESULT: PASS`.

Last rehearsal: 2026-10-19, GitHub Codespaces (universal:2 image), `grafana/otel-lgtm:latest` with Grafana 13.2.3 — **PASS** (traces, logs, metrics HTTP 200; 7 spans; 1 log record; exemplar → trace). Pin that image version for the session.

## Rehearsal checklist (day before)

- [ ] Stack reachable from the demo machine and the meeting network (no VPN or proxy surprise).
- [ ] Image version pinned (`LGTM_VERSION`) and the same one rehearsed.
- [ ] Steps 1–3 work, including **trace → logs** and **exemplars** (the most fragile part; if a link is missing, configure it in the data source settings: Tempo *Trace to logs* → Loki filtered by trace id; Prometheus *Exemplars* → Tempo with label `trace_id`).
- [ ] One replay done just before the session, trace id noted, as a fallback.
- [ ] Fallback slides ready: 30 (OTLP walkthrough), 31 (NIN journey view), 33 (report).
- [ ] Demo driver is not the presenter; editor font enlarged; notifications muted.

## Security notes

- Grafana: no anonymous access; change the admin password; keep forwarded ports private.
- Never expose the OTLP ports to the internet without authentication.
- Tokens only in environment variables, never in the repository.
- Only the synthetic example data is replayed.
