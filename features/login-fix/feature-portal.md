# Part 2: Solar Portal Authentication Fix

**Target repository:** Solar portal  
**Model:** GPT-5.6-Terra High  
**Boundary:** Do not change or claim completion of the Home Assistant integration.

## Problem
The portal starts interactive Entra login repeatedly and then shows `Authentication was not completed`. The portal is not restoring the pending Home Assistant OAuth transaction after the Entra round trip.

## Goal
Authenticate once, restore the pending Home Assistant request, show the selected account, and require explicit device-link confirmation.

## Step 1: Separate The Two OAuth Transactions
1. Treat the incoming Home Assistant request and the portal's Entra login as separate transactions.
2. Preserve the complete Home Assistant request before leaving `/portal/horizoniq/connect`, including:
   - `state`
   - `redirect_uri`
   - `response_type`
   - `client_id`
   - `scope`
   - `code_challenge`
   - `code_challenge_method`
   - `installationId`
   - `mode`
3. Use the portal's existing secure transaction/session storage. Bind it to the browser session, expire it, and consume it once.
4. Do not reuse or overwrite Home Assistant's `state` as the Entra login state.

## Step 2: Fix Entra Login Lifecycle
1. On initial connect, store the Home Assistant request before starting Entra authentication.
2. Start Entra authentication only when there is no verified portal account.
3. Use `prompt=select_account` for account selection. Do not use `prompt=login` or `max_age=0` on every route render.
4. On the Entra callback, process the authentication-library redirect result first.
5. Do not validate the original Home Assistant query or start another login until callback processing finishes.
6. Restore the pending Home Assistant transaction after successful authentication.
7. Show the restart error only when the pending transaction is genuinely missing, expired, invalid, or already consumed.

## Step 3: Confirmation Page
1. Read the email or display name from the portal's validated Entra account.
2. Show `Signed in as {account}` directly above `Link device`.
3. Keep `Link device` unavailable until both identity and pending Home Assistant context are valid.
4. When linking, continue with the exact restored Home Assistant `state`, redirect URI, and PKCE values.
5. Consume the pending transaction only after the link action succeeds.

## Step 4: Switch Account
1. Add `Switch account` beside the displayed identity.
2. Preserve the pending Home Assistant transaction.
3. Clear only the active portal account selection required by the auth library.
4. Start Entra authorization with `prompt=select_account`.
5. Return to the confirmation page and require `Link device` again.

## Step 5: Tests
1. Fresh connection starts exactly one Entra login.
2. Entra callback restores a Home Assistant request even when the callback URL lacks the original query.
3. Callback processing does not start a second login.
4. Restored `state`, redirect URI, PKCE, installation ID, and mode exactly match the original values.
5. Missing, expired, changed, and replayed transactions are rejected.
6. The confirmation page displays the validated account.
7. `Switch account` preserves context and changes the displayed account.
8. Linking redirects to Home Assistant with the original state and authorization result.
9. Add an end-to-end test for connect, Entra round trip, confirmation, link, and Home Assistant redirect.

## Acceptance Criteria
- One connection attempt causes at most one automatic Entra login round trip.
- Returning from Entra does not show `Authentication was not completed` when valid context exists.
- The confirmation page identifies the selected account.
- Account switching does not lose Home Assistant state or PKCE.
- A device is linked only after explicit confirmation.
- Portal unit and end-to-end tests pass.
