# Forecast diagnostics HA test migration ledger

Status: implemented / ready_for_review, 2026-10-22 against d65d3ec. All 253 original dispositions, 20 required additions, seven extra regressions and the adjacent retained test_init test are covered. Host focused-2: 505 passed; targeted-1: 30 passed; full-2: 859 passed; all exit0, zero failures/skips, including zero required skips and executed real Recorder DB coverage. Orchestrator acceptance is pending. Historical attempt evidence below is unchanged; final evidence supersedes earlier pending/failure status.

This local ledger carries the HA-only named dispositions from C:/git/solar/features/remove-simulation/test-migration-ledger.md, followed by required prerequisite and schema-8 additions. The source removal and diagnostics companions govern behavior. Existing named tests and parameter sets remain unless the removal ledger explicitly retires/replaces the corresponding remote feature. Schema 8 removes or renames no existing test. Preserve retained behavior even when an old test name contains a retired term. Existing registration-cache and authentication regressions remain required.

The tables below are copied from the source HA sections; Solar test tables are excluded. See feature.md for exact implementation inventory, combined WSL gates, routing and acceptance criteria.
## HA

### tests/components/horizoniq/simulation/test_simulation.py

| Existing named test | Disposition |
| --- | --- |
| `test_idle_and_zero_time_are_unchanged` | Retained — preserve purpose; update reduced-contract fixtures/schema/mode only |
| `test_self_consumption_and_battery_supported_load` | Retained — preserve purpose; update reduced-contract fixtures/schema/mode only |
| `test_grid_charging_and_solar_charging_apply_efficiency` | Retained — preserve purpose; update reduced-contract fixtures/schema/mode only |
| `test_deliberate_export_and_residual_grid_after_reserve_clamp` | Retained — preserve purpose; update reduced-contract fixtures/schema/mode only |
| `test_capacity_and_power_limits_apply` | Retained — preserve purpose; update reduced-contract fixtures/schema/mode only |
| `test_invalid_or_expired_commands_fallback_explicitly` | Retained — preserve purpose; update reduced-contract fixtures/schema/mode only |
| `test_negative_time_and_nonfinite_are_rejected` | Retained — preserve purpose; update reduced-contract fixtures/schema/mode only |
| `test_balance_and_cumulative_ledger_are_explicit` | Retained — preserve purpose; update reduced-contract fixtures/schema/mode only |
| `test_normal_ticks_never_create_manual_adjustments` | Retained — preserve purpose; update reduced-contract fixtures/schema/mode only |
| `test_clock_rates_step_reset_and_isolation` | Retained — preserve purpose; update reduced-contract fixtures/schema/mode only |
| `test_accelerated_clock_rates` | Retained — preserve purpose; update reduced-contract fixtures/schema/mode only |
| `test_profile_validation_cursor_and_limit` | Retained — preserve purpose; update reduced-contract fixtures/schema/mode only |
| `test_snapshot_round_trip_reproduces_next_step_exactly` | Retained — preserve purpose; update reduced-contract fixtures/schema/mode only |

### tests/components/horizoniq/test_cross_repo_broker.py

| Existing named test | Disposition |
| --- | --- |
| `test_real_broker_command_atomicity_and_retained_input_safety` | Removed — obsolete Solar peer protocol; HA-local atomic command and retained-input tests retained |
| `test_real_broker_replay_failure_is_peer_driven_and_state_neutral` | Removed — deleted remote replay protocol and replay-api-failure fault |
| `test_real_broker_status_schema_two_and_two_entry_isolation` | Removed — obsolete Solar peer protocol; HA-local status and two-entry isolation tests retained |

### tests/components/horizoniq/test_direct_control.py

| Existing named test | Disposition |
| --- | --- |
| `test_live_charge_and_import_are_clamped_to_virtual_limits` | Retained — preserve purpose; update reduced-contract fixtures/schema/mode only |
| `test_live_charge_import_and_hold_ignore_retired_permissions` | Retained — preserve purpose; update reduced-contract fixtures/schema/mode only |
| `test_replay_and_virtual_export_need_no_profile_permission` | Replaced by test_virtual_export_needs_no_profile_permission — preserve normal virtual recommendation power and authority assertions |
| `test_complete_schema5_fixture_normalizes_and_drives_direct_charge` | Retained — preserve purpose; update reduced-contract fixtures/schema/mode only |
| `test_schema6_forecast_normalizes_without_export_control_side_effects` | Retained — preserve purpose; update reduced-contract fixtures/schema/mode only |
| `test_virtual_recommendations_ignore_production_adapter_capabilities` | Retained — preserve purpose; update reduced-contract fixtures/schema/mode only |
| `test_live_control_never_uses_a_generic_recommendation` | Retained — preserve purpose; update reduced-contract fixtures/schema/mode only |
| `test_virtual_recommendation_rejects_stale_invalid_or_wrong_period_data` | Retained — preserve purpose; update reduced-contract fixtures/schema/mode only |
| `test_virtual_import_for_export_then_profit_export_changes_soc` | Retained — preserve purpose; update reduced-contract fixtures/schema/mode only |
| `test_virtual_refresh_has_no_client_control_capability_override` | Retained — preserve purpose; update reduced-contract fixtures/schema/mode only |
| `test_unload_cancels_only_its_local_virtual_recommendation` | Retained — preserve purpose; update reduced-contract fixtures/schema/mode only |
| `test_runtime_maps_explicit_stale_snapshot_to_fallback_stale_not_missing` | Retained — preserve purpose; update reduced-contract fixtures/schema/mode only |
| `test_runtime_maps_explicit_missing_snapshot_to_fallback_missing` | Retained — preserve purpose; update reduced-contract fixtures/schema/mode only |
| `test_runtime_maps_fresh_snapshot_without_direct_model_to_fallback_invalid` | Retained — preserve purpose; update reduced-contract fixtures/schema/mode only |
| `test_live_none_with_null_command_metadata_is_safe_self_consumption` | Retained — preserve purpose; update reduced-contract fixtures/schema/mode only |
| `test_runtime_marks_a_valid_none_forecast_healthy` | Retained — preserve purpose; update reduced-contract fixtures/schema/mode only |
| `test_raw_api_to_coordinator_model_to_runtime_boundary_for_no_action` | Retained — preserve purpose; update reduced-contract fixtures/schema/mode only |
| `test_paused_runtime_stages_forecasts_and_reset_reports_awaiting` | Retained — preserve purpose; update reduced-contract fixtures/schema/mode only |
| `test_live_advisory_and_expired_actions_are_rejected` | Retained — preserve purpose; update reduced-contract fixtures/schema/mode only |
| `test_missing_or_wrong_schema5_fields_are_rejected` | Retained — preserve purpose; update reduced-contract fixtures/schema/mode only |
| `test_replay_export_uses_half_hour_power_and_no_command_identity` | Removed — pure parse_replay_command feature is deleted |

### tests/components/horizoniq/test_entities.py

