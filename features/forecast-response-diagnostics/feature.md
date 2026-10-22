# Forecast response diagnostics compatibility

Status: complete; orchestrator review passed, 2026-10-22. Host focused-2 PASS (505 passed in 17.83s), targeted-1 PASS (30 passed in 2.65s) and full-2 PASS (859 passed in 30.23s), each with zero failures/skips. Required real Recorder DB coverage ran using per-command isolated SQLite 3.54.1. All six approved criteria are evidence-backed below and accepted. Single manifest bump `2.0.80` to `2.0.81`; local validation only, no deployment. Earlier attempts/results remain historical. See [implementation review](implementation.review.md).

## Goal and user outcome

Accept Solar schema-8 forecasts with nested or unavailable planned-energy diagnostics while preserving safe live control, historical schema-5/6/7 readers, entry isolation, credential refresh, and recorder limits. First complete the explicitly required HA simulation-removal prerequisite. Users retain normal virtual-battery control and HA-local manual physics without the retired cloud Replay dependency.

## Sources and approved-plan baseline

- Requested contract: [Solar HA diagnostics companion](C:/git/solar/features/forecast-response-diagnostics/ha-integration.md).
- Required predecessor: [Solar HA simulation-removal companion](C:/git/solar/features/remove-simulation/ha-integration.md), its [review](C:/git/solar/features/remove-simulation/ha-integration.review.md), and the HA sections of its [test ledger](C:/git/solar/features/remove-simulation/test-migration-ledger.md).
- Repository instructions: [AGENTS.md](../../AGENTS.md). Use the integration layout, a manifest patch increment, and WSL for Python tests.
- Local reconciled [test migration ledger](test-migration-ledger.md) and [planning review](feature.review.md).

At planning baseline d65d3ec, the prerequisite was not implemented. `forecast_schema5.py` accepts only 5/6, requires a root ledger and a period simulation action, and accepts `sandbox_replay`. `direct_control.py` has replay parsing and schema-6 equality checks for current priorities. `coordinator.py` still exposes `async_fetch_sandbox_replay`; `sandbox_runtime.py` retains remote session orchestration and Replay mode. Private state/snapshot versions are 13/4. The obsolete Solar-peer tests and helpers remain.

The existing coordinator already accepts each complete forecast in `_build_snapshot_or_stale` independently of `_update_cached_state` hash comparison. Its registration metadata refresh also operates independently of forecast hash changes. Preserve both behaviors. Schema-8 support alone would leave an incompatible prerequisite in place.

## Proposed design and sequence

Implement both HA scopes as one approved change with one patch increment, in this order. The source companions remain authoritative for their detailed contracts. Change only this HA repository; rollout and deployment remain separate.

### 1. Remove the cloud simulation contract and add schema 7

Support historical 5/6 and new 7 before adding 8. Remove typed, required, aliased and serialized `simulation_action`/`simulationAction`; ignore historical extra simulation fields without giving them command authority. Accept only `live` and `import_for_export_advisory`; reject replay plans for every schema before runtime mutation. Keep advisory non-commanding and live `executableAction` authoritative.

Remove remote replay HTTP, URL construction, request/status/clock topics, timers, heartbeat, retries, ready cache, sessions, replay-only faults, cloud-file profile playback and the five cloud-profile services. Disconnect all callers before deleting the retired modules. Preserve the normal Forecast_Get/authentication/credential-refresh topology, limits, cancellation, safe fallback and per-entry ownership. Keep HA-local physics, standard scenarios, load/solar controls, local faults, stepping, snapshots and local MQTT command safety.

Use `virtual` for normal wall-clock cloud control and `manual` for local-only physics/scenarios. Same-mode selection remains a no-op; invalid selection raises `ValueError("Sandbox operating mode is invalid")`. Stop/disable owned work, checkpoint, notify and request the existing entry reload. Both transitions remain paused after reload until explicitly enabled. Manual mode never calls Forecast_Get or validates a cloud command against synthetic time. Returning to virtual clears local commands and uses real UTC on the next explicit enable, without automatic refresh/re-enable.

