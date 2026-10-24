# Remove forecast action priority

Status: **complete; orchestrator review passed** after the user's separate approval. Prepared, implemented and validated 2026-10-24 against HEAD `d9c86ddcd1d57415b73c99d100f16f6a04d7d09f` and working manifest `2.0.82`, now `2.0.83`. Approved host WSL gates passed: focused **608 passed in 21.35s**, full **1211 passed in 40.91s**, both with zero failures/errors/skips, including required Recorder database coverage. All five acceptance criteria are met and accepted. The historical worker WSL startup denial is resolved by these host results; see [implementation evidence and review](implementation-evidence.md). The dated planning review remains unchanged. No deployment occurred.

## Goal and compatibility

Accept the backend's priority-free forecasts through the existing parser, coordinator and live-command path. Older responses containing any retired priority alias/value remain accepted; ordinary allowlist projection discards that member. Preserve schemas 5/6/7/8 and every retained control, metadata, physical, time, security and entry-isolation guard. Do not replace the field with a local rank or another compatibility parser.

Release this integration before the backend removal. Current `2.0.82` requires the member for parsing/executable commands; backend deployment first can interrupt live commands. The updated reader must handle old production and new test responses independently, using the same integration and existing per-entry ownership. No deployment is included.

## Authoritative sources and discovery

- Requested [HA plan](C:/git/solar/features/forecast-action-priority-removal/ha-integration-plan.md), its [named-test ledger](C:/git/solar/features/forecast-action-priority-removal/ha-test-migration-ledger.md) and [planning review](C:/git/solar/features/forecast-action-priority-removal/ha-integration-plan.review.md).
- Local [AGENTS.md](../../AGENTS.md), [test ledger](test-migration-ledger.md), and [review](feature.review.md).

Current production consumers match the source plan: `Schema5Period` requires/serializes the member; `DirectForecastPeriod` and `ForecastPeriod` expose it; period normalization copies/coerces it twice; `parse_live_command` requires an integer and checks a schema-specific action table. The three priority-only helpers each have one consumer and can be removed with that consumer. The supported schema set remains 5/6/7/8. No extra production priority consumer was found by the scoped search.

Five files already have unrelated, uncommitted CloudUpdateEnabled-removal changes: `coordinator_helpers.py`, `models.py`, `manifest.json`, `tests/components/horizoniq/test_coordinator_helpers.py`, and `tests/components/horizoniq/test_init.py`. Preserve these edits and their tests, distinguish them from this task, and apply the new model/helper edits on top. HEAD's manifest is `2.0.81`; the working version is already `2.0.82`. This feature increments the then-current working patch once, expected `2.0.83`. Never reset overlapping files to HEAD or absorb the unrelated test edits into this feature's claimed implementation.

## Intended changes

1. Remove `action_priority` from the two models in `models.py`. Remove `Schema5Period.action_priority`, its constructor input and `to_dict` member, `actionPriority` from `_PERIOD_FIELDS` and `_period`, and sole-use `_required_optional_integer`.
2. Remove both normalization/conversion copies and sole-use `_direct_optional_int` from `coordinator_helpers.py`. Keep retained nullable metadata and existing ordinary/strict normalization policies. Old normalized dictionaries project retained fields and never reconstruct priority.
3. Remove the priority assertion/table, sole-use `_required_int`, and priority-specific error classification from `direct_control.py`. Keep the existing `DirectCommand` and `DirectForecastValidation`, action allowlists, executable-action authority, identity/expiry/current-period checks, physical limits and rejection categories. Missing/bad retained metadata remains `COMMAND_METADATA_INVALID`; invalid windows remain `COMMAND_WINDOW_INVALID`.
4. Update the two owned current test fixtures to omit the field, preserving all other values. Update six existing test modules according to the complete named dispositions and add the single specified regression module. Explicit legacy tests inject old values locally. Increment the working manifest patch once, expected `2.0.82` to `2.0.83`.

| Boundary | Required result |
| --- | --- |
| Retired camel/Pascal/snake aliases, absent/null/numeric/boolean/string/list/object | Discard before canonical/model construction; no type conversion, storage, diagnostic output or logging |
| Conflicting retired aliases | Ignore all; no retired alias-conflict validation |
| Conflicting retained aliases or malformed retained fields | Existing atomic failures, no partial horizon/cache/control update |
| Legacy backend response with a priority | Same retained action, metadata and physical outcome as the priority-free response |
| Unsupported schema/action, bad ID/timestamps, future issue/exact expiry/wrong period end | Existing rejection and public-safe categories; no expanded execution authority |
| `none` without command metadata | Existing self-consumption behavior |
| Old normalized cached dictionary with priority | Project retained fields; no priority restoration, migration or persistence sweep |
| Missing/null/empty/partial forecast or period, null element | Existing complete-payload parser/coordinator policy |

