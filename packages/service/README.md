# ovenbird (service)

The asyncio service that talks MQTT to the heat pump, runs the controller from
`ovenbird-core`, stores state and exposes the API used by the UI and Home Assistant.

It subscribes to HeishaMon (`<base>/#`), optional plain MQTT topics and optional Home
Assistant entities, keeps the latest state, writes history to `<data_dir>/history.db`,
runs the controller every 60 s and serves the API v1 (`docs/api-v1.md`) plus the UI.

**Default mode is `shadow`: decisions are computed, logged (decision table, API,
WebSocket) and nothing is published.**

## Control loop and command path

Every tick builds the controller inputs from the state store, runs `OvenbirdController`
(`ovenbird-core`), stores the decision record and lets the **arbiter** compare each
intent with what the pump reports (`Z1_Water_Target_Temp`, `Max_Pump_Duty`,
`Quiet_Mode_Level`): `none` when already applied, in flight or queued; `skip` when the
pump's value is unknown or stale (never write blind) or the adapter holds; `send`
otherwise. In `shadow` a `send` only records what would have been sent.

The **HeishaMon command adapter** (`ovenbird/control/adapter/`; its link in `publish.py`) is the only code that
can publish. It accepts a closed allowlist of three settings: the water setpoint (via
`SetCurves` `zone1.heat.target.high` or `SetZ1HeatRequestTemperature`, see
`OVENBIRD_COMMAND_SETPOINT_REGISTER`), `SetMaxPumpDuty` and `SetQuietMode`. It clamps to
integers within the safety limits (setpoint within the emitter preset's minimum
setpoint and maximum supply temperature, pump duty within the configured range, quiet
0..3), publishes only while a fresh `Heating_Mode` is Direct and `Operating_Mode_State`
is heat (a change raises `mode_mismatch` and drops the queue), keeps one command in
flight with the newest value per setting queued and at least 7 s between commands,
verifies each command against the pump's read-back within 30 s with up to 3 retries
(then `verification_failed` and a hold), counts commands per UTC day against a budget
(`write_budget` alarm when used up) and detects a foreign writer when a verified value
is later read back different (`foreign_writer` alarm, hold, queue dropped). Queued
values the controller no longer wants are dropped (`superseded`), and a value the pump
already reports and the controller wants is adopted as ovenbird's own. Commands are
published with QoS 1, never retained, over a separate connection without a last will.
Every event goes to the `command` table (`GET api/v1/commands`).

### Operator pump settings (the second allowlist)

