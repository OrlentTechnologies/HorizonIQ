# Subscribe Flow Stays On Check Screen

| Step | Owner |
| --- | --- |
| 1. Verify Home Assistant flow support | GPT-5.4 |
| 2. Change Subscribe behavior | GPT-5.4 |
| 3. Update config-flow tests | GPT-5.4 |
| 4. Update release metadata and run tests | GPT-5.4 |

## Problem
Clicking `Subscribe` opens the billing website, then Home Assistant shows an `Open website` step. After completing checkout, the website does not redirect back, so the integration is left on the wrong screen.

## Goal
Clicking `Subscribe` should open the billing website and leave the visible config flow on `no_subscription`, showing:
- `Check Again`
- `Subscribe`
- `Start Trial` when still eligible

## Implementation Steps

### Step 1: Verify Home Assistant Flow Support
- Inspect `async_step_no_subscription` and `async_step_subscribe`.
- Confirm `ACTION_SUBSCRIBE` currently returns `async_external_step`.
- Confirm tests assert `FlowResultType.EXTERNAL_STEP`.
- Verify the Home Assistant-supported way to open an external URL without leaving the visible form on the `Open website` step.
- If Home Assistant cannot do both, stop and document the limitation before changing behavior.

### Step 2: Change Subscribe Behavior
- In `async_step_no_subscription`, keep using `_active_billing_url()`.
- Replace the subscribe-only external step with the verified pattern from Step 1.
- Keep the visible step on `no_subscription` after the billing website opens.
- Remove `async_step_subscribe` if it becomes unused.
- Preserve Test Mode billing URL behavior.

### Step 3: Update Config-Flow Tests
- Update subscribe tests to expect the flow to remain on `no_subscription`.
- Assert the billing URL is still emitted/opened by the subscribe action.
- Cover production and Test Mode URLs.
- Assert trial-eligible state still includes `Start Trial` after pressing `Subscribe`.
- Assert no result leaves the user waiting on the subscribe `Open website` step.

### Step 4: Release and Verification
- Remove obsolete tests for the `Open website` step.
- Update `custom_components/horizoniq/manifest.json`.
- Update `INTEGRATION_VERSION` if present.
- Run:
  `wsl bash -lc "cd /mnt/c/git/ha-integration && source .venv-wsl/bin/activate && python -m pytest tests/components/horizoniq -q"`

## Acceptance Criteria
- `Subscribe` opens the billing website.
- The integration remains on `no_subscription`.
- `Check Again`, `Subscribe`, and eligible `Start Trial` remain available.
- No `Open website` step is shown after pressing `Subscribe`.
- Production and Test Mode billing URLs still work.
- HorizonIQ tests pass.