| Existing named test | Disposition |
| --- | --- |
| `test_monetary_sensor_exposes_value_currency_and_environment` | Retained — preserve purpose; update reduced-contract fixtures/schema/mode only |
| `test_binary_sensors_reflect_should_import_state` | Retained — preserve purpose; update reduced-contract fixtures/schema/mode only |
| `test_live_export_mirrors_snapshot_without_typed_diagnostics` | Retained — preserve purpose; update reduced-contract fixtures/schema/mode only |
| `test_should_import_false_does_not_imply_export` | Retained — preserve purpose; update reduced-contract fixtures/schema/mode only |
| `test_export_mirrors_backend_should_export_without_action_inference` | Retained — preserve purpose; update reduced-contract fixtures/schema/mode only |
| `test_export_reads_backend_boolean_and_has_bounded_attributes` | Retained — preserve purpose; update reduced-contract fixtures/schema/mode only |
| `test_export_snapshot_boolean_is_not_overridden_by_optional_diagnostics` | Retained — preserve purpose; update reduced-contract fixtures/schema/mode only |
| `test_export_entities_are_entry_local` | Retained — preserve purpose; update reduced-contract fixtures/schema/mode only |
| `test_forecast_cadence_sensor_exposes_minutes_and_environment` | Retained — preserve purpose; update reduced-contract fixtures/schema/mode only |
| `test_forecast_cadence_sensor_falls_back_to_effective_interval` | Retained — preserve purpose; update reduced-contract fixtures/schema/mode only |
| `test_forecast_detail_sensor_exposes_only_a_bounded_summary` | Retained — preserve purpose; update reduced-contract fixtures/schema/mode only |
| `test_sandbox_forecast_diagnostics_stays_available_without_coordinator_data` | Retained — preserve purpose; update reduced-contract fixtures/schema/mode only |
| `test_forecast_detail_sensor_never_exposes_forecast_payload_values` | Retained — preserve purpose; update reduced-contract fixtures/schema/mode only |
| `test_forecast_detail_sensor_does_not_copy_trial_state` | Retained — preserve purpose; update reduced-contract fixtures/schema/mode only |
| `test_forecast_detail_sensor_keeps_authorization_payload_out_of_state` | Retained — preserve purpose; update reduced-contract fixtures/schema/mode only |
| `test_forecast_detail_sensor_is_bounded_at_maximum_horizon` | Retained — preserve purpose; update reduced-contract fixtures/schema/mode only |
| `test_trial_status_sensor_exposes_trial_state` | Retained — preserve purpose; update reduced-contract fixtures/schema/mode only |
| `test_trial_status_sensor_falls_back_to_eligibility_state` | Retained — preserve purpose; update reduced-contract fixtures/schema/mode only |
| `test_trial_status_sensor_stays_available_with_cached_trial_state` | Retained — preserve purpose; update reduced-contract fixtures/schema/mode only |
| `test_trial_status_sensor_exposes_authorization_state` | Retained — preserve purpose; update reduced-contract fixtures/schema/mode only |
| `test_bms_sensor_uses_current_period_when_forecast_state_missing` | Retained — preserve purpose; update reduced-contract fixtures/schema/mode only |
| `test_clear_registration_button_calls_coordinator_refresh` | Retained — preserve purpose; update reduced-contract fixtures/schema/mode only |
| `test_default_environment_unique_ids_include_entry_id` | Retained — preserve purpose; update reduced-contract fixtures/schema/mode only |
| `test_default_environment_names_remain_unchanged` | Retained — preserve purpose; update reduced-contract fixtures/schema/mode only |
| `test_sandbox_environment_names_are_prefixed` | Retained — preserve purpose; update reduced-contract fixtures/schema/mode only |

### tests/components/horizoniq/test_forecast_schema5.py

| Existing named test | Disposition |
| --- | --- |
| `test_complete_schema5_contract_survives_strict_normalization` | Retained — preserve purpose; update reduced-contract fixtures/schema/mode only |
| `test_old_and_new_profiles_normalize_to_identical_physical_profile` | Retained — preserve purpose; update reduced-contract fixtures/schema/mode only |
| `test_retained_physical_profile_validation_is_unchanged` | Retained — preserve purpose; update reduced-contract fixtures/schema/mode only |
| `test_retired_profile_aliases_reject_nested_diagnostic_secrets` | Retained — preserve purpose; update reduced-contract fixtures/schema/mode only |
| `test_new_profile_survives_real_coordinator_refresh` | Retained — preserve purpose; update reduced-contract fixtures/schema/mode only |
| `test_schema6_requires_and_preserves_backend_should_export` | Retained — preserve purpose; update reduced-contract fixtures/schema/mode only |
| `test_schema6_rejects_missing_or_non_boolean_should_export` | Retained — preserve purpose; update reduced-contract fixtures/schema/mode only |
| `test_schema6_rejects_simultaneous_import_and_export` | Retained — preserve purpose; update reduced-contract fixtures/schema/mode only |
| `test_complete_solar_dto_alias_fixtures_normalize_once` | Retained — preserve purpose; update reduced-contract fixtures/schema/mode only |
| `test_conflicting_schema5_wire_aliases_are_rejected_atomically` | Retained — preserve purpose; update reduced-contract fixtures/schema/mode only |
| `test_schema5_contract_rejects_incomplete_period_atomically` | Retained — preserve purpose; update reduced-contract fixtures/schema/mode only |
| `test_schema5_contract_rejects_transport_secrets_in_diagnostics_objects` | Retained — preserve purpose; update reduced-contract fixtures/schema/mode only |
| `test_schema5_contract_omits_top_level_transport_metadata` | Retained — preserve purpose; update reduced-contract fixtures/schema/mode only |
| `test_malformed_schema5_refresh_keeps_the_last_complete_plan_as_stale` | Retained — preserve purpose; update reduced-contract fixtures/schema/mode only |
| `test_three_coordinators_keep_schema5_diagnostics_entry_local` | Retained — preserve purpose; update reduced-contract fixtures/schema/mode only |
| `test_schema5_preserves_all_action_semantics` | Retained — preserve purpose; update reduced-contract fixtures/schema/mode only |
| `test_import_for_export_decision_keeps_exact_backend_reason_codes` | Retained — preserve purpose; update reduced-contract fixtures/schema/mode only |
| `test_import_for_export_decision_selected_and_disabled` | Retained — preserve purpose; update reduced-contract fixtures/schema/mode only |
| `test_import_for_export_uses_the_action_authoritative_for_each_plan_kind` | Retained — preserve purpose; update reduced-contract fixtures/schema/mode only |
| `test_zero_period_schema5_forecast_is_unavailable_and_kept_complete` | Retained — preserve purpose; update reduced-contract fixtures/schema/mode only |
| `test_current_schema5_period_uses_utc_half_hour_boundaries` | Retained — preserve purpose; update reduced-contract fixtures/schema/mode only |
| `test_stale_last_good_forecast_remains_visible_after_refresh_failure` | Retained — preserve purpose; update reduced-contract fixtures/schema/mode only |
| `test_full_horizon_is_explicitly_unrecorded` | Retained — preserve purpose; update reduced-contract fixtures/schema/mode only |
| `test_recorder_serializes_only_bounded_forecast_diagnostics` | Retained — preserve purpose; update reduced-contract fixtures/schema/mode only |
| `test_recorder_database_omits_only_the_full_forecast` | Retained — preserve purpose; update reduced-contract fixtures/schema/mode only |

