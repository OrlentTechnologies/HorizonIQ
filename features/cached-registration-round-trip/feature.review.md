# Cached registration round-trip review

Status: complete; orchestrator review passed. Final acceptance audit passed; no remaining gaps.

Reviewed 13 October 2026 against `C:/git/ha-integration` commit `04da1eb6c820eb784e4222ee9bad384755705f32`, version `2.0.79`. Evidence paths below are relative to the integration repository unless explicitly prefixed Solar.

Pass 1 checked the required behavior against actual HTTP entry points, source selection, parser, cache/persistence/reload flow, previous legacy behavior and existing tests. Pass 2 checked contract boundaries, exact file ownership, every stage/test reference, complete 42-method ledger, fixtures, failures, versioning and validation commands.

## Resolved review findings

1. The canonical plan intentionally drops credentials. Extract from the original payload only after successful plan parsing, into the existing private snapshot field; do not relax public-schema filtering.
2. Legacy registration coercion can serialize non-string values. The new schema-5/6 path accepts opaque strings only and ignores invalid metadata, while retaining the legacy path unchanged.
3. Existing hash round-trip tests omit registration. Require a flat-response, actual HTTP next-request test for both schemas and both fetch paths, with recorded failing baseline before the production fix.
4. Valid metadata without an optional direct-control model still needs caching. Name this case explicitly and do not tie credential acceptance to executable direct control.
5. Do not change shared fixture defaults: missing metadata remains accepted. List all existing named tests as retained and add targeted credential cases locally.

## Evidence matrix

