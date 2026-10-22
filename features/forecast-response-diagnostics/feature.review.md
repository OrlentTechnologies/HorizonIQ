# Forecast diagnostics HA planning review

2026-10-22. Baseline: clean checkout `d65d3ec`, manifest `2.0.80`. This is a preimplementation review of the local plan against the requested Solar companion, its required removal companion, the existing removal review/test ledger, AGENTS.md and targeted HA source/test inspection. It is not an implementation review or a claim that tests passed.

| Area | Observed repository evidence | Plan resolution and required proof |
| --- | --- | --- |
| Missing prerequisite | `forecast_schema5.py` versions 5/6 and replay plan/period fields; `direct_control.py` replay parser and schema-6 priority equality | Execute simulation removal first, then extend explicit current priority set to 6/7/8; retain schema-5 semantics and add required schema-7/8 tests |
| Cloud/local ownership | `coordinator.py::async_fetch_sandbox_replay`; `sandbox_runtime.py` remote preparation/restore/mode branches | Remove cloud replay entirely; preserve normal Forecast_Get and HA-local physics, faults and manual scenarios |
| Migration scope | `sandbox_storage.py` version 13/4; `simulation/snapshots.py` legacy decoder and positional constructor; runtime restore paths | Storage 14/snapshot 5; atomic retained-field validation, paused legacy replay migration, named constructor arguments and per-entry ownership tests |
| Mode transitions | `sandbox_runtime.py::async_select_operating_mode` stops control and reloads entry | Preserve sequence and paused reload; local manual time never authorizes cloud commands; wall-clock virtual control only on explicit enable |
| Ledger authority | `forecast_schema5.py::Schema5Forecast`, `parse_schema5_forecast`, `to_dict` currently require/serialize root ledger | One optional normalized ledger; exact legacy root versus schema-8 nested/null matrix; reject any schema-8 root ledger and schema 9 |
| Allowlist and secret boundary | `adapt_schema5_wire`, `_adapt_object`, `_alias_value`, retired-profile recursive scanner | Add wrapper aliases; scan unknown nested diagnostic mappings/lists before filtering; retain prohibited-key/alias errors; generic new shape/numeric error |
| Numeric validation | `_complete_object` currently checks complete safe JSON but does not express the new tolerance/health contract | Dedicated schema-8 validation of all ten fields, finite nonboolean numbers, exact tolerance, inclusive absolute error, negative balance and next-float cases |
| Publication/cache separation | `coordinator.py::_build_snapshot_or_stale` accepts a complete model; `_update_cached_state` independently compares hash and registration data | No diagnostics-driven coordinator edit; real same-hash refresh regression, stale-last-good and no unchanged entry write |
| Credential preservation | Existing coordinator registration/hash tests and completed `features/cached-registration-round-trip` scope | Retain all credential extraction, renewal, persistence, authentication and safe omission behavior while removing replay only |
| Existing tests | Current named schema/direct/coordinator tests; external HA migration tables and additional HA callers | Local ledger preserves all existing named dispositions, required prerequisite additions and additive schema-8 cases; fixtures remain unchanged |
| Edit inventory | Required removal inventory plus the exact five-file additive diagnostics scope | Separate inventories in feature.md; no new Python module/service/test application; no Solar edits or deployment |
| Release/gates | AGENTS.md requires manifest bump and WSL; current manifest 2.0.80 | One combined patch bump to 2.0.81 if baseline unchanged; combined focused and full WSL gates with actual counts and no required skipped tests |

Named-test audit: the local ledger carries 253 existing named tests across 23 HA test files. A source-name comparison against this checkout found zero missing listed names and zero unlisted current names in those files. This is a static inventory check, not a test execution result.

Result: the prerequisite is confirmed absent, and the local plan reconciles both ordered HA scopes. No blocking design question identified. Implementation requires a separate user approval message under the active orchestration policy. No application, test, configuration, manifest or operational state was changed, and no test suite was run for this planning review.