### tests/components/horizoniq/test_reserve_grid_hold_runtime.py

| Existing named test | Disposition |
| --- | --- |
| `test_real_entry_holds_for_four_hours_then_charges` | Retained — preserve purpose; update reduced-contract fixtures/schema/mode only |
| `test_fresh_hold_replaces_export_without_retaining_export_power` | Retained — preserve purpose; update reduced-contract fixtures/schema/mode only |
| `test_hold_expiry_stale_refresh_and_entry_lifecycle_remain_isolated` | Retained — preserve purpose; update reduced-contract fixtures/schema/mode only |
| `test_hold_status_and_restore_use_existing_wire_and_storage_contracts` | Retained — preserve purpose; update reduced-contract fixtures/schema/mode only |

### tests/components/horizoniq/test_reserve_grid_hold.py

| Existing named test | Disposition |
| --- | --- |
| `test_all_direct_use_grid_paths_select_grid_preservation` | Retained — preserve purpose; update reduced-contract fixtures/schema/mode only |
| `test_live_priorities_match_each_supported_schema` | Retained — preserve purpose; update reduced-contract fixtures/schema/mode only |
| `test_hold_uses_actual_load_and_solar` | Retained — preserve purpose; update reduced-contract fixtures/schema/mode only |
| `test_hold_window_and_invalid_setpoint_use_existing_fallbacks` | Retained — preserve purpose; update reduced-contract fixtures/schema/mode only |
| `test_hold_snapshot_round_trip_and_invalid_restore_are_atomic` | Retained — preserve purpose; update reduced-contract fixtures/schema/mode only |
| `test_partial_period_command_uses_remaining_time_and_full_slot_solar_power` | Retained — preserve purpose; update reduced-contract fixtures/schema/mode only |
| `test_replay_snapshot_restore_retains_valid_hold_and_rejects_invalid_atomically` | Replaced by test_manual_snapshot_restore_retains_valid_hold_and_rejects_invalid_atomically — use schema5 local manual snapshot, retain None setpoint and atomic invalid rejection |
| `test_live_unsupported_action_cannot_become_a_grid_hold` | Retained — preserve purpose; update reduced-contract fixtures/schema/mode only |

### tests/components/horizoniq/test_sandbox_faults.py

| Existing named test | Disposition |
| --- | --- |
| `test_every_fault_kind_is_bounded_and_immutable` | Retained — preserve purpose; update reduced-contract fixtures/schema/mode only |
| `test_fault_validation_limits_precedence_and_unknown_data` | Retained — preserve purpose; update reduced-contract fixtures/schema/mode only |
| `test_fault_runtime_store_snapshot_and_no_effects` | Retained — preserve purpose; update reduced-contract fixtures/schema/mode only |
| `test_outbound_faults_are_scoped_fifo_and_effect_free_outside_publication` | Retained — preserve purpose; update reduced-contract fixtures/schema/mode only |
| `test_telemetry_disconnect_and_cleanup_faults` | Retained — preserve purpose; update reduced-contract fixtures/schema/mode only |
| `test_replay_command_and_runtime_restart_faults_are_local` | Replaced by test_command_and_runtime_restart_faults_are_local — preserve command/restart isolation, remove retired replay_api_failure branch |
| `test_fault_corruption_fails_closed` | Retained — preserve purpose; update reduced-contract fixtures/schema/mode only |

### tests/components/horizoniq/test_sandbox_profiles.py

| Existing named test | Disposition |
| --- | --- |
| `test_json_csv_and_aggregation_are_canonical_and_pure` | Removed — retired remote/testing contract; normal live/physics counterparts covered by new regressions |
| `test_profile_validation_rejects_gaps_invalid_rates_and_naive_timestamps` | Removed — retired remote/testing contract; normal live/physics counterparts covered by new regressions |
| `test_profile_files_are_entry_scoped_and_playback_splits_boundaries` | Removed — retired remote/testing contract; normal live/physics counterparts covered by new regressions |
| `test_changed_profile_pauses_restore_without_mqtt_or_backend` | Removed — retired remote/testing contract; normal live/physics counterparts covered by new regressions |

### tests/components/horizoniq/test_sandbox_replay_contract.py

| Existing named test | Disposition |
| --- | --- |
| `test_request_json_shape_units_negative_import_and_absent_sensitive_fields` | Removed — retired remote/testing contract; normal live/physics counterparts covered by new regressions |
| `test_request_horizon_order_capacity_and_size_boundaries` | Removed — retired remote/testing contract; normal live/physics counterparts covered by new regressions |
| `test_stored_request_parser_rejects_unknown_forbidden_and_invalid_fields` | Removed — retired remote/testing contract; normal live/physics counterparts covered by new regressions |
| `test_simulated_failure_flag_is_optional_strict_and_hash_bound` | Removed — retired remote/testing contract; normal live/physics counterparts covered by new regressions |
| `test_local_hash_and_replay_id_collision_guard_are_deterministic` | Removed — retired remote/testing contract; normal live/physics counterparts covered by new regressions |
| `test_sandbox_replay_topics_reject_non_generated_gx_ids` | Removed — retired remote/testing contract; normal live/physics counterparts covered by new regressions |
| `test_status_identity_schema_and_transition_validation_are_strict` | Removed — retired remote/testing contract; normal live/physics counterparts covered by new regressions |
| `test_clock_reset_sequence_paused_heartbeat_and_backwards_time` | Removed — retired remote/testing contract; normal live/physics counterparts covered by new regressions |
| `test_replay_session_value_data_is_versioned_and_side_effect_free` | Removed — retired remote/testing contract; normal live/physics counterparts covered by new regressions |

### tests/components/horizoniq/test_sandbox_replay_orchestration.py

| Existing named test | Disposition |
| --- | --- |
| `test_ready_starts_once_and_publishes_one_reset_clock` | Removed — retired remote/testing contract; normal live/physics counterparts covered by new regressions |
| `test_boundary_completion_stop_and_telemetry_remain_local` | Removed — retired remote/testing contract; normal live/physics counterparts covered by new regressions |
| `test_paused_heartbeat_and_isolation_do_not_advance_other_entry` | Removed — retired remote/testing contract; normal live/physics counterparts covered by new regressions |
| `test_clock_rate_and_delayed_tick_preserve_deterministic_physics` | Removed — retired remote/testing contract; normal live/physics counterparts covered by new regressions |

### tests/components/horizoniq/test_sandbox_replay_runtime.py

