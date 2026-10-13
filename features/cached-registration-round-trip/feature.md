# Cached registration round trip

Status: complete; orchestrator review passed. Final focused/full host gates passed; all original acceptance criteria are evidence-backed. Repository: `C:/git/ha-integration`. Reviewed baseline: `04da1eb6c820eb784e4222ee9bad384755705f32`, version `2.0.79`; implemented version pair `2.0.80`.

## Issue and required result

The schema-5/6 response path drops `registrationData` before filling the coordinator's private cache. Each later request therefore sends an empty value and reloads registration from the backend.

After the first accepted response, normal and virtual-battery requests must send the returned registration string. Renewed strings must replace the old value, and integration reload must retain it. **A regression test must demonstrate the failure before the fix and pass afterward.**

## Ownership and exact change

Solar issues and validates the opaque credential; this integration owns its transport and entry-local storage. Only this repository changes. No backend, infrastructure, public forecast contract, controller or sensor changes are required.

In `custom_components/horizoniq/coordinator_helpers.py::_schema5_snapshot`, after the schema-5/6 plan has successfully parsed:

1. Read the original response using existing `_extract_registration_data_value(payload)`, rather than the sanitized canonical forecast.
2. Accept a string only: `raw.strip()` if `isinstance(raw, str)`, otherwise `None`; map the resulting empty string to `None`. Keep internal characters unchanged. Do not decrypt, JSON-parse, stringify other types or introduce another parser/helper.
3. Pass the result as `registration_data=` to the existing `HorizonIQSnapshot` constructor. Keep it out of `snapshot.forecast`, `snapshot.registration`, `Schema5Forecast.to_dict()`, `Forecast` direct-control data, periods, sensors and logs.
4. Keep the existing coordinator path: parse → commit accepted snapshot → `_update_cached_state` → `_persist_state`. Its existing `registration_data` field then updates `_registration_data` and `ConfigEntry.data[CONF_REGISTRATION_DATA]`; `_build_request_url` URL-encodes it on later calls. Both `_async_update_data` and `async_fetch_sandbox_forecast` use this path. Do not change coordinator production code.

There is one schema-5/6 production path. Preserve the separate legacy normalization/coercion behavior and existing hash rules.

## Metadata contract and failure boundaries

The existing field remains `str | None`: `None` means no credential update, not clear the cache. There are no new types, enums, timestamps, monetary values or methods.

| Input | Exact behavior |
|---|---|
| Nonblank string | Trim surrounding whitespace only; carry the opaque string in the private snapshot field. |
| Absent, null, empty, whitespace-only, bool, numeric value, list (including null elements), or mapping | Private field `None`; accept an otherwise valid forecast and retain the previous credential. No exception, coercion or credential-value logging. |
| Flat response or wrapper `Forecast`, `forecast`, `forecastEntity` | Use existing source selection. Search the envelope first, then the selected forecast object. Within each object, first present alias wins: `RegistrationData`, `registrationData`, `registration_data`. |
| Duplicate, conflicting or partial metadata | Preserve that deterministic first-present precedence, including an invalid/null winning alias blocking fallback. Validate only that selected value; do not merge, concatenate or reject the valid plan. |
| Malformed plan, missing required plan field, unknown schema/action, or invalid plan diagnostics | Existing `Schema5ForecastError` → coordinator `UpdateFailed`/stale publication; no new credential accepted and no new diagnostic reason. Extract metadata only after successful plan validation. |
| Stale/authorization diagnostic, HTTP failure, timeout, or caller cancellation | Existing handling and cache retention remain; new schema metadata does not enter those paths. Existing explicit clear button and exact terminal subscription-loss clear remain authoritative. |
| Valid plan without optional direct-control model | Carry valid credential metadata normally; plan diagnostics remain fresh and direct control remains absent. |

Expiry and registration-version checks remain server-owned; no client timestamp or TTL is introduced. Parsing and cache updates are synchronous once HTTP returns; preserve existing completion-order updates, entry isolation and refresh coalescing. Storage remains the existing config-entry key and startup input, so no migration or storage version change is needed.

Retain the existing HTTP topology: HA-owned session, same GET endpoint/headers/query keys, `urlencode`, complete `response.json(content_type=None)` reading, 10-second `asyncio.timeout` per fetch invocation, one credential-refresh retry inside the original timeout, existing cancellation/error mapping and aiohttp redirect defaults. No new I/O path, dependency, body/header/page limit or cache is added; the repository currently specifies no explicit response-body/aggregate/page-count cap.

## Complete file manifest

Modify application/packaging:

- `custom_components/horizoniq/coordinator_helpers.py`: private metadata extraction above.
- `custom_components/horizoniq/manifest.json` and `custom_components/horizoniq/const.py`: matching next patch version, `2.0.80` at this baseline. If the checkout has advanced, use current major/minor and current patch + 1 in both; record the baseline change.

Modify executable tests, with additive tests and all 42 existing named tests retained:

- `tests/components/horizoniq/test_coordinator_helpers.py`.
- `tests/components/horizoniq/test_coordinator.py`.

Planning artifacts created now and updated with implementation evidence later:

- `features/cached-registration-round-trip/feature.md`.
- `features/cached-registration-round-trip/test-plan.md`.
- `features/cached-registration-round-trip/feature.review.md`.

No other source/test files, fixtures, projects, tools or scripts are to be created, modified or deleted. No deletes. Test evidence belongs under this repository's `.agent-work`. Preserve others' edits; no commit, push or deployment is requested.

## Implementation gates

Use the complete commands, required assertions and named-test migration ledger in [test-plan.md](test-plan.md).

1. **Reproduction evidence:** add the principal real-parser/real-coordinator HTTP test first; run its baseline command and record the expected missing-registration assertion failure before changing production code. A setup/import/environment failure is not reproduction evidence.
2. **Fix gate:** apply the small extraction change, add the remaining regressions, and pass the focused command. Do not mock the parser, cache methods, storage update or request builder.
3. **Completion gate:** bump both versions, pass the full HA suite and `git diff --check`, review credential handling against the public-output tests, compare every requirement/file/test against the diff, and append exact commands/results/deviations to these documents. Do not mark implementation complete with skipped required regressions or unresolved failures.

Implementation owner: one Home Assistant agent in this repository. Perform a bounded security review of credential acceptance, retention and public-output exclusion. Do not split this small fix into separate implementations.

Acceptance: schema 5 and 6 round trip through both fetch paths; accepted renewal survives reload; absent/invalid/rejected metadata preserves the existing credential; no credential appears in canonical/direct forecast data, sensors or logs; legacy/hash/clear/subscription behavior remains; focused and full gates pass. Open questions: none. Planning review: [feature.review.md](feature.review.md).

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