| Area | Repository evidence | Plan location | Status | Finding/resolution |
|---|---|---|---|---|
| Contracts/operations: parsing | `coordinator_helpers.py:651–658,780–809` | Ownership and exact change steps 1–3 | checked | Only `_schema5_snapshot` changes; parse success precedes original-payload extraction. `test_schema56_registration_metadata_is_kept_private` covers both schemas and raw forms. |
| Contracts/operations: cache, storage, sending | `coordinator.py:134–155,249–284,569–633` | Ownership and exact change step 4 | checked | Both production fetch paths update the existing entry-local cache, actual entry, then later URL. Principal HTTP regression covers both paths; no new operation or parallel path. |
| Request/result properties: private metadata | `models.py:205–227`; `coordinator.py:197–199,608–615` | Metadata contract and failure boundaries | checked | Existing `registration_data: str \| None`; trim string; absent/invalid → None means keep old credential. Invalid-shape and keep-cached tests cover null, empty and other types. |
| Request/result properties: public and private authority | `forecast_schema5.py:74–116,424–453`; `coordinator_helpers.py:780–809,410–440` | Ownership steps 1–3 | checked | Public schema/direct forecast remains credential-free; private snapshot carries only transport metadata. No existing type replaced. Private-only helper and sensor/log regressions enforce separation. |
| Runtime/conversion: aliases, raw shapes | `coordinator_helpers.py:837–864,879–895` | Metadata contract table | checked | Flat and three wrapper spellings use existing source selection, envelope-first then selected forecast, first-present alias order. Precedence test covers conflicts, duplicates and invalid winners; no broad coercion. |
| Runtime/conversion: legacy and hash | `coordinator_helpers.py:666–677,813–835,1339–1348`; existing helper tests:478–568; coordinator hash test:215 | Ownership final paragraph; test ledger | checked | Do not change legacy coercion, envelope hash validation or those assertions. All 42 existing methods retained. New credential acceptance does not depend on a changed hash. |
| Runtime/failures: validation, stale and authorization | `forecast_schema5.py:489–549`; `coordinator.py:295–327,401–465,505–524,594–609` | Metadata contract failure rows | checked | Malformed plan retains existing Schema5ForecastError → UpdateFailed/stale mapping; unauthorized/HTTP failure cannot rotate metadata. Rejected-response regression asserts previous credential and no replacement. |
| Persistence/migration: write and reload | `coordinator.py:622–633,82–90`; `__init__.py:222–234`; `config_data.py:69` | Storage paragraph; complete file manifest | checked | Use existing CONF_REGISTRATION_DATA config-entry key; no storage/schema migration. Reload test gets value from real persisted entry; renewed-value test covers replacement with unchanged hash. |
| Persistence/migration: explicit clear and subscription loss | `coordinator.py:378–399,636–665`; existing tests:434,488,870 | Metadata contract failure rows; ledger | checked | Existing explicit and terminal cache-clear behaviors preserved; invalid metadata never clears. Named retained tests protect explicit refresh and exact subscription-loss clearing. |
| Concurrency/time: commit ordering | `coordinator.py:134–155,249–284,329–364,586–633` | Time/concurrency paragraph | checked | No new await, lock, version or freshness clock; retain current completion-order winner and coordinator refresh behavior. Validation occurs before credential update/persist. Existing publication/cancellation tests retained. |
| Cache/time: ownership and expiry | `coordinator.py:82–90,569–576,586–645`; Solar `RegistrationExtensions.cs:113–123` | Ownership; time/storage paragraphs | checked | Cache stays per entry, server validates registration freshness. No client TTL, parsed credential content or host cache introduced; reload and both-fetch-path regressions cover intended reuse. |
| Files/stages/gates and packaging | `manifest.json:13`; `const.py:4`; `AGENTS.md` manifest rule; `.github/workflows/tests.yml:34` | Complete file manifest; implementation gates | checked | Exactly three application/packaging and two test files in scope; three planning artifacts. Baseline next patch 2.0.80; deterministic next-patch rule if baseline advances. Focused/full commands and diff check named; no extra tooling. |
| Cross-stage references and regression proof | `test_coordinator.py:215–252`; production `coordinator_helpers.py:651–658` | Implementation gates; test-plan required-tests and commands | checked | Principal test name is identical in feature gate, baseline -k command and additive table. Red must be dropped-registration assertion, not setup failure; fix and full gates require pass. The prior hash-only round trip did not test registration. |
| I/O/HTTP limits, failure and cancellation | `const.py:87`; `coordinator.py:401–465,527–549`; `.get` invocation:410 | Retained HTTP topology paragraph | checked | Keep 10s asyncio timeout, one auth-refresh retry nested under original timeout, buffered JSON reading and existing errors/cancellation. No explicit repo body/aggregate/page cap; no I/O path replacement or new limit. Existing retries, failure and cancellation tests retained. |
| Endpoints/URI identity | `coordinator.py:569–584` | Ownership step 4; retained HTTP paragraph | checked | Same configured GET URI and query keys; urlencode preserves credential characters; logs drop query/fragment. Principal test decodes actual outgoing query; log regression forbids sentinel in logs. |
| DI/client/fixture topology | `coordinator.py:86`; `tests/components/horizoniq/conftest.py:30–61` | test-plan fixtures and production topology | checked | Real HA-owned aiohttp session, real coordinator/config entry; only external HTTP intercepted. Existing fixture defaults and JSON remain unchanged; no fake parser/storage/session lifetime or new project. |
| API read/write schemas | Solar `ForecastFunction.cs:1190–1197,1280`; integration `coordinator_helpers.py:780–809`, `coordinator.py:569–576` | Issue/result; private metadata contract | checked | Existing backend returns metadata alongside flat forecast. Read original successful response, keep private string, write same registrationData query on next request. No API schema, upstream product name or backend change. |
| Existing-test disposition: helper | `test_coordinator_helpers.py` 19 named methods, baseline inventory | test-plan existing-test migration ledger, helper table | checked | Every original method named individually and retained unchanged; no test silently removed or replaced. New helper tests additive. |
| Existing-test disposition: coordinator | `test_coordinator.py` 23 named methods, baseline inventory | test-plan existing-test migration ledger, coordinator table | checked | Every original method named individually and retained unchanged; existing hash, legacy, stale, auth, retry, cancellation and clear assertions remain. New HTTP/reload/security cases additive. |
| Fixture metadata and boundary tests | Helper `_schema_payload`/`_schema6_payload`:23–36; coordinator `_schema6_payload`:33–45; existing fixture JSON | test-plan fixtures; required cases | checked | New credential tests inject synthetic metadata locally; existing fixtures may omit it because metadata stays optional. Both schemas complete; absent-direct-model, null elements, precedence and special-character cases named. |
| Security/logging | `sensors/diagnostic.py:20–44,79–119`; `test_entities.py:418–471`; `test_forecast_schema5.py:379–407`; `coordinator.py:580–584` | Ownership step 3; security acceptance; test-plan sensor/log test | checked | Private credential never enters canonical/direct plan, sensor attributes or logs. Existing omission and prohibited-diagnostic-key tests retained; new actual round-trip sentinel test verifies outputs and DEBUG logs. |