| Existing named test | Disposition |
| --- | --- |
| `test_request_uses_exact_topics_profile_settings_and_non_retained_publish` | Removed — retired remote/testing contract; normal live/physics counterparts covered by new regressions |
| `test_toggle_defaults_and_invalid_values_fail_closed` | Removed — retired remote/testing contract; normal live/physics counterparts covered by new regressions |
| `test_status_transitions_timeout_failures_and_late_callbacks_are_local` | Removed — retired remote/testing contract; normal live/physics counterparts covered by new regressions |
| `test_rejected_failed_publish_failure_and_explicit_retry` | Removed — retired remote/testing contract; normal live/physics counterparts covered by new regressions |
| `test_simulated_api_failure_waits_for_matching_node_red_failure` | Removed — retired remote/testing contract; normal live/physics counterparts covered by new regressions |
| `test_simulated_api_failure_retry_restarts_normally_with_new_identity` | Removed — retired remote/testing contract; normal live/physics counterparts covered by new regressions |
| `test_simulated_failure_request_keeps_existing_transport_fault_precedence` | Removed — retired remote/testing contract; normal live/physics counterparts covered by new regressions |
| `test_two_and_three_entries_have_no_replay_crosstalk` | Removed — retired remote/testing contract; normal live/physics counterparts covered by new regressions |
| `test_schema_two_migrates_and_restart_reconstructs_with_one_publication` | Removed — retired remote/testing contract; normal live/physics counterparts covered by new regressions |
| `test_schema_six_defaults_flag_and_restart_republishes_flagged_request` | Removed — retired remote/testing contract; normal live/physics counterparts covered by new regressions |
| `test_replay_status_subscription_failure_keeps_existing_enable_rollback` | Removed — retired remote/testing contract; normal live/physics counterparts covered by new regressions |
| `test_snapshot_restore_and_storage_exclude_profile_payload_or_backend_data` | Removed — retired remote/testing contract; normal live/physics counterparts covered by new regressions |

### tests/components/horizoniq/test_sandbox_runtime.py

| Existing named test | Disposition |
| --- | --- |
| `test_simulator_configuration_is_sandbox_and_registration_scoped` | Retained — preserve purpose; update reduced-contract fixtures/schema/mode only |
| `test_runtime_lifecycle_and_step_are_isolated` | Retained — preserve purpose; update reduced-contract fixtures/schema/mode only |
| `test_unload_prevents_late_mqtt_callbacks_from_mutating_state` | Retained — preserve purpose; update reduced-contract fixtures/schema/mode only |
| `test_failed_mqtt_setup_cleans_up_only_its_runtime` | Retained — preserve purpose; update reduced-contract fixtures/schema/mode only |
| `test_virtual_mode_external_power_uses_physics_and_expires` | Retained — preserve purpose; update reduced-contract fixtures/schema/mode only |
| `test_external_power_rejects_wrong_mode_source_and_duration` | Retained — preserve purpose; update reduced-contract fixtures/schema/mode only |
| `test_mqtt_setup_is_coordinator_ordered_and_entry_local` | Retained — preserve purpose; update reduced-contract fixtures/schema/mode only |
| `test_runtime_ignores_invalid_issued_metadata_and_unstaged_victron_write` | Retained — preserve purpose; update reduced-contract fixtures/schema/mode only |
| `test_registration_and_topic_identity_fail_closed` | Retained — preserve purpose; update reduced-contract fixtures/schema/mode only |

### tests/components/horizoniq/test_sandbox_soc_control.py

| Existing named test | Disposition |
| --- | --- |
| `test_virtual_entities_remain_available_when_runtime_is_disabled_or_offline` | Retained — preserve purpose; update reduced-contract fixtures/schema/mode only |
| `test_service_and_number_update_paused_virtual_battery_entities` | Retained — preserve purpose; update reduced-contract fixtures/schema/mode only |
| `test_soc_validation_persistence_snapshots_and_isolation` | Retained — preserve purpose; update reduced-contract fixtures/schema/mode only |

### tests/components/horizoniq/test_sandbox_status_mqtt.py

| Existing named test | Disposition |
| --- | --- |
| `test_exact_schema_two_payloads_triggers_and_semantic_coalescing` | Retained — preserve purpose; update reduced-contract fixtures/schema/mode only |
| `test_simulator_state_mapping_and_diagnostic_only_reason` | Retained — preserve purpose; update reduced-contract fixtures/schema/mode only |
| `test_fault_configured_mapping_clear_active_bounds_and_unique_kinds` | Retained — preserve purpose; update reduced-contract fixtures/schema/mode only |
| `test_status_parser_rejects_schema_one_encoded_data_and_invalid_bounds` | Retained — preserve purpose; update reduced-contract fixtures/schema/mode only |
| `test_node_red_status_rejects_retained_stale_invalid_and_cross_entry` | Retained — preserve purpose; update reduced-contract fixtures/schema/mode only |
| `test_fault_bridge_reconnect_teardown_and_three_entry_isolation` | Retained — preserve purpose; update reduced-contract fixtures/schema/mode only |

### tests/components/horizoniq/test_sandbox_storage.py

| Existing named test | Disposition |
| --- | --- |
| `test_clean_setup_has_disabled_default_without_store` | Retained — preserve purpose; update reduced-contract fixtures/schema/mode only |
| `test_storage_restores_entry_local_mode_and_charging_source` | Retained — preserve purpose; update reduced-contract fixtures/schema/mode only |
| `test_virtual_restore_ignores_stale_clock_without_simulating_downtime` | Retained — preserve purpose; update reduced-contract fixtures/schema/mode only |
| `test_schema_twelve_mode_migration_is_idempotent_and_mode_aware` | Retained — preserve purpose; update reduced-contract fixtures/schema/mode only |
| `test_virtual_restore_rejects_invalid_core_battery_state` | Retained — preserve purpose; update reduced-contract fixtures/schema/mode only |
| `test_storage_restore_failures_are_staged_sanitized_and_non_destructive` | Retained — preserve purpose; update reduced-contract fixtures/schema/mode only |
| `test_storage_restore_keeps_known_sanitized_validation_reason` | Retained — preserve purpose; update reduced-contract fixtures/schema/mode only |
| `test_save_reload_restore_preserves_state_without_time_jump` | Retained — preserve purpose; update reduced-contract fixtures/schema/mode only |
| `test_enabled_runtime_restart_restores_only_its_clock_and_task` | Retained — preserve purpose; update reduced-contract fixtures/schema/mode only |
| `test_three_entries_keep_records_and_snapshots_isolated` | Retained — preserve purpose; update reduced-contract fixtures/schema/mode only |
| `test_identity_mismatch_and_invalid_records_fall_back_without_deletion` | Retained — preserve purpose; update reduced-contract fixtures/schema/mode only |
| `test_schema_one_record_migrates_without_losing_state_or_snapshots` | Retained — preserve purpose; update reduced-contract fixtures/schema/mode only |
| `test_schema_ten_ledger_migration_resets_only_corrupted_ledgers` | Retained — preserve purpose; update reduced-contract fixtures/schema/mode only |
| `test_reserve_validation_rejects_snapshot_atomically` | Retained — preserve purpose; update reduced-contract fixtures/schema/mode only |
| `test_named_snapshot_lifecycle_limit_and_atomic_restore` | Retained — preserve purpose; update reduced-contract fixtures/schema/mode only |
| `test_snapshot_restore_discards_observed_node_red_status` | Retained — preserve purpose; update reduced-contract fixtures/schema/mode only |
| `test_unload_flushes_and_removal_deletes_only_own_store` | Retained — preserve purpose; update reduced-contract fixtures/schema/mode only |
| `test_serialized_storage_excludes_secrets_and_actual_telemetry` | Retained — preserve purpose; update reduced-contract fixtures/schema/mode only |

