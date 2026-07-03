# Test Mode Redirect Persistence

## Problem
When Test Mode uses a custom portal connect URL, sign-in works through that test portal, but later actions such as Subscribe still redirect to the production HorizonIQ portal.

Example test URL:
`https://........./portal/horizoniq/connect`

Expected billing URL from that test portal:
`https://........./portal/billing`

## Goal
Persist the selected Test Mode portal base and use it for every portal redirect tied to that config flow or config entry.

## Implementation Steps

### Agent 1: URL Derivation
- Add a helper that derives portal base URL from a valid portal connect URL.
- Input: `/portal/horizoniq/connect` URL.
- Output: same scheme/host with no path/query/fragment.
- Add helper for deriving billing URL: `{portal_base}/portal/billing`.
- Keep production fallback as `PORTAL_BILLING_URL`.
- Unit test URL derivation and invalid input behavior.

### Agent 2: Config Flow State
- Store the selected Test Mode portal connection URL already captured in `_portal_connection_url`.
- Add a flow helper that returns the active billing URL:
  - Test Mode/custom portal: derive from `_portal_connection_url`.
  - Production/default: `PORTAL_BILLING_URL`.
- Update `async_step_no_subscription` Subscribe action to use that active billing URL.
- Update `_no_subscription_placeholders` so displayed Subscribe URL matches the active portal where possible.
- Add flow-manager tests for Subscribe in production and Test Mode.

### Agent 3: Entry Persistence
- Ensure entitled and no-subscription entry data persists OAuth runtime portal data.
- Ensure repairs/issues use the stored runtime portal base when available.
- Do not persist a duplicate billing URL unless needed; derive it from stored portal runtime.
- Add tests for existing entries using test portal runtime.

### Agent 4: Docs and Release
- Update README/local docs to explain Test Mode redirects stay on the selected portal.
- Update translations if user-facing text changes.
- Bump `manifest.json` and `INTEGRATION_VERSION`.
- Run `compileall` and `tests/components/horizoniq`.

## Acceptance Criteria
- Test Mode sign-in through a custom portal keeps Subscribe on the same host.
- Production Subscribe still goes to `https://horizoniq.uk/portal/billing`.
- No redirect uses production when a valid test portal URL is active.
- Home Assistant config flow does not raise `UnknownStep`.
- Full HorizonIQ test suite passes.