Migrate private storage 13 to 14 and snapshots 4 to 5 while retaining Store version 1, existing entry keys, atomic validation, 30-second checkpoint and 20-snapshot limit. Known old replay state becomes paused manual/self-consumption with no network/resume. Missing legacy mode defaults to virtual; malformed retained data, null/unknown current mode and future schemas fail closed. Preserve retained battery/ledger/clock/local faults and unrelated named snapshots; discard retired replay session/profile fields and replay fault. Keep local scenario identity/cursor. Validate before committing; cancel owned tasks before replacement and await them on unload.

Snapshots 1/2/3/4 use the same validated decoder and migrate to 5, clearing active commands and pending replay work, setting FALLBACK_MISSING and stopped playback. Newly written schema-5 manual snapshots may restore validated local manual commands. Retain the grid-preservation `requested_grid_power_w=None` invariant and atomic invalid rejection. Use named snapshot constructor arguments to preserve faults-field ownership.

### 2. Add schema 8 to the existing normalized reader and controller

Set `LEGACY_SCHEMA_VERSION=5`, `SCHEMA_VERSION=8` and the supported set to exactly `{5,6,7,8}`. Keep one `Schema5Forecast` model; change `planned_energy_ledger` to `dict[str, object] | None`. Do not create another parsed forecast/ledger model.

| Wire contract | Accepted ledger authority | Canonical serialization |
| --- | --- | --- |
| Schemas 5/6/7 | Required complete root `plannedEnergyLedger` | Root ledger |
| Schema 8 with missing/null diagnostics | Unavailable, normalized to `None` | `diagnostics: null`, no root ledger |
| Schema 8 with diagnostics object | Required non-null complete `diagnostics.plannedEnergyLedger` | Nested ledger only |
| Schema 8 with any root ledger, including null | Reject; no root fallback | No accepted model |
| Schema 9 or any other unsupported version | Reject | No accepted model |

Add `diagnostics` and its `plannedEnergyLedger` child to the existing wire allowlist. Preserve camelCase, PascalCase and snake_case aliases and atomic conflicting-alias rejection at each level. Keep exactly the existing ten ledger fields. Missing/null wrapper is permitted on 8; an object must contain a complete non-null object ledger. Reject empty, scalar/list wrapper or ledger, missing fields, nonfinite numbers, bool-as-number, nonboolean healthy, tolerance other than `0.001`, and health inconsistent with `abs(balanceErrorKwh) <= toleranceKwh`. Accept negative finite balance error. Do not add unrelated sign restrictions.

Ignore unknown nonsecret fields as before. Before allowlist filtering, recursively inspect nested diagnostics/ledger content, including discarded unknown mappings/lists, for transport-secret keys. Preserve existing prohibited-key/conflicting-alias errors. New schema-8 shape/numeric failures use exactly `Schema-8 diagnostics are invalid.` without interpolating values. Validate the entire candidate before coordinator/runtime state changes; malformed refresh retains the last complete forecast as stale.

Use explicit `{6,7,8}` membership wherever command priority chooses the current contract; schema 5 retains legacy priorities. Keep the accepted-version set imported from the reader. Never use `>=6`. Preserve command identity, deduplication, real UTC expiry, physical limits, permitted export policies and entry ownership. Missing/null diagnostics must not disable an otherwise valid live command.

Diagnostics remain entry-local memory and existing optional client-controlled exports. Preserve bounded sensor output and recorder exclusions. No raw diagnostics storage, registration metadata, recorder attributes or logging. No additional coordinator implementation change is expected for diagnostics: same-hash complete refresh must replace diagnostics without persisting unchanged entry configuration. Coordinator/helper/model/sensor changes in the combined diff belong only to the removal prerequisite.

### 3. Reconcile tests, validate and increment the release version

Follow every named disposition in [test-migration-ledger.md](test-migration-ledger.md). Preserve all surviving named tests and their retained parameter sets, plus additive schema-7 tests. Rebase only the prerequisite's explicitly retired mixed cases; schema 8 removes/renames none.

