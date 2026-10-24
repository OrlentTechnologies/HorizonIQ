# Action-priority retirement implementation evidence and review

2026-10-24. **Complete; orchestrator review passed; all five acceptance criteria met and accepted.** Separate user approval authorized implementation and host evidence reconciliation. HEAD remains `d9c86ddcd1d57415b73c99d100f16f6a04d7d09f`; captured working manifest was `2.0.82`, now `2.0.83`. Focused host WSL: **608 passed in 21.35s**; full host WSL: **1211 passed in 40.91s**. Both exited 0 with zero failures/errors/skips, including Recorder database coverage. No deployment or release is claimed. HA must release before backend removal under separate authorization.

## Orchestrator acceptance

Account b accepted the valid evidence-backed `ready_for_review` report from task `20261024T192401032Z-5d49c3e4c63f4dfe868e41b3e0168ae6`, with all five criteria met and no remaining gaps. The bounded final review inspected the four production-module diffs, version/inventory, preservation and fixture audits, host evidence, and the new retained metadata/window rejection assertions. The changes remove only the retired priority surfaces and their sole-use helpers; command identity, issued/expiry/current-period validation and retained rejection categories remain. The existing CloudUpdateEnabled edits are preserved, and both unrelated test files remain byte-identical to the captured working baseline. No blocking finding remains.

The orchestrator executed both recorded WSL gates directly: focused 608 passed, full 1211 passed, no failures/errors/skips and clean teardown. Product/tests/fixtures were preserved through final reconciliation, so no repeat test run was needed. Only planning/review status changed during acceptance; final whitespace validation passed. The release ordering remains HA first, backend afterward; no deployment, installation, Home Assistant restart, commit or push was performed.

## Changes and preservation

All 14 approved application/test paths are implemented: four production Python modules, manifest, six existing test modules, two existing JSON fixtures and the new regression module. The implementation inventory is `.agent-work/tasks/ha-action-priority-removal/implementation-paths.json`; `combined-inventory.json` in the same directory also accounts for the three feature documents, reconciliation artifacts and preserved unrelated files. Only this feature specification, ledger and evidence document are updated outside the application/test inventory; disposable evidence remains under `.agent-work`. No file deletions, Solar edits, dependency/configuration/policy changes, installation, restart, commit or push occurred. The dated `feature.review.md` is preserved.

The typed models, strict period allowlist/parser/serializer, ordinary and direct normalization, live priority table/assertion and priority-specific error classification no longer contain the retired member. Removed sole-use helpers: `_required_optional_integer`, `_direct_optional_int`, `_required_int`. No replacement rank, branch, parser, schema, type, status, endpoint, migration or persistence operation was added.

Evidence was captured before editing under `.agent-work/tasks/ha-action-priority-removal/`: `pre-existing.diff`, `pre-existing-status.txt`, `baseline-head.txt`, `pre-edit-sha256.txt`, and `baseline/` copies of the five modified files. The exact transformation audit proves all four production modules equal their working baseline after only the approved priority removals. This preserves the existing CloudUpdateEnabled removals in models/helpers. The existing CloudUpdateEnabled test files (`test_coordinator_helpers.py`, `test_init.py`) are byte-identical to their captured copies; SHA-256 pairs are in `static-audit.json`. Manifest was advanced once from the captured working version, preserving the earlier version increment as prior work.

Both fixture text and parsed-JSON comparisons prove only two wire priority members and one normalized member were removed, with every retained identity/timestamp/value unchanged. No fixture was regenerated. The feature-owned diff and complete working diff are saved separately as `task-owned-diff.patch` and `working-tree.diff` so the latter's unrelated edits are not attributed to this task.

## Specialist review

