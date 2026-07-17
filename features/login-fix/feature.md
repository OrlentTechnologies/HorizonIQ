# Part 1: Home Assistant Integration Fix

**Target repository:** `ha-integration`  
**Model:** GPT-5.6-Terra High  
**Boundary:** Do not change or claim completion of Solar portal behavior.

## Goal
Return ownership of interactive Entra authentication to the portal. The integration should only start the Home Assistant OAuth transaction.

## Changes
1. In `HorizonIQConfigFlow.extra_authorize_data`, remove `prompt` and `max_age`.
2. Keep only portal routing data owned by the integration:
   - `installationId`
   - `mode`
3. Continue using Home Assistant's OAuth helper for `state`, PKCE, scope, and redirect URI.
4. Do not change token exchange, bootstrap, subscription, or retry behavior.
5. Do not add portal account UI or portal-session logic to this repository.

## Tests
1. Update the config-flow authorization URL test.
2. Assert `installationId` and `mode` are present.
3. Assert `prompt` and `max_age` are absent.
4. Assert `state`, `code_challenge`, and `code_challenge_method=S256` remain present.
5. Run the HorizonIQ test suite.

## Release
1. Update `manifest.json` and `INTEGRATION_VERSION` together.
2. Run:
   `wsl bash -lc "cd /mnt/c/git/ha-integration && source .venv-wsl/bin/activate && python -m pytest tests/components/horizoniq -q"`

## Acceptance Criteria
- The integration no longer forces Entra login behavior.
- Home Assistant OAuth state and PKCE remain intact.
- No portal or Solar code is changed.
- HorizonIQ tests pass.