Create a test-local schema-8 payload factory by transforming the existing fixture once, removing the root ledger and nesting it. Leave historical fixture files unchanged. Use existing external Forecast_Get stubs and real parsing/coordinator/runtime paths; no test service, new test module, sleeps or live backend dependency. Cover invalid shape/numeric inputs atomically, exact positive/negative tolerance boundaries and next representable values, aliases and secrets, same-hash refresh, stale-last-good, recorder bounds, direct action guards and entry isolation.

Increment `manifest.json` once from `2.0.80` to `2.0.81` if unchanged; otherwise increment the then-current patch once. No dependency changes or backend release.

## Exact implementation inventory

Paths below are relative to `custom_components/horizoniq/` unless otherwise stated.

Prerequisite modifications: `coordinator.py`, `coordinator_helpers.py`, `forecast_schema5.py`, `direct_control.py`, `models.py`, `sandbox_runtime.py`, `sandbox_storage.py`, `select.py`, `switch.py`, `button.py`, `services.py`, `strings.json`, `services.yaml`, `manifest.json`, `sensors/binary.py`, `sensors/diagnostic.py`, `sensors/import_for_export.py`, `simulation/models.py`, `simulation/runtime_status.py`, `simulation/snapshots.py`, `simulation/topics.py`, `simulation/faults.py`, `translations/en.json`, `local_docs/simulation.md`.

Prerequisite deletions: `simulation/replay_contract.py`, `sandbox_profiles.py`; `tests/components/horizoniq/test_sandbox_profiles.py`, `test_sandbox_replay_contract.py`, `test_sandbox_replay_orchestration.py`, `test_sandbox_replay_runtime.py`, `test_cross_repo_broker.py`; and `tests/components/horizoniq/cross_repo/{__init__.py,solar_peer.py,mqtt_adapter.py,README.md}` after their callers are disconnected. Verify every deletion is within this workspace. No new Python modules/test files.

Prerequisite surviving test modifications, all under `tests/components/horizoniq/`: `simulation/test_simulation.py`, `test_direct_control.py`, `test_entities.py`, `test_forecast_schema5.py`, `test_reserve_grid_hold_runtime.py`, `test_reserve_grid_hold.py`, `test_sandbox_faults.py`, `test_sandbox_runtime.py`, `test_sandbox_soc_control.py`, `test_sandbox_status_mqtt.py`, `test_sandbox_storage.py`, `test_use_grid_sensor.py`, `test_virtual_wall_clock.py`, `test_coordinator.py`, `test_direct_forecast_e2e.py`, `test_sandbox_command_lifecycle.py`, `test_sandbox_mqtt_contract.py`, `test_sandbox_phase5.py`. The local ledger carries all 23 modified/deleted test-file dispositions.

Schema-8 additive inventory is exactly five existing files: `forecast_schema5.py`, `direct_control.py`, `manifest.json`, `tests/components/horizoniq/test_forecast_schema5.py`, `tests/components/horizoniq/test_direct_control.py`. No additive file creation/deletion, historical fixture edits, new service/application, config/dependency change, other translation changes or Solar edits.

Planning documents may receive implementation evidence after approval. New worker prompts/logs/results belong under Git-root `.agent-work/`.

## Validation and acceptance

Run targeted affected tests during implementation; after the final scoped edits pass the combined focused gate through WSL:

```powershell
wsl bash -lc "cd /mnt/c/git/ha-integration && source .venv-wsl/bin/activate && python -m pytest tests/components/horizoniq/test_forecast_schema5.py tests/components/horizoniq/test_direct_control.py tests/components/horizoniq/test_coordinator.py tests/components/horizoniq/test_reserve_grid_hold_runtime.py tests/components/horizoniq/test_sandbox_runtime.py tests/components/horizoniq/test_sandbox_storage.py -q"
```

Then run the full completion gate once on the completed change:

```powershell
wsl bash -lc "cd /mnt/c/git/ha-integration && source .venv-wsl/bin/activate && python -m pytest tests/components/horizoniq -q"
```

The combined focused gate includes the diagnostics companion's three-file gate. Record actual commands/counts/failures and skip reasons; missing WSL or skipped required coverage blocks completion. Request host execution if the sandbox cannot access WSL. Do not substitute native Windows Python or repeat unchanged passed gates without new edits/failures.