### tests/components/horizoniq/test_use_grid_sensor.py

| Existing named test | Disposition |
| --- | --- |
| `test_use_grid_entity_uses_current_accepted_recommendation` | Retained — preserve purpose; update reduced-contract fixtures/schema/mode only |
| `test_use_grid_entity_rejects_stale_missing_and_conflicting_state` | Retained — preserve purpose; update reduced-contract fixtures/schema/mode only |
| `test_use_grid_entity_expires_without_a_refresh` | Retained — preserve purpose; update reduced-contract fixtures/schema/mode only |
| `test_use_grid_entity_replacement_and_unload_cancel_old_deadlines` | Retained — preserve purpose; update reduced-contract fixtures/schema/mode only |
| `test_use_grid_entity_is_entry_local` | Retained — preserve purpose; update reduced-contract fixtures/schema/mode only |
| `test_use_grid_real_config_entry_expires` | Retained — preserve purpose; update reduced-contract fixtures/schema/mode only |

### tests/components/horizoniq/test_virtual_wall_clock.py

| Existing named test | Disposition |
| --- | --- |
| `test_virtual_tick_uses_monotonic_elapsed_without_clock_drift` | Retained — preserve purpose; update reduced-contract fixtures/schema/mode only |
| `test_virtual_repeated_overhead_tracks_wall_time_without_clock_drift` | Retained — preserve purpose; update reduced-contract fixtures/schema/mode only |
| `test_virtual_wall_clock_accepts_current_action_despite_stale_replay_clock` | Renamed to test_virtual_wall_clock_ignores_stale_manual_clock — normal live authority uses real UTC |
| `test_virtual_forecast_generation_becomes_effective_solar_without_backfill` | Retained — preserve purpose; update reduced-contract fixtures/schema/mode only |
| `test_virtual_forecast_solar_reselects_at_the_half_hour_boundary` | Retained — preserve purpose; update reduced-contract fixtures/schema/mode only |
| `test_invalid_virtual_forecast_generation_clears_previous_solar` | Retained — preserve purpose; update reduced-contract fixtures/schema/mode only |
| `test_repeated_current_command_id_keeps_virtual_charging` | Retained — preserve purpose; update reduced-contract fixtures/schema/mode only |
| `test_reset_restages_only_the_current_staged_fresh_snapshot_without_resetting_sequence` | Retained — preserve purpose; update reduced-contract fixtures/schema/mode only |
| `test_reset_restage_cannot_revive_fresh_control_after_newer_stale_wins_lock` | Retained — preserve purpose; update reduced-contract fixtures/schema/mode only |
| `test_virtual_action_expiry_returns_safely_to_self_consumption` | Retained — preserve purpose; update reduced-contract fixtures/schema/mode only |
| `test_virtual_command_validity_uses_wall_utc` | Retained — preserve purpose; update reduced-contract fixtures/schema/mode only |
| `test_virtual_refresh_uses_monotonic_cadence_after_failure` | Retained — preserve purpose; update reduced-contract fixtures/schema/mode only |
| `test_direct_refresh_timeout_uses_stale_snapshot_not_last_direct_forecast` | Retained — preserve purpose; update reduced-contract fixtures/schema/mode only |
| `test_fresh_recovery_after_stale_accepts_new_command_once_at_lock_boundary` | Retained — preserve purpose; update reduced-contract fixtures/schema/mode only |
| `test_virtual_timing_gap_skips_catch_up_energy` | Retained — preserve purpose; update reduced-contract fixtures/schema/mode only |
| `test_mode_transitions_preserve_energy_and_clear_only_mode_owned_state` | Retained — preserve purpose; update reduced-contract fixtures/schema/mode only |
| `test_mode_transition_reloads_only_the_owning_entry` | Retained — preserve purpose; update reduced-contract fixtures/schema/mode only |
| `test_virtual_hides_replay_only_entities` | Renamed to test_virtual_hides_manual_only_entities — preserve mode-dependent local UI coverage |
| `test_simulator_status_uses_the_active_mode_time_source` | Retained — preserve purpose; update reduced-contract fixtures/schema/mode only |
| `test_mixed_mode_entries_keep_time_and_energy_isolated` | Retained — preserve purpose; update reduced-contract fixtures/schema/mode only |

Theory-specific changes: ForecastRepositoryTests removes the simulation component InlineData row/case from action comparisons, preserving recommendation/execution/all and every non-simulation field. ForecastSnapshotPolicyTests removes its simulation-only mutation row, preserving every remaining safety field. Tests whose old helper called SandboxReplayFunction now use test-local production GraphForecast/mapper fixtures; no production test hook is added. Legacy frozen JSON fixture bytes/hashes remain unchanged where integrity guards depend on them.

JS .each and pytest parametrization remain one named test with its full applicable case matrix; no skipped cases count as validation. During implementation reconcile this ledger against framework discovery before editing; a newly discovered test must be added explicitly rather than silently dropped. Tests of production command anti-replay/security and legitimate forecaster physical replay remain unchanged.


## Additional surviving HA callers

### HA: tests/components/horizoniq/test_coordinator.py

