# Walkthrough session — agenda (45 min)

Audience: test community, plus invited reviewers (security / audit, platform / DevOps, a project outside MOSIP).
Goal: make the proposal understood, show it working, and start the review with the right questions.

| Time | Part | Content | Deck slides |
|---|---|---|---|
| 0:00 | Why (8 min) | The problem: a red test has three causes. Why signals must be designed first. The signal contract. | 2, 3, 6 |
| 0:08 | How (7 min) | From use case to oracle; anatomy of one step (state, message, state, signals); what a true oracle contains. | 7, 8, 10 |
| 0:15 | What it buys (5 min) | Three uses; seven verdict classes, each with an owner. | 11, 15 |
| 0:20 | Worked example (5 min) | NIN issuance: sequence, one NIN across journeys, observability and audit flow. | 24, 31, 32 |
| 0:25 | **Live demo (10 min)** | See the demo script below. | 33 (fallback if the demo fails) |
| 0:35 | Review launch (10 min) | How to review, targeted questions, timeline; open Q&A. | 17, 36 + review guide |

Slide numbers refer to the current 36-slide deck. Slides not shown stay available as backup for questions (layers 4–5, keys 9, uses 12–14, requirements 19–23, oracle walkthroughs 29–30, architecture 35).

## Demo script (simulation mode, no MOSIP needed)

Prerequisite: an observability stack reachable (local Docker, GitHub Codespaces, Grafana Cloud free tier, or the DEV platform), Python 3, the repository checked out. Setup, demo steps and rehearsal checklist: `validation/demo/README.md`.

1. **Replay NIN-001** with fresh identifiers and timestamps:
   `python3 validation/replay_nin001.py oracles/examples/NIN-001.otlp-example.json http://<agent>:4318`
   The script prints the new trace id.
2. **Show the trace** in Grafana Explore (Tempo): the span tree from the Jarvis ROOT span through the packet receiver, the Kafka hop and the stage consumer; point at `cloud.region`, `test.case.name`, `mosip.rid`.
3. **Jump to the log** of the packet-receiver span (trace-to-logs) and to the **metric exemplar** pointing at the same span.
4. **Show the oracle check by hand**: open `oracles/NIN-001.oracle.yaml` next to the trace and match one span template (name, kind, parent, attributes). Say clearly that the evidence collector and oracle engine are **not built yet** (WP0.3); the review should shape them.
5. Optional, once WP0.3 exists: run the evidence collector and oracle on the replay, then replay fault data set D3-c (error span) and show the verdict switch to PRODUCT BUG with its first source.

Fallback if the platform is not reachable: slides 30 (OTLP walkthrough), 31 (journey view) and 33 (report).

## Roles during the session
- Presenter: [name]
- Demo driver: [name]
- Note taker (captures questions as draft issues): [name]

## After the session (same day)
- Share recording, slides and links; open the review window.
- Create one issue per question raised in the session, labelled `review` and the area.