**Verdict: 21/21 checked; unchecked: 0; unresolved: 0.** The plan is implementable. This verdict describes the approved planning review; final implementation, security and acceptance evidence follow below.

## Implementation review

Final bounded acceptance/security review passed. All criteria below are evidence-backed; historical pending statuses are superseded. Only approved source/test/version files comprise the implementation.

## Final acceptance evidence — 13 October 2026

**Task outcome: ready_for_review. Process status: completed.** All original
acceptance criteria are supported by the retained final host XML/logs and scoped
source/security evidence. This final disposition supersedes all historical
pending, blocked and incomplete statuses in earlier worker reports and audits.
There are no remaining acceptance gaps; no new implementation approval is needed.
HEAD remains `04da1eb6c820eb784e4222ee9bad384755705f32`; the existing feature
changes remain in the checkout for review. No commit, push or deployment occurred.

Authoritative execution summary:
`.agent-work/test-results/cached-registration-round-trip/final-host-validation.json`.
Read-only XML reconciliation:
`.agent-work/tasks/20261013-cached-registration-final-acceptance/acceptance-evidence-audit.json`
(command: `& ./.agent-work/tasks/20261013-cached-registration-final-acceptance/audit.ps1`,
exit 0). This audit reads existing evidence; it does not rerun tests or compile code.

### Exact gate commands and results

Baseline, executed by the orchestrator in host WSL **before production changes**:

```powershell
wsl bash -lc "cd /mnt/c/git/ha-integration && source .venv-wsl/bin/activate && python -m pytest tests/components/horizoniq/test_coordinator.py -k test_schema56_registration_data_persists_and_is_sent_on_next_request -q --junitxml=.agent-work/test-results/cached-registration-round-trip/baseline.xml"
```

**Exit 1: 4 failed, 25 deselected in 6.93s; 0 errors, 0 skipped.** Each of
`normal-5`, `normal-6`, `virtual-5`, `virtual-6` failed at the dropped-registration
assertion (`snapshot.registration_data` was `None`) after actual HTTP request and
FRESH plan checks passed. This is defect reproduction, not a setup/import failure.
Retained evidence: `baseline.xml` and `baseline-host.log` in the evidence directory.

Final focused gate, executed by the orchestrator in host WSL:

```powershell
wsl bash -lc "cd /mnt/c/git/ha-integration && source .venv-wsl/bin/activate && python -m pytest tests/components/horizoniq/test_coordinator_helpers.py tests/components/horizoniq/test_coordinator.py tests/components/horizoniq/test_forecast_schema5.py tests/components/horizoniq/test_entities.py tests/components/horizoniq/test_init.py -q --junitxml=.agent-work/test-results/cached-registration-round-trip/focused.xml"
```

**Exit 0: 378 passed, 1 skipped in 12.51s; 0 failures, 0 errors.** XML records
379 cases, including all 204 new cases passing without skips. Retained evidence:
`focused.xml` and `focused-host.log` in the evidence directory.

Final full gate, executed by the orchestrator in host WSL:

