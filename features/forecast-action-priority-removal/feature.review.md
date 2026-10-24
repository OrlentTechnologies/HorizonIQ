# Action-priority removal planning review

2026-10-24. Baseline HEAD `d9c86ddcd1d57415b73c99d100f16f6a04d7d09f`, working manifest `2.0.82`, five existing modified files. Reviewed the Solar plan/review/ledger, AGENTS.md, current priority consumers/helpers, two fixture references, affected tests and the pre-existing diff. This is planning evidence; no implementation or test execution is claimed.

| Area | Repository evidence | Resolution |
| --- | --- | --- |
| Strict input/model/output | `forecast_schema5.py` period allowlist, dataclass, constructor, serializer and sole-use optional integer helper | Remove member before adaptation so arbitrary/conflicting retired aliases are ignored; retained alias/security failures remain |
| Ordinary/direct normalization | `coordinator_helpers.py` period projection, direct constructor and sole-use optional integer helper; both typed fields in `models.py` | Remove all consumers and typed/output surfaces with no replacement rank or cached restoration |
| Live control | `direct_control.py` priority table/assertion, sole-use helper, metadata error classifier | Remove only priority behavior; retain actions, command ID, issue/expiry/period checks, power bounds and public rejection types |
| Backward compatibility/release | Current strict parser still requires the property; schema support 5/6/7/8 | Updated HA handles old/new backend shapes per response; deploy HA before backend, deployments separately authorized |
| Dirty shared files | Existing diff removes CloudUpdateEnabled from helpers/models and adjusts helper/init tests; working version already 2.0.82 | Preserve all five files' existing changes; stage feature changes on top; expected new working patch 2.0.83 |
| Fixture/test inventory | Scoped search matches the 14-path source inventory, including one new regression module and two fixture updates | No extra implementation path identified; existing external-value tests inject retired member locally |
| Existing-name audit | Source ledger's 79 top-level names match all six files with no missing names; forecast test file also contains one class test omitted by that inventory | Local ledger adds retained Recorder DB case, yielding 80 existing named cases and the same three explicit replacements; no hidden deletion |
| Validation environment | AGENTS.md WSL rule; retained `.agent-work/cache/sqlite/3.54.1` tool from prior task | Focused/full WSL gates, actual counts and required no-skip coverage; host route if sandbox WSL fails; no test execution during planning |
| Scope/ownership | Existing endpoints, coordinator/runtime persistence and source ownership | No backend, dependency, transport, configuration, migration, timestamp/energy/lock or agent-policy change; no deployment |

Result: source plan matches the inspected checkout. One source-ledger omission was reconciled locally without weakening coverage. No blocking design question or additional application scope identified. Local feature specification and ledger are ready for a separate implementation approval. Only planning artifacts were written.
