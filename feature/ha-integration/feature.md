# Home Assistant Repository Handoff: Subscription Bootstrap

## Purpose

This file contains only the changes required in the external Home Assistant custom integration repository. It is self-contained because that repository is not available to the agent that created the main specification.

Implement this document in the Home Assistant integration repository without changing the backend contract. First discover the integration domain, manifest, config flow, config-entry schema, API client, update coordinator, entities, translations, diagnostics, and test conventions.

## Required Outcome

Replace manual forecast credentials with an Entra-authenticated bootstrap flow.

The integration must:

- use a stable Home Assistant installation UUID as its device ID;
- display `Sign In` and `Create Account` during setup when no bootstrap configuration exists;
- include that installation ID in the Mesh Solar portal authorization URL;
- use OAuth Authorization Code with PKCE to obtain a short-lived backend API access token;
- call the Entra-protected Mesh Solar bootstrap endpoint;
- report trial availability without starting the trial;
- require an explicit user-confirmed `Start Trial` action before beginning the 14-day period;
- configure forecasting only for `trial` or `subscribed`;
- call forecasts with the returned function key and registration ID, not with Entra;
- refresh bootstrap configuration every 24 hours;
- stop forecasting on exact subscription failure;
- support Home Assistant reauthentication and reload recovery;
- redact every secret from logs and diagnostics.

## Fixed Backend Contract

### Portal authorization entry

Use the environment-configured portal route equivalent to:

```text
https://mesh-forecaster.com/portal/ha-integration/connect
```

Build two authorization URLs:

- sign in: `mode=signin`
- create account: `mode=create`

Include:

- `installationId=<stable-uuid>`
- OAuth `state`
- `code_challenge`
- `code_challenge_method=S256`
- the registered Home Assistant OAuth `redirect_uri`

Do not invent a second callback mechanism. Use Home Assistant's OAuth2/config-flow helpers and the registered OAuth callback.

### Bootstrap endpoint

```http
POST /api/ha/bootstrap
Authorization: Bearer <entra-access-token>
Content-Type: application/json
```

```json
{
  "installationId": "76d85cbc-5a44-4e41-88f7-f02f41562f15",
  "deviceToken": "existing-trial-token-if-present",
  "rotateDeviceToken": false,
  "integrationVersion": "<integration-version>"
}
```

Expected business statuses:

- `no_subscription`
- `trial`
- `subscribed`

Only `trial` and `subscribed` responses contain forecast configuration.

For an eligible user who has not started a trial, `no_subscription` includes:

```json
{
  "reason": "trial_available",
  "trial": {
    "eligible": true,
    "durationDays": 14,
    "startsOnlyOnExplicitRequest": true
  }
}
```

Bootstrap is observational. It must not start or reserve the trial.

### Explicit trial start endpoint

Call only after the user presses `Start Trial` and confirms the warning:

```http
POST /api/trials/start
Authorization: Bearer <entra-access-token>
Content-Type: application/json
```

```json
{
  "deviceId": "<installation-id>",
  "deviceDisplayName": "Home Assistant"
}
```

Store the one-time `deviceToken` from the successful response, then call bootstrap again with that token.

Expected entitled forecast fields:

```json
{
  "endpoint": "https://api.mesh-forecaster.com/api/Forecast_Get",
  "functionKey": "<dedicated-function-key>",
  "deviceToken": "<trial-token-or-null>",
  "cadenceMinutes": 30
}
```

The response also contains:

- `registrationId`
- `installationId`
- `refreshAfterUtc`
- `entitlementExpiresOnUtc`
- a restricted `registration` object containing only configuration required by this integration.

Treat unknown `schemaVersion` values as unsupported and create a repair issue rather than guessing.

## Discovery Tasks

Before editing:

1. Find `manifest.json` and record the integration domain.
2. Find the current `config_flow.py` and identify every manually entered forecast field.
3. Find constants, config-entry keys, and migration/version handling.
4. Find the forecast API client and how it builds the `Forecast_Get` request.
5. Find the coordinator or polling loop and its retry behavior.
6. Find how `hash`, encrypted `registrationData`, and current battery capacity are persisted between calls.
7. Find existing repair issues, reauth flows, diagnostics, translations, and tests.
8. Preserve unrelated device/inverter configuration that cannot be supplied by bootstrap.

