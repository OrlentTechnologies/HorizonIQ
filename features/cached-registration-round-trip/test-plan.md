# Cached registration round-trip tests

Baseline: `04da1eb6c820eb784e4222ee9bad384755705f32`. Status: complete; orchestrator review passed. All ten required named regressions / 204 parametrized cases pass in both final host gates. Baseline reproduction and historical attempts are preserved. Full test requirements remain authoritative.

## Fixtures and production topology

Use existing `fixtures/direct_schema5_forecast.json` and the local schema-6 builders in the two test files. Do not edit shared JSON or inject registration metadata into shared defaults: absence remains valid, so all existing fixtures may omit it. New credential cases add synthetic strings locally. Keep both supported schemas structurally complete, including schema-6 `shouldExport` fields.

The existing `hass`, `mock_config_entry`, `entry_data` and `aioclient_mock` fixtures are authoritative. The coordinator must use its actual HA-owned aiohttp session; mock only external HTTP through `aioclient_mock`. Use real `build_snapshot`, schema parser, coordinator, config-entry updates and URL builder. Wrap storage updates only to count calls; do not replace them. No live HTTP, battery, MQTT, account access or new test runner.

For new flat-response cases, set the existing camelCase plan fields plus top-level `hash` and `registrationData`, matching the backend's response; do not invent a `Forecast` wrapper for the principal regression. Helpers also cover documented wrappers and aliases.

Use a synthetic value containing `+`, `/`, `=`, `&`, `?` and an internal space. Compare decoded request query parameters using `urllib.parse` so encoding cannot hide a regression. Never print actual credentials.

## Required additive tests

In `test_coordinator_helpers.py`:

| New named test | Required cases and assertions |
|---|---|
| `test_schema56_registration_metadata_is_kept_private` | Parametrize schemas 5/6; all three registration aliases; flat payload and each wrapper `Forecast`/`forecast`/`forecastEntity`; metadata beside wrapper and, separately, inside its selected forecast. Assert exact trimmed private field, fresh plan, unchanged source input, and absence of sentinel from normalized forecast, public schema dictionary, direct model and periods. |
| `test_schema56_missing_or_invalid_registration_metadata_is_ignored` | Schemas 5/6 with field absent, null, empty, whitespace, bool, integer, float, empty/nonempty list including null, empty/nonempty mapping. Assert private field `None`, no parsing exception, otherwise valid forecast unchanged. |
| `test_schema56_registration_metadata_uses_existing_alias_precedence` | Conflicting aliases within one object; envelope versus nested value; null/invalid higher-priority alias beside a valid lower-priority/nested value; entirely absent envelope permits selected forecast value. Assert exact first-present result described in feature.md, including no fallback after invalid selection. |
| `test_schema56_registration_metadata_is_preserved_without_direct_model` | Both schemas without optional equipment profile; private field retained, fresh diagnostics, direct forecast absent. |

In `test_coordinator.py`:

| New named test | Required cases and assertions |
|---|---|
| **`test_schema56_registration_data_persists_and_is_sent_on_next_request`** | **Principal defect regression.** Parametrize schema 5/6 and normal `_async_update_data` versus virtual `async_fetch_sandbox_forecast`. Start with empty registration memory and config entry; set battery sensor, serve a complete **flat** response as the backend does, including registration and hash. Verify first outgoing query registration empty, accepted private value equals response, actual config-entry value updated, then make a second HTTP request and verify decoded registration exactly equals the accepted value. Second response omits registration and retains hash; cache remains and storage is not rewritten. Assert two actual HTTP calls, proper hash/battery parameters and no mutation of unrelated entry fields. This must fail for the cache/persisted/next-request assertion on the baseline. |
| `test_schema56_registration_data_rotates_without_hash_change` | Both schemas; accepted response A then response B with same hash and changed registration; issue third request. Verify B stored in memory/entry and third actual request sends B while hash remains unchanged. |
| `test_schema56_registration_data_survives_coordinator_reload` | Both schemas; obtain and persist credential through an actual HTTP response; construct a fresh production coordinator using actual stored `CONF_HASH` and `CONF_REGISTRATION_DATA`, as `async_setup_entry` does, and verify its first actual HTTP request sends the persisted credential. No manual replacement of persisted values or cache seeding with the expected result. |
| `test_schema56_absent_or_invalid_registration_metadata_keeps_cached_value` | Start with an accepted existing credential and unchanged hash; valid subsequent plan with absent/null/empty/whitespace/bool/number/list/mapping metadata. Verify old memory/config/request value retained, valid plan accepted and no credential-only config-entry write. |
| `test_schema56_rejected_responses_do_not_replace_registration_data` | Seed an accepted credential via real HTTP, then offer a replacement sentinel alongside a malformed plan (remove required `planId`), a 401 authorization diagnostic, or a 500 failure. Assert old credential remains in memory, entry and next request; malformed/HTTP failures follow existing `UpdateFailed`, authorization follows existing missing/stale diagnostics. Run normal and virtual fetch paths. Retain existing cancellation and stale-on-transport-failure tests unchanged; HTTP policy is not modified. |
| `test_schema56_cached_registration_is_not_exposed_by_sensors_or_logs` | Capture DEBUG logs during real round trip; publish accepted snapshot to coordinator and instantiate actual `ForecastDetailSensor`. Sentinel absent from log messages, sensor state/attributes, public schema dictionary and direct forecast. Query-redacted request logging stays redacted. Do not assert against private snapshot/config-entry representation, which intentionally carries metadata. |

Retain and run unchanged `test_schema5_contract_omits_top_level_transport_metadata`, `test_schema5_contract_rejects_transport_secrets_in_diagnostics_objects` and `test_forecast_detail_sensor_never_exposes_forecast_payload_values` in their existing files. Do not modify those files just to accommodate this fix.

## Commands and sequencing

Run from Windows through WSL as required by AGENTS.md. Request host execution if the sandbox cannot access the existing WSL environment. Do not create another environment, install dependencies or write a helper runner.

Reproduction evidence, before production edits: add the principal test, then run:

```powershell
wsl bash -lc "cd /mnt/c/git/ha-integration && source .venv-wsl/bin/activate && python -m pytest tests/components/horizoniq/test_coordinator.py -k test_schema56_registration_data_persists_and_is_sent_on_next_request -q --junitxml=.agent-work/test-results/cached-registration-round-trip/baseline.xml"
```

Expected: assertion failures caused by dropped registration data; retain exact failures. This is baseline evidence, not a passing implementation stage. If it unexpectedly passes, explain the changed checkout before altering code.

Fix gate after extraction and additive tests:

```powershell
wsl bash -lc "cd /mnt/c/git/ha-integration && source .venv-wsl/bin/activate && python -m pytest tests/components/horizoniq/test_coordinator_helpers.py tests/components/horizoniq/test_coordinator.py tests/components/horizoniq/test_forecast_schema5.py tests/components/horizoniq/test_entities.py tests/components/horizoniq/test_init.py -q --junitxml=.agent-work/test-results/cached-registration-round-trip/focused.xml"
```

Completion gate after version bump:

```powershell
wsl bash -lc "cd /mnt/c/git/ha-integration && source .venv-wsl/bin/activate && python -m pytest tests/components/horizoniq -q --junitxml=.agent-work/test-results/cached-registration-round-trip/full.xml"
git -C C:/git/ha-integration diff --check
```

Review matching manifest/constant versions, approved file manifest, no credential added to canonical/direct models, unchanged request topology, and every acceptance assertion. Append exact counts, commands, failures/skips and deviations to feature.md and feature.review.md. Required new tests may not skip; report unrelated pre-existing environment skips accurately.

## Existing-test migration ledger

**19 helper methods + 23 coordinator methods = 42 named methods, all retained.** Their current parametrization remains. Inventory is independent of pytest's collected case count.

### tests/components/horizoniq/test_coordinator_helpers.py

Every named method below is **retained with its existing assertions and parametrization**. New tests are additive; no renames, replacements or removals.

| Existing named test | Disposition |
|---|---|
| `test_extract_first_handles_none_and_missing` | Retained |
| `test_normalize_periods_handles_nested_forecast_payload` | Retained |
| `test_normalize_forecast_extracts_primary_fields` | Retained |
| `test_normalize_forecast_extracts_trial_fields` | Retained |
| `test_normalize_forecast_extracts_top_level_trial_with_nested_forecast` | Retained |
| `test_normalize_trial_extracts_nested_trial_container` | Retained |
| `test_build_snapshot_keeps_trial_payload_out_of_registration` | Retained |
| `test_normalize_registration_extracts_json_payload_from_registration_data` | Retained |
| `test_normalize_registration_accepts_top_level_registration_payload` | Retained |
| `test_extract_forecast_cadence_minutes_from_registration_data` | Retained |
| `test_build_snapshot_accepts_top_level_registration_payload` | Retained |
| `test_build_snapshot_keeps_forecast_payload_out_of_registration` | Retained |
| `test_build_snapshot_prefers_normalized_shape` | Retained |
| `test_schema6_envelope_hash_is_preserved_with_canonical_aliases` | Retained |
| `test_schema56_envelope_hash_invalid_shapes_or_conflicts_do_not_coerce_or_replace_legacy_diagnostics` | Retained |
| `test_schema56_invalid_or_conflicting_present_envelope_hash_never_uses_nested_cache_fallback` | Retained |
| `test_legacy_snapshot_keeps_existing_nested_hash_only_when_envelope_alias_is_truly_absent` | Retained |
| `test_valid_schema56_without_optional_direct_model_remains_fresh_but_non_executable` | Retained |
| `test_legacy_direct_capable_and_non_direct_payloads_keep_the_freshness_matrix` | Retained |

### tests/components/horizoniq/test_coordinator.py

Every named method below is **retained with its existing assertions and parametrization**. New tests are additive; no renames, replacements or removals.

| Existing named test | Disposition |
|---|---|
| `test_sandbox_forecast_request_has_no_client_control_capability` | Retained |
| `test_coordinator_updates_cached_values_from_api` | Retained |
| `test_schema6_envelope_hash_persists_and_is_sent_on_the_next_request` | Retained |
| `test_stale_response_keeps_cached_hash_and_publishes_non_executable_stale_snapshot` | Retained |
| `test_malformed_schema6_after_history_publishes_stale_once_then_fails_each_fetch_path` | Retained |
| `test_absent_schema_or_authorization_diagnostic_after_history_is_stale_but_initial_is_missing` | Retained |
| `test_legacy_direct_capable_response_remains_fresh_with_or_without_schema_history` | Retained |
| `test_commit_rejects_non_integer_uncommitted_sequence_without_state_change` | Retained |
| `test_exact_subscription_failure_clears_persisted_hash_but_never_publishes_executable_control` | Retained |
| `test_coordinator_cancellation_does_not_publish_or_increment_sequence` | Retained |
| `test_clear_registration_data_persists_and_refreshes` | Retained |
| `test_sandbox_pause_prevents_forecast_http_after_initial_failure` | Retained |
| `test_clear_registration_data_preserves_hash_and_makes_one_request` | Retained |
| `test_forecast_request_sends_trial_headers_when_configured` | Retained |
| `test_forecast_request_omits_trial_headers_when_blank` | Retained |
| `test_forecast_request_uses_separate_function_key` | Retained |
| `test_forecast_auth_failure_refreshes_key_and_retries_once` | Retained |
| `test_coordinator_uses_trial_payload_from_unauthorized_response` | Retained |
| `test_coordinator_uses_diagnostic_payload_from_plain_unauthorized_response` | Retained |
| `test_coordinator_initial_failures_follow_retry_schedule` | Retained |
| `test_coordinator_initial_http_failures_make_one_request_and_ignore_retry_after` | Retained |
| `test_coordinator_success_resets_initial_retry_state_and_later_uses_cadence` | Retained |
| `test_exact_subscription_failure_stops_polling_and_clears_cache` | Retained |

## Results

Final focused and full gates passed. All 204 new cases and every retained original method's cases pass in both XML reports. Exact commands, skips and acceptance evidence follow.

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