Besides the controller's three intents, an admin may write exactly three pump
settings (`POST api/v1/pump/settings/{id}`): the heating delta-T (`SetFloorHeatDelta`,
read back on `main/Heat_Delta`, 3–10 K), the pump flow-rate mode (`SetPumpFlowrateMode`,
`main/Pump_Flowrate_Mode`, 0 DeltaT / 1 Max flow) and the heating-off outdoor
temperature (`SetHeatingOffOutdoorTemp`, `main/Heating_Off_Outdoor_Temp`, 10–35 °C).
HeishaMon reads these as integers and passes them to the pump without a range
check, so only decimal integers inside the clamp are ever sent. The
write is a one-shot request into the same adapter: the same publish guard, a second
closed allowlist (`PumpSetting`, so the adapter's topic allowlist is exactly six
topics), spacing, verification against the read-back topic with retries, daily
budget and journal (every event's `detail` starts with `operator: <actor>`). It
differs from a controller intent in that a value outside the clamp or not an integer is
**refused** (never clamped), it is written only when the operator's `expect` equals the
fresh reported value (compare-and-set), never during a defrost, a DHW run, any hold
(board, mode, foreign writer, verification, safety) or in shadow, one at a time, at
most once per setting per 10 min and six times per 24 h (service clock, kept across a
restart). A queued write that a defrost, DHW run or safety hold overtakes is dropped. A
failed verification raises `verification_failed` ("not supported by this model?")
but does **not** hold setpoint control; a later change of such a value that ovenbird
did not make (the Panasonic remote) raises `pump_setting_changed` (info), not a
foreign-writer hold. The controller's own path can never reach these settings, and
every other HeishaMon command (operating mode, DHW, zones, backup heater, ...) has no
code path at all. Each accepted write is audited (`pump_setting`).

### Holds, escalation and release

A foreign writer or a verification failure starts a hold. Within
`OVENBIRD_COMMAND_ESCALATION_HOURS` (12 h) the first hold lasts
`OVENBIRD_COMMAND_HOLD_S` (1 h), the second `OVENBIRD_COMMAND_ESCALATION_FACTOR` times
as long (4 h) and the `OVENBIRD_COMMAND_LATCH_AFTER`-th (third) is **latched**: it ends
only through `POST api/v1/control/release-hold` by the admin (see `docs/api-v1.md`),
which also restarts the count. Every hold start, expiry and release is journalled
(`alarm` table, code `command_hold`). Alarms clear only when their condition is gone:
`foreign_writer` and `verification_failed` stay after the hold until ovenbird's value is
in effect again (a verified command, or the pump reporting the value the controller
wants), `mode_mismatch` until a fresh Direct/heat reading, `write_budget` at the next
UTC day. A read-back difference within 10 min of a detected HeishaMon restart (uptime
reset, heartbeat back after a gap, LWT Offline then Online) is not a foreign writer:
ovenbird drops its ownership of that setting, raises `heishamon_restarted` (info) and
sends its value again. With `OVENBIRD_ENVELOPE_RULE_INSTALLED=true`, a water setpoint
difference the HeishaMon envelope rule explains (ovenbird's value outside the envelope
band at the current `Outside_Temp`, the pump now reporting the rule's value there) is
not a foreign writer either: it is journalled as `envelope_correction` (info), counted
and adopted; `envelope_mismatch` (warning, once) when ovenbird's value already lay
outside the band when it was set.

A `foreign_writer` alarm and the hold it starts carry structured forensics in `detail`
(register, the value ovenbird set, the value seen and since when, what the pump keeps,
the hold end and whether ovenbird writes again then or waits for a release).

### Release control (hand-back)

At go-live (the first `auto` tick with publishing permitted, before the arbiter) the
pump state is recorded: the water setpoint, pump duty and quiet level ovenbird may
write, plus the heating mode, operating state and curve as facts
(`GET api/v1/control/snapshot`, kept in `config.db`). `POST api/v1/control/release`
(admin, optional `{"rehearsal": true}`) stores the pause first (a storage error refuses
the release with `503 storage_failed` and changes nothing), stops the controller, waits
for any of its own commands still in flight, restores every snapshot value that differs
through the normal adapter (allowlist, clamps, spacing, budget, verification; refused
during a hold; the water setpoint kept inside the envelope band at the current outside
temperature), reads the pump's values back and then pauses, so the previous controller can take over.
Each item, the time taken and the outcome are reported and audited
(`control_release`); a rehearsal counts for the trial checklist when it restored
everything within 5 min. Only an `ok` release uses up the snapshot: after an incomplete
one a resume keeps it. The run is stored as it goes; a restart in the middle reports
`interrupted` and raises `release_interrupted`. Settings ovenbird does not manage are
never touched.

Before go-live, in shadow, an admin captures a snapshot from the pump's current values
(`POST api/v1/control/snapshot`) and runs a dry rehearsal against it
(`{"rehearsal": true, "dry": true}`: the plan, nothing sent); the go-live replaces the
captured snapshot with its own. A snapshot shows its age and turns stale after 7 days
(captured) or 30 days (go-live).

### Shadow and trial facts

`GET api/v1/shadow/divergence` compares ovenbird's would-be setpoint with the pump's
water target per minute (series, per-day summary, episodes with ovenbird's reason; gaps
are reported, not counted; an admin can mark a long episode as explained with a note,
`POST api/v1/shadow/episodes/explain`, audited). `GET api/v1/trial/status` is the
checklist from live facts in two groups: go-live (shadow days, divergence, envelope rule
declared, notifications, release plan, alarms, room, snapshot), which can all turn `ok`
in shadow, and trial (envelope rule proven, rollback rehearsal), which need ovenbird in
control; each `ok`/`warn`/`fail` with evidence and a message saying what is missing.
The trial summary compares the trial with an equal baseline period; `met` only for a
complete trial (a go-live snapshot and at least 7 days). `GET api/v1/insight/runs` reports compressor run
lengths. `GET api/v1/system/about` shows version, uptime, starts, register, interval,
connections and the safety net: whether the HeishaMon envelope rule is declared
installed and when it was last seen correcting the pump (a change from outside the
envelope band to exactly the rule's value that no known writer explains: not sent by
ovenbird and seen only while ovenbird is the only controller, never in shadow), plus
ovenbird's own corrections.

### Notifications

With `OVENBIRD_NOTIFY_NTFY_URL` and `_TOPIC` every raised alarm at or above
`OVENBIRD_NOTIFY_MIN_SEVERITY` is sent to ntfy (JSON publish, optional bearer token),
its clearing once it stayed clear for 10 min (so a flapping alarm sends one raise, and a
raise after a sent clearing is never dropped); `OVENBIRD_NOTIFY_EVENTS` adds hold,
wood-stove, pause/resume and release events. Titles and bodies are readable text in
`OVENBIRD_NOTIFY_LANGUAGE` (`en` or `nl`). The notifier is attached before anything can
raise an alarm and replays the active ones at start; what the phone was told is kept in
`config.db`. Failed sends are retried with back-off (30 s doubling to 15 min); after 3
failures in a row the warning `notify_failing` shows on the dashboard. Rate limits are
per severity and hour (critical 30, warning 20, info 20, so a burst of warnings never
starves a critical alarm); the test has its own limit (one per 30 s, 10 per hour).
`OVENBIRD_NOTIFY_DEADMAN_URL` (e.g. a healthchecks.io check, `https` unless
`_DEADMAN_ALLOW_HTTP`; redirects are never followed) gets an HTTP `GET` every
`_DEADMAN_INTERVAL_S` while the service is live, MQTT connected, HeishaMon alive, the
history being written and the control loop ticking; when the pings stop, the external
service alerts. `GET api/v1/notifications/status` (with one `health` verdict that the
System tile and the checklist share) and `POST api/v1/notifications/test` (operate)
show and test it. All of it is environment or options file only; topic, token, dead-man
URL and the ntfy URL (which may not carry credentials, a query or a fragment) never
appear in the API, logs or the configuration store.

### Exports and diagnostics

`history`, `decisions`, `commands`, `alarms` and `audit` take `?format=csv` (formula
cells escaped). `GET api/v1/diagnostics` (admin, `?format=zip`) is a redacted bundle
for issue reports: version, effective configuration (secrets as `set`/`unset`), health,
control and monitors, the newest decisions, commands and alarms, notifications, release
and trial status; no secrets, no audit trail, no client addresses or user names, no
location, MQTT or Home Assistant hosts and no local paths (the exact list is in
`docs/api-v1.md`).

### Safety monitors

`ovenbird/control/monitors.py` evaluates every `OVENBIRD_SAFETY_INTERVAL_S` (5 s), in
every mode, also during holds:

| Code | Severity | Condition |
|---|---|---|
| `setpoint_above_max` | critical | `Z1_Water_Target_Temp`, `Z1_Heat_Request_Temp` (Direct mode) or the controller's setpoint above the preset's maximum supply (40 °C for `mixed`); immediate |
| `outlet_overshoot` | critical | `Main_Outlet_Temp` above maximum supply + `OVENBIRD_SAFETY_OUTLET_MARGIN_K` (5 K) for `_OUTLET_SUSTAIN_S` (600 s); not during DHW |
| `low_flow` | critical | `Pump_Flow` below `OVENBIRD_SAFETY_MIN_FLOW_LPM` (8 l/min, model dependent) while the compressor runs, for `_FLOW_SUSTAIN_S` (120 s); not during a defrost |
| `pump_error` | critical | `Error` is not `No error`; immediate |
| `backup_heater` | warning | `Internal_Heater_State` or `External_Heater_State` active |
| `defrost_stuck` | warning | `Defrosting_State` on for longer than `OVENBIRD_SAFETY_DEFROST_MAX_S` (20 min; in a profile's deice mode 2 at least its longest mode 2 defrost + 5 min) |
| `low_flow_defrost` | warning | `Pump_Flow` below the minimum during a defrost while the compressor runs, for `_FLOW_SUSTAIN_S`; journal only or alarm per `OVENBIRD_SAFETY_DEFROST_LOW_FLOW` (see below) |
| `room_below_floor` | warning | room more than `OVENBIRD_SAFETY_ROOM_FLOOR_K` (1.5 K) below comfort for `_ROOM_FLOOR_SUSTAIN_S` (30 min) |
| `room_sensor_quiet` | warning | `on_change` room sensor: no proof of life for 8 h (`OVENBIRD_CONTROL_ROOM_ALIVE_DECAY_END_S`); raised by the control loop, clears on the next report |
| `room_sensor_silent` | warning | `on_change` room sensor: no proof of life (its value or a liveness signal) for longer than the silence limit |
| `room_report_overdue` | warning | `periodic` room sensor: no report for 3 x its report interval (it may report on change only) |
| `ha_link_down` | warning | HA configured but not connected, or no successful `get_states` re-read, for 5 min; held room values fall back to 1800 s |
| `backup_heater_allowed` | info | `Room_Heater_State` free |
| `heating_off_outdoor` | info | `Outside_Temp` at or above `Heating_Off_Outdoor_Temp` (clears 1 K below) |

`room_implausible` (warning) is raised by the control loop when the optional cross-check
switched the room feedback off (see Room sensor profiles); during a wood-stove episode
the cross-check keeps running with a wider threshold (`docs/control-interface.md`), so a
sensor far off is still flagged and a manual stove request never clears it.
`stove_reference_missing` (warning) is raised by the control loop while a wood-stove
episode runs with `control_stove_reference_signal` set but no fresh temperature from it
(unknown entity, stale, not in °C): the back-off is halved meanwhile; it clears when the
reference reports again or the episode ends. Wood-stove mode's entries and exits go to
the alarm journal as informational `stove_mode` events (not alarms).
`release_interrupted` (warning) is raised at start when a release was still running when
the service stopped (it says which settings were not confirmed); it clears when a
release finishes ok or ovenbird controls again. `notify_failing` (warning) is raised
after 3 failed push sends in a row and clears on the next delivered one; it is never
pushed itself. The yearly archive raises `archive_failing` (warning) after 4 failed steps
in a row (history retention waits for it at most 3 days) and `archive_rebuilt` (warning,
24 h) when it moved a damaged working copy aside and rebuilt it (`docs/api-v1.md`,
Yearly archive).

A monitor whose inputs are missing or stale is `unknown` and keeps its alarm as it is;
an alarm clears only when its monitor reports `ok`. Every transition goes to the
`alarm` table (`GET api/v1/alarms`). `checks.alarms` in `api/v1/health` is the highest
active severity; a critical alarm makes `ready` false.

Some heat pumps stop their water pump while defrosting. `Heat_Pump_Model` selects a
model profile (`ovenbird_core.pumpmodel`; only ID bytes verified on a real unit) with
facts from Panasonic's service manual: for the WH-MXC12J9E8 (PAPAMY2110029CE, 14.2.2
"Deice Operation") deice mode 1 is the reverse-cycle defrost with the water pump
running (at most 9.5 min), mode 2 a hot-gas-bypass defrost with the water pump off by
design (at most 30 min), picked when the water inlet is below 27 °C, or below 60 °C with
the outdoor air below −10 °C. The monitor latches `Main_Inlet_Temp` and `Outside_Temp`
when `Defrosting_State` turns on (the profile may arrive later). An unknown model gets
no deice mode and a message that only describes what was seen.
`OVENBIRD_SAFETY_DEFROST_LOW_FLOW` (editable under Settings): `auto` (default) only
journals a low flow in mode 2 and raises the warning otherwise, `log` also only
journals it for an unknown model, `alarm` always raises it; in mode 1 it is always the
warning. Journalled means a `started` and a `cleared` event with severity `info` and
`detail.logged_only`, never an active alarm and never a notification.

While publishing is permitted, critical alarms act on the adapter:

- **Out-of-range setpoint** (`setpoint_above_max`, e.g. a foreign `SetCurves` 300 that
  the pump stores as 44 °C): the reading itself counts as a foreign writer (ovenbird
  never sends it; hold and escalation as above), and the adapter **re-asserts a safe
  setpoint** — the controller's current water intent, else ovenbird's last verified
  value, else the safety minimum, clamped to the safety range. The correction bypasses
  foreign-writer, verification and latched holds, pre-empts the queue and any normal
  command in flight, keeps the 7 s spacing, may use 10 writes beyond the daily budget
  and is limited to 3 per hour. It is never sent while the guard refuses, in
  simulation mode without a simulated board, or without a fresh Direct `Heating_Mode`
  and heat `Operating_Mode_State` (in compensation mode the register is a shift). When
  the corrections run out, `correction_failed` (critical) is raised.
- **Every other critical alarm** (`outlet_overshoot`, `low_flow`, `pump_error`,
  `correction_failed`) is a **safety hold**: only water setpoint decreases below the
  reported value are released; everything else waits until the alarm clears.

### Room sensor profiles

The room sensor's reporting behaviour is a profile (`OVENBIRD_CONTROL_ROOM_*`), applied
by the state store to the room signal so the controller, the monitors, the history and
the API agree on its freshness:

- `periodic` (default): the sensor reports on a schedule or with a heartbeat; its value
  is stale after `max(1800 s, 3 x OVENBIRD_CONTROL_ROOM_REPORT_INTERVAL_S)` (300 s by
  default, so 1800 s: unchanged behaviour when nothing is configured).
- `on_change`: the sensor reports only when the value moves by `STEP_K` (battery Zigbee
  or Thread sensors without a heartbeat). The last value is held while the device is
  alive - its own reports or those of `LIVENESS_SIGNALS` (sibling entities of the same
  device such as its humidity, subscribed automatically) - up to
  `SILENCE_LIMIT_S` (24 h). The hold needs the source link: for HA a connection and a
  successful `get_states` re-read within 900 s, for MQTT a connected broker; otherwise the
  normal 1800 s applies. HA `unavailable` still invalidates at once. A retained MQTT
  value seeds the held value but only counts as alive after a live report of the value
  or a liveness signal.

The controller guards a held value: its integrator ignores one full `STEP_K` of error
(the value is only known to that precision), cooling feedback loses authority linearly
from 6 h held to zero at the silence limit (a sensor that died at a warm reading cannot
keep the water below the curve for a day), and an optional
`OVENBIRD_CONTROL_ROOM_CROSSCHECK_SIGNAL` (e.g. `main/Room_Thermostat_Temp`) switches
the feedback off when it disagrees with the room value by more than 1.5 K (after a
slowly learned offset) for 2 h. The decision note shows the state, e.g. "held value
22.9 °C (2 h 10 m), device alive (humidity 4 min ago), ±0.2 K, authority 100 %".
`python -m ovenbird_sim.sensorcheck` (`make evaluate-sensorcheck`) proposes a profile
from the sensor's recorded HA history.

### Restart recovery

On start the adapter rebuilds from the journal: commands `sent` since UTC midnight (the
daily budget), holds since the last release (the escalation count) and the hold active
at shutdown (latched stays latched, a timed hold keeps its end), and the operator's
pump-setting requests of the last 24 h (their rate limits). The controller state
(integrator, outside filter, run timers, ramp, last setpoints) is saved after every
tick (`control_state` table) and restored when it is at most
`OVENBIRD_CONTROL_STATE_MAX_AGE_S` (15 min) old, so a restart does not reset the PI.

### Publish guard

Publishing is possible only when **all four** hold:

1. `OVENBIRD_CONTROL_MODE=auto` (default `shadow`);
2. `OVENBIRD_ALLOW_COMMANDS=true` (default false);
3. the configured broker is listed in `OVENBIRD_COMMAND_BROKERS` (default empty), as
   `host` or `host:port`, compared exactly and case-insensitively with
   `OVENBIRD_MQTT_HOST`/`_PORT` — no DNS resolution, no wildcards, no ranges;
4. the service clock is real time (`OVENBIRD_CLOCK_SPEED` 1, no `OVENBIRD_CLOCK_START`),
   or `OVENBIRD_SIMULATION=true`.

`OVENBIRD_SIMULATION` marks the broker as a simulator. It is environment only, cannot
be combined with HA app (ingress) mode, and the settings refuse it unless
`OVENBIRD_MQTT_HOST` and every `OVENBIRD_COMMAND_BROKERS` entry is a loopback address
or the dev stack's `mosquitto`. In simulation mode the adapter additionally releases
nothing until HeishaMon's `stats` report a simulated firmware version (`*-sim`, as the
simulated HeishaMon does), so even a production broker that happens to be named
`mosquitto` never receives a command timed by a scaled clock.

`OVENBIRD_ALLOW_COMMANDS`, `OVENBIRD_COMMAND_BROKERS` and `OVENBIRD_SIMULATION` are read
from the environment only; an options file (HA app options, a copied `options.json`) can never switch
publishing on. Without all three the publishing connection is never created, the
adapter refuses every request and the link refuses every publish (the guard is checked
at build time, per request and per publish). Listing only a dev broker name such as the
compose service `mosquitto` means a configuration pointed at a production broker cannot
publish by accident. `GET api/v1/decisions/latest` reports `publishing` and the unmet
conditions; a `COMMANDS ENABLED` warning is logged at start when publishing is possible.

On top of the four installation conditions a runtime **shadow hold** can stop an `auto`
installation: an operator's pause (`POST api/v1/control/pause`, kept across restarts,
ended by `POST api/v1/control/resume`) or a lost configuration store (below). While it
holds the loop runs as `shadow` (decisions record `mode: shadow`), the guard refuses
("control is paused"), the adapter drops its queue, forgets its verified
values (whoever writes meanwhile is not a foreign writer) and releases nothing, not
even a safety correction; the publishing connection stays open but idle.