| Existing named test | Disposition |
| --- | --- |
| `test_schema56_registration_data_persists_and_is_sent_on_next_request` | Retained — preserve production/local-physics purpose; update fixtures if necessary |
| `test_schema56_registration_data_rotates_without_hash_change` | Retained — preserve production/local-physics purpose; update fixtures if necessary |
| `test_schema56_registration_data_survives_coordinator_reload` | Retained — preserve production/local-physics purpose; update fixtures if necessary |
| `test_schema56_absent_or_invalid_registration_metadata_keeps_cached_value` | Retained — preserve production/local-physics purpose; update fixtures if necessary |
| `test_schema56_rejected_responses_do_not_replace_registration_data` | Retained — preserve production/local-physics purpose; update fixtures if necessary |
| `test_schema56_cached_registration_is_not_exposed_by_sensors_or_logs` | Retained — preserve production/local-physics purpose; update fixtures if necessary |
| `test_sandbox_forecast_request_has_no_client_control_capability` | Retained — preserve production/local-physics purpose; update fixtures if necessary |
| `test_coordinator_updates_cached_values_from_api` | Retained — preserve production/local-physics purpose; update fixtures if necessary |
| `test_schema6_envelope_hash_persists_and_is_sent_on_the_next_request` | Retained — preserve production/local-physics purpose; update fixtures if necessary |
| `test_stale_response_keeps_cached_hash_and_publishes_non_executable_stale_snapshot` | Retained — preserve production/local-physics purpose; update fixtures if necessary |
| `test_malformed_schema6_after_history_publishes_stale_once_then_fails_each_fetch_path` | Retained — preserve production/local-physics purpose; update fixtures if necessary |
| `test_absent_schema_or_authorization_diagnostic_after_history_is_stale_but_initial_is_missing` | Retained — preserve production/local-physics purpose; update fixtures if necessary |
| `test_legacy_direct_capable_response_remains_fresh_with_or_without_schema_history` | Retained — preserve production/local-physics purpose; update fixtures if necessary |
| `test_commit_rejects_non_integer_uncommitted_sequence_without_state_change` | Retained — preserve production/local-physics purpose; update fixtures if necessary |
| `test_exact_subscription_failure_clears_persisted_hash_but_never_publishes_executable_control` | Retained — preserve production/local-physics purpose; update fixtures if necessary |
| `test_coordinator_cancellation_does_not_publish_or_increment_sequence` | Retained — preserve production/local-physics purpose; update fixtures if necessary |
| `test_clear_registration_data_persists_and_refreshes` | Retained — preserve production/local-physics purpose; update fixtures if necessary |
| `test_sandbox_pause_prevents_forecast_http_after_initial_failure` | Retained — preserve production/local-physics purpose; update fixtures if necessary |
| `test_clear_registration_data_preserves_hash_and_makes_one_request` | Retained — preserve production/local-physics purpose; update fixtures if necessary |
| `test_forecast_request_sends_trial_headers_when_configured` | Retained — preserve production/local-physics purpose; update fixtures if necessary |
| `test_forecast_request_omits_trial_headers_when_blank` | Retained — preserve production/local-physics purpose; update fixtures if necessary |
| `test_forecast_request_uses_separate_function_key` | Retained — preserve production/local-physics purpose; update fixtures if necessary |
| `test_forecast_auth_failure_refreshes_key_and_retries_once` | Retained — preserve production/local-physics purpose; update fixtures if necessary |
| `test_coordinator_uses_trial_payload_from_unauthorized_response` | Retained — preserve production/local-physics purpose; update fixtures if necessary |
| `test_coordinator_uses_diagnostic_payload_from_plain_unauthorized_response` | Retained — preserve production/local-physics purpose; update fixtures if necessary |
| `test_coordinator_initial_failures_follow_retry_schedule` | Retained — preserve production/local-physics purpose; update fixtures if necessary |
| `test_coordinator_initial_http_failures_make_one_request_and_ignore_retry_after` | Retained — preserve production/local-physics purpose; update fixtures if necessary |
| `test_coordinator_success_resets_initial_retry_state_and_later_uses_cadence` | Retained — preserve production/local-physics purpose; update fixtures if necessary |
| `test_exact_subscription_failure_stops_polling_and_clears_cache` | Retained — preserve production/local-physics purpose; update fixtures if necessary |

### HA: tests/components/horizoniq/test_direct_forecast_e2e.py

| Existing named test | Disposition |
| --- | --- |
| `test_paused_entry_processes_real_coordinator_refresh_without_mqtt` | Retained — preserve production/local-physics purpose; update fixtures if necessary |
| `test_real_schema5_refresh_exposes_complete_entry_local_diagnostics` | Retained — preserve production/local-physics purpose; update fixtures if necessary |
| `test_late_coordinator_update_after_unload_is_inert` | Retained — preserve production/local-physics purpose; update fixtures if necessary |
| `test_two_paused_entries_stage_isolated_forecasts` | Retained — preserve production/local-physics purpose; update fixtures if necessary |
| `test_newer_invalid_fresh_blocks_queued_older_valid_fresh` | Retained — preserve production/local-physics purpose; update fixtures if necessary |
| `test_non_fresh_snapshot_with_direct_data_is_invalid_safe` | Retained — preserve production/local-physics purpose; update fixtures if necessary |
| `test_queued_older_stale_listener_cannot_overwrite_newer_fresh_forecast` | Retained — preserve production/local-physics purpose; update fixtures if necessary |
| `test_newer_stale_listener_clears_prior_fresh_virtual_export_without_accepting_a_command` | Retained — preserve production/local-physics purpose; update fixtures if necessary |
| `test_unknown_or_invalid_publication_sequence_is_a_runtime_noop` | Retained — preserve production/local-physics purpose; update fixtures if necessary |

### HA: tests/components/horizoniq/test_sandbox_command_lifecycle.py

| Existing named test | Disposition |
| --- | --- |
| `test_issued_received_three_writes_and_applied_are_atomic` | Retained — preserve production/local-physics purpose; update fixtures if necessary |
| `test_retained_invalid_expired_duplicate_and_fault_ordering` | Retained — preserve production/local-physics purpose; update fixtures if necessary |
| `test_mismatch_timeout_expiry_and_teardown_fail_safe` | Retained — preserve production/local-physics purpose; update fixtures if necessary |
| `test_ledger_migration_restart_and_three_runtime_isolation` | Retained — preserve production/local-physics purpose; update fixtures if necessary |

### HA: tests/components/horizoniq/test_sandbox_mqtt_contract.py

| Existing named test | Disposition |
| --- | --- |
| `test_frozen_topic_parity_and_payload_validation` | Retained — preserve production/local-physics purpose; update fixtures if necessary |
| `test_snapshot_is_complete_non_retained_and_uses_frozen_units` | Retained — preserve production/local-physics purpose; update fixtures if necessary |
| `test_exact_subscriptions_reject_retained_writes_and_refreshes` | Retained — preserve production/local-physics purpose; update fixtures if necessary |
| `test_refresh_is_state_neutral_and_entry_isolated` | Retained — preserve production/local-physics purpose; update fixtures if necessary |
| `test_snapshot_fault_bridge_and_disable_discard_pending_publication` | Retained — preserve production/local-physics purpose; update fixtures if necessary |

### HA: tests/components/horizoniq/test_sandbox_phase5.py

| Existing named test | Disposition |
| --- | --- |
| `test_manual_controls_persist_and_status_entities_are_entry_local` | Retained — preserve production/local-physics purpose; update fixtures if necessary |
| `test_virtual_battery_ui_formats_states_and_categories` | Retained — preserve production/local-physics purpose; update fixtures if necessary |
| `test_state_of_charge_control_availability_follows_loaded_runtime` | Retained — preserve production/local-physics purpose; update fixtures if necessary |
| `test_fault_selector_uses_friendly_enum_labels` | Retained — preserve production/local-physics purpose; update fixtures if necessary |
| `test_profile_controls_expose_selection_state_and_virtual_availability` | Retained — preserve production/local-physics purpose; update fixtures if necessary |
| `test_manual_control_and_input_bounds_match_the_mqtt_contract` | Retained — preserve production/local-physics purpose; update fixtures if necessary |
| `test_snapshot_services_are_registered_and_scoped_to_owning_entry` | Retained — preserve production/local-physics purpose; update fixtures if necessary |
| `test_forecast_diagnostics_service_returns_one_complete_entry_horizon` | Retained — preserve production/local-physics purpose; update fixtures if necessary |
| `test_mutating_services_reject_inactive_and_unknown_entries` | Retained — preserve production/local-physics purpose; update fixtures if necessary |