1. Removal is complete: no production replay endpoint/topic/contract, typed simulation action or `sandbox_replay`; remaining simulation terms are classified as retained local physics/testing. Verify whole diff against both source companions and the ledger.
2. Local virtual/manual operation, transitions, cancellation, state/snapshot migration and two-entry ownership satisfy the prerequisite and all its named regressions. Local physics/scenarios/faults remain functional.
3. Exact schema-5/6/7/8 parsing, authority/serialization, aliases, schema-8 validation/error safety and unknown-9 rejection pass. No retired simulation contract is restored.
4. Normal parsed schema-8 commands preserve priorities, limits, expiry/identity and permitted actions even with unavailable diagnostics. Advisory/non-live/stale/malformed responses cannot command.
5. Real coordinator refresh verifies complete replacement, same-hash diagnostics update without entry write, stale-last-good, isolation and bounded/unrecorded diagnostics; credential-cache and authentication regressions remain intact.
6. The ledger is honored, required focused/full WSL gates pass with evidence and no required skips, and one manifest patch bump is present. All changes stay within the inventory; any justified additional scope is reported before implementation outside it.

## Routing and review

| Task | Complexity | Owner | Routing reason | Further decomposition | Required review |
| --- | --- | --- | --- | --- | --- |
| Reconcile prerequisites and schema-8 contract | Complex | Account b orchestrator | Cross-contract ownership and approval scope | Completed as one local plan | Planning review beside this file |
| Removal, migrations, schema-8 reader/control, retained/additive tests and gates | Complex; safety-sensitive validation | One account a worker, Home Assistant specialist instructions | Runtime, models, persistence and tests share invariants | One autonomous handoff; implement internally in the sequence above | Evidence-backed result, then one bounded orchestrator review |

After a separate implementation approval, use the fixed PowerShell worker launcher for account a. The worker owns detailed investigation, implementation, tests and routine corrections; account b coordinates and reviews. Native fallback is allowed only after the bridge explicitly verifies zero usable account-a allowance and available account-b allowance. No deployment, installation, HA restart, commit or push is part of this plan.

## Open questions and risks

No unresolved contract decision prevents implementation approval. The required predecessor makes this substantially larger than a five-file diagnostics patch; approval covers both ordered HA scopes. The greatest risks are old-state/snapshot atomicity, late replay callbacks after teardown, manual/virtual wall-clock separation, retained test coverage and secrets hidden in discarded diagnostic content. Existing required regressions and the additive cases address these risks and now pass the host gates. This is local validation; deployment is outside scope.

## Implementation attempt — 2026-10-22

The account-a worker inspected the approved local and Solar companions, planning review, migration ledger, repository instructions and relevant production entry points. The baseline remains `d65d3ece5edc8afddde3036df8bbbb679daa1346`, manifest `2.0.80`. A fresh static comparison reconciled all 253 existing test names across 23 affected files, with zero missing or unlisted names.

Both exact required WSL gate commands failed before Linux/pytest startup with `Wsl/Service/CreateInstance/E_ACCESSDENIED` and native exit code `-1`. No tests were collected, passed, failed or skipped; these are launcher failures, not test results. This worker's sandbox approval policy is `never`, so it cannot request the unsandboxed host execution needed to resolve the denial. Native Windows Python was not substituted.

Application/test/fixture files and the manifest remain unchanged. The worker stopped before the coupled command-authority and storage migrations because the required targeted validation cannot run in this execution environment. There is no design change, partial implementation, deployment, installation, restart, commit or push. All six acceptance criteria remain unmet. Resume the approved implementation in a worker with functioning WSL access; approval of the feature itself is already recorded in the handoff.

Changes in this attempt are limited to this status/evidence, the ledger evidence appendix and the sibling [implementation evidence](implementation.evidence.md). Exact commands, native exit codes, raw failure logs and the static audit are retained under `.agent-work/test-results/forecast-response-diagnostics-account-a/`. The dated planning review remains unchanged. No implementation or orchestrator acceptance is claimed.


