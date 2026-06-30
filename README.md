# HorizonIQ (Home Assistant Custom Integration)

HorizonIQ is developed by Orlent Technologies.

This integration polls a HorizonIQ forecast endpoint and exposes forecast-driven entities in Home Assistant.

When loaded, the integration publishes a local documentation page to:
- `/local/horizoniq/index.html`

## Installation

### HACS

This integration can be installed through HACS as a custom repository.

[![Open your Home Assistant instance and show this repository in HACS.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=OrlentTechnologies&repository=HorizonIQ&category=integration)

1. Open HACS in Home Assistant.
2. Go to `Integrations`.
3. Open the menu and select `Custom repositories`.
4. Add `https://github.com/OrlentTechnologies/HorizonIQ`.
5. Select `Integration` as the category.
6. Install `HorizonIQ`.
7. Restart Home Assistant.
8. Go to `Settings` > `Devices & services` > `Add integration` and search for `HorizonIQ`.

### Manual

1. Copy `custom_components/horizoniq` from this repository into the `custom_components` directory in your Home Assistant configuration directory.
2. Restart Home Assistant.
3. Go to `Settings` > `Devices & services` > `Add integration` and search for `HorizonIQ`.

## What This Integration Does

- Calls your configured API using the current forecast cadence. The default fallback is 5 minutes until the API returns a clear-text cadence value.
- Sends your current battery capacity, plus cached forecast `hash` and `registration_data`, to reduce payload churn.
- Exposes import/export mode, monetary values, forecast diagnostics, and BMS state as entities.
- Provides a `Clear Registration` button that clears cached registration data and refreshes immediately.
- Keeps Test Mode portal redirects on the same selected portal host for sign-in, subscribe, and repair links.

## Configuration Fields

These are available in `Add Integration` and in `Configure` for existing entries.

| Field | Required | Description |
|---|---|---|
| `home_assistant_installation_id` | Read-only | Stable Home Assistant installation identifier from `core.uuid`, shown for copying when registering licensing or trials. Not stored by this integration. |
| `url` | Yes | Forecast API endpoint URL. |
| `api_key` | Yes | Value sent in `X-API-KEY` request header. |
| `battery_capacity_sensor` | Yes | Entity ID whose state is sent as `currentBatteryCapacity` query value. |
| `environment` | No | `Live` or `Sandbox`. `Live` is stored internally as an empty value. |
| `hash` | No | Deterministic result of the most recent forecast, sent as the `hash` query value. Usually managed automatically. |
| `registration_data` | No | Registration data for your site, sent as `registrationData` so it is not constantly reloaded from the database. It refreshes daily or when you force refresh with the button. |
| `forecast_device_id` | No | Canonical device ID for app-owned trial binding, sent as `X-HorizonIQ-Device-Id` when set. Victron/Home Assistant setups usually use the GX device ID. |
| `forecast_device_token` | No | Portal-generated app trial device token, sent as `X-HorizonIQ-Device-Token` when set. |

## Entities Created

### Binary Sensors

- `HorizonIQ Import`
- `HorizonIQ Export`

Behavior:
- `Import` is on when API response contains `shouldImport = true`.
- `Export` is the inverse of `Import`.

### Sensors

- `HorizonIQ Total Cost` (monetary)
- `HorizonIQ Charging Cost` (monetary)
- `HorizonIQ Saving` (monetary)
- `HorizonIQ Forecast Diagnostics` (diagnostic)
- `HorizonIQ BMS State`
- `HorizonIQ Trial Status` (diagnostic)

Behavior:
- Monetary sensors read values from API payload keys like `TotalCost`, `ChargingCost`, `Saving`.
- Currency is taken from API (`currency`, `Currency`, etc.) when present.
- Forecast Diagnostics state is the number of forecast periods and its attributes include trial status details when returned by the API.
- BMS State is derived from top-level forecast state, otherwise current/upcoming period state.
- Trial Status reads app-trial fields like `hasTrial`, `isActive`, `isEligible`, `status`, `startsOnUtc`, `expiresOnUtc`, and `deviceDisplayName`. If the forecast endpoint returns HTTP 401, the integration still loads and the sensor shows `unauthorized` with authorization diagnostics.

### Button

- `HorizonIQ Clear Registration`

Behavior:
- Clears stored `registration_data` in the config entry.
- Triggers a refresh request.
- Remains available even when the coordinator is unhealthy.

## Client-Side Stored Values

The integration stores values in Home Assistant config entry storage (`.storage/core.config_entries`).

The Home Assistant Installation ID shown in the config/options flow is read from Home Assistant's own `core.uuid` storage and is displayed only as read-only metadata.

### Persisted (entry data)

| Key | How It Is Used | How It Changes |
|---|---|---|
| `url` | API endpoint used for polling. | Set by user in config/options flow. |
| `api_key` | Sent as `X-API-KEY` header. | Set by user in config/options flow. |
| `battery_capacity_sensor` | Source entity for battery capacity query value. | Set by user in config/options flow. |
| `environment` | Labels entities and keeps environment mode. | Set by user in config/options flow. |
| `hash` | Deterministic result of the most recent forecast, sent as `hash`. | Updated from API response (`hash`/variants). |
| `registration_data` | Site registration data sent as `registrationData` to avoid constant database reloads. | Refreshed daily by upstream behavior, editable in options, and force-refreshable via button. |
| `forecast_device_id` | Optional device binding header `X-HorizonIQ-Device-Id` for app-owned trials. | Set by user in config/options flow. Defaults from `gx_device_id` on legacy/external entries when present. |
| `forecast_device_token` | Optional device binding header `X-HorizonIQ-Device-Token` for app-owned trials. | Set by user in config/options flow. |

### Runtime-only (not persisted)

- Last raw API response (`coordinator.data`)
- Normalized forecast object and periods
- Derived `currency`
- Derived `target_capacity`
- App trial status details from the latest forecast response
- Last update success status

## Request/Response Notes

Each poll includes:
- `currentBatteryCapacity`
- `hash`
- `registrationData`

App-owned trials can also send optional request headers:
- `X-HorizonIQ-Device-Id`
- `X-HorizonIQ-Device-Token`

Those header names still use the legacy HorizonIQ contract and are expected.

These values are never sent as query parameters. Paid subscriptions and Stripe/provider trialing subscriptions can leave them empty.

If API returns updated hash/registration data, the integration persists them automatically.

The integration does not decrypt `registrationData`. If the backend sends `registrationData` as an encrypted blob, Home Assistant can only store and forward it unchanged. Any values Home Assistant needs to read directly, such as `forecastCadenceMinutes`, must be returned unencrypted elsewhere in the API response.

## Operational Notes

- Update interval: backend-controlled via `forecastCadenceMinutes`, with a 5-minute fallback when no clear-text cadence is available
- Request timeout: 10 seconds
- Initial refresh failures do not block entity creation; entities still load so registration can be cleared.

## License

HorizonIQ is licensed under the GNU General Public License, version 3 or later. See `LICENSE`.

## Release Checklist

Before publishing a HACS release:

- Confirm the GitHub repository is public, has a description, has topics, and has issues enabled.
- Run and pass the HACS validation, Hassfest, and test workflows.
- Update `custom_components/horizoniq/manifest.json` with the release version.
- Create a GitHub release, not only a tag, for the same version.
- Add a repository license before wider distribution.