```powershell
wsl bash -lc "cd /mnt/c/git/ha-integration && source .venv-wsl/bin/activate && python -m pytest tests/components/horizoniq -q --junitxml=.agent-work/test-results/cached-registration-round-trip/full.xml"
```

**Exit 0: 652 passed, 4 skipped in 34.37s; 0 failures, 0 errors.** XML records
656 cases, including all 204 new cases passing without skips. Retained evidence:
`full.xml` and `full-host.log` in the evidence directory.

Exact pre-existing skip reasons, verified from the final XML:

- Both gates: `test_recorder_database_omits_only_the_full_forecast` requires
  Home Assistant Recorder SQLite **3.40.1 or newer**.
- Full gate only: `test_real_broker_command_atomicity_and_retained_input_safety`,
  `test_real_broker_replay_failure_is_peer_driven_and_state_neutral`, and
  `test_real_broker_status_schema_two_and_two_entry_isolation` opt in via
  `HORIZONIQ_CROSS_REPO_MQTT=1`. These existing optional real-broker Solar tests
  are outside this feature's scope and were not enabled.

Required post-documentation gate:

```powershell
git -C C:/git/ha-integration diff --check
```

**Exit 0 after final document edits.** Evidence:
`.agent-work/tasks/20261013-cached-registration-final-acceptance/final-diff-check.json`.
The final handoff changes only these three durable documents and disposable task
evidence. Application/test/version files, baseline/final XML and host logs are
preserved; hash evidence is retained in this task directory. No WSL test,
compilation, dependency/environment/policy change or optional external test rerun
was performed during acceptance reconciliation.

## Implementation Notes

### Complete implemented file manifest

| File | Actual change |
|---|---|
| `custom_components/horizoniq/coordinator_helpers.py` | Seven added lines in `_schema5_snapshot`: extract original response metadata via the existing helper, accept trimmed nonblank strings only, populate existing private `registration_data`. |
| `custom_components/horizoniq/manifest.json` | Version `2.0.79` → `2.0.80`. |
| `custom_components/horizoniq/const.py` | Matching `INTEGRATION_VERSION` `2.0.80`. |
| `tests/components/horizoniq/test_coordinator_helpers.py` | Four additive named regressions, 124 passing parametrized cases. |
| `tests/components/horizoniq/test_coordinator.py` | Six additive named regressions, 80 passing parametrized cases; exact external HTTP matching and one extra legacy private-field assertion corrected. |
| `features/cached-registration-round-trip/feature.md` | Approved feature contract and reconciled final implementation/acceptance evidence. |
| `features/cached-registration-round-trip/test-plan.md` | Required tests, complete original-method ledger and reconciled final results. |
| `features/cached-registration-round-trip/feature.review.md` | Approved planning review and final scope/security/acceptance review. |

No additional source/test files or shared fixtures changed. Existing production
coordinator, public schema, direct model, sensor and init code are unchanged.
The version pair is the approved next patch; this documentation handoff does not
introduce another version bump. Retained static evidence:
`implementation-static-review.json`, `correction-static-review.json`, and
`assertion-correction-static-review.json` in the evidence directory. These verify
all **19 helper + 23 coordinator original named methods**, including decorators,
assertions and parametrization, match the baseline exactly. Both final XML gates
also confirm every retained method's cases pass. Protected public-contract,
entity, init tests and shared fixtures were preserved.

### Required new regressions: executed case ledger

Every count below is independently verified in **both** final XML gates; all
204 cases passed, with zero new failures, errors or skips.

| Named test | Passed cases per gate |
|---|---:|
| `test_schema56_registration_metadata_is_kept_private` | 42 |
| `test_schema56_missing_or_invalid_registration_metadata_is_ignored` | 26 |
| `test_schema56_registration_metadata_uses_existing_alias_precedence` | 54 |
| `test_schema56_registration_metadata_is_preserved_without_direct_model` | 2 |
| `test_schema56_registration_data_persists_and_is_sent_on_next_request` | 4 |
| `test_schema56_registration_data_rotates_without_hash_change` | 4 |
| `test_schema56_registration_data_survives_coordinator_reload` | 4 |
| `test_schema56_absent_or_invalid_registration_metadata_keeps_cached_value` | 52 |
| `test_schema56_rejected_responses_do_not_replace_registration_data` | 12 |
| `test_schema56_cached_registration_is_not_exposed_by_sensors_or_logs` | 4 |