## Corrective implementation - 2026-10-22

The corrective handoff resolves the execution boundary: the orchestrator successfully verified `.venv-wsl/bin/python` through approved host WSL execution. This worker did not retry known sandbox startup failures, change policy, attempt a workaround, or run native Windows Python tests. Its native Python commands only edited or statically parsed source; no application or test module was imported for execution.

The combined application/test patch is now present. Forecast schemas are exactly 5/6/7/8, current 8 and legacy 5; one normalized model owns the optional ledger. Schema 8 rejects every root ledger alias, accepts missing/null diagnostics, validates the ten nested fields, retains alias/prohibited-key errors and uses the generic safe error for new shape/numeric failures. Recursive secret screening happens before unknown diagnostic content is discarded. Live priority selection uses explicit {6,7,8} membership.

Cloud Replay endpoint, parser, sessions, readiness/heartbeat/timeout orchestration, topics, file playback, selectors and the five profile services were removed. The retired modules, peer helpers and dedicated tests were deleted only after their callers were disconnected and absolute targets verified within this workspace. Historical extra simulation fields are ignored and never serialized or promoted to authority. Normal Forecast_Get, authentication and credential/hash persistence code retain their existing paths; coordinator implementation changes only remove the retired endpoint.

Virtual uses real UTC; Manual uses only local physics/scenarios/inputs/steps and rejects live MQTT envelopes rather than validating them against synthetic time. Mode transitions retain paused reload and explicit enable. Store stays version 1; private state/snapshots are 14/5, with entry keys, checkpoint delay and snapshot limit unchanged. Older state and snapshots validate retained physics/clock/ledger/faults before commit; legacy Replay becomes paused Manual with no network/resume. Old commands and retired session/profile/fault data are sanitized, local scenario identity/cursor and unrelated snapshots retained. Current Manual snapshots retain validated local commands, including grid preservation with None setpoint. Snapshot restore cancels/awaits its loop and recreates local work without calling the backend.

The frozen simulator-status schema keeps its reserved `replayState` slot null, with no session enum or state vocabulary. This preserves the bounded non-command status shape while retiring Replay authority. The pure local profile/aggregation library remains, explicitly as required by the predecessor inventory.

Three small adjacent caller corrections were announced before editing: `sensors/__init__.py` changes Manual registration and its bounded local-cursor label; `__init__.py` cleans retired registry controls in both modes and retains Manual inputs; `number.py` exposes local Manual load/solar inputs through the existing bounds and setters. No new Python/test module, dependency, service, fixture edit, backend change, installation, restart, deployment, commit or push was introduced.

All 253 original ledger names reconcile: 215 retained, five approved replacement/rename destinations present, 33 approved removals absent. All 20 mandated addition names are present, along with seven further boundary/migration/UI regressions. Decorator comparison found only three approved retired-parameter changes: the two replay plan/action cases and the two removed profile/replay restoration stages. No other retained decorator/parameter set changed.

Static evidence is in `.agent-work/test-results/forecast-response-diagnostics-corrective/`: `static-audit.json`, `retained-parameter-audit.json`, `source-review.json`, `production-reference-audit.json`, `changed-files.json`, `diff-check.log` and the reviewed `implementation.diff`. The static audit parses 71 Python source/test files and finds no syntax errors, undefined-global candidates, unresolved absolute integration imports or unresolved runtime members. JSON and service-schema name checks pass. Historical fixture diff is empty. These are source checks, not pytest results.

At the initial corrective handoff, host gates were unexecuted as originally recorded in `host-gates.json`. The host results and corrections below supersede that historical incomplete status. The current host-gate record links the successful results; historical worker reports remain unchanged. Orchestrator final acceptance is not claimed.


Final lifecycle corrections from detailed review: restoration pauses the existing coordinator for Manual, disabled and migrated records before setup's unconditional refresh can fetch; invalid restoration also pauses and disables checkpoint writes, preserving the rejected source through unload. Explicit Virtual enable still uses normal refresh. Added `test_restored_paused_modes_suppress_setup_forecast_get` exercises the real coordinator without a backend stub. Two further UI regressions cover owning-entry registry cleanup and Manual load/solar input bounds.