## House-model learner

The optional learner (`python -m ovenbird_sim.learn`, root `Dockerfile` target `learner`)
refits the house model weekly and writes JSON that the service serves under
`api/v1/insight/house` (`docs/design.md`, House insight). It is untrusted code with the
scientific stack, so it gets only what it needs:

- `<data_dir>/learner/` (mode 0750, files 0640), written by the service, **read-only**
  for the learner: `learner-config.json` (the effective `control_*` and `house_*`
  fields, no secrets; rewritten at start and after every apply) and
  `history.snapshot.db` (a hard link to the atomically replaced backup snapshot, or a
  copy where links fail; refreshed every 10 min).
- `<data_dir>/models/` (mode 2770), the learner's output. The service reads it as
  untrusted: no links (`O_NOFOLLOW`), regular files of at most 4 MB, strict JSON, an
  allow-list of keys with bounded sizes and checked types; anything else is answered
  as `state: learning` with the reason. A model whose learner has not run for twice its
  interval (`interval_h` in `status.json`, else weekly) is reported with
  `learner.stale: true`.

Never mount the whole data volume into the learner: it holds `options.json` (MQTT and
HA credentials), `config.db` and the live `history.db`. Production recipe, next to a
service whose data volume is `ovenbird-data` (Docker 26 or newer for
`volume-subpath`; with a bind-mounted data directory use `-v <dir>/learner:/learner:ro
-v <dir>/models:/models`):

