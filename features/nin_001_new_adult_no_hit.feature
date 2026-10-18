# language: en
@TC-NIN @NIN-001 @regType-NEW @abis-NO_HIT @oracle:oracles/NIN-001.oracle.yaml
@persona:adult-nohit @env:env-nin-baseline @mosip-1.2.0.x
Feature: NIN issuance for a new adult resident with no deduplication hit
  As the identity authority
  I want a new adult resident with unique demographics and biometrics to receive a valid NIN (UIN)
  So that the resident can authenticate, and every processing step is provable by audit and telemetry evidence

  # Conventions
  #  - ${...} are variables captured during the run (stored in the evidence manifest).
  #  - Every step runs inside a Jarvis INTERNAL span "step: <step text>" child of the ROOT span.
  #  - "the oracle section X holds" = deterministic check of oracles/NIN-001.oracle.yaml#X
  #    against data fetched from Tempo / Loki / Mimir / audit / DB after the settle window.

  Background:
    Given the target environment "${cli.env}" is resolved from the environment configuration manager
      | variable      | example      | telemetry attribute          |
      | env.id        | ENV-000123   | oaef.env.id                  |
      | env.name      | test-int     | deployment.environment.name  |
      | env.site      | dc1          | cloud.region                 |
      | env.site_role | primary      | oaef.site.role               |
      | env.cluster   | dc1-k8s-test | k8s.cluster.name             |
    And the environment satisfies prerequisites "env-nin-baseline"
    And the collectors of cluster "${env.cluster}" stamp environment "${env.name}" and site "${env.site}"
    And the observability canary "OBS-01" is retrievable in Tempo within 60 seconds
    And the ABIS mock is configured in mode "NO_HIT"
    And Jarvis starts the ROOT span "NIN-001 New adult registration no hit" with baggage
      | key                  | value              |
      | cicd.pipeline.name   | ${ci.pipeline.name} |
      | cicd.pipeline.run.id | ${run.id}          |
      | test.suite.name      | TC-NIN             |
      | test.case.name       | NIN-001            |
    And Jarvis records metric baselines from oracle section "metrics.baseline"

  Scenario: New adult resident without demo or bio hit obtains a UIN, a VID, an IDA credential and a notification
    # ---------- A. data and packet ----------
    Given a resident generated from persona "adult-nohit" with seed "${run.id}:NIN-001"
    And the ID schema version "${schema.idVersion}" is captured from "GET /v1/syncdata/latestidschema"
    When Jarvis authenticates with "POST /v1/authmanager/authenticate/clientidsecretkey" for appId "regproc"
    Then the HTTP status is 200 and the response matches
      """json
      { "response": { "status": "Success", "message": "Clientid and Secret key successful" }, "errors": null }
      """
    When the packet creator builds a NEW packet for the resident at center "10001" machine "10001" by operator "110001"
    Then the RID matches "^[0-9]{29}$" and is captured as "${rid}"
    And the RID starts with "1000110001"

    # ---------- B. sync and upload ----------
    When Jarvis syncs the packet with "POST /registrationprocessor/v1/registrationstatus/sync"
      | field           | value                  |
      | registrationId  | ${rid}                 |
      | registrationType| NEW                    |
      | packetHashValue | ${packet.sha256.upper} |
      | packetSize      | ${packet.size}         |
      | supervisorStatus| APPROVED               |
      | langCode        | eng                    |
    Then the HTTP status is 200 and the response matches
      """json
      { "response": [ { "registrationId": "${rid}", "status": "SUCCESS" } ], "errors": null }
      """
    When Jarvis uploads "${rid}.zip" with "POST /registrationprocessor/v1/packetreceiver/registrationpackets"
    Then the HTTP status is 200 and "response.status" matches "(?i).*(PACKET_RECEIVED|RECEIVED).*"
    And the database row matches oracle section "db.regprc_registration_list"

    # ---------- C/D/E. asynchronous processing ----------
    When Jarvis polls "POST /registrationprocessor/v1/registrationstatus/search" for "${rid}" every 10 seconds up to 600 seconds
    Then the external status of "${rid}" is "PROCESSED"
    And the elapsed time from upload to "PROCESSED" is at most 600 seconds
    And the database rows match oracle section "db.regprc_transactions"
    And the UIN is captured from "GET /idrepository/v1/identity/idvid/${rid}?idType=RID&type=demo" as "${uin}"

    # ---------- F. functional oracle ----------
    Then "${uin}" satisfies oracle section "rules.uin"
    And the identity returned by "GET /idrepository/v1/identity/idvid/${uin}?type=all" satisfies oracle section "api.idrepo_read"
    And the identity JSON validates against ID schema "${schema.idVersion}"
    And every field listed in persona "derived_expectations.demographic_equality" equals the generated resident value
    And a perpetual VID exists for "${uin}" and satisfies oracle section "rules.vid" captured as "${vid}"
    And the database rows match oracle section "db.idrepo_and_kernel"
    And a credential request for partner "${ida.partnerId}" has status "ISSUED"
    And the mock SMTP inbox of "${resident.email}" contains one message matching oracle section "notification.uin_email"
    When Jarvis performs a demographic authentication with VID "${vid}" on "POST /idauthentication/v1/auth/${mispLK}/${ida.partnerId}/${ida.apiKey}"
    Then the response "response.authStatus" is true

    # ---------- evidence and signal oracle ----------
    When Jarvis ends all step spans and waits for the settle window from oracle section "settle"
    And Jarvis collects the evidence bundle for trace "${trace.root}" and rid "${rid}"
    Then oracle section "traces" holds
    And oracle section "logs" holds
    And oracle section "metrics.assertions" holds
    And oracle section "audit" holds
    And oracle section "nfr" holds
    And the signal-contract coverage is 100 percent
    And the verdict is "PASS" and is written to the ROOT span attribute "oaef.test.verdict"
