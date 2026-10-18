# Test case catalog — NIN (UIN) issuance, MOSIP 1.2.x LTS

**Test case (business intent)** — *TC-NIN: "A resident registered at an enrolment center obtains a unique, valid NIN (UIN) usable for authentication, or is rejected for a deterministic, explained reason — and every step leaves the expected trace, log, metric and audit evidence."*

Each scenario below is a concrete, automatable instance of that intent. IDs are stable and used everywhere (Gherkin tags, oracle file names, evidence bucket paths, test-management keys).

Legend — **Expected end state**: `registration.status_code` in `mosip_regprc` / external status from `registrationstatus/search`. **Verdict class** = what the oracle must classify if the scenario behaves as designed.

## 1. Nominal issuance (NEW packets)

| ID | Scenario | Key data variation | ABIS response | Expected end state | Generated elements |
|---|---|---|---|---|---|
| **NIN-001** | New adult, demo + bio **no hit** | adult (≥ 18), all 10 fingers, 2 irises, face | IDENTIFY → 0 candidates | `PROCESSED` | UIN, perpetual VID, IDA credential, UIN notification |
| NIN-002 | New adult with biometric exception | 2 fingers marked exception + exception photo | 0 candidates | `PROCESSED` | as 001, exception recorded in CBEFF |
| NIN-003 | New child (< 5 y) with introducer | introducer UIN/RID, face only | 0 candidates (child: no bio dedupe per config) | `PROCESSED` | UIN, notification to guardian |
| NIN-004 | New resident, secondary language | second language data (e.g. `ara`/`fra`) | 0 | `PROCESSED` | notification in both languages |
| NIN-005 | Pre-registered resident | pre-registration ID + booking | 0 | `PROCESSED` | pre-reg status `CONSUMED` |

## 2. Deduplication outcomes

| ID | Scenario | Setup | Expected end state |
|---|---|---|---|
| NIN-010 | Demo dedupe **hit** → manual adjudication confirms duplicate | same name/DOB/gender as existing identity | `REJECTED`, no UIN consumed |
| NIN-011 | Demo dedupe hit → adjudicator says *not duplicate* | homonym, different biometrics | `PROCESSED`, UIN issued |
| NIN-012 | Bio dedupe **hit** (ABIS IDENTIFY returns candidate ≥ threshold) | biometrics re-used from existing identity | `REJECTED` (or manual adjudication per policy) |
| NIN-013 | ABIS INSERT failure | ABIS mock returns failure reason | `REPROCESS` then `FAILED` after retries |
| NIN-014 | ABIS timeout | ABIS mock does not reply | stage retry, `REPROCESS`; verdict INFRA if mock down |

## 3. Packet / sync validation failures (deterministic business rejections)

| ID | Scenario | Fault injected | Expected end state / API answer |
|---|---|---|---|
| NIN-020 | Upload without prior sync | skip `registrationstatus/sync` | packet receiver error (RID not synced) |
| NIN-021 | Hash mismatch | sync with wrong `packetHashValue` | packet receiver rejection, no landing-zone object |
| NIN-022 | Duplicate upload | upload same RID twice | 2nd call: duplicate-upload error, 1 registration row |
| NIN-023 | Inactive center | center `is_active=false` in masterdata | `REJECTED` at CMD validation |
| NIN-024 | Machine not mapped to center | broken center–machine mapping | `REJECTED` at CMD validation |
| NIN-025 | Operator not authorised / inactive | operator user inactive | `REJECTED` at operator validation |
| NIN-026 | ID-schema violation | mandatory field missing / wrong format | `REJECTED` at packet validation |
| NIN-027 | Missing mandatory document | POA absent for applicant type | `REJECTED` at packet validation |
| NIN-028 | Supervisor rejected on client | client status `REJECTED` | `REJECTED`, no further stages |
| NIN-029 | Low biometric quality | quality < threshold | per policy: `REJECTED` or tagged + manual verification |

## 4. Other registration types touching the NIN