```fish
docker run -d --name ovenbird-learner --restart unless-stopped \
    --user 10003:10001 --read-only --network none --cap-drop ALL \
    --security-opt no-new-privileges \
    --mount type=volume,src=ovenbird-data,dst=/learner,readonly,volume-subpath=learner \
    --mount type=volume,src=ovenbird-data,dst=/models,volume-subpath=models \
    ovenbird-learner
```

The image's default command reads `/learner/history.snapshot.db` and
`/learner/learner-config.json`, writes `/models` and repeats every 168 h. uid 10003 is
the learner's own user; group 10001 is the service's, which gives it read access to
`learner/` and write access to `models/` and nothing else. Both directories exist once
the service has started. A weekly cron job of the same command (`--history
<data>/learner/history.snapshot.db --config <data>/learner/learner-config.json --models
<data>/models`) works too, but only the container keeps the rest of the data directory
out of the learner's reach.

## Configuration store

Control settings live in `<data_dir>/config.db` (`ovenbird/configstore/`): append-only
versions of the stored values, an audit trail of every state-changing request and the
runtime flags (pause, pending reset). Precedence, highest first: environment, options
file, store, emitter preset / default. A field set by the environment or the options
file is **locked**: the API refuses to change it (`422 locked`) and the UI shows it
read-only with its variable name. The publish gates, secrets, connections, bind
addresses, `OVENBIRD_CONTROL_MODE` (the mode ceiling) and the expert constants can never
be stored (`not_editable`), whatever a stored document contains. The safety envelope
stays anchored to the emitter preset's curve: a stored curve must lie inside it, and
the maximum supply temperature can only be lowered through the store.

