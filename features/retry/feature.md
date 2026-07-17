# Forecast Retry Scheduling

| Step | Model |
| --- | --- |
| 1. Add retry state and constants | GPT-5.6-Terra High |
| 2. Move initial retries into the coordinator | GPT-5.6-Terra High |
| 3. Use forecast cadence after initialization | GPT-5.6-Terra High |
| 4. Clear registration on subscription refresh | GPT-5.6-Terra High |
| 5. Close retry test gaps | GPT-5.6-Terra High |
| 6. Release and verify | GPT-5.6-Terra High |

## Goal
- Before the first successful forecast, retry after `10, 30, 60, 120, 240, 480` seconds, then every `480` seconds.
- After the first successful forecast, retry at `ForecastCadenceMinutes`.
- Keep 500/429 handling unchanged: one request, no immediate retry, ignore HTTP `Retry-After`.
- Keep bootstrap API behavior unchanged.
- Clear cached registration data during an explicit subscription refresh.

## Design Constraint
Home Assistant owns `ConfigEntryNotReady` timing and caps it near 80 seconds. To use the required schedule, let the entry load with unavailable entities and let the coordinator own retries until its first successful forecast.

`async_setup_entry` cannot distinguish manual reload from startup. Clear registration only in the explicit subscription-refresh action, not on every setup.

## Implementation

### Step 1: Retry State
- Add `INITIAL_FORECAST_RETRY_SECONDS = (10, 30, 60, 120, 240, 480)`.
- Track whether the coordinator has completed one successful forecast.
- Track consecutive pre-initialization failures, capped at the final delay.

### Step 2: Initial Load
- Replace `async_config_entry_first_refresh()` with a non-raising coordinator refresh during setup.
- Store the coordinator and forward platforms even when that refresh fails.
- Keep entities unavailable until forecast data succeeds.
- For pre-initialization failures, set `UpdateFailed.retry_after` from the retry sequence.
- Reset initial retry state after the first success.

### Step 3: Initialized Retries
- After initialization, raise forecast failures without a custom retry delay.
- Let the coordinator's `update_interval` use the effective `ForecastCadenceMinutes` value.
- Remove `FAILED_REFRESH_RETRY_SECONDS` when unused.
- Preserve subscription-loss and credential-refresh behavior.

### Step 4: Subscription Refresh
- Reuse the coordinator's registration-clear behavior in the user-triggered subscription-refresh action.
- Clear both in-memory and persisted `CONF_REGISTRATION_DATA` before the next forecast request.
- Preserve the cached forecast hash and avoid a duplicate forecast request.
- Keep automatic bootstrap refresh and normal startup unchanged.

### Step 5: Tests
- Test the complete initial sequence and repeated `480`-second delay.
- Test both 500 and 429 with one request per refresh.
- Test that HTTP `Retry-After` does not change scheduling.
- Test setup completes with unavailable entities after an initial failure.
- Test recovery marks the coordinator initialized and resets retry state.
- Test a later failure uses `ForecastCadenceMinutes`, including a non-default cadence.
- Add bootstrap 500/429 regression coverage confirming cached credentials and current behavior remain unchanged.
- Test explicit subscription refresh clears registration before one forecast request.
- Test startup and automatic bootstrap refresh do not clear registration.

### Step 6: Release and Verification
- Update `manifest.json` and `INTEGRATION_VERSION`.
- Run `wsl bash -lc "cd /mnt/c/git/ha-integration && source .venv-wsl/bin/activate && python -m pytest tests/components/horizoniq -q"`.

## Acceptance Criteria
- Initial forecast failures use `10/30/60/120/240/480/480...` seconds.
- After one successful forecast, failures retry at `ForecastCadenceMinutes`.
- 500/429 do not retry immediately or honor HTTP `Retry-After`.
- Bootstrap behavior is unchanged.
- Explicit subscription refresh clears cached registration data without duplicate requests.
- HorizonIQ tests pass.