The tests cover both schemas and both fetch paths with the real HA-owned HTTP
session, parser, coordinator, config-entry storage updates, URL builder and
ForecastDetailSensor. Only external HTTP responses are mocked; the real storage
update is wrapped solely to count writes. Requests are decoded independently of
mock matching. Synthetic credentials include all required special characters
and an internal space; no real credentials were accessed or logged.

Key decisions: extraction follows successful plan parsing; only surrounding
whitespace is trimmed. Envelope-first, first-present alias precedence is retained,
including invalid winners blocking fallback. Missing/invalid metadata means no
cache update. Accepted renewal with an unchanged hash updates actual storage;
reload constructs a fresh coordinator from that persisted entry and sends the
renewed value. A valid plan without the optional direct model still carries
private metadata. Legacy coercion, hash validation, completion ordering,
entry-local storage and existing clear/subscription authority remain intact.

### Final bounded security review

**Passed; no new credential disclosure path or unresolved security finding.**
The small production diff sends the opaque value exclusively to the existing
private snapshot field and existing entry-local config key. It adds no logging,
I/O, parsing of credential contents, decryption, coercion or public-schema field.
Canonical schema conversion precedes unchanged normalized/direct forecast
construction, so those consumers receive sanitized plan data. Registration views
and periods remain credential-free for the accepted schema path; direct-model
`registration_data` stays empty. Existing request logs remove query/fragment;
storage messages identify the entry without printing values.

The 42 helper privacy cases verify canonical/normalized/direct forecast,
registration and periods, source immutability and trimmed private metadata.
The four real sensor/log cases verify actual sensor state/attributes, public
forecast data and DEBUG messages, excluding both raw and URL-encoded credentials.
All pass in both final gates. Existing public-contract regressions
`test_schema5_contract_omits_top_level_transport_metadata`,
`test_schema5_contract_rejects_transport_secrets_in_diagnostics_objects`, and
`test_forecast_detail_sensor_never_exposes_forecast_payload_values` also pass in
both gates. Rejection tests verify malformed plans, 401 authorization diagnostics
and HTTP 500 cannot replace an accepted memory/storage/request credential.

Retained security evidence: `security-review.json` and
`correction-security-review.json`; their historical runtime-pending statements
are superseded by final XML and `acceptance-evidence-audit.json`. No public
filtering, retry/timeout/cancellation semantics, endpoint/header/query topology,
HTTP limits, schema/storage migration, controller, sensor or backend change was
introduced. Expiry and version checks remain server-owned.

### Final acceptance disposition

| Original criterion / gate | Met | Evidence |
|---|---|---|
| Schemas 5/6 round trip through normal and virtual fetch paths | Yes | Four principal cases pass in focused/full XML; decoded next request contains accepted value. |
| Accepted renewal with unchanged hash survives reload | Yes | Four rotation and four actual persisted-entry reload cases pass in both gates. |
| Absent/invalid/rejected metadata preserves existing credential | Yes | 26 helper invalid, 52 HTTP invalid and 12 rejected cases pass; precedence and absent-direct-model coverage also pass. |
| No credential in canonical/direct forecasts, registration, periods, sensors or logs | Yes | 42 helper privacy + four real sensor/log cases and three existing privacy regression methods pass in both gates; private-only production diff reviewed. |
| Legacy/hash/clear/subscription behavior remains | Yes | Only `_schema5_snapshot` behavior changes; retained legacy/hash/auth/stale/retry/cancellation/clear/subscription cases pass in both gates. |
| All 42 original named tests and parametrization unchanged | Yes | Retained exact-source static audits: 19 helper + 23 coordinator; XML confirms their cases pass. |
| Failing defect reproduction before production change | Yes | Baseline exit 1, four dropped-registration assertions; baseline XML/log untouched. |
| Focused/full gates pass with no skipped required regressions | Yes | Exit 0 in both; all 204 new cases pass in each; only pre-existing SQLite/optional MQTT skips. |
| Diff gate passes | Yes | Post-documentation `final-diff-check.json`, exit 0. |
| Matching next patch version `2.0.80` | Yes | Manifest/constant diff and retained static version audit. |
| All three durable documents reconcile implementation and validation | Yes | Final status, commands/counts/skips, manifest, decisions, security and historical deviations recorded here and in companion documents. |