Keep schema-specific shouldExport/diagnostics requirements, retained alias/transport-secret checks, UTC/offset and half-hour rules, numeric bounds, stale last-good behavior, same-hash refresh, deduplication and per-entry isolation. Discarding a retired member must not alter security checks on retained sibling fields/objects. No new schema, type, status, exception, endpoint, configuration, dependency, cache, timestamp/energy conversion, lock or storage operation.

## Exact implementation inventory

All paths relative to Git root. Modify:

- `custom_components/horizoniq/models.py`
- `custom_components/horizoniq/forecast_schema5.py`
- `custom_components/horizoniq/coordinator_helpers.py`
- `custom_components/horizoniq/direct_control.py`
- `custom_components/horizoniq/manifest.json`
- `tests/components/horizoniq/test_direct_control.py`
- `tests/components/horizoniq/test_forecast_schema5.py`
- `tests/components/horizoniq/test_reserve_grid_hold.py`
- `tests/components/horizoniq/test_measured_capacity_refresh_regressions.py`
- `tests/components/horizoniq/test_reserve_grid_hold_runtime.py`
- `tests/components/horizoniq/test_use_grid_sensor.py`
- `tests/components/horizoniq/fixtures/direct_schema5_forecast.json`
- `tests/components/horizoniq/fixtures/deployed_schema5_normalized.json`

Add `tests/components/horizoniq/test_action_priority_removal.py`. Delete no files. Remove only dead functions inside the existing modules. Existing tests outside this inventory remain unchanged unless a concrete fixture dependency requires a documented correction/disposition. Do not edit Solar, immutable user/audit data, agent policy, configuration or deployment state. Keep new agent artifacts under Git-root `.agent-work/`; durable implementation evidence belongs beside this specification.

## Tests and acceptance

The source ledger accounts for all 79 top-level existing named tests in six modified test files. The local ledger additionally retains `TestRecorderForecastAttributes.test_recorder_database_omits_only_the_full_forecast`, omitted by the source's top-level inventory: **80 existing named cases in total**. Only the three explicitly priority-specific names are replaced; remove only obsolete priority assertions/parameter rows. Keep all other purposes, decorators/parameter sets and guards. All eight named new acceptance tests are in the local ledger.

Require the real response-to-strict-parser-to-coordinator-model-to-live-command path, ordinary normalization, canonical diagnostics, restored normalized dictionaries, current sensor/runtime behavior, same-hash refresh, stale last-good and separate entries. Use existing external Forecast_Get stubs and deterministic times; no replacement internal parser/controller, backend test service, sleeps or live backend dependency.

Executed focused host gate, through WSL only (608 passed in 21.35s; exit 0; zero failures/errors/skips):

```powershell
wsl bash -lc "cd /mnt/c/git/ha-integration && source .venv-wsl/bin/activate && LD_LIBRARY_PATH=/mnt/c/git/ha-integration/.agent-work/cache/sqlite/3.54.1/lib python -m pytest tests/components/horizoniq/test_action_priority_removal.py tests/components/horizoniq/test_direct_control.py tests/components/horizoniq/test_forecast_schema5.py tests/components/horizoniq/test_reserve_grid_hold.py tests/components/horizoniq/test_measured_capacity_refresh_regressions.py tests/components/horizoniq/test_reserve_grid_hold_runtime.py tests/components/horizoniq/test_use_grid_sensor.py -q -rs --basetemp=.agent-work/tmp/forecast-action-priority-removal-focused-1 -o cache_dir=.agent-work/cache/pytest --junitxml=.agent-work/test-results/forecast-action-priority-removal-host/focused-1.xml"
```

Executed full host completion gate after focused passed (1211 passed in 40.91s; exit 0; zero failures/errors/skips):

```powershell
wsl bash -lc "cd /mnt/c/git/ha-integration && source .venv-wsl/bin/activate && LD_LIBRARY_PATH=/mnt/c/git/ha-integration/.agent-work/cache/sqlite/3.54.1/lib python -m pytest tests/components/horizoniq -q -rs --basetemp=.agent-work/tmp/forecast-action-priority-removal-full-1 -o cache_dir=.agent-work/cache/pytest --junitxml=.agent-work/test-results/forecast-action-priority-removal-host/full-1.xml"
```

Record exact commands, actual pass/fail/skip counts and reasons, `git diff --check`, and the final production search for `actionPriority`, `ActionPriority`, `action_priority` and the three removed helper names. No retired symbol should survive in production or current canonical fixtures; deliberate legacy tests/planning/history may retain it. Any failed stage or required skip remains a blocker, not completion. Preserve unrelated CloudUpdateEnabled-removal regressions in the full gate.