## Required prerequisite additions

Add these to the existing schema/direct/coordinator/runtime/storage/simulation files in the source removal inventory; no new test module. Retain them when adding schema 8.

| Named regression | Required behavior |
| --- | --- |
| test_schema7_accepts_no_simulation_field | Complete schema 7 parses with no simulation field and does not serialize one |
| test_legacy5_and6_ignore_retired_simulation_field | Absent, null or extra retired fields never acquire command authority or disable valid historical live commands |
| test_replay_plan_is_rejected_without_control_mutation | Rejected for every supported version, before runtime state changes |
| test_live_command_uses_current_priority_for6_and7 | Explicit current priorities for 6/7; legacy 5 preserved; physical and action guards retained |
| test_live_virtual_battery_uses_normal_forecast_get_only | Normal virtual control uses wall-clock Forecast_Get and real live metadata |
| test_removed_replay_endpoint_is_never_called | No replay endpoint or alternative remote simulator is called |
| test_replay_state13_migrates_paused_without_remote_resume | Old replay becomes paused manual/self-consumption without restored command or network work |
| test_snapshot4_migration_preserves_battery_and_local_faults | Legacy retained physics validated atomically, replay fields discarded, faults/local scenarios retained |
| test_two_entries_removal_does_not_cross_ownership | Migration, unload and cancellation operate on the owning entry only |
| test_manual_mode_advances_local_physics_without_network_or_live_command | Manual scenario/step controls remain local; no synthetic-time cloud authority |
| test_manual_to_virtual_stays_paused_and_uses_wall_clock_on_enable | Paused transitions/reload and explicit real-time virtual enable; no automatic refresh |

Retained or extended cases must also prove future/invalid storage and snapshot rejection, current schema-5 manual-command snapshot restore, grid-preservation None setpoint/atomic invalid rejection, absent/null retired state, malformed retained physics, missing legacy mode, invalid current modes, expiry boundaries, cancellation/unload, retained MQTT safety, credential refresh and no cross-entry deletion.

## Schema-8 additions

Add to tests/components/horizoniq/test_forecast_schema5.py, except the explicitly named direct-control test. Build a test-local factory by transforming the existing historical fixture once; do not edit fixture files. Exercise real normalization/coordinator/runtime with existing external Forecast_Get stubs, without sleeps, live backend or a test service.

| Named regression | Required behavior |
| --- | --- |
| test_schema8_normalizes_nested_diagnostics_for_each_wire_style | CamelCase/PascalCase/snake_case at every nested level normalize into the single model |
| test_schema8_missing_or_null_diagnostics_does_not_disable_live_command | Missing/null diagnostics mean unavailable ledger while valid command guards/priorities remain effective |
| test_schema8_rejects_invalid_diagnostics_atomically | Wrapper scalar/list/empty object; missing/null/scalar/list/incomplete ledger; every nonfinite/bool number; nonboolean healthy; wrong tolerance; inconsistent health; exact inclusive positive/negative boundary and next representable outside value; generic safe shape/numeric error |
| test_schema8_rejects_root_ledger_and_conflicting_nested_aliases | Any root ledger alias, including null, rejected for 8; wrapper/ledger/field alias conflicts rejected atomically; unknown 9 rejected |
| test_schema8_diagnostics_reject_nested_transport_secrets | Prohibited key detection before dropping unknown fields, recursively through mappings/lists; retain existing prohibited-key error |
| test_schema8_to_dict_emits_only_nested_diagnostics | Schema 8 emits nested ledger or diagnostics null, never root; 5/6/7 retain required root ledger and distinct legacy behavior |
| test_schema8_refresh_keeps_diagnostics_entry_local_and_unrecorded | Real refresh and invalid-refresh stale-last-good preserve entry isolation, bounded sensor/recorder output, no credential/raw-diagnostic leakage |
| test_schema8_same_hash_refreshes_entry_local_diagnostics | Real coordinator accepts changed diagnostics at unchanged hash without rewriting unchanged entry configuration |
| test_schema8_live_commands_keep_current_priorities_and_guards | In test_direct_control.py: normal parsed payloads cover required charge, optional import, grid preservation, allowed virtual exports, advisory/non-live rejection, missing/null diagnostics, unchanged identity/expiry/physical guards |

Use parametrization/behavioral assertions for all required cases. Keep all 24 existing named schema tests and every surviving direct-control name from the removal tables, including replacement test_virtual_export_needs_no_profile_permission. Preserve the additive schema-7 cases. Schema 8 makes no additional deletion or rename.

## Validation evidence requirements

Record the actual focused and full WSL commands, passed/failed/skipped counts and required skip reasons. The six-file combined focused command in feature.md includes the required three-file diagnostics gate. Missing WSL or required skipped tests blocks completion. Production-reference and retained/deleted/replaced-name audits are preserved in the corrective evidence; actual passing host validation is recorded in the final section below.

### Account-a implementation attempt — 2026-10-22

Static source-name reconciliation was repeated at `d65d3ece5edc8afddde3036df8bbbb679daa1346`: 23 files, 253 listed/current test names, zero missing names and zero unlisted names. Evidence: `.agent-work/test-results/forecast-response-diagnostics-account-a/baseline-ledger-audit.json` and `baseline-ledger-summary.json`. This checks names only; parameter coverage and behavior have not been executed or changed.

The exact focused/full WSL commands from feature.md were attempted; both returned native exit `-1` with `Wsl/Service/CreateInstance/E_ACCESSDENIED` before pytest startup. Test counts and skip reasons are unavailable because no test ran. Evidence: `gate-attempts.json`, `focused.log`, and `full.log` in the same evidence directory. No native Windows Python fallback was used. Required coverage remains outstanding and blocks readiness. No tests were edited, removed, renamed or added; every planned disposition and required addition still needs implementation.


### Corrective implementation evidence - 2026-10-22

The 253 original named dispositions are implemented: 215 retained names remain, all five explicit replacement/rename destinations are present, and 33 approved retired names are absent. The two renamed Virtual tests are `test_virtual_wall_clock_ignores_stale_manual_clock` and `test_virtual_hides_manual_only_entities`. All 20 required prerequisite/schema-8 names are present in their existing test files. Seven additional regressions cover accepted tolerance boundaries, invalid retained migration physics, mode defaults/invalid current modes, and current/future snapshot validation. No new test module or historical fixture was added or changed.

