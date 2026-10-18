# NIN enrolment and issuance — user journey specification (NIMS 2.0 on MOSIP 1.2)

Status: **draft for review**. Values in `[brackets]` and items marked **[A]** are assumptions based on common user-experience expectations and on conditions an enrolment network such as NIMS 2.0 in Nigeria can face (intermittent connectivity, power outages, multiple languages, high volumes). They must be confirmed by the contracting authority before they become binding.

Diagrams: [`nin-usecase.puml`](nin-usecase.puml), [`nin-enrolment-activity.puml`](nin-enrolment-activity.puml). Scenarios: [`../catalog/TC-NIN-scenarios.md`](../catalog/TC-NIN-scenarios.md).

## Actors

| Actor | Kind | Role in the journey |
|---|---|---|
| Resident applicant | human | Requests a NIN, provides data, documents and biometrics |
| Enrolment officer | human | Captures data at the enrolment station |
| Supervisor | human | Approves the enrolment before the RID slip is printed |
| Introducer | human | Parent or guardian vouching for a child applicant |
| Adjudicator | human | Resolves possible duplicates |
| Auditor / regulator | human | Consults the audit trail |
| Enrolment station | technical | Registration client, works offline |
| Central platform (MOSIP) | technical | Registration processor, ID generator, ID repository, credential, authentication |
| ABIS | technical (vendor) | Biometric deduplication |
| Messaging gateway | technical (provider) | SMS and email delivery |
| Relying party | technical (partner) | Bank, telco or agency verifying a NIN |

## User journey story (contractual form)

Ada, an adult resident, arrives at an enrolment centre with her documents. The enrolment officer captures her demographic data and supporting documents; every field is validated against the active ID schema and the reference data (locations, document types) **[F-01]**. The officer captures her ten fingerprints, two irises and face with certified devices; each modality passes a quality check, with at most three retries before the biometric-exception path is used **[F-02] [NF-02]**. The supervisor approves the enrolment and the station prints an acknowledgement slip carrying the Registration ID (RID); the whole station session takes at most `[15]` minutes for an adult without exception **[F-03] [NF-01]**.

The centre's network is down that afternoon. The station keeps the encrypted packet in a local queue for at least `[72]` hours, loses nothing, and uploads it automatically when the network returns **[NF-03]**.

The central platform verifies the packet's integrity and signature, checks that the centre, machine and operator were valid at the time of enrolment, and checks conformance to the ID schema; an invalid packet is rejected with a reason and the resident is informed **[F-04]**. Ada's demographics and biometrics are deduplicated against the national gallery through the ABIS **[F-05]**. A possible match would go to manual adjudication, and no NIN would be issued until it is resolved **[F-06]**; Ada has no match.

The platform assigns exactly one NIN — 11 digits with a check digit, consistent with the existing NIN format **[A]** — and one perpetual Virtual ID **[F-07]**. For a no-hit applicant, the time from packet upload to NIN assignment is at most `[24]` hours under normal load **[NF-04] [A]**. Her identity is activated and an authentication credential is issued to the verification partners **[F-08]**. Within `[15]` minutes of issuance she receives her NIN by SMS and email, in the language she chose (English, Hausa, Yoruba or Igbo **[A]**) **[F-09] [NF-05] [NF-09]**. A relying party (her bank) can then verify her NIN or VID **[F-11]**.

Every business step above produces an immutable audit event linked to the RID (and later to the NIN hash) **[F-10]**. Her personal data and identifiers never appear in clear in logs, traces or metrics, in line with the Nigeria Data Protection Act 2023 **[NF-07]**. Every step emits the traces, logs, metrics and audit events of the signal contract, tagged with environment and site **[NF-08]**. If the primary data centre fails, the secondary site takes over within the recovery objectives **[NF-06]**.

A child under five is enrolled with an introducer's identity instead of full biometrics **[F-12]**.

## Requirement register

| Tag | Requirement | Verified by (scenario) | Oracle section |
|---|---|---|---|
| F-01 | Demographics and documents validated against ID schema and reference data | NIN-001, NIN-026, NIN-027 | `api`, `db`, `rules` |
| F-02 | 10 fingers, 2 irises, face; quality check; exception path | NIN-001, NIN-002, NIN-029 | `api.idrepo_read.checks` |
| F-03 | Supervisor approval; RID slip issued | NIN-001, NIN-028 | `rules.rid` |
| F-04 | Packet integrity, CMD/operator validity, schema conformance; reject with reason | NIN-020…027 | `db.regprc_transactions` |
| F-05 | Demographic and biometric deduplication via ABIS | NIN-001, NIN-010…014 | `traces` (ABIS spans), `audit` |
| F-06 | Possible match → manual adjudication; no NIN until resolved | NIN-010, NIN-011, NIN-012 | `db`, `audit` |
| F-07 | Exactly one NIN (11 digits, check digit **[A]**) and one perpetual VID | NIN-001 | `rules.uin`, `rules.vid`, `db.idrepo_and_kernel` |
| F-08 | Identity activated; credential issued to verification partners | NIN-001, NIN-056 | `db`, trace T2 |
| F-09 | Notification by SMS and email in chosen language | NIN-001, NIN-004, NIN-074 | `notification` |
| F-10 | Immutable audit event per business step, linked to RID / NIN hash | all | `audit` |
| F-11 | Relying party verifies NIN or VID | NIN-050…055 | feature step (auth) |
| F-12 | Child under five enrolled with introducer | NIN-003 | — |
| NF-01 | Station session ≤ `[15]` min (adult, no exception) **[A]** | NIN-001 (station timing) | `nfr` (client spans) |
| NF-02 | ≤ 3 capture retries per modality **[A]** | NIN-002, NIN-029 | client spans |
| NF-03 | Offline ≥ `[72]` h, no loss, automatic sync **[A]** | NIN-070, offline variant of NIN-001 | `traces`, `db` |
| NF-04 | Upload → NIN ≤ `[24]` h (no hit, normal load) **[A]** | NIN-001 | `nfr.e2e_upload_to_processed_s` |
| NF-05 | Notification ≤ `[15]` min after issuance **[A]** | NIN-001 | `notification`, spans |
| NF-06 | DR: RPO ≤ `[15]` min, RTO ≤ `[4]` h **[A]** | NIN-080…082 | `traces` (site), `nfr` |
| NF-07 | No PII or identifier in clear in signals; audit immutable and access-controlled (NDPA 2023) | all | `logs.forbidden`, `nfr.security` |
| NF-08 | Signal contract 100 %, every signal tagged with environment and site | all, NIN-090…093 | `traces`, `logs`, `metrics`, `audit` |
| NF-09 | Languages: English, Hausa, Yoruba, Igbo **[A]** | NIN-004 | `notification` |

## Open points

- **NIN length**: MOSIP's default UIN length is 10; NIMS 2.0 is assumed to keep the existing 11-digit NIN. The oracle reads the length from the deployed `mosip.kernel.uin.length` and must be set accordingly.
- All bracketed figures are placeholders to be agreed; none is a measured value.