A new version (`PUT api/v1/config`, admin; at most one per 60 s and 30 per day) is
validated by the same settings model, written with its audit row, snapshotted to
`config.snapshot.db` (the backup copy) and swapped into the control loop between two
ticks (`config.db` runs with `synchronous = FULL`, so a stored pause survives a power
cut): the controller state carries over, so the setpoint moves only through deadband
and dwell (or a safety bound). The first decision made with it carries the new
`config_version`.

When `config.db` is missing after having existed (and no snapshot can restore it), is
corrupt (moved aside) or its newest version no longer validates, the service starts
with the installation's values in shadow and the warning alarm `config_reset` until an
admin acknowledges it (`POST api/v1/config/reset-ack`). `OVENBIRD_CONFIG_SEED` names an
export file whose values become version 1 of an empty store (the dev stack uses
`dev/config-seed.json`). To hand an environment-set field to the UI: export, remove the
variable, restart (the stored value then applies) or import.

### Preview

`POST api/v1/config/preview` steps the controller once with the candidate on the current
inputs, and replays the recorded decisions of the last 1–72 h with it (open loop, from
the recorded controller state at the window start; inputs rebuilt from each decision's
`inputs_used`). The same replay with the active configuration must reproduce every
recorded setpoint made under the active version (`identity_ok`); 72 h replay in about a
second.