Use the existing `.venv-wsl`. Prior work established that the worker sandbox can deny WSL even though host execution works. If that recurs, continue authorized code/static work and return the precise validation gap for orchestrator host execution, rather than stopping before implementation or changing sandbox policy. The cached isolated SQLite library remains at `.agent-work/cache/sqlite/3.54.1/lib/libsqlite3.so.0`; if needed for the retained Recorder test, use per-command `LD_LIBRARY_PATH=/mnt/c/git/ha-integration/.agent-work/cache/sqlite/3.54.1/lib`. Keep `-rs`, pytest cache and basetemp outputs under `.agent-work/` when selecting test artifact locations. Do not install dependencies, alter system libraries, change test guards or substitute native Windows Python tests to hide missing coverage. Do not rerun passed unchanged gates without edits/failures/concrete concerns.

Acceptance criteria:

1. Retired field and sole-use helpers are absent from all four production modules/model/output paths; supported schemas/actions and every retained safety guard/rejection category are unchanged.
2. Priority-free responses and all old arbitrary/conflicting retired aliases normalize and execute identically for supported live actions; no retired field/value appears in canonical, typed, recorded or restored output.
3. Retained aliases, metadata, windows, partial/invalid payloads, diagnostics/security and physical bounds still fail safely and atomically; no recommendation becomes live authority.
4. Real refresh/runtime/sensor tests prove same-hash/stale behavior, deduplication and per-entry ownership; all ledger dispositions and eight additions are satisfied without weakening existing guards.
5. Required focused/full WSL gates pass, required coverage is not skipped, final symbol/whitespace checks pass, working patch increments once, and all five pre-existing modified-file changes remain preserved.

## Routing, review and approval

| Task | Complexity | Owner | Reason | Further decomposition | Required review |
| --- | --- | --- | --- | --- | --- |
| Scope/reconcile plan and test ledger | Moderate | Account b orchestrator | Resolve current contract, dirty baseline and release order | Complete as one local planning task | Sibling planning review |
| Remove field, adapt fixtures/tests, validate and correct | Moderate; safety-sensitive control boundary | One account a worker with Home Assistant specialist instructions | Four coupled production surfaces and shared fixtures | One autonomous implementation handoff | Evidence-backed ready_for_review report, then bounded orchestrator review of retained guards and preservation |

The user separately approved this feature with "approve" after presentation of the local plan, review and ledger. This account-a implementation handoff includes routine scoped corrections and the established host-validation route. No release, HA restart, commit or push is included.

No blocking contract question remains. Main risks are preserving unrelated edits in shared files, accidentally retaining a projection/conversion, and weakening metadata/expiry checks while removing the redundant rank. The local ledger, passing targeted regressions, scoped final search and passing full gate address these risks. All five acceptance criteria are met; bounded orchestrator review remains the next step.

## Implementation evidence — 2026-10-24

Implemented all 14 approved application/test paths without deletion or additional application scope. Retired fields/helpers/table/classification are removed; both fixtures lose only the priority member. The six existing test modules retain 80 named cases (77 retained, three approved replacements), with retained bodies/decorators/parameter combinations audited. The new module contains all eight named acceptance tests, representing 252 parameter cases by static inventory; this is not a pytest collection or pass count.

Static audit proves the four production modules equal the captured working baseline after only the approved priority removals. The pre-existing CloudUpdateEnabled edits remain intact; the two unrelated test files remain byte-identical. Fixture comparison proves all retained identities, timestamps and values unchanged. Manifest advances once from the working `2.0.82` to `2.0.83`. Production/current-fixture retired-symbol search and `git -c core.safecrlf=false diff --check` pass.

The earlier targeted worker WSL attempt failed at startup with `Wsl/Service/CreateInstance/E_ACCESSDENIED`, before collection; counts for that historical attempt remain unavailable. Approved orchestrator-host focused/full execution subsequently passed with the counts above. JSON executable/arguments/exit codes, clean logs and JUnit cases are retained in `.agent-work/test-results/forecast-action-priority-removal-host/{focused-1,full-1}.{json,log,xml}`. Required Recorder coverage and all 80 existing dispositions (77 retained/3 replaced) plus eight additions have actual execution evidence. The 252 new parameter cases are confirmed in each JUnit report; they are a subset of each gate, not its total.

Reconciliation changed only the three local feature documents and agent evidence records. SHA-256 comparison against the original `final-sha256.txt` confirms all 14 application/test paths remain unchanged; original preservation hashes still match both unrelated CloudUpdateEnabled test files. The production transformation audit continues to establish preservation in shared models/helpers and the single manifest increment to `2.0.83`. The dated planning review hash is unchanged. Combined inventory and verification: `.agent-work/tasks/ha-action-priority-removal/{combined-inventory.json,host-reconciliation.json,validation.json}`. No design/scope deviation or remaining acceptance gap was found. No deployment, restart, installation, commit/push or Solar edit occurred; HA must be released before backend removal under separate authorization. Validation uses mocked external boundaries and does not claim live backend or deployed HA testing.