Do not remove a manual field until its replacement field is present in and validated from the bootstrap response.

## OAuth And Config Flow Changes

### OAuth model

- Use Home Assistant's OAuth2 support.
- Use Authorization Code with PKCE `S256`.
- Treat the Entra application as a public client; do not require or store a client secret.
- Use the dedicated backend API scope supplied by environment/application credentials.
- Validate OAuth state through Home Assistant's framework.
- Never put access tokens, refresh tokens, function keys, or trial tokens in URLs.

### Installation ID

- Generate a UUID once when the flow begins if one does not already exist.
- Persist it in the config entry and reuse it forever for that installation.
- Do not derive it from host name, external URL, MAC address, user email, or registration ID.
- Do not regenerate it during reload, reauth, migration, or integration upgrade.
- Use it as `X-Mesh-Device-Id` for app-trial forecasts.

### Initial form

When no bootstrap configuration exists, show a page with:

- current state: `No subscription connected`;
- `Sign In` action;
- `Create Account` action;
- short text explaining that the installation ID will identify this Home Assistant installation;
- no manual function-key, registration-ID, or trial-token fields.

Use Home Assistant's external-step/OAuth conventions rather than embedding a remote page.

### After OAuth

1. Acquire an access token for the backend API scope.
2. Call bootstrap with the installation ID and any existing trial device token.
3. Validate the complete response before updating the config entry.
4. Branch by `subscriptionStatus`.

`subscribed`:

- require `canForecast=true`;
- require endpoint, function key, registration ID, cadence, and required registration fields;
- store configuration and complete setup.

`trial`:

- require `canForecast=true`;
- require endpoint, function key, registration ID, installation ID, device token, cadence, and required registration fields;
- store the returned device token and complete setup.

`no_subscription`:

- do not initialize forecast polling;
- show the stable backend reason and subscribe URL;
- if `trial.eligible=true`, offer `Start Trial` as well as `Subscribe`, `Check Again`, and `Reauthenticate`;
- before starting, show a confirmation that the 14-day trial begins immediately and cannot be restarted for the same account or installation;
- only after confirmation, call `POST /api/trials/start`, store its one-time token, and call bootstrap again;
- canceling or dismissing the confirmation must leave trial state unchanged;
- do not treat it as a transient network retry.

Signing in, creating an account, checking again, reauthenticating, reloading, and daily bootstrap refresh must never start a trial.

### Reauthentication

Implement the standard Home Assistant `SOURCE_REAUTH` flow.

Reauth is required when:

- OAuth refresh fails;
- bootstrap returns `401`;
- forecast function-key rejection cannot be repaired by one authenticated bootstrap refresh;
- the user explicitly selects reconnect/check subscription;
- a stored trial token is missing and explicit recovery is required.

After successful reauth, call bootstrap before reloading platforms.

## Config Entry Data

Use constants and typed parsing. Recommended logical fields:

```text
installation_id
subscription_status
registration_id
forecast_endpoint
forecast_function_key
forecast_device_token
forecast_cadence_minutes
bootstrap_refresh_after_utc
entitlement_expires_on_utc
registration_config
bootstrap_schema_version
```

OAuth token data should remain under Home Assistant's OAuth implementation rather than being copied into arbitrary config-entry fields.

Update the config entry atomically only after a full response passes validation. Keep the old known-good forecast credentials if a daily refresh fails due to a temporary network/server error. Do not keep using them after a valid `no_subscription` response.

### Entry version migration

- Increment the config-entry version.
- Migrate existing manual entries without losing unrelated inverter/device settings.
- Existing entries may continue forecasting with their current endpoint/key until the user completes the new connection flow, but mark them for reauth/migration.
- Do not silently fabricate an installation ID for a running trial entry if that would change its device binding. Generate it during migration only when no trial binding exists, or require reauth to bind safely.
- Remove deprecated manual credential fields only after successful bootstrap.

## API Client Changes

Create separate clients or clearly separate methods for:

- Entra-protected bootstrap API;
- function-key-protected forecast API.

Do not add the Entra bearer token to forecast requests.

### Forecast URL construction

Build requests with the HTTP client's URL/query facilities:

```text
endpoint: response.forecast.endpoint
query code: response.forecast.functionKey
query currentBatteryCapacity: current value
query hash: cached value when present
query registrationData: cached value when present
```

Headers:

```text
X-API-KEY: registrationId
```

For `trial`, also include:

```text
X-Mesh-Device-Id: installationId
X-Mesh-Device-Token: deviceToken
```

Paid/provider-backed `subscribed` calls do not require trial headers. It is acceptable to include the installation ID for diagnostics only if the backend contract allows it, but never send a blank token header.

### Response handling

Preserve the integration's current successful forecast parsing and cache update behavior.

Classify errors explicitly:

- network/timeout/5xx: transient availability error;
- `429`: respect cadence/retry information and do not reauthenticate;
- `400` with exact body `No valid subscription found.`: terminal entitlement loss until bootstrap succeeds;
- other `400`: configuration or request error, not subscription loss;
- forecast `401`/`403`: possible function-key rotation, perform one bootstrap refresh then retry once;
- bootstrap `401`: reauth required;
- bootstrap `no_subscription`: stop forecasts.

Never loop bootstrap and forecast retries indefinitely.

## Coordinator And Lifecycle Changes

### Setup gate

`async_setup_entry` must not create forecast platforms/coordinators until the stored bootstrap state is entitled and structurally valid.

Before starting forecasts:

1. If bootstrap refresh is due, refresh it.
2. If refresh returns `trial` or `subscribed`, apply it and continue.
3. If refresh returns `no_subscription`, create/update the repair issue and raise the integration's not-ready/auth state without scheduling forecast polling.
4. If refresh requires user interaction, start reauth.

### Daily refresh

- Schedule the next refresh from `refreshAfterUtc`; default to 24 hours only when the field is absent in a compatible schema.
- Add deterministic jitter based on installation ID.
- Acquire an Entra access token only for the refresh call.
- Atomically replace function key and returned registration configuration.
- Keep the old key during temporary refresh failure.
- Expose refresh failure through normal Home Assistant availability/issue patterns without logging secrets.

### Entitlement loss

On exact forecast subscription failure:

- cancel or suspend the forecast update listener/coordinator;
- clear cached forecast `hash` and encrypted `registrationData`;
- set the internal state to `no_subscription`;
- create a persistent repair issue with translation-backed text;
- point the user to the returned/stored portal billing URL;
- offer reauth/reload/check-again actions;
- do not continue one-minute or normal cadence retries.

On config-entry reload:

- authenticate if necessary;
- call bootstrap first;
- restart forecasting only when the response is entitled.

### Key rotation recovery

On a forecast `401` or `403`:

1. Pause normal polling.
2. Run one authenticated bootstrap refresh.
3. If entitled, store the new key and retry forecast once.
4. If retry succeeds, resume normal polling.
5. If OAuth needs interaction, start reauth.
6. If retry fails, create a repair issue and remain paused.

## Trial Token Recovery

The backend stores only a hash of the trial device token, so it cannot return a lost token.

When an existing trial is bound to this installation ID but the local token is missing:

- require explicit user reauthentication;
- call bootstrap with `rotateDeviceToken=true`;
- accept a replacement only when the backend confirms the same account and device fingerprint;
- store the new token atomically;
- never rotate automatically during ordinary daily refresh;
- inform the user that other copies of the old token will stop working.

## User Experience

Use translations for all strings.

Required states/messages:

- `No subscription connected`
- `Trial active until {date}`
- `Subscription active`
- `Your Mesh Solar trial or subscription is no longer valid. Subscribe, then reload or reconnect the integration.`
- `Home Assistant needs you to sign in again to check your subscription.`
- `Forecast credentials could not be refreshed.`
- `The trial device token must be replaced for this installation.`
- `Starting the trial begins your 14-day period immediately. The trial cannot be restarted for this account or Home Assistant installation.`

Required actions where supported:

- Sign In
- Create Account
- Start Trial
- Subscribe
- Check Again
- Reauthenticate
- Reload

Do not display the function key, trial token, Entra token, encrypted registration data, MPAN, or cloud credentials in UI text.

## Diagnostics And Logging

Redact at minimum:

- `forecast_function_key`
- any URL `code` query value;
- `forecast_device_token`
- OAuth access/refresh/id tokens;
- cached encrypted `registrationData`;
- authorization headers;
- MPAN or external-cloud credentials if legacy entries contain them.

Safe diagnostic fields include:

- integration version;
- bootstrap schema version;
- subscription status;
- can-forecast boolean;
- cadence;
- entitlement expiry;
- refresh due time;
- endpoint host without query parameters;
- installation ID only if Home Assistant diagnostic policy permits it, otherwise redact/hash it;
- whether each required credential is present, never its value.

Use exception types that do not embed request URLs containing `code`.

## Tests

Follow the repository's existing pytest fixtures and Home Assistant test helpers.

### Config flow tests

- Initial setup shows Sign In and Create Account.
- Installation ID is generated once and included in both URLs.
- OAuth state and PKCE are preserved.
- Create Account uses create mode.
- Successful subscribed bootstrap creates an entry.
- Successful trial bootstrap stores the device token.
- Trial-eligible bootstrap shows Start Trial but does not start it.
- Canceling the Start Trial confirmation does not call the trial endpoint.
- Confirming Start Trial calls `POST /api/trials/start` with the installation ID, stores the token, then calls bootstrap again.
- No-subscription bootstrap does not start forecasting or consume trial eligibility.
- Invalid/missing bootstrap fields abort with a stable error.
- Unknown schema version creates an unsupported-version error.
- Reauth updates the existing entry rather than creating a duplicate.

### Migration tests

- Manual credential entry migrates without losing unrelated settings.
- Deprecated credentials are retained until bootstrap succeeds.
- Trial-bound entries do not silently change installation ID.

### API tests

- Subscribed forecast sends `code` and `X-API-KEY`.
- Trial forecast also sends both device headers.
- Entra bearer token is sent to bootstrap only.
- URL encoding protects query values.
- Secrets are absent from exception text.

### Coordinator tests

- Entitled setup starts updates.
- No-subscription setup does not schedule updates.
- Exact `400` subscription body stops updates and creates an issue.
- Other `400` errors do not get mislabeled as subscription loss.
- `429` respects cadence.
- Forecast `401`/`403` performs one bootstrap refresh and one retry.
- A rotated key is applied atomically.
- Failed key refresh does not loop.
- Daily refresh uses `refreshAfterUtc` and jitter.
- Valid no-subscription refresh stops an already running coordinator.
- Reload checks bootstrap before restarting.

### Trial recovery tests

- Missing token requires explicit recovery.
- Token rotation request is sent only after user confirmation/reauth.
- Returned replacement token supersedes the old stored value.
- Different installation ID cannot be used for recovery.

### Diagnostics tests

- Function key is redacted.
- `code` query parameter is redacted.
- Trial token is redacted.
- OAuth tokens are redacted.
- Encrypted registration data is redacted.

## Acceptance Criteria

1. A new user can create an account, then choose to subscribe or explicitly start the trial without manually entering forecast credentials.
2. An existing user can sign in and complete setup using the same Home Assistant installation ID.
3. App-trial users send the installation ID and returned device token on every forecast.
4. Provider-subscribed users forecast without a trial token.
5. Bootstrap, sign-in, account creation, reload, and refresh never start a trial.
6. The 14-day trial begins only after the user explicitly confirms Start Trial.
7. `no_subscription` never starts or continues forecast polling.
8. Exact forecast subscription failure pauses the integration until bootstrap succeeds again.
9. Daily bootstrap refresh applies key rotation without downtime for online installations.
10. Reauth and reload check subscription before restarting forecasts.
11. No secret appears in Home Assistant logs, issues, UI, or diagnostics.
12. All repository tests, linting, formatting, and Home Assistant quality checks pass.

## Constraints For The Implementing Agent

- Adapt names and file paths to the external repository's established conventions.
- Do not redesign the backend API contract.
- Do not restore manual function-key or registration-ID entry as the primary flow.
- Do not use Entra access tokens for forecast requests.
- Do not retry after entitlement loss on the ordinary polling cadence.
- Do not serialize or expose secrets for debugging.
- If the existing integration architecture cannot support OAuth2/PKCE or reauth without a major redesign, stop and report the concrete repository constraint before implementing an insecure workaround.