### Historical attempts and deviations

These earlier failures/statuses describe completed intermediate stages and do
not change final acceptance:

- Initial sandbox baseline access failed with WSL `E_ACCESSDENIED` before pytest;
  `baseline-environment.log` remains historical. The orchestrator subsequently
  obtained the valid pre-production four-case defect reproduction on host WSL.
- Focused attempt 1: **exit 1; 76 failed, 302 passed, 1 skipped in 20.98s; 0 errors**.
  Ordinary external mock URL matching ignored blank query values and reused the
  first registered response. Fourteen new mock sites were corrected to supported
  escaped `re.compile` matching with `\A`/`\Z` anchors around the `yarl.URL` form
  of the real production request URL. Decoded actual queries remain independent
  assertions. Rejection recovery retains the first two request tuples before
  `clear_requests`, combines the recovery tuple, and asserts three real calls.
  Artifacts: `focused-attempt1.xml`, `focused-attempt1-host.log`.
- Focused attempt 2: **exit 1; 4 failed, 374 passed, 1 skipped in 18.38s; 0 errors**
  (JUnit 18.371s). Only four unauthorized rejection cases failed at the extra
  `assert stale.registration_data is None`. The schema-free 401 diagnostic uses
  unchanged legacy normalization, which can carry private metadata; unchanged
  stale/authorization cache rules reject it. The extra assertion was removed;
  all approved stale/direct/auth, memory, config-entry, next-request, call-count
  and recovery assertions remain. No production behavior or acceptance criterion
  was relaxed. Artifacts: `focused-attempt2.xml`, `focused-attempt2-host.log`.
- Execution deviation: workers could not access WSL from the sandbox; the
  orchestrator ran the exact approved baseline/focused/full commands in the
  existing authorized host WSL environment. No policy change, new environment,
  dependencies or runner was required. This is now completed execution evidence,
  not a remaining blocker. Documentation-only reconciliation warrants no runtime
  reruns. The failed capacity audit preceding this retry made no edits.

Earlier worker reports remain at:
`.agent-work/tasks/20261013T053140078Z-67371b8b6495495bb7a1b40648577f79/report.json`
(implementation),
`.agent-work/tasks/20261013T061226309Z-54e30473d6e54bce8e8af024ad8dd723/report.json`
(HTTP matching), and
`.agent-work/tasks/20261013T062241074Z-4cd83f559fbe475ab79c57d2e503cfcb/report.json`
(assertion correction). All prior evidence is preserved. No remaining gaps or
follow-up implementation work is identified; the checkout is ready for review.

### Orchestrator completion review — 13 October 2026

Accepted after the evidence-backed worker report and one bounded final review.
The production diff contains only private string extraction after successful
schema parsing and the matching 2.0.80 version updates. The sensor/log regression
uses actual HTTP, coordinator publication and ForecastDetailSensor, and checks
raw and URL-encoded credentials. No unresolved implementation or security finding.

Host evidence confirms four expected pre-fix failures, 378 focused passes and
652 full-suite passes. All 204 new cases pass without skips; all 42 existing
named methods are retained. The SQLite and optional MQTT skips remain documented.
The three documents are marked complete; no further runtime checks are warranted
by this documentation-only review update.