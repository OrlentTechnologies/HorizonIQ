# HA existing-test migration ledger

Migrated and validated on 2026-10-24 after separate implementation approval; **ready_for_review**. Approved host WSL gates passed: focused 608 passed in 21.35s, full 1211 passed in 40.91s, both exit 0 with zero failures/errors/skips. The earlier worker WSL startup denial is historical and resolved through host execution. Inventory: **79 top-level named tests in six modified files**, plus the class test retained by the local reconciliation appendix below. Every method below retains its existing purpose unless explicitly replaced. New cases are additive. Only retired priority-specific constructor arguments, assertions and parameter rows may disappear; other guards/parametrisations remain.

## tests/components/horizoniq/test_direct_control.py

| Existing named test | Disposition | Treatment |
|---|---|---|
| `test_live_charge_and_import_are_clamped_to_virtual_limits` | Retained | Retain all existing non-priority behaviour and assertions; remove rank construction from shared fixtures. |
| `test_live_charge_import_and_hold_ignore_retired_permissions` | Retained | Retain permission-independence/schema/action/limit cases. Deliberately remove the appended wrong-priority rejection, since this member is retired; no other guard is removed. |
| `test_virtual_export_needs_no_profile_permission` | Retained | Retain all existing non-priority behaviour and assertions; remove rank construction from shared fixtures. |
| `test_complete_schema5_fixture_normalizes_and_drives_direct_charge` | Retained | Retain all existing non-priority behaviour and assertions; remove rank construction from shared fixtures. |
| `test_schema6_forecast_normalizes_without_export_control_side_effects` | Retained | Retain all existing non-priority behaviour and assertions; remove rank construction from shared fixtures. |
| `test_virtual_recommendations_ignore_production_adapter_capabilities` | Retained | Retain all existing non-priority behaviour and assertions; remove rank construction from shared fixtures. |
| `test_live_control_never_uses_a_generic_recommendation` | Retained | Retain all existing non-priority behaviour and assertions; remove rank construction from shared fixtures. |
| `test_virtual_recommendation_rejects_stale_invalid_or_wrong_period_data` | Retained | Retain all existing non-priority behaviour and assertions; remove rank construction from shared fixtures. |
| `test_virtual_import_for_export_then_profit_export_changes_soc` | Retained | Retain all existing non-priority behaviour and assertions; remove rank construction from shared fixtures. |
| `test_virtual_refresh_has_no_client_control_capability_override` | Retained | Retain all existing non-priority behaviour and assertions; remove rank construction from shared fixtures. |
| `test_unload_cancels_only_its_local_virtual_recommendation` | Retained | Retain all existing non-priority behaviour and assertions; remove rank construction from shared fixtures. |
| `test_runtime_maps_explicit_stale_snapshot_to_fallback_stale_not_missing` | Retained | Retain all existing non-priority behaviour and assertions; remove rank construction from shared fixtures. |
| `test_runtime_maps_explicit_missing_snapshot_to_fallback_missing` | Retained | Retain all existing non-priority behaviour and assertions; remove rank construction from shared fixtures. |
| `test_runtime_maps_fresh_snapshot_without_direct_model_to_fallback_invalid` | Retained | Retain all existing non-priority behaviour and assertions; remove rank construction from shared fixtures. |
| `test_live_none_with_null_command_metadata_is_safe_self_consumption` | Retained | Retain all existing non-priority behaviour and assertions; remove rank construction from shared fixtures. |
| `test_runtime_marks_a_valid_none_forecast_healthy` | Retained | Retain all existing non-priority behaviour and assertions; remove rank construction from shared fixtures. |
| `test_raw_api_to_coordinator_model_to_runtime_boundary_for_no_action` | Retained | Retain all existing non-priority behaviour and assertions; remove rank construction from shared fixtures. |
| `test_paused_runtime_stages_forecasts_and_reset_reports_awaiting` | Retained | Retain all existing non-priority behaviour and assertions; remove rank construction from shared fixtures. |
| `test_live_advisory_and_expired_actions_are_rejected` | Retained | Retain all existing non-priority behaviour and assertions; remove rank construction from shared fixtures. |
| `test_missing_or_wrong_schema5_fields_are_rejected` | Retained | Retain all existing non-priority behaviour and assertions; remove rank construction from shared fixtures. |
| `test_live_command_uses_current_priority_for6_and7` | Replaced → `test_live_command_for6_and7_requires_no_priority` | Retain actions, power results and supported schemas; replace retired rank checks with absence/ignored-old-field coverage. |
| `test_schema8_live_commands_keep_current_priorities_and_guards` | Replaced → `test_schema8_live_commands_keep_guards_without_priority` | Keep diagnostics present/missing/null, command ID, issued/expiry, action and time-boundary assertions. Remove only rank invalidation. |

## tests/components/horizoniq/test_forecast_schema5.py

| Existing named test | Disposition | Treatment |
|---|---|---|
| `test_complete_schema5_contract_survives_strict_normalization` | Retained | Remove priority from the retained-field equality list; assert it is absent from canonical output. Keep every other field and secrecy assertion. |
| `test_old_and_new_profiles_normalize_to_identical_physical_profile` | Retained | Retain all existing non-priority behaviour and assertions; remove rank construction from shared fixtures. |
| `test_retained_physical_profile_validation_is_unchanged` | Retained | Retain all existing non-priority behaviour and assertions; remove rank construction from shared fixtures. |
| `test_retired_profile_aliases_reject_nested_diagnostic_secrets` | Retained | Retain all existing non-priority behaviour and assertions; remove rank construction from shared fixtures. |
| `test_new_profile_survives_real_coordinator_refresh` | Retained | Retain all existing non-priority behaviour and assertions; remove rank construction from shared fixtures. |
| `test_schema6_requires_and_preserves_backend_should_export` | Retained | Retain all existing non-priority behaviour and assertions; remove rank construction from shared fixtures. |
| `test_schema6_rejects_missing_or_non_boolean_should_export` | Retained | Retain all existing non-priority behaviour and assertions; remove rank construction from shared fixtures. |
| `test_schema6_rejects_simultaneous_import_and_export` | Retained | Retain all existing non-priority behaviour and assertions; remove rank construction from shared fixtures. |
| `test_complete_solar_dto_alias_fixtures_normalize_once` | Retained | Retain all existing non-priority behaviour and assertions; remove rank construction from shared fixtures. |
| `test_conflicting_schema5_wire_aliases_are_rejected_atomically` | Retained | Retain all existing non-priority behaviour and assertions; remove rank construction from shared fixtures. |
| `test_schema5_contract_rejects_incomplete_period_atomically` | Retained | Retain all existing non-priority behaviour and assertions; remove rank construction from shared fixtures. |
| `test_schema5_contract_rejects_transport_secrets_in_diagnostics_objects` | Retained | Retain all existing non-priority behaviour and assertions; remove rank construction from shared fixtures. |
| `test_schema5_contract_omits_top_level_transport_metadata` | Retained | Retain all existing non-priority behaviour and assertions; remove rank construction from shared fixtures. |
| `test_malformed_schema5_refresh_keeps_the_last_complete_plan_as_stale` | Retained | Retain all existing non-priority behaviour and assertions; remove rank construction from shared fixtures. |
| `test_three_coordinators_keep_schema5_diagnostics_entry_local` | Retained | Retain all existing non-priority behaviour and assertions; remove rank construction from shared fixtures. |
| `test_schema5_preserves_all_action_semantics` | Retained | Retain all existing non-priority behaviour and assertions; remove rank construction from shared fixtures. |
| `test_import_for_export_decision_keeps_exact_backend_reason_codes` | Retained | Retain all existing non-priority behaviour and assertions; remove rank construction from shared fixtures. |
| `test_import_for_export_decision_selected_and_disabled` | Retained | Retain all existing non-priority behaviour and assertions; remove rank construction from shared fixtures. |
| `test_import_for_export_uses_the_action_authoritative_for_each_plan_kind` | Retained | Retain all existing non-priority behaviour and assertions; remove rank construction from shared fixtures. |
| `test_zero_period_schema5_forecast_is_unavailable_and_kept_complete` | Retained | Retain all existing non-priority behaviour and assertions; remove rank construction from shared fixtures. |
| `test_current_schema5_period_uses_utc_half_hour_boundaries` | Retained | Retain all existing non-priority behaviour and assertions; remove rank construction from shared fixtures. |
| `test_stale_last_good_forecast_remains_visible_after_refresh_failure` | Retained | Retain all existing non-priority behaviour and assertions; remove rank construction from shared fixtures. |
| `test_full_horizon_is_explicitly_unrecorded` | Retained | Retain all existing non-priority behaviour and assertions; remove rank construction from shared fixtures. |
| `test_recorder_serializes_only_bounded_forecast_diagnostics` | Retained | Retain all existing non-priority behaviour and assertions; remove rank construction from shared fixtures. |
| `test_schema7_accepts_no_simulation_field` | Retained | Retain all existing non-priority behaviour and assertions; remove rank construction from shared fixtures. |
| `test_legacy5_and6_ignore_retired_simulation_field` | Retained | Retain all existing non-priority behaviour and assertions; remove rank construction from shared fixtures. |
| `test_replay_plan_is_rejected_without_control_mutation` | Retained | Retain all existing non-priority behaviour and assertions; remove rank construction from shared fixtures. |
| `test_schema8_normalizes_nested_diagnostics_for_each_wire_style` | Retained | Retain all existing non-priority behaviour and assertions; remove rank construction from shared fixtures. |
| `test_schema8_missing_or_null_diagnostics_does_not_disable_live_command` | Retained | Retain all existing non-priority behaviour and assertions; remove rank construction from shared fixtures. |
| `test_schema8_rejects_invalid_diagnostics_atomically` | Retained | Retain all existing non-priority behaviour and assertions; remove rank construction from shared fixtures. |
| `test_schema8_accepts_inclusive_tolerance_and_finite_negative_error` | Retained | Retain all existing non-priority behaviour and assertions; remove rank construction from shared fixtures. |
| `test_schema8_rejects_root_ledger_and_conflicting_nested_aliases` | Retained | Retain all existing non-priority behaviour and assertions; remove rank construction from shared fixtures. |
| `test_schema8_diagnostics_reject_nested_transport_secrets` | Retained | Retain all existing non-priority behaviour and assertions; remove rank construction from shared fixtures. |
| `test_schema8_to_dict_emits_only_nested_diagnostics` | Retained | Retain all existing non-priority behaviour and assertions; remove rank construction from shared fixtures. |
| `test_schema8_same_hash_refreshes_entry_local_diagnostics` | Retained | Retain all existing non-priority behaviour and assertions; remove rank construction from shared fixtures. |
| `test_schema8_refresh_keeps_diagnostics_entry_local_and_unrecorded` | Retained | Retain all existing non-priority behaviour and assertions; remove rank construction from shared fixtures. |

## tests/components/horizoniq/test_reserve_grid_hold.py

| Existing named test | Disposition | Treatment |
|---|---|---|
| `test_all_direct_use_grid_paths_select_grid_preservation` | Retained | Retain all existing non-priority behaviour and assertions; remove rank construction from shared fixtures. |
| `test_live_priorities_match_each_supported_schema` | Replaced → `test_live_actions_accept_priority_free_supported_schemas` | No per-schema rank input. Preserve unsupported-schema9 rejection and live action behaviour; old rank values are ignored. |
| `test_hold_uses_actual_load_and_solar` | Retained | Retain all existing non-priority behaviour and assertions; remove rank construction from shared fixtures. |
| `test_hold_window_and_invalid_setpoint_use_existing_fallbacks` | Retained | Retain all existing non-priority behaviour and assertions; remove rank construction from shared fixtures. |
| `test_hold_snapshot_round_trip_and_invalid_restore_are_atomic` | Retained | Retain all existing non-priority behaviour and assertions; remove rank construction from shared fixtures. |
| `test_partial_period_command_uses_remaining_time_and_full_slot_solar_power` | Retained | Retain all existing non-priority behaviour and assertions; remove rank construction from shared fixtures. |
| `test_manual_snapshot_restore_retains_valid_hold_and_rejects_invalid_atomically` | Retained | Retain all existing non-priority behaviour and assertions; remove rank construction from shared fixtures. |
| `test_live_unsupported_action_cannot_become_a_grid_hold` | Retained | Retain all existing non-priority behaviour and assertions; remove rank construction from shared fixtures. |

## tests/components/horizoniq/test_measured_capacity_refresh_regressions.py

| Existing named test | Disposition | Treatment |
|---|---|---|
| `test_live_sensor_4320_wh_refresh_replaces_cached_22000_wh_forecast_and_stages_fresh_response` | Retained | Retain all existing non-priority behaviour and assertions; remove rank construction from shared fixtures. |
| `test_timeout_after_live_sensor_4320_wh_keeps_stale_22000_wh_forecast_without_new_command` | Retained | Retain all existing non-priority behaviour and assertions; remove rank construction from shared fixtures. |
| `test_fresh_schema6_recovery_after_timeout_replaces_stale_history_and_hash_once` | Retained | Retain all existing non-priority behaviour and assertions; remove rank construction from shared fixtures. |

## tests/components/horizoniq/test_reserve_grid_hold_runtime.py

| Existing named test | Disposition | Treatment |
|---|---|---|
| `test_real_entry_holds_for_four_hours_then_charges` | Retained | Retain all existing non-priority behaviour and assertions; remove rank construction from shared fixtures. |
| `test_fresh_hold_replaces_export_without_retaining_export_power` | Retained | Retain all existing non-priority behaviour and assertions; remove rank construction from shared fixtures. |
| `test_hold_expiry_stale_refresh_and_entry_lifecycle_remain_isolated` | Retained | Retain all existing non-priority behaviour and assertions; remove rank construction from shared fixtures. |
| `test_hold_status_and_restore_use_existing_wire_and_storage_contracts` | Retained | Retain all existing non-priority behaviour and assertions; remove rank construction from shared fixtures. |

## tests/components/horizoniq/test_use_grid_sensor.py

| Existing named test | Disposition | Treatment |
|---|---|---|
| `test_use_grid_entity_uses_current_accepted_recommendation` | Retained | Retain all existing non-priority behaviour and assertions; remove rank construction from shared fixtures. |
| `test_use_grid_entity_rejects_stale_missing_and_conflicting_state` | Retained | Retain all existing non-priority behaviour and assertions; remove rank construction from shared fixtures. |
| `test_use_grid_entity_expires_without_a_refresh` | Retained | Retain all existing non-priority behaviour and assertions; remove rank construction from shared fixtures. |
| `test_use_grid_entity_replacement_and_unload_cancel_old_deadlines` | Retained | Retain all existing non-priority behaviour and assertions; remove rank construction from shared fixtures. |
| `test_use_grid_entity_is_entry_local` | Retained | Retain all existing non-priority behaviour and assertions; remove rank construction from shared fixtures. |
| `test_use_grid_real_config_entry_expires` | Retained | Retain all existing non-priority behaviour and assertions; remove rank construction from shared fixtures. |

## New acceptance cases

Add `tests/components/horizoniq/test_action_priority_removal.py`; exercise existing real parser/coordinator/direct-control implementations, not replacement internal doubles.

| Named test | Cases |
|---|---|
| `test_priority_free_forecast_round_trips_and_executes` | Supported schemas5/6/7/8; all three live actions; camel/Pascal/snake wire forms; typed models and canonical output omit the field. |
| `test_legacy_priority_aliases_and_values_are_discarded` | Each retired alias: absent/null/1/99/boolean/string/list/object. No canonical/diagnostic/state output retains the member or discarded value. |
| `test_retired_priority_alias_conflicts_are_ignored` | Conflicting spellings of this retired member do not reject an otherwise valid forecast. |
| `test_retained_alias_conflicts_still_reject_atomically` | Conflicting retained field aliases still raise existing Schema5ForecastError; accepted horizon/control is not partially updated. |
| `test_priority_removal_preserves_command_metadata_and_expiry_guards` | Missing/malformed ID/issued/expiry, now before issue, exact expiry, wrong period end; same typed rejection categories. |
| `test_priority_removal_preserves_none_and_unsupported_action_paths` | None needs no metadata; unsupported schema/action still fail through existing paths; no recommendation becomes live authority. |
| `test_old_normalised_priority_is_not_restored_into_direct_model` | An old cached normalised dictionary is projected into a priority-free typed model, with retained nullable metadata unchanged. |
| `test_priority_free_refresh_keeps_runtime_state_entry_local` | Real async refresh/runtime with equal hash, stale last-good and independent entries; no additional command or cross-entry mutation. |

## Fixture and boundary ownership

- Remove priority construction from `_payload`/`_recommended_payload` and metadata loops in the six named files. Explicit legacy cases alone inject it locally.
- Update `fixtures/direct_schema5_forecast.json` and its normalised expected fixture; leave all retained values/identity/timestamps intact. These are test fixtures, not user/audit storage.
- No response handler gains new headers, tokens, timestamps or provider metadata. Preserve the production real-entry topology/clock/lifetimes used by existing runtime tests.
- Prohibited retained diagnostic keys, retained alias conflicts, raw timestamp validation, null elements, empty/partial horizons and snapshot/cache atomicity keep their existing tests. Ignoring a retired member does not broaden these contracts.

## Execution

The original worker targeted WSL attempt failed before startup with `Wsl/Service/CreateInstance/E_ACCESSDENIED`; counts for that historical attempt remain unavailable. The approved orchestrator-host focused/full gates subsequently passed with 608/1211 actual executed cases, respectively, and zero failures/errors/skips. Exact executed commands and JSON/log/JUnit pointers are in [implementation evidence](implementation-evidence.md) and [feature.md](feature.md). Both reports include the retained Recorder database case, all 80 current ledger names and all eight additions. Existing tests outside the approved inventory remain unchanged.

## Local HA reconciliation — 2026-10-24

Source: C:/git/solar/features/forecast-action-priority-removal/ha-test-migration-ledger.md. Local baseline HEAD d9c86ddcd1d57415b73c99d100f16f6a04d7d09f, working manifest 2.0.82. This reconciliation was prepared before implementation. The source's 79 top-level names all exist and match the six files. Current source also contains the class test below, so the complete local retained/replaced inventory comprises 80 existing named cases. All eight named new acceptance cases above remain required.

| Additional existing named test | Disposition | Treatment |
| --- | --- | --- |
| TestRecorderForecastAttributes.test_recorder_database_omits_only_the_full_forecast in test_forecast_schema5.py | Retained | Preserve real Recorder database coverage and its bounded/unrecorded forecast assertions after the canonical fixture loses priority. Do not delete, rename, weaken or count a required skip as completion. |

| Existing test file | Source top-level names | Class names added locally | Total existing names |
| --- | --- | --- | --- |
| test_direct_control.py | 22 | 0 | 22 |
| test_forecast_schema5.py | 36 | 1 | 37 |
| test_reserve_grid_hold.py | 8 | 0 | 8 |
| test_measured_capacity_refresh_regressions.py | 3 | 0 | 3 |
| test_reserve_grid_hold_runtime.py | 4 | 0 | 4 |
| test_use_grid_sensor.py | 6 | 0 | 6 |
| Total | 79 | 1 | 80 |

Only the three source-ledger priority-specific names are replaced. All other named tests, retained decorators/parameter sets and guard assertions stay. The five pre-existing modified files include unrelated tests in test_coordinator_helpers.py and test_init.py; preserve those tests and their new CloudUpdateEnabled-removal cases in the full gate. This feature does not own or delete them.

After implementation, record exact current focused/full WSL commands, actual passed/failed/skipped counts and reasons, symbol/whitespace checks, deviations, changed files, pre-existing-edit preservation and release version in local feature.md and sibling implementation evidence. Do not edit the Solar planning sources. Use the existing isolated SQLite cache per command if needed for required Recorder coverage; host execution is the established fallback for worker sandbox WSL denial. Planning review and source-name reconciliation are not passing test evidence.

## Implemented disposition audit — 2026-10-24

Static audit: **80 existing names = 77 retained + 3 replaced**, no other renames/deletions. All 77 retained test bodies match the baseline except the two explicitly allowed edits: removing the wrong-priority rejection from `test_live_charge_import_and_hold_ignore_retired_permissions`, and replacing the retired equality-list member with canonical absence in `test_complete_schema5_contract_survives_strict_normalization`. Every retained decorator/parameter set is unchanged. For the three replacements, the retained action/schema/diagnostics combinations match after removing only the joint priority column. The schema-8 metadata/action/time/advisory/virtual guards remain. The Recorder class body, SQLite skip guard and database assertions are unchanged.

| New name | Parameter cases (static inventory and confirmed passing in each host JUnit) |
| --- | ---: |
| `test_priority_free_forecast_round_trips_and_executes` | 36 |
| `test_legacy_priority_aliases_and_values_are_discarded` | 108 |
| `test_retired_priority_alias_conflicts_are_ignored` | 4 |
| `test_retained_alias_conflicts_still_reject_atomically` | 12 |
| `test_priority_removal_preserves_command_metadata_and_expiry_guards` | 60 |
| `test_priority_removal_preserves_none_and_unsupported_action_paths` | 4 |
| `test_old_normalised_priority_is_not_restored_into_direct_model` | 27 |
| `test_priority_free_refresh_keeps_runtime_state_entry_local` | 1 |
| Total | 252 |

The retained-alias test also covers missing metadata/export fields, prohibited retained secrets, invalid diagnostics, null/missing/partial periods and invalid retained numeric types through raw parsing and real HTTP refresh/stale publication. The no-action test preserves null/empty forecast handling and complete empty-horizon policy. The refresh test uses real config entries, coordinator, runtime, sensors and Recorder serialization, with only external HTTP/MQTT/docs boundaries stubbed and a frozen deterministic clock. It checks equal-hash diagnostic replacement, repeated-publication suppression, stale fallback and an independent entry.

Current fixtures remove two wire priority members and one normalized member, with every retained JSON value and line unchanged. Explicit legacy tests inject retired members locally. No extra test module needed a fixture dependency correction. Unrelated CloudUpdateEnabled tests remain byte-identical and passed in the full WSL gate. Detailed original/current name mappings, decorator/body checks and fixture/preservation proof remain in the historical `.agent-work/tasks/ha-action-priority-removal/static-audit.json`; current execution/preservation reconciliation is in `host-reconciliation.json` and `validation.json` beside it. Static evidence is supplemented by actual skip-free host coverage, not treated as execution.

## Host execution reconciliation — 2026-10-24

The seven-file focused gate passed 608 cases in 21.35s; the full integration gate passed 1211 cases in 40.91s. Both exit codes are 0 and both JUnit suites report zero failures/errors/skips. Each contains all 80 current names (77 retained/3 approved replacements), all eight additions (252 passing parameter cases), and `TestRecorderForecastAttributes.test_recorder_database_omits_only_the_full_forecast`. The full gate includes the preserved unrelated CloudUpdateEnabled tests. Counts overlap across gates and must not be added as unique coverage.

Commands use existing `.venv-wsl`, `-rs`, per-gate basetemp/JUnit paths under `.agent-work`, pytest cache under `.agent-work/cache/pytest`, and existing SQLite 3.54.1 via per-command `LD_LIBRARY_PATH`. Exact executable/arguments/exit codes, clean logs and JUnit records: `.agent-work/test-results/forecast-action-priority-removal-host/{focused-1,full-1}.{json,log,xml}`. No dependency/system/guard/configuration change was needed.

Reconciliation preserves all 14 application/test hashes, both unrelated test baseline hashes and the dated planning review. Manifest remains the single working patch bump `2.0.82` to `2.0.83`. Final `git -c core.safecrlf=false diff --check` passes. No test/static sweep was repeated, no product/test/fixture edits or scope deviations were needed, and no deployment occurred. Complete combined inventory: `.agent-work/tasks/ha-action-priority-removal/combined-inventory.json`. All five approved acceptance criteria are satisfied; no required gate remains unexecuted.