Static comparison of retained test decorators against HEAD finds exactly three approved reductions: the retired sandbox_replay case in each of the two mixed plan/action tests, and the profile_restore/replay_restore stages removed with their feature. Every other retained decorator/parameter set is unchanged. The mixed export, manual grid-hold snapshot and command/restart-fault replacements retain their local behavior assertions. Six-subscription assertions reflect deletion of the one Replay-status subscription. Legacy extra simulation fields remain only in historical-input/rejection coverage.

Evidence: `.agent-work/test-results/forecast-response-diagnostics-corrective/static-audit.json`, `retained-parameter-audit.json`, `production-reference-audit.json`, `source-review.json`, `changed-files.json` and `host-gates.json`. The initial whitespace-only diff-check findings were corrected; the final result is recorded separately. At this initial corrective handoff, zero Python tests had run in the worker and host counts were unknown. The first host result below supersedes that pending status. Name/parameter reconciliation is not behavioral validation or final acceptance.


The three additional lifecycle/UI names are `test_restored_paused_modes_suppress_setup_forecast_get`, `test_manual_registry_cleanup_removes_only_owned_retired_controls` and `test_manual_input_entities_preserve_local_load_and_solar_controls`, bringing additive coverage to 20 required names plus seven extra regressions. Invalid retained-physics cases also assert that unload preserves the rejected source record. Local pause expectations replace old no-pause assertions where necessary to prevent setup refresh; this is local orchestration and performs no HTTP I/O.

### First host focused gate and mappingproxy correction - 2026-10-22

Host evidence: `.agent-work/test-results/forecast-response-diagnostics-host/focused-1.json` (exact command and exit 1) and `focused-1.log` (1 failed, 503 passed, 1 skipped in 22.88s). The sole failed name is `test_schema8_refresh_keeps_diagnostics_entry_local_and_unrecorded`. Both entry-data persistence assertions now pass ordinary `dict(...)` snapshots to `json.dumps`, preserving every existing assertion and named/parameterized disposition. No new name, deletion or rename is involved.

The required `TestRecorderForecastAttributes` DB case remains guarded at SQLite >=3.40.1; host SQLite 3.37.2 caused the historical focused-1 skip per supplied host evidence (that log lacks skip reasons). The guard and required coverage are unchanged. Subsequent focused-2 and full-2 selected isolated supported SQLite 3.54.1 and ran required Recorder coverage without skips. Earlier attempt evidence is preserved.

### Historical host gate evidence and retained-test corrections - 2026-10-22

Superseding historical pending/skip status above: focused-2 passed **505, zero skipped, 17.83s**, including required real Recorder DB coverage; full-1 failed **3, passed 856, zero skipped, 36.88s**. Exact commands and outputs remain in `.agent-work/test-results/forecast-response-diagnostics-host/{focused-2,full-1}.{json,log}`. Both selected isolated SQLite 3.54.1 per command; the existing verified provenance/build evidence is preserved.

| Named test | Current retained disposition |
| --- | --- |
| `test_sandbox_devices_are_entry_scoped_and_persist_across_unload` | Necessary adjacent `test_init.py` correction outside original inventory: awaited pause protocol is now AsyncMock. All file names/parameter sets and device identity, ownership, unload/reload persistence assertions retained. No production restore weakening. This supplements the original 253-name ledger without reclassifying it. |
| `test_exact_subscriptions_reject_retained_writes_and_refreshes` | Retained: only the retired Replay-status topic removed from exact expectation; no-wildcard, retained write/refresh safety and entry-isolation coverage preserved. |
| `test_service_and_number_update_paused_virtual_battery_entities` | Retained: exact six surviving topics expected on each of two enables, replacing stale count14; paused enable/disable, snapshot, SoC, energy ledger and physical assertions preserved. Test-local resumed-refresh stub prevents real HTTP work; unload drains HA work and asserts runtime loop/subscriptions cleared. |

No test name, decorator or parameter set changed in these three files. No fixture, test module or production change; manifest remains 2.0.81. At that handoff targeted execution and a final full run were pending; both subsequently passed. Existing six-file focused inputs are unchanged, so that passed gate need not repeat. The worker ran no Python tests and did not retry sandbox WSL. Historical failed attempt logs/reports remain untouched.

### Final passing host coverage - 2026-10-22

| Gate and exact-command/output artifacts under .agent-work/test-results/forecast-response-diagnostics-host/ | Passed | Failed | Skipped / required skipped | Duration |
| --- | --- | --- | --- | --- |
| focused-2.json / focused-2.log; six approved focused files | 505 | 0 | 0 / 0 | 17.83s |
| targeted-1.json / targeted-1.log; all tests in test_init.py, test_sandbox_mqtt_contract.py, test_sandbox_soc_control.py | 30 | 0 | 0 / 0 | 2.65s |
| full-2.json / full-2.log; tests/components/horizoniq after corrections | 859 | 0 | 0 / 0 | 30.23s |

All commands exited0, activated `.venv-wsl` and selected isolated SQLite 3.54.1 per command using `LD_LIBRARY_PATH=/mnt/c/git/ha-integration/.agent-work/cache/sqlite/3.54.1/lib`. Required real Recorder DB coverage ran under its unchanged guard. Full-2 output contains only progress and the final summary, with no teardown/network errors. Full-2 covers every file in the earlier proposed seven-file targeted gate; that selection is satisfied by full-suite coverage and is not an additional pending requirement. Product and six focused-file inputs are unchanged since focused-2; no passed gate was repeated during evidence reconciliation.

Reproduce SQLite setup with `.agent-work/tmp/forecast-response-diagnostics-host/build-sqlite.sh`. `.agent-work/cache/sqlite/3.54.1/provenance.txt` records official source `https://www.sqlite.org/2026/sqlite-autoconf-3540100.tar.gz` and verified SHA3-256 `b6ced585c750916b1052667239a12c25a7ff34e7f06e1e6e01ecb0427657d9c4` (published at `https://www.sqlite.org/download.html`); host `sqlite-build.log` records Python runtime 3.54.1. No system-library, dependency-declaration or test-guard changes.

The original 253 dispositions remain 215 retained, five approved replacements/renames and 33 removals. The 20 required additions and seven extra regressions remain; the adjacent retained test_init regression supplements rather than changes that ledger. Prior source/name/parameter evidence remains in corrective `final-ledger-summary.json`, `static-audit.json` and `retained-parameter-audit.json`. All original declarations/decorators/parameters in the three full-correction files remain, as documented by `.agent-work/test-results/forecast-response-diagnostics-full-corrections/retained-tests.json`. No fixture edits or new test modules. Complete combined inventory is `.agent-work/test-results/forecast-response-diagnostics-reconciliation/changed-files.json`.

Current host records link actual commands/counts: corrective `host-gates.json` and full-corrections `host-reruns.json`; raw host artifacts and historical worker reports remain unchanged. All six acceptance criteria in feature.md/implementation.review.md are met; ready_for_review with no remaining coverage gap. Orchestrator acceptance remains separate. Local validation only; no deployment, installation, restart, commit or push.
