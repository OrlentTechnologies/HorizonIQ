# Virtual battery and local simulation

The integration owns one isolated virtual battery per Sandbox config entry. Configuration, stored energy, local faults, command deduplication and named snapshots belong to that entry. Live equipment entries do not create these controls.

## Operating modes

**Virtual** uses real UTC and a monotonic physics loop. Explicitly enabling Simulation fetches the normal Forecast_Get endpoint and schedules later refreshes at the returned cadence. Forecast schemas 5, 6, 7 and 8 are supported. Live executable commands retain their identity, expiry, priority and equipment limits; the existing local Virtual recommendation path retains its bounded import, grid-preservation and profit-export behavior. Advisory plans cannot command. Forecast solar comes from the current period. No downtime is simulated.

**Manual** runs only HA-owned physics, built-in scenarios, load/solar inputs, clock rates and explicit steps. It never fetches a forecast or validates a cloud command against synthetic time. The local physics engine and local synthetic-profile validation library remain available for HA tests. Cloud-file profile selection/playback, Replay sessions, remote simulator topics and the five profile services have been removed.

Changing either mode stops owned work, clears active power instructions, checkpoints, notifies entities and requests the existing entry reload. The reloaded entry stays paused until Simulation is explicitly enabled. Selecting the current mode is a no-op. Returning to Virtual uses real UTC on its next enable.

**Charging source** in Virtual mode is either Virtual battery or External controller. The external-power service applies bounded power through the same physics, with a default 60-second and maximum 300-second validity. Expiry, disable, unload and mode/source changes return to safe self-consumption.

## Local physics and controls

Energy is Wh, power is W and timestamps are UTC. Grid import and battery charging are positive. Export and battery discharge are negative. Initial energy is the greater of 50% capacity and reserve. Load/solar controls remain local. Grid preservation keeps battery energy available for later use and always has a None grid-power setpoint.

Set state of charge accepts reserve through 100%, changes only local energy and adds a signed manual_adjustment_wh ledger term. It invalidates the prior direct instruction until a normal scheduled forecast replaces it. The balance tolerance is accounting tolerance, not an unmodeled loss. Standard scenarios, local faults and explicit steps remain entry scoped.

## MQTT safety

Synthetic Victron telemetry remains under the generated entry-owned GX identity. Exact non-retained write and issued-command subscriptions retain validation, correlation, expiry, bounded power, duplicate protection and atomic application. Manual mode cannot accept these live envelopes. Retained input is rejected. The keepalive subscription republishes a complete current telemetry snapshot without advancing physics.

Normal command, simulator, fault and Node-RED diagnostic status remain bounded. The frozen schema-2 simulator status retains the reserved replayState slot as null; it has no session vocabulary or authority. Replay request/status/clock topics are no longer subscribed or published. Local faults retain their existing effects and ownership; replay_api_failure has been retired.

## Private storage and snapshots

Store version stays 1, private storage schema is 14 and snapshot schema is 5. Per-entry keys, atomic writes, the 30-second checkpoint delay and 20 named snapshot limit are unchanged. Records contain local battery/control/ledger/clock/scenario/fault state and the bounded duplicate-command ledger. They contain no forecasts, diagnostics, credentials, broker settings, observed outcomes or production telemetry.

Known older storage is validated before commit. Legacy Replay migrates to paused Manual/self-consumption without a network request or remote resume. Missing legacy mode defaults to Virtual; null/unknown current modes, future versions and malformed retained physics fail closed without deleting the source record. Retired session/profile fields and the retired fault are discarded. Local scenario identity/cursor and unrelated named snapshots are retained.

Snapshots 1–4 are decoded through the same validator and migrated to 5, clearing commands and stopping playback. Current Manual snapshots may restore validated local commands; grid preservation requires a None setpoint. Virtual restores never restore executable commands. Invalid restores leave current state unchanged. Restore cancels and awaits owned loop work and reestablishes only local fault effects; it makes no forecast request.

## Forecast diagnostics

One entry-local model normalizes versions 5–8. Versions 5–7 require the root plannedEnergyLedger. Version 8 accepts unavailable diagnostics or a complete nested diagnostics.plannedEnergyLedger and rejects root ledger aliases. Missing diagnostics never disable a valid command. Malformed replacements retain the last complete forecast as stale.

The existing optional forecast-diagnostics service returns the complete normalized horizon on request. Sensor summaries stay bounded and Recorder excludes the full horizon. Diagnostics are never written to integration storage, registration metadata or logs.