### Weather

With `weather_enabled` and a location (manual, else HA's `zone.home`), the service
fetches an Open-Meteo forecast every hour (stdlib `urllib` in a thread, backoff after a
failure; simulation mode uses a simulated provider and never the network) and stores
every issue as issued in `history.db` (table `forecast`, retention as the 1 h rollup).
It is display-only (`GET api/v1/weather`), not a controller input; health check
`weather` never affects readiness.

## Configuration

Environment variables (`OVENBIRD_*`) override `/data/options.json` (path:
`OVENBIRD_OPTIONS_FILE`), whose keys are the names below without the prefix. Every
control field (`OVENBIRD_CONTROL_*` except the mode and interval, `OVENBIRD_WEATHER_*`,
the room-floor monitor) can also be left unset here and set in the configuration store
instead; see `GET api/v1/config/schema` for the full list with bounds.

| Variable | Default | |
|---|---|---|
| `OVENBIRD_MQTT_HOST` / `_PORT` | `localhost` / `1883` | broker |
| `OVENBIRD_MQTT_USERNAME` / `_PASSWORD` | unset | broker credentials |
| `OVENBIRD_MQTT_TLS` / `_CA_FILE` | `false` / system CAs | TLS |
| `OVENBIRD_HEISHAMON_BASE` | `panasonic_heat_pump` | HeishaMon topic base |

The broker fields above (`OVENBIRD_MQTT_*` but the inputs, and the base) can also be
set in the app (Settings → MQTT, `PUT api/v1/config/mqtt` after a successful
`POST api/v1/config/mqtt/test`); a value set here or in the options file wins and
shows read-only there. A change that brings no HeishaMon data within 60 s is
reverted (see `docs/api-v1.md`).

| Variable | Default | |
|---|---|---|
| `OVENBIRD_MQTT_INPUTS` | `[]` | JSON list of `{"topic", "signal", "unit", "minimum", "maximum"}`; also editable in the app (Settings → MQTT, a configuration version) |
| `OVENBIRD_HA_URL` / `_TOKEN` / `_ENTITIES` | unset | HA input (entities comma-separated) |
| `OVENBIRD_DATA_DIR` | `/data` | `history.db` and the instance lock |
| `OVENBIRD_UI_DIR` | `/opt/ovenbird/ui` | built UI |
| `OVENBIRD_HTTP_HOST` / `_PORT` | `127.0.0.1` / `8099` | HTTP bind |
| `OVENBIRD_ADMIN_USERNAME` / `_PASSWORD` | `admin` / unset | HTTP Basic on everything but `api/v1/health`; required for a non-loopback bind |
| `OVENBIRD_LOG_LEVEL` | `INFO` | |
| `OVENBIRD_HISTORY_RAW_DAYS` / `_1M_DAYS` / `_15M_DAYS` / `_1H_DAYS` | `14` / `90` / forever / forever | retention; `0` keeps forever, any other value is at least 1 day |
| `OVENBIRD_HISTORY_MIN_FREE_MB` | `256` | history writes pause below this free space |
| `OVENBIRD_HISTORY_SNAPSHOT_HOURS` | `6` | interval of the consistent `history.snapshot.db` copy used for backups |
| `OVENBIRD_HTTP_ALLOWED_ORIGINS` | `[]` | extra browser origins allowed for the WebSocket (list a reverse proxy's public origin here) |
| `OVENBIRD_INGRESS` | auto (on when `SUPERVISOR_TOKEN` is set) | HA app ingress mode: trust only the Supervisor ingress source without a password |
| `OVENBIRD_UID` / `_GID` | `10001` / `10001` | user the launcher drops to after fixing `/data` ownership; run the container as this user directly (e.g. `user: "10001:10001"`, Kubernetes `runAsUser`) to skip the root phase |
| `OVENBIRD_HISTORY_DECISION_DAYS` | `30` | retention of the decision and command logs |
| `OVENBIRD_HISTORY_ARCHIVE_ENABLED` | `true` | freeze every finished month into `archive/YYYY-MM.zip` (see `docs/api-v1.md`, Yearly archive) |
| `OVENBIRD_CONTROL_MODE` | `shadow` | `shadow`, `auto` or `off` |
| `OVENBIRD_CONTROL_INTERVAL_S` | `60` | controller tick |
| `OVENBIRD_CONTROL_EMITTER` | `mixed` | preset: `screed_floor`, `radiators`, `mixed` |
| `OVENBIRD_CONTROL_ROOM_SIGNAL` | unset | room signal id (`ha/sensor...` or an MQTT input's signal) |
| `OVENBIRD_CONTROL_ROOM_PROFILE` | `periodic` | room sensor profile: `periodic` or `on_change` (see Room sensor profiles) |
| `OVENBIRD_CONTROL_ROOM_STEP_K` | `0.1` / `0.2` | sensor step (`periodic` / `on_change` default) |
| `OVENBIRD_CONTROL_ROOM_REPORT_INTERVAL_S` | `300` | report interval of a `periodic` sensor (stale after `max(1800, 3 x interval)`) |
| `OVENBIRD_CONTROL_ROOM_SILENCE_LIMIT_S` | `86400` | an `on_change` value without proof of life for this long is stale (1800 s to 7 days) |
| `OVENBIRD_CONTROL_ROOM_LIVENESS_SIGNALS` | empty | sibling signals of the room sensor's device (`ha/<entity>` or MQTT input signals, comma-separated); their HA entities are subscribed automatically |
| `OVENBIRD_CONTROL_ROOM_CROSSCHECK_SIGNAL` | unset | optional plausibility cross-check (e.g. `main/Room_Thermostat_Temp`) |
| `OVENBIRD_CONTROL_COMFORT_C` | `21` | room target |
| `OVENBIRD_CONTROL_OUTSIDE_SIGNAL` / `_MAX_AGE_S` | unset / `1800` | outside thermometer for the heating curve (`ha/<entity_id>` or an MQTT input's signal, in °C) instead of the pump's `main/Outside_Temp`; the safety envelope, monitors and learning keep the pump's sensor. Older than the age limit: the curve uses the pump's sensor and `outside_sensor_stale` is raised (see `docs/control-interface.md`) |
| `OVENBIRD_CONTROL_OUTSIDE_PLAUSIBLE_MIN_C` / `_PLAUSIBLE_MAX_C` / `_MAX_DEVIATION_K` | `-40` / `50` / `10` | a chosen outside value outside the plausible range, not finite, or further than the deviation from the pump's fresh reading is not used: the curve uses the pump's sensor for that tick and `outside_sensor_implausible` is raised |
| `OVENBIRD_HOT_WATER` | `auto` | show hot water (DHW) in the app: `auto` follows the pump's `main/DHW_Installed` (shown while unknown), `on`, `off`; display only, a DHW run still freezes the corrections |
| `OVENBIRD_CONTROL_STOVE_ENABLED` | `false` | wood-stove mode (`docs/control-interface.md`): room feedback paused with its integrator held and the curve lowered while a stove heats the sensor's room; manual start/stop through `POST api/v1/control/stove` |
| `OVENBIRD_CONTROL_STOVE_AUTO` / `_ENTER_ABOVE_K` / `_EXIT_HYSTERESIS_K` | `true` / `1.5` / `1.0` | automatic detection (needs a room signal): enter at comfort + 1.5 K, leave 1 K lower |
| `OVENBIRD_CONTROL_STOVE_RISE_ENABLED` / `_RISE_K` / `_RISE_WINDOW_S` | `true` / `1.0` / `1800` | also enter on a fast rise above comfort |
| `OVENBIRD_CONTROL_STOVE_BACKOFF_K` / `_TO_MINIMUM` | `3.0` / `false` | how far the curve is lowered (or down to the safety minimum); the pump is never switched off |
| `OVENBIRD_CONTROL_STOVE_MIN_ACTIVE_S` / `_MAX_ACTIVE_S` | `3600` / `28800` | shortest automatic episode / hard cap (an automatic episode lasts while the room stays above the exit threshold; after the cap only a new fast rise enters until the room has cooled) |
| `OVENBIRD_CONTROL_STOVE_REENTRY_HOLD_S` | `900` | after an episode ended on an untrusted room value, how long the value must be trusted again before the detection re-enters |
| `OVENBIRD_CONTROL_STOVE_REFERENCE_SIGNAL` / `_REFERENCE_FLOOR_C` / `_REFERENCE_BAND_K` | unset / `19` / `1.0` | a second room (e.g. the hall): below its floor the back-off shrinks, to none at floor − band; stale: the full back-off |
| `OVENBIRD_CONTROL_MIN_SETPOINT_C` | preset (20) | lowest water setpoint; e.g. 24 to stay within what a previous controller used |
| `OVENBIRD_CONTROL_PUMP_DUTY` | `true` | let the controller set the max pump duty (heating vs idle); `false` leaves the pump's own setting alone |
| `OVENBIRD_CONTROL_PUMP_DUTY_HEAT` / `_IDLE` | `159` / `102` | max pump duty while the compressor runs or defrosts / while idle (raw HeishaMon value, within the command clamp) |
| `OVENBIRD_CONTROL_PUMP_DUTY_IDLE_DELAY_S` | `300` | wait after a compressor stop before lowering to the idle duty |
| `OVENBIRD_CONTROL_CURVE` | preset | JSON list of 2-6 `[outside_c, water_c]` points, inside the safety envelope |
| `OVENBIRD_CONTROL_MAX_SUPPLY_C` | preset (40 / 55) | hard maximum water setpoint; only here can it be raised above the emitter's |
| `OVENBIRD_CONTROL_FEEDBACK_*`, `_DEADBAND_K`, `_DWELL_S`, `_RAMP_*`, `_CYCLING_*`, `_OUTSIDE_FILTER_S` | preset | controller tuning (`GET api/v1/config/schema`) |
| `OVENBIRD_CONTROL_QUIET_WINDOWS` / `_TIMEZONE` | `[]` / `UTC` | up to four daily quiet-mode windows `{"start": "22:00", "end": "06:00", "level": 1}` |
| `OVENBIRD_CONTROL_ENVELOPE_CURVE` / `_BELOW_K` / `_ABOVE_K` | preset curve / 6 / 5 | safety envelope (expert) |
| `OVENBIRD_WEATHER_ENABLED` / `_LATITUDE` / `_LONGITUDE` / `_LOCATION_SOURCE` | `false` / unset / unset / `ha_zone_home` | forecast (opt-in; Open-Meteo, no key; location rounded to 0.01°, else HA's `zone.home`); see Weather |
| `OVENBIRD_WEATHER_SIM_FILE` | unset | simulation only: the simulator's Open-Meteo cache the simulated forecast derives from (synthetic winter when unset) |
| `OVENBIRD_OPERATE_TOKEN` | unset | environment only: bearer token (≥ 32 characters) of the operate role (validate, pause) |
| `OVENBIRD_CONFIG_SEED` | unset | export file that becomes version 1 of an empty configuration store |
| `OVENBIRD_ALLOW_COMMANDS` | `false` | publish guard, environment only |
| `OVENBIRD_COMMAND_BROKERS` | empty | publish guard, environment only (`host` or `host:port`, comma-separated) |
| `OVENBIRD_COMMAND_SETPOINT_REGISTER` | `setcurves_target_high` | or `z1_heat_request_temperature` (decided by the phase-3 spike) |
| `OVENBIRD_COMMAND_MIN_SPACING_S` / `_VERIFY_TIMEOUT_S` / `_MAX_RETRIES` | `7` / `30` / `3` | adapter timing |
| `OVENBIRD_COMMAND_DAILY_BUDGET` / `_HOLD_S` | `150` / `3600` | write budget per UTC day, hold after an alarm |
| `OVENBIRD_COMMAND_PUMP_DUTY_MIN` / `_MAX` | `80` / `200` | pump duty clamp |
| `OVENBIRD_COMMAND_ESCALATION_HOURS` / `_FACTOR` / `_LATCH_AFTER` | `12` / `4` / `3` | hold escalation |
| `OVENBIRD_CONTROL_STATE_MAX_AGE_S` | `900` | saved controller state older than this is not restored |
| `OVENBIRD_NOTIFY_NTFY_URL` / `_NTFY_TOPIC` / `_NTFY_TOKEN` | unset | ntfy server (http/https, no credentials, query or fragment), topic (secret, `[A-Za-z0-9_-]`) and optional access token; URL and topic together |
| `OVENBIRD_NOTIFY_MIN_SEVERITY` / `_EVENTS` | `warning` / `false` | lowest alarm severity sent; also send hold, stove, pause and release events |
| `OVENBIRD_NOTIFY_DEADMAN_URL` / `_DEADMAN_INTERVAL_S` | unset / `300` | dead-man ping URL (secret, `https`) and interval (60..3600 s) |
| `OVENBIRD_NOTIFY_DEADMAN_ALLOW_HTTP` | `false` | allow a plain `http` dead-man URL (a local checker) |
| `OVENBIRD_NOTIFY_LANGUAGE` | `en` | language of the push titles and bodies (`en`, `nl`) |
| `OVENBIRD_ENVELOPE_RULE_INSTALLED` | `false` | the owner declares the HeishaMon envelope fallback rule installed (trial checklist, `system/about`) |
| `OVENBIRD_SAFETY_*` | see Safety monitors | monitor thresholds and interval |
| `OVENBIRD_SIMULATION` | `false` | environment only: the broker is a simulator (see Publish guard) |
| `OVENBIRD_CLOCK_SPEED` / `_START` | `1` / now | simulation only: scaled service clock (the dev stack runs 60x from the simulator's start); publishing needs `OVENBIRD_SIMULATION=true` |

Failed logins are rate limited per source address and username: after five wrong
passwords for one username from one address that pair gets `429` with an exponentially
growing `Retry-After` (up to 5 minutes) and its credentials are not checked meanwhile.
Failures under another username, or from another address, do not affect it, so a stray
bad login behind NAT or a proxy never locks out the admin with the correct password.
At most 4096 (address, username) pairs are tracked; the least recently failing one is
forgotten first. WebSocket handshakes from browsers must come from the service's own
origin (same scheme, host and port as the request) or one in
`OVENBIRD_HTTP_ALLOWED_ORIGINS`. Roles: `read` (any authenticated request; without an
admin password a loopback-only service serves requests without credentials as `read`),
`operate` (`Authorization: Bearer <OVENBIRD_OPERATE_TOKEN>`, same lockout as Basic) and
`admin` (Basic admin, or the ingress source). Every state-changing request needs
`Content-Type: application/json`, the header `X-Ovenbird-Request: 1`, an own or allowed
`Origin` when sent, `Sec-Fetch-Site: same-origin` when sent, and a body of at most
64 kB; this applies behind ingress too (see `docs/api-v1.md`).

`GET api/v1/health` reports `checks.history` as `ok`, `starting` (the history writer has
not finished opening the database yet, normally about a second after start) or `error`.

The `history.snapshot.db` backup copy is first written after the first successful history
commit, goes through `history.snapshot.db.tmp` (removed after a failed or interrupted
copy and at start-up), and is skipped with a warning while free space is below
`OVENBIRD_HISTORY_MIN_FREE_MB` plus the current database size; a skipped snapshot never
pauses history writes. History queries with `step=0` seed a series with the value held at
`from` only when its last change is within the signal's staleness limit.

`python -m ovenbird --check` is the container health check: with a service running on
the data directory it probes the liveness endpoint, otherwise it validates the settings
and installation.