| Surface | Reviewed result | Evidence / limit |
| --- | --- | --- |
| Wire aliases and retired objects | Removing the member from `_PERIOD_FIELDS` means retired aliases are never read, conflict-checked, converted, deep-copied or recursively scanned. Retired secret-shaped objects are discarded. | Exact production transformation plus passing legacy/conflict cases in both host gates |
| Retained security | `_adapt_object` still checks prohibited keys on retained objects; retained nested diagnostics and transport-secret checks are unchanged. No raw retired values are logged or serialized by the changed production code. | Exact unchanged retained parser code; new retained-secret/stale case and existing security tests retained |
| Schemas, actions and authority | Supported set stays exactly 5/6/7/8; unknown 9 rejection and action allowlists are unchanged. Live `none` still returns self-consumption before command metadata checks; recommendedAction gains no live authority. | Source comparison, retained guards and added raw-path cases |
| Command metadata/windows | ID validation, mandatory nullable properties, issued <= now < expiry, exact half-hour end, current period and public retained rejection categories are unchanged. | Direct-control diff removes only the priority block/helper/classification member; metadata/window tests retained and supplemented |
| Diagnostics, numbers and physical bounds | shouldExport requirements, diagnostics policy, retained aliases, finite/type checks, power clamps and generation bounds are unchanged. | Exact production transformation, preserved parameter sets and new invalid-retained cases |
| Time, transport and ownership | UTC/offset parsing and all coordinator/client/runtime/persistence code remain unchanged. Existing stale/same-hash/entry/duplicate behavior is preserved in source. | Passing real entry/sensor/refresh cases check retained-alias rejection and recovery before timeout/stale fallback |
| Existing coverage | 80 original names audited: 77 retained and only three approved replacements. All retained decorators/parameters and retained bodies are checked after the two allowed assertion migrations. Recorder class body and SQLite guard unchanged. | `static-audit.json` plus JUnit-confirmed execution of all 80 current names and eight additions in both gates; Recorder case passed |

No design or application-scope deviation was needed. A disposable audit initially failed because Node could not spawn Git (`spawnSync git EPERM`). The audit reads HEAD snapshots exported by ordinary PowerShell `git show`; this affects evidence tooling only. No Python application/test execution was attempted natively. The original worker did not retry WSL or change policy; subsequent approved orchestrator-host execution resolved the sandbox boundary. This reconciliation neither reran passed gates nor changed product/tests/fixtures or the version.

## Actual validation

Attempted targeted command (before the new regression module was completed):

```powershell
wsl bash -lc "cd /mnt/c/git/ha-integration && source .venv-wsl/bin/activate && LD_LIBRARY_PATH=/mnt/c/git/ha-integration/.agent-work/cache/sqlite/3.54.1/lib python -m pytest tests/components/horizoniq/test_direct_control.py tests/components/horizoniq/test_forecast_schema5.py tests/components/horizoniq/test_reserve_grid_hold.py -q -rs --basetemp=.agent-work/tmp/ha-action-priority-removal/targeted -o cache_dir=.agent-work/cache/pytest"
```

Historical result: WSL startup denied, `Wsl/Service/CreateInstance/E_ACCESSDENIED`, before Bash/pytest started. Log: `.agent-work/tasks/ha-action-priority-removal/wsl-targeted-attempt.txt`. Collected/pass/fail/skip counts for that attempt are **unavailable**, not zero. The original worker did not attempt focused/full after that boundary; its original report is preserved as `validation-before-host.json`. The host gates below subsequently passed and resolve this former gap.

| Executed static command | Result |
| --- | --- |
| `node .agent-work/tasks/ha-action-priority-removal/static-audit.cjs` | Passed: 80 original names, 77 retained/3 replaced, eight additions; all retained test bodies/decorators/parameters checked; exact production removal and prior-work preservation; three fixture members only; working version 2.0.83 |
| `rg -n 'actionPriority\|ActionPriority\|action_priority\|_required_optional_integer\|_direct_optional_int\|_required_int\b' custom_components/horizoniq tests/components/horizoniq/fixtures` | No matches (rg exit 1 is expected for this absence check) |
| `git -c core.safecrlf=false diff --check` | Passed, no whitespace errors |

The static inventory estimated 252 new parameter cases; both actual host JUnit reports confirm all 252 executed and passed across the eight new names. The focused/full totals are 608/1211, respectively; do not substitute the 252-case subset for a gate total. Static text checks alone do not prove runtime behavior; host JUnit/logs supply that evidence, including Recorder coverage. The historical `static-audit.json`, `final-sha256.txt` and diff snapshots remain unchanged and are linked to current execution by `host-reconciliation.json`.

Discarded-value log assertions capture the integration at DEBUG level. The real-entry test verifies a retained alias conflict makes only the affected entry stale/self-consuming, retains configuration/command ledger and the other entry, and recovers from the same accepted response before the separate timeout check.

## Passed orchestrator-host gates

The orchestrator executed focused then full using the existing `.venv-wsl` and cached supported SQLite 3.54.1 library selected per command. No installation, dependency, system-library, guard or configuration change was needed. Exact executable/arguments/exit codes are in `.agent-work/test-results/forecast-action-priority-removal-host/{focused-1,full-1}.json`; sibling `.log` and `.xml` files corroborate each result. Logs contain clean progress/summary output without teardown/network errors.