Additional caller corrections were announced before editing: `__init__.py` removes retired profile registry entries in both modes and preserves Manual input entities; `number.py` exposes the existing load control in Manual and routes its solar control through the same local setter/bounds. Together with `sensors/__init__.py`, these are the three adjacent files outside the initial list. They complete the approved local-control/removal behavior without a new module, service or cloud contract. These are necessary local caller corrections to complete the approved behavior.

The runtime retains an entry-scoped HA reference separately from active loop ownership so changing modes while already paused still requests the existing entry reload. The retained owning-entry reload test now exercises both active and paused transitions plus same-mode no-op. The reference is cleared on unload and is never serialized.

## Historical first host gate and mappingproxy correction - 2026-10-22

The exact six-file focused WSL command, including artifact-routing flags, is retained in `.agent-work/test-results/forecast-response-diagnostics-host/focused-1.json`; its output is in `focused-1.log` beside it. Pytest reached execution and returned exit 1: **1 failed, 503 passed, 1 skipped in 22.88s**. This supersedes the earlier unknown-count status without changing historical evidence.

The sole failure was `test_schema8_refresh_keeps_diagnostics_entry_local_and_unrecorded`: `json.dumps` cannot serialize Home Assistant's read-only entry-data `mappingproxy`. Both final persistence assertions now serialize explicit `dict(entry.data)` snapshots. The diagnostics-persistence, entry-isolation, secret and Recorder assertions are retained. This correction changes no integration behavior, dependencies, manifest version or accepted scope; the single combined version increment remains `2.0.81`.

The required real Recorder DB test in `TestRecorderForecastAttributes` was skipped because that host command loaded SQLite 3.37.2 and its existing guard requires >=3.40.1. The initial command did not include skip reasons; the SQLite cause is supplied host evidence and agrees with the retained source guard. Neither that test nor its guard changed. The orchestrator subsequently selected an isolated test-only SQLite library per command; focused-2 and full-2 executed required Recorder coverage with zero skips. The first failure/skip evidence is preserved. This worker did not duplicate setup, retry sandbox WSL or run native Python tests.

## Historical host evidence and full-gate corrections - 2026-10-22

The host six-file focused gate passed: **505 passed, zero skipped in 17.83s**, exit 0. Exact command/output: `.agent-work/test-results/forecast-response-diagnostics-host/focused-2.json` and `focused-2.log`. Required real Recorder DB coverage ran. Host full-1 failed: **3 failed, 856 passed, zero skipped in 36.88s**, exit 1; exact command/output are `full-1.json` and `full-1.log` in the same directory. These supersede earlier pending/required-skip status without altering historical evidence. Both commands selected the existing isolated SQLite 3.54.1 via per-command `LD_LIBRARY_PATH`; verified source/build provenance remains under `.agent-work/cache/sqlite/3.54.1/provenance.txt` and `sqlite-build.log` in the host results directory. No setup or dependency change was repeated.

Only three existing tests were corrected. The justified adjacent file `tests/components/horizoniq/test_init.py`, outside the original inventory, supplies `AsyncMock` for `async_pause_for_sandbox` in `test_sandbox_devices_are_entry_scoped_and_persist_across_unload`; its prior `MagicMock` could not be awaited during paused restore. All test_init names, parameter sets and device ownership/persistence assertions remain intact. Product paused restore and its safe-default path are unchanged. The MQTT contract test drops only the retired Replay-status topic expectation, retaining exact non-wildcard subscriptions and retained-input/entry safety. The SoC test checks the six surviving exact topics twice across two enables, preserves snapshot/energy/SoC/physical assertions, stubs resumed coordinator refresh within its existing test-local coordinator mocks to avoid real HTTP work, and drains HA work after unload while asserting no runtime loop or subscriptions remain.

At this correction handoff, targeted execution and a final full rerun were pending. Both subsequently passed as recorded below. The six-file focused inputs and product code are unchanged since focused-2, so that gate needs no repeat. The worker did not retry inaccessible sandbox WSL, run native Windows application/tests, or repeat broad static review. Manifest remains the single combined `2.0.81` bump; no production, fixture, dependency, backend, policy or operational change accompanied these corrections.

