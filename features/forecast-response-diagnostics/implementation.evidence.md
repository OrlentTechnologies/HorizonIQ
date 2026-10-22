# Implementation attempt evidence

2026-10-22, account-a worker. Outcome: **blocked before application edits**. This is execution-environment evidence, not an implementation review or orchestrator acceptance. User approval of both ordered scopes was supplied in the handoff.

The checkout is at `d65d3ece5edc8afddde3036df8bbbb679daa1346`; manifest remains `2.0.80`. Only the pre-existing untracked planning directory existed at entry. No narrower AGENTS.md was found under the affected source, tests or features directories. The feature-workflow skill was read; delegation was not used under the worker instruction.

## Required gate attempts

```powershell
wsl bash -lc "cd /mnt/c/git/ha-integration && source .venv-wsl/bin/activate && python -m pytest tests/components/horizoniq/test_forecast_schema5.py tests/components/horizoniq/test_direct_control.py tests/components/horizoniq/test_coordinator.py tests/components/horizoniq/test_reserve_grid_hold_runtime.py tests/components/horizoniq/test_sandbox_runtime.py tests/components/horizoniq/test_sandbox_storage.py -q"
wsl bash -lc "cd /mnt/c/git/ha-integration && source .venv-wsl/bin/activate && python -m pytest tests/components/horizoniq -q"
```

Each WSL process returned native exit code `-1`, reporting `Access is denied` and `Wsl/Service/CreateInstance/E_ACCESSDENIED`. Neither reached bash, virtualenv activation or pytest. Test passed/failed/skipped counts are unavailable; no tests ran. The PowerShell evidence-capture command itself exited zero after recording these failures; that process success does not indicate successful gates.

The active execution environment permits workspace writes but sets approval policy to `never` and forbids requesting unsandboxed execution. There is no available host-execution tool to run the required WSL commands outside that restriction. No policy/configuration changes, native Python test substitution or sandbox workaround was attempted. Relaunch with WSL-accessible execution to implement and validate the approved work.

## Static findings and security boundary

- The ledger still matches 253 existing test names across 23 files, with zero missing/unlisted names. Parameter sets were not evaluated by pytest.
- Baseline production searches still find the retired cloud Replay contract and simulation action fields. These are pending removals; no successful final-removal search is claimed. Local simulation physics/scenarios remain unchanged.
- The reader still supports schemas 5/6, and private storage/snapshot versions remain 13/4. Required schema 7/8 and 14/5 migrations are not implemented.
- No credential, authentication, command-authority, diagnostic handling, logging or persistence code changed. The requested secret-boundary review and behavioral regressions remain outstanding. Evidence contains source locations and WSL errors, not runtime credentials or forecast payloads.
- Manifest remains at the baseline because the combined application change has not begun. Its single patch increment remains due with implementation. Historical fixtures and all application/test files remain unchanged.

## Acceptance status

| Criterion | Met | Outstanding |
| --- | --- | --- |
| 1. Remove cloud Replay contract | No | All production removals and final reference classification |
| 2. Local modes and safe migrations | No | Runtime, storage/snapshot migration and regressions |
| 3. Exact schema 5/6/7/8 contract | No | Reader, aliases, diagnostics validation and serialization |
| 4. Schema-8 command safety | No | Explicit priorities, command guards and tests |
| 5. Real coordinator refresh/isolation/recorder | No | Additive refresh regressions and retained credential tests |
| 6. Ledger, gates, scope and release | No | Test implementation, successful WSL gates and manifest bump |

## Evidence pointers

All disposable evidence is under `.agent-work/test-results/forecast-response-diagnostics-account-a/`:

- `gate-attempts.json`: exact commands, native exit codes and startup-failure classification.
- `focused.log`, `full.log`: raw WSL failure output.
- `baseline-ledger-audit.json`, `baseline-ledger-summary.json`: static named-test reconciliation.
- `baseline-production-references.log`: pending production contract references.

The approved plan, inventory, prerequisite ordering and original planning review remain authoritative. No design deviation was introduced. Resume implementation from the original baseline; there is no partial application patch to repair.