```powershell
wsl bash -lc "cd /mnt/c/git/ha-integration && source .venv-wsl/bin/activate && LD_LIBRARY_PATH=/mnt/c/git/ha-integration/.agent-work/cache/sqlite/3.54.1/lib python -m pytest tests/components/horizoniq/test_action_priority_removal.py tests/components/horizoniq/test_direct_control.py tests/components/horizoniq/test_forecast_schema5.py tests/components/horizoniq/test_reserve_grid_hold.py tests/components/horizoniq/test_measured_capacity_refresh_regressions.py tests/components/horizoniq/test_reserve_grid_hold_runtime.py tests/components/horizoniq/test_use_grid_sensor.py -q -rs --basetemp=.agent-work/tmp/forecast-action-priority-removal-focused-1 -o cache_dir=.agent-work/cache/pytest --junitxml=.agent-work/test-results/forecast-action-priority-removal-host/focused-1.xml"
wsl bash -lc "cd /mnt/c/git/ha-integration && source .venv-wsl/bin/activate && LD_LIBRARY_PATH=/mnt/c/git/ha-integration/.agent-work/cache/sqlite/3.54.1/lib python -m pytest tests/components/horizoniq -q -rs --basetemp=.agent-work/tmp/forecast-action-priority-removal-full-1 -o cache_dir=.agent-work/cache/pytest --junitxml=.agent-work/test-results/forecast-action-priority-removal-host/full-1.xml"
```

| Gate | Passed | Failed | Errors | Skipped | Log elapsed | JUnit suite elapsed | Exit |
| --- | ---: | ---: | ---: | ---: | --- | --- | ---: |
| Focused (seven files) | 608 | 0 | 0 | 0 | 21.35s | 21.344s | 0 |
| Full integration | 1211 | 0 | 0 | 0 | 40.91s | 40.904s | 0 |

`TestRecorderForecastAttributes.test_recorder_database_omits_only_the_full_forecast` passed in each gate. All 80 ledger current names match JUnit execution, including the three replacements, as do all eight additions and their per-name parameter counts. The full gate also executes the unchanged unrelated CloudUpdateEnabled regressions. `host-reconciliation.json` records name mapping, per-module totals, artifact hashes and preservation checks; no required coverage was skipped.

Reconciliation SHA-256 checks match all 14 original product/test hashes, both unrelated test-file baseline hashes, and the dated planning review hash `C2603BF7E869093D089DBDCD9C511DC0046108AB85B038B49298D795DCFBEFC3`. The original exact production transformation preserves unrelated shared-file edits and retained guards; fixtures and the single working `2.0.83` bump remain unchanged. `git -c core.safecrlf=false diff --check` passes after the document updates; `diff-check.txt` records the result. No unchanged static sweep or passed test gate was rerun.

## Five acceptance criteria

| Criterion | Met | Evidence / remaining limit |
| --- | --- | --- |
| 1. Retired production surfaces/helpers absent; retained schemas/actions/guards/categories unchanged | Yes | Exact production transformation and no-symbol search; unchanged source hashes link this audit to both passing host gates |
| 2. Priority-free/arbitrary/conflicting legacy input equivalence; no canonical/typed/recorded/restored priority | Yes | Passing raw-path, legacy/conflict, canonical/model/restoration and Recorder cases in focused 608/full 1211 gates |
| 3. Retained alias/metadata/window/partial/diagnostic/security/physical guards and live authority preserved | Yes | Exact retained-source/test audit plus passing atomic failure, transport-secret, metadata/expiry, physical and authority cases |
| 4. Real refresh/runtime/sensor, stale/same-hash/deduplication/entry isolation and complete ledger | Yes | All 80 current ledger names and eight additions executed; retained bodies/parameters audited; real-entry/sensor/runtime coverage passes |
| 5. Focused/full WSL gates without required skips, symbols/whitespace, single version bump, prior work | Yes | 608/1211 passed, zero failures/errors/skips; symbol check retained; final diff check passes; hashes preserve all product/tests/prior work and manifest 2.0.83 |

No acceptance gap or security finding remains from this scoped review. Retained transport-secret checks, alias checks, metadata/expiry, physical limits and entry-local ownership remain enforced; no discarded raw value is exposed by the changed production path. Validation is deterministic with external systems mocked; it does not establish live backend or deployed HA behavior. The worker sandbox startup denial remains historical evidence, not a current blocker. Bounded orchestrator final review is next; deployment/restart/release, installation, commit/push and backend changes remain outside this task.