| ID | Scenario | Expected |
|---|---|---|
| NIN-040 | UPDATE (demographic change of existing UIN) | same UIN, identity version updated, credential re-issued |
| NIN-041 | LOST (resident lost UIN) | ABIS IDENTIFY hit → existing UIN retrieved & notified, no new UIN |
| NIN-042 | RES_UPDATE via Resident service | same UIN, updated fields |
| NIN-043 | De-activate / re-activate UIN | status `DEACTIVATED` / `ACTIVATED`, IDA auth fails / succeeds |

## 5. Post-issuance use of the NIN

| ID | Scenario | Expected |
|---|---|---|
| NIN-050 | Demo auth with UIN | `authStatus=true` |
| NIN-051 | Demo auth with VID | `authStatus=true` |
| NIN-052 | Bio auth **match** (finger) | `authStatus=true` |
| NIN-053 | Bio auth **no match** (other finger) | `authStatus=false`, error `IDA-BIA-001` family |
| NIN-054 | OTP auth (OTP from mock SMTP/SMS) | `authStatus=true` |
| NIN-055 | Auth with revoked VID | `authStatus=false`, VID error |
| NIN-056 | Credential / print issuance | credential `ISSUED`, datashare reachable |

## 6. Resilience and infrastructure (expected verdict ≠ PRODUCT BUG)

| ID | Fault | Expected behaviour | Expected verdict class |
|---|---|---|---|
| NIN-070 | Kafka broker restart mid-flow | messages redelivered, `PROCESSED` within extended SLO | PASS (resilience) |
| NIN-071 | Keymanager unavailable during decrypt | `REPROCESS`, then success after recovery | PASS / INFRA if not recovered |
| NIN-072 | ID Repo DB unavailable | `REPROCESS`; UIN **not** double-consumed (UIN pool status consistent) | INFRA |
| NIN-073 | UIN pool exhausted | uin-generator failure, alert fired | TEST DATA / CONFIG |
| NIN-074 | Notifier/SMTP down | UIN still issued, notification failure recorded | PASS + notification defect |
| NIN-075 | Pod OOMKilled in regproc-group | message reprocessed | INFRA |

## 6b. Multi-site / disaster recovery (DC1 primary, DC2 = DRS)

Every scenario can run with `--env <env>@<site>`; site-specific expectations come from `observability/attribute-model.md`.

| ID | Scenario | Expected signals (env/site) | Expected verdict class |
|---|---|---|---|
| NIN-080 | NIN-001 executed against DC2 after planned failover | all MOSIP spans/logs/metrics carry `cloud.region=dc2`, `acme.site.role=primary`; none from DC1 | PASS |
| NIN-081 | Failover **during** processing (packet uploaded on DC1, stages finish on DC2) | trace T1 contains spans of both sites; first site change after the last DC1 stage; same RID, one UIN, no duplicate `UIN_GENERATOR` transaction | PASS (resilience) |
| NIN-082 | Data replication check DC1 → DC2 | identity readable on DC2 (`GET idvid/${uin}` with DC2 endpoint) within RPO; replication lag metric ≤ RPO | PASS / INFRA if RPO exceeded |
| NIN-083 | Mis-stamped collector (DC2 cluster labelled DC1) | env-manager vs collector drift detected by ENV-02 | ENV_NOT_READY (scenario not run) |

## 7. Observability / evidence negative tests (prove the oracle itself works)

| ID | Fault | Expected verdict class |
|---|---|---|
| NIN-090 | OTel collector gateway scaled to 0 during run | INCONCLUSIVE (pipeline failure) — never PASS |
| NIN-091 | Audit manager reachable but audit row missing (simulated) | PASS + OBSERVABILITY DEFECT |
| NIN-092 | Log export disabled on one service | PASS + OBSERVABILITY DEFECT (missing log contract items) |
| NIN-093 | Tail-sampling misconfigured (test traces dropped) | INCONCLUSIVE |

> Scenario **NIN-001** is fully specified in this repository: `features/nin_001_new_adult_no_hit.feature`, `oracles/NIN-001.oracle.yaml`, `data/personas/adult-nohit.persona.yaml`, `prerequisites/env-nin-baseline.yaml`.