## Final acceptance evidence reconciliation - 2026-10-22

Implemented / ready_for_review. Exact host commands are retained in `.agent-work/test-results/forecast-response-diagnostics-host/{focused-2,targeted-1,full-2}.json`, with paired `.log` output: exit 0, **505 passed in 17.83s**, **30 passed in 2.65s**, and **859 passed in 30.23s**, respectively. Each has zero failures and zero skips, including zero required skips. Targeted-1 covers the three corrected files; full-2 covers all `tests/components/horizoniq`, including the earlier proposed seven-file targeted selection, so no additional targeted gate is pending. Full-2 output contains only progress and its final summary, with no teardown/network errors. No passed test or static sweep was repeated for this documentation reconciliation.

All three commands activate `.venv-wsl` and set `LD_LIBRARY_PATH=/mnt/c/git/ha-integration/.agent-work/cache/sqlite/3.54.1/lib` for that command only. Required real Recorder DB coverage ran with supported SQLite 3.54.1; the existing guard is unchanged. Reproduce the isolated setup with `.agent-work/tmp/forecast-response-diagnostics-host/build-sqlite.sh`. Its official source is `https://www.sqlite.org/2026/sqlite-autoconf-3540100.tar.gz`, SHA3-256 `b6ced585c750916b1052667239a12c25a7ff34e7f06e1e6e01ecb0427657d9c4` (published at `https://www.sqlite.org/download.html`). `.agent-work/cache/sqlite/3.54.1/provenance.txt` records the verified source/hash/selection; host `sqlite-build.log` records Python loading 3.54.1. No system library, venv dependency declaration, project dependency or test guard changed.

| Approved criterion | Evidence and result |
| --- | --- |
| 1. Removal complete | Corrective `source-review.json` and `production-reference-audit.json`: no forbidden production authority references; remaining terms classified as local library, null reserved status or legacy sanitation. Focused-2 and full-2 pass the endpoint/replay rejection regressions. Met. |
| 2. Local operation and ownership | Focused-2 runtime/storage/reserve coverage and full-2 pass modes, transitions, cancellation, state14/snapshot5 migrations, physics/scenarios/faults and entry isolation. Targeted-1 confirms corrected lifecycle/MQTT/SoC tests and clean teardown. Met. |
| 3. Exact schemas and diagnostics safety | Focused-2 reader tests and full-2 pass 5/6/7/8 authority/serialization, aliases, numeric/shape boundaries, safe errors, nested secret screening and unknown-9 rejection. Met. |
| 4. Live command safety | Focused-2 direct-control/reserve/runtime and full-2 pass current priorities, limits, expiry/identity, missing/null diagnostics, allowed actions and non-live/stale/malformed rejection. Met. |
| 5. Refresh and credential/Recorder boundaries | Focused-2 real coordinator/HTTP same-hash replacement, no entry rewrite, stale-last-good, isolation and real Recorder tests pass without skips; full-2 includes authentication/registration regressions. Existing security review finds no new diagnostics persistence/logging or Recorder expansion. Met. |
| 6. Ledger, gates, version and scope | Original 253 dispositions and 20 required additions retained as reconciled, plus seven extra regressions and the adjacent retained test_init test; retained declarations/decorators/parameters audit preserved. Focused-2/full-2 pass with zero required skips; single version2.0.81 bump, no fixture changes. Met. |

Complete combined inventory: `.agent-work/test-results/forecast-response-diagnostics-reconciliation/changed-files.json`; original detailed inventory/source/security review: `.agent-work/tasks/forecast-response-diagnostics-corrective/report.json`. The mappingproxy and three full-gate corrections remain documented in their separate worker reports. The three adjacent production callers and adjacent test_init correction above are justified local changes; no new module, service or cloud contract was introduced. Historical focused-1/full-1 failures, planning review and initial sandbox evidence remain historical, not current failures. No remaining implementation/validation gap is identified. Orchestrator review/acceptance remains separate; no deployment, installation, restart, commit or push was performed.
