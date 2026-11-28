# ovenbird HTTP API v1

All paths are relative (`api/v1/...`) so the UI works behind a path prefix such as Home
Assistant ingress. JSON everywhere; timestamps are ISO 8601 UTC strings; ages are seconds.
The only API path to the pump is an admin's write of one of three pump settings
(`POST pump/settings/{id}`), which goes through the command adapter like every
controller command. State-changing endpoints: the configuration (`config/validate`,
`config/preview`, `PUT config`, `config/rollback`, `config/reset-ack`), the mode
(`control/pause`, `control/resume`), wood-stove mode (`control/stove`), boost and away
(`control/boost`, `control/away`), `control/release-hold`, `pump/settings/{id}`, release control (`control/release`,
`control/snapshot`), `shadow/episodes/explain`, `notifications/test` and starting or
cancelling a replay (`replay`, `replay/{id}/cancel`).
The response bodies are also described in `docs/openapi.json`, generated from the
service's response models (`make api-schema`); the UI's TypeScript types are generated
from it (`npm --prefix ui run api-types`), and `make api-check` fails when either is stale.
Default time windows end at the service clock's "now" (the simulated time when the dev
stack runs a scaled clock) and are `[from, to)`.

## Roles and request rules

| Role | How | May |
|---|---|---|
| read | any authenticated request; without `OVENBIRD_ADMIN_PASSWORD` a loopback-only service serves requests without credentials as read | every `GET` except `config/export`, `config/signals`, `audit` and `diagnostics` |
| operate | `Authorization: Bearer <OVENBIRD_OPERATE_TOKEN>` (environment only, at least 32 characters, constant-time compare, same lockout as Basic) | read + `POST config/validate`, `POST config/preview`, `POST replay`, `POST replay/{id}/cancel`, `POST control/pause`, `POST control/stove`, `POST`/`DELETE control/boost`, `PUT`/`DELETE control/away`, `POST notifications/test` |
| admin | HTTP Basic admin credentials, or a request from the Home Assistant ingress proxy (the app panel is admin-only) | everything |

Wrong credentials or a wrong token get `401` (`429` while locked out, see the service
README); a role that is too low gets `403` (for admin actions without a configured admin
password outside ingress: `403` "this action requires OVENBIRD_ADMIN_PASSWORD").

The `401` carries the Basic challenge (`WWW-Authenticate`) except for background loads a
browser makes on its own (`Sec-Fetch-Dest` `image`, `font`, `manifest`, `websocket`, `audio`,
`video`, `track`): Safari sends those without the login and would otherwise ask for it again
over a page that is already open. The tab icons (`/favicon.svg`, `/favicon.ico`,
`/apple-touch-icon.png`) and `health` need no login.

Safari never sends the login on a WebSocket, so the UI opens the live connection with a
pass: `POST api/v1/live/ticket` (any role, the request rules below apply, body `{}`)
returns `{"ticket": "<random>", "expires_in": 30}` with `Cache-Control: no-store`, and
`WS api/v1/ws?ticket=<ticket>` is then served with the role of the request that got the
pass. A pass works for one handshake within 30 s; an unknown, used or expired pass falls
back to the normal login check. The Origin check applies as well.

Every non-`GET` request must pass, in this order (also behind ingress):

1. a body of at most 64 kB (`413`);
2. `Sec-Fetch-Site`, when sent, is `same-origin` (`403`);
3. `Origin`, when sent, is the service's own origin or one in
   `OVENBIRD_HTTP_ALLOWED_ORIGINS` (`403`). Behind ingress the own origin is Home
   Assistant's, taken from `X-Forwarded-Host`/`X-Forwarded-Proto`, which are honoured
   only from the ingress source;
4. `Content-Type: application/json` (`415`), body a JSON object (`400`);
5. the header `X-Ovenbird-Request: 1` (`403`). It forces a CORS preflight that is never
   granted: no CORS headers are sent at all.

Refused state-changing requests are audited (`auth_refused`, a few per source and
minute). The audit actor is `admin from <ip>`, `operate token from <ip>`, or under
ingress `<X-Remote-User-Name> (Home Assistant via ingress)` (the header is trusted only
from the ingress source; without it `ingress (Home Assistant admin)`).

Every response carries `Content-Security-Policy: default-src 'self'; connect-src 'self';
img-src 'self' data:; style-src 'self' 'unsafe-inline'` (plus `; frame-ancestors 'self'`
outside ingress) and `X-Content-Type-Options: nosniff`.

## `POST api/v1/live/ticket` (read)

```json
{"ticket": "<random>", "expires_in": 30.0}
```

A single-use pass for `WS api/v1/ws` (see Roles and request rules); sent with
`Cache-Control: no-store`.

## `GET api/v1/health`

```json
{"live": true, "ready": true, "version": "0.6.0", "api_version": 1,
 "checks": {"mqtt": "connected", "heishamon": "alive", "ha": "disabled", "history": "ok",
            "alarms": "ok", "weather": "disabled"}}
```

`live` is false only when the process is broken (used by the container health check);
`ready` is false while any required dependency (MQTT, HeishaMon liveness) is down or a
critical alarm is active.
`checks` values: `connected` / `disconnected` / `alive` / `dead` / `disabled` / `ok` /
`starting` / `error`; `checks.alarms` is the highest active alarm severity (`ok`, `info`,
`warning`, `critical`), `starting` before the first safety evaluation or `disabled`
without a control loop. `checks.history` is `ok` while history is being written, `starting` until
the history writer has opened the database (normally about a second after start), or `error`;
`ready` is unaffected by `starting`. `checks.weather` is the forecast: `disabled` (not
opted in or no location), `starting` (no issue yet), `ok` or `stale` (the newest issue
is older than 3 h); it never affects `ready`.

## `GET api/v1/snapshot`

```json
{
  "at": "2026-01-14T18:00:00Z",
  "heishamon": {"alive": true, "last_heartbeat_age": 3.2, "lwt": "Online"},
  "links": {"ha": true, "mqtt": true},
  "signals": {
    "main/Outside_Temp": {"value": 3, "unit": "°C", "label": null, "age": 12.0,
                          "held": 3600.4, "max_age": 330.0, "alive_by": null,
                          "fresh": true, "source": "heishamon", "retained": false,
                          "reason": null},
    "main/Operating_Mode_State": {"value": 0, "unit": null, "label": "heat",
                                  "age": 40.1, "held": 86400.0, "max_age": 330.0,
                                  "alive_by": null, "fresh": true, "source": "heishamon",
                                  "retained": false, "reason": null},
    "ha/sensor.living_room_temperature": {
        "value": 21.9, "unit": "°C", "label": null, "age": 240.0, "held": 7800.0,
        "max_age": 86400.0, "alive_by": "ha/sensor.living_room_humidity",
        "fresh": true, "source": "ha", "retained": false, "reason": null}
  },
  "derived": {
    "compressor_running": {"value": true, "reason": null},
    "defrost_active": {"value": false, "reason": null},
    "dhw_active": {"value": false, "reason": null},
    "heat_delivered_w": {"value": 8400.0, "reason": null}
  },
  "defrost": {"active": true, "mode": 2, "since": "2026-01-14T17:56:40Z",
              "inlet_at_start_c": 25.5, "outside_at_start_c": -2.0, "max_s": 2100.0}
}
```

`age` is the time since the last proof of life of a signal: its own last report, or a
report of one of its liveness signals (`alive_by` names that signal, null when the signal
confirmed itself). `held` is the time since the value last changed (seeded from HA's
`last_changed` after a restart; null when only a retained delivery was seen). `max_age` is
the limit in effect: for a room sensor with the `on_change` profile it is the silence
limit while the source link is up and the source default (1800 s) otherwise. `links`
reports whether each source link is up: `ha` while connected and a `get_states` re-read
succeeded within 900 s, `mqtt` while the broker is connected.

`defrost` is the current defrost as the safety monitor latched it when
`Defrosting_State` turned on: `active` follows `Defrosting_State` in the same snapshot;
`mode` is the deice mode the unit picks by its model profile (`1`: reverse cycle with the
water pump running, `2`: hot-gas defrost with the water pump off by design; `null` for a
model without a profile, see `profile` in `GET api/v1/pump/settings`); `since` is when
the monitor saw the defrost start, `inlet_at_start_c` and `outside_at_start_c` are
`Main_Inlet_Temp` and `Outside_Temp` at that moment and `max_s` is the `defrost_stuck`
limit in effect (in mode 2 at least the profile's longest mode 2 defrost + 300 s).
Until the monitor's next evaluation (every 5 s) latched a new defrost, `active` is
already true while the rest is `null`; outside a defrost everything but `active` is
`null`.

Home Assistant temperatures in °F or K are converted to °C when they arrive: `unit` is
then `°C` and `source_unit` (present only for a converted value) the unit HA reported.
A temperature input (room, cross-check, wood-stove reference or outside thermometer)
without a known temperature unit is accepted only when HA's unit system is metric;
otherwise it is refused with `reason` `unit: no temperature unit ... ; ha/<entity_id> is
not used as a temperature` (naming the refused signal), the controller treats it as
missing and `room_unit_refused` is raised for the room signal.

`label` is the enum meaning for enum signals, otherwise null. A signal's `reason` is null unless
a later live delivery made its value unusable (for example HA `unavailable`, a HeishaMon `-1`
enum, or an out-of-range payload); the last value then stays visible but `fresh` is false. A
missing or stale input makes a derived `value` null with a human-readable `reason`.

`heat_delivered_w` is space-heating power from flow × (outlet − inlet): 0 W while the
compressor is off, null (with a reason) during domestic hot water runs, negative during defrost.

## `GET api/v1/history?signals=<id>,<id>&from=<iso>&to=<iso>&step=<seconds>`

Returns aligned series; `step` is one of 0 (raw), 60, 900, 3600. Default window: last 24 h,
step chosen so a series has at most ~1,500 points.

```json
{"from": "...", "to": "...", "step": 60,
 "series": {"main/Outside_Temp": {"unit": "°C", "points": [["2026-01-14T17:00:00Z", 3.0], ...]}}}
```

Numeric signals are averaged per step; enum/boolean signals take the last value per step.

## `GET api/v1/decisions?from=<iso>&to=<iso>&limit=<n>`

The decision log: one entry per controller tick (every 60 s), whatever the mode. Default
window: the last 24 h; `limit` 1..5000 (default 500) keeps the newest entries, returned
oldest first. Retention: `history_decision_days` (30 days; Settings → Data or
`OVENBIRD_HISTORY_DECISION_DAYS`). The whole journal, without the 5,000 cap, comes from
`GET api/v1/export/journal/decisions`.

```json
{"from": "...", "to": "...", "limit": 500,
 "decisions": [
  {"at": "2026-01-07T06:00:00Z", "controller": "ovenbird", "mode": "auto",
   "ladder": "schedule_curve_feedback", "reason": "room_feedback", "setpoint": 31,
   "note": "Room 0.4 K below target; PI adds +1.2 K to the curve's 31.0 °C ...",
   "arbiter": [{"kind": "water_setpoint", "intent": 31, "actual": 30, "action": "send",
                "reason": "pump reports 30"}],
   "commands": [{"at": "...", "kind": "water_setpoint", "value": 31, "status": "queued",
                 "attempt": 0, "detail": "queued",
                 "topic": "panasonic_heat_pump/commands/SetCurves",
                 "payload": "{\"zone1\":{\"heat\":{\"target\":{\"high\":31}}}}"}],
   "config_version": 12,
   "record": {"schema": 1, "...": "DecisionRecord.to_json_dict(), see control-interface.md"}}
 ]}
```

`config_version` is the configuration version the tick ran with (`null` for ticks made
before the configuration store existed, or with an empty store). `record.inputs_used`
holds everything a replay needs (`config/preview`): the snapshot signals, the pump's
reported settings (also `Max_Pump_Duty`), the heartbeat, the room input and the
cross-check signal when one is configured.

`arbiter` holds one entry per controller intent: `action` is `none` (already applied, in
flight or queued), `skip` (pump value unknown or stale, or the adapter holds after an
alarm) or `send`. In `shadow` mode `send` records what *would* have been sent and
`commands` is always empty; in `auto` mode `commands` holds the adapter's `queued` or
`refused` events of that tick.

## `GET api/v1/decisions/latest`

```json
{"decision": <latest decision as above, or null>,
 "control": {"mode": "auto", "configured_mode": "auto", "paused": false,
             "releasing": false, "reset_pending": false, "config_version": 12,
             "controller": "ovenbird", "interval_s": 60.0, "ticks": 312,
             "restored_state": true, "publishing": true, "refusals": [],
             "alarms": [{"code": "foreign_writer", "severity": "warning",
                         "message": "...", "since": "...", "detail": {"...": "..."}}],
             "safety": {"level": "warning", "interval_s": 5.0,
                        "monitors": [{"code": "low_flow", "severity": "critical",
                                      "status": "ok", "message": "...", "value": 25.9,
                                      "since": null, "limit": 8.0, "unit": "l/min",
                                      "direction": "below"}]},
             "adapter": {"setpoint_register": "setcurves_target_high",
                         "hold": "foreign writer", "hold_until": "2026-01-07T07:00:00Z",
                         "hold_latched": false, "hold_incidents": 1, "safety_hold": [],
                         "corrections": {"recent": 0, "limit": 3, "window_s": 3600.0},
                         "in_flight": null, "queued": {},
                         "verified": {"water_setpoint": 31, "max_pump_duty": 102},
                         "budget": {"day": "2026-01-07", "used": 12, "limit": 150,
                                    "safety_reserve": 10},
                         "counters": {"sent": 12, "verified": 12, "retried": 0, "failed": 0,
                                      "refused": 0, "clamped": 0, "foreign": 1,
                                      "superseded": 0, "corrections": 0, "restarts": 0,
                                      "envelope_corrections": 0}},
             "room": {"signal": "ha/sensor.living_room_temperature",
                      "profile": "on_change", "step_k": 0.1, "max_age_s": 86400.0,
                      "report_interval_s": 300.0, "silence_limit_s": 86400.0,
                      "liveness": ["ha/sensor.living_room_humidity"],
                      "crosscheck": null, "value": 21.9, "fresh": true, "held_s": 7800.0,
                      "alive_s": 240.0, "alive_by": "ha/sensor.living_room_humidity",
                      "link_up": true, "authority": 1.0, "plausible": null},
             "stove": {"enabled": true, "auto": true, "active": true, "source": "auto",
                       "trigger": "level", "since": "2026-01-14T16:40:00Z",
                       "entry_c": 23.3, "integral_k": -0.4, "blocked": false,
                       "level_blocked": false, "reentry_wait": false,
                       "backoff_k": 3.0, "enter_c": 23.3, "exit_c": 22.3,
                       "reference_c": 19.6, "request": null}}}
```

`control.mode` is the effective mode: `shadow` while an `auto` installation is
paused or waits for a configuration-reset acknowledgement; `configured_mode` is
`OVENBIRD_CONTROL_MODE` (the ceiling). `config_version` is the configuration the loop
runs. `control.publishing` is true only when all four publish conditions hold and no
shadow hold applies (see the service README); `refusals` lists the unmet ones (for a
pause: `control is paused`). `adapter` is null when the installation does not
permit publishing (it stays present, idle, during a pause).
`restored_state` is true when the controller state was restored after a restart.
`adapter.hold` is why the controller's values are not published (simulation board check,
mode problem, or a foreign-writer/verification hold); `hold_until` is the wall-clock end
of a timed hold (service clock), null when latched or without a hold; `hold_incidents`
counts the holds within the escalation window; `safety_hold` lists the critical alarms
that restrict releases to water setpoint decreases. `counters.envelope_corrections`
counts (since start) the read-back differences of the water setpoint recognised as the
HeishaMon envelope rule's correction and adopted instead of a foreign-writer hold (only
with `OVENBIRD_ENVELOPE_RULE_INSTALLED=true`): ovenbird's value lay outside the
envelope band at the current `Outside_Temp` and the pump now reports what the rule
writes there (the envelope curve at that temperature within the band, rounded either
way). Any other difference stays a foreign writer.
`safety.monitors` has one entry per monitor with `status` `ok`, `pending` (condition seen,
not sustained yet), `active` or `unknown` (inputs missing or stale).
Each monitor also carries `limit` (the threshold it compares against, null for state
monitors and while a threshold read from the pump is unknown), the `unit` of `limit` and
`direction` (`above`: exceeding the limit is the condition; `below`: falling under it;
null for state monitors): `setpoint_above_max` (maximum setpoint, °C, above),
`outlet_overshoot` (maximum supply + margin, °C, above), `low_flow` and
`low_flow_defrost` (minimum flow, l/min, below), `heating_off_outdoor` (the pump's `Heating_Off_Outdoor_Temp`, °C,
above), `defrost_stuck` (longest defrost, s, above; it applies to the time since
`since`, not to `value`; in a profile's deice mode 2 at least its longest mode 2
defrost plus 5 min, 2100 s for the WH-MXC12J9E8), `room_below_floor` (comfort floor, °C, below),
`room_sensor_silent` and `room_report_overdue` (s, above, against `value` = the report
age), `compressor_starts` (`safety_starts_per_hour_max`, starts/h, above, against `value`
= the starts in the last hour); `pump_error`, `backup_heater`, `backup_heater_allowed`, `ha_link_down` and
`room_unit_refused` have none.
`room` is the room input under its sensor profile (null without a room signal): the
profile and its limits, the value, `fresh`, `held_s` (since the value changed),
`alive_s` and `alive_by` (last proof of life), `link_up` (the source link the hold
depends on), and from the latest decision `authority` (share of cooling feedback left
for a long-held `on_change` value) and `plausible` (cross-check verdict; null without a
cross-check signal).
Alarm codes and severities: `setpoint_above_max`, `outlet_overshoot`, `low_flow`,
`pump_error`, `correction_failed` (critical); `mode_mismatch`, `verification_failed`,
`write_budget`, `foreign_writer`, `hold_latched`, `backup_heater`, `defrost_stuck`,
`low_flow_defrost` (`Pump_Flow` below the minimum during a defrost while the compressor
runs, for the flow sustain time; `low_flow` is suspended during a defrost and starts its
sustain time again when it ends. For a model with a profile (`profile` of
`GET api/v1/pump/settings`) the deice mode is judged from `Main_Inlet_Temp` and
`Outside_Temp` when the defrost starts: for the WH-MXC12J9E8 (Panasonic service manual
PAPAMY2110029CE, 14.2.2) mode 2, a hot-gas defrost with the water pump off by design,
when the inlet is below 27 °C, or below 60 °C with the outdoor air below −10 °C; mode 1,
with the pump running, otherwise. An unknown model gets a message that only describes
what was seen. `safety_defrost_low_flow`: `auto` (default) only journals it in mode 2
and raises it otherwise, `log` only journals it in mode 2 and for an unknown model,
`alarm` always raises it; in mode 1 it is always raised. Journalled, it is never active
and never notified: the journal gets a `started` and a `cleared` event with severity
`info` and `detail` `logged_only` = true, `profile`, `deice_mode`, `inlet_at_start_c`
and `outside_at_start_c`),
`room_below_floor`, `room_sensor_quiet` (an `on_change` room sensor without any proof of
life for 8 h; cooling learned since then is undone; clears on the next report),
`room_sensor_silent` (an `on_change` room sensor without any proof of
life beyond the silence limit), `room_unit_refused` (the HA room temperature has no
temperature unit and HA's unit system is not metric, so its value is not used; clears
when a value with a unit arrives or HA reports a metric system), `room_report_overdue` (a `periodic` room sensor without a
report for 3 x its interval), `room_implausible` (the room value disagrees with the
cross-check signal; during a wood-stove episode with a threshold widened by 4 K, and a
manual stove request never clears it), `stove_reference_missing` (a wood-stove episode
runs with a reference room configured but the reference has no fresh temperature in °C:
the back-off is halved until it reports again or the episode ends),
`outside_sensor_stale` (the outside sensor chosen for the heating curve,
`control_outside_signal`, has no usable value or none younger than
`control_outside_max_age_s`: the curve uses the pump's `main/Outside_Temp` until it
reports again), `outside_sensor_implausible` (its value is no finite number, lies outside
`control_outside_plausible_min_c` … `control_outside_plausible_max_c`, default −40 … 50 °C,
or is more than `control_outside_max_deviation_k`, default 10 K, from the pump's own
reading: the curve uses the pump's sensor meanwhile; at most one of the two outside alarms
is active, and both carry `detail` `signal` and `reason`, the decision's `outside_reason`), `ha_link_down` (HA configured but not connected or no successful
re-read for 5 min), `config_reset` (the configuration store was lost or invalid; shadow
until an admin acknowledges it with `POST api/v1/config/reset-ack`), `envelope_mismatch`
(the envelope rule corrected a water setpoint of ovenbird's that already lay outside the
envelope band when ovenbird set it: the controller did not clamp to the envelope the
rule enforces; raised once, clears when ovenbird's next own value is inside the band),
`archive_failing`, `archive_rebuilt` (the yearly archive; see Yearly archive),
`compressor_starts` (more than `safety_starts_per_hour_max`, default 4, compressor starts
in the last hour and in the hour before it, or more than `safety_starts_per_day_max`,
default 30, in 24 h; counted from `Compressor_Freq`, a restart after a defrost is no
start; the start times survive a restart; off with `safety_starts_alarm_enabled`)
(warning);
`heishamon_restarted`, `backup_heater_allowed`, `heating_off_outdoor`,
`pump_setting_changed` (a writable pump setting changed without ovenbird, e.g. on the
Panasonic remote; clears 24 h after the last such change) (info). An alarm clears only
when its condition is gone. `verification_failed` is also raised when an operator's
pump-setting write is not confirmed after its retries ("not supported by this
model?"); that does not hold setpoint control and clears once the pump reports the
value (a later verified write, or the remote).
`stove` is wood-stove mode (see `POST control/stove`): `enabled` / `auto` from the
configuration; `active`, `source` (`auto` or `manual`), `trigger` (`level`, `rise`,
`manual`, `handover`: a manual episode continued by the detection), `since` and
`entry_c` (the room value at entry) of the current episode; `integral_k` the room
feedback integrator held through it; `blocked` true after a manual stop until the room
has cooled below `exit_c`; `level_blocked` true after an episode reached the 8 h cap
(`control_stove_max_active_s`) until the room has been below `exit_c` (only a new fast
rise enters meanwhile); `reentry_wait` true after an episode ended on an untrusted room
value until the value has been trusted for `control_stove_reentry_hold_s` (15 min);
`backoff_k` the applied back-off
(after the reference-room guard: halved while a configured reference has no fresh
temperature); `enter_c` / `exit_c` the thresholds (comfort +
`enter_above_k`, minus the hysteresis); `reference_c` the reference room (null without
one or when stale); `request` the stored manual request (as in `POST control/stove`).
The decision record carries the same as `controller_state.stove_*` plus
`stove_event` (`entered` / `exited`, on the transition tick), `stove_exit`
(`cooled`, `max_active`, `room_untrusted`, `room_jump`, `reference_warm`, `manual_stop`,
`manual_ended`, `auto_off`, `disabled`), `stove_fault` (a rise of 2 K within 10 min was
taken for a sensor fault: no automatic detection until the room has cooled below
`exit_c`) with `stove_jump_k`, `stove_reference_gap_k` (room minus reference; an
automatic entry needs 1 K) and `stove_reference_share`; reason `stove` while the
back-off shapes the setpoint, and the `stove` term (K). `room_plausible` stays the
cross-check's verdict during an episode (`room_crosscheck_threshold_k` its threshold).
`boost` and `away` are as in `GET control/boost` and `GET control/away`. `summer` is the
summer switch (`control_summer_*`): `enabled`, `active` (no space heating), `mean_c` the
slow outside mean (an exponential mean of the curve's outside value with time constant
`mean_tau_s`, 24 h by default), `off_c` / `on_c` the limits (heating stops above `off_c`,
resumes below `on_c` = `off_c` - `control_summer_hysteresis_k`), `warming_up` true until
the mean has one time constant of samples (it does not switch before). The decision
record carries `controller_state.summer_*`, the `summer` term (K, the cut to the
safety minimum) and reason `summer` while it holds the water at the minimum; with the
switch off none of it is present. A boost or away carries `room_override`
(`room_target` or `away`), `room_override_k` and `room_override_paused` (`stove`,
`summer` or null), the `room_target` term and reasons `room_target` / `away`.
`controller_state.quiet_start` is true while quiet mode after a start applies
(`control_quiet_start_*`; reason `quiet_start` on the quiet-mode intent).
`control` is null when the service runs without a control loop.

## CSV exports (`?format=csv`)

`history`, `decisions`, `commands`, `alarms` and `audit` take `format=csv` (default
`json`; anything else `422`) with the same window, limit and role rules. The answer is
a download (`text/csv; charset=utf-8`, `Content-Disposition: attachment;
filename="ovenbird-<name>-<from>.csv"`) with a header row:

| Export | Columns |
|---|---|
| `history` | `signal,unit,at,value` (one row per point and signal) |
| `decisions` | `at,controller,mode,ladder,reason,setpoint,config_version,note,arbiter,commands` |
| `commands` | `at,kind,value,status,attempt,topic,payload,detail` |
| `alarms` | `at,code,severity,event,message,detail` (the journal; not `active`) |
| `audit` | `at,actor,source_ip,action,detail` |

Nested values are compact JSON text. A text cell starting with `=`, `+`, `-`, `@`, a
tab or a carriage return gets a leading `'` so a spreadsheet never evaluates it.

These per-page downloads keep the endpoints' caps (5,000 rows, 50 signals, 100,000
points); for everything use the streamed exports under `export/` (see Data).

## `GET api/v1/commands?from=<iso>&to=<iso>&limit=<n>`

The command journal (audit trail), same window and limit rules as `decisions`.

```json
{"from": "...", "to": "...", "limit": 500,
 "commands": [{"at": "...", "kind": "water_setpoint", "value": 31, "status": "verified",
               "attempt": 1, "topic": "panasonic_heat_pump/commands/SetCurves",
               "payload": "...", "detail": "applied in 12 s"}]}
```

`status`: `queued`, `sent`, `verified`, `retry`, `failed`, `refused` (publish guard,
allowlist, hold or mode) or `dropped` (queue cleared by a hold or a mode change, a value
the controller no longer wants, pre-empted by a safety correction, or an operator's
write that a defrost, DHW run or hold overtook). Safety corrections are ordinary events
whose `detail` starts with `safety correction`. `kind` is a controller intent
(`water_setpoint`, `max_pump_duty`, `quiet_mode`) or an operator's pump setting
(`heat_delta`, `pump_flowrate_mode`, `heating_off_outdoor`); every event of an
operator's write has a `detail` starting with `operator: <actor>: ` and counts against
the same daily budget.

## `GET api/v1/alarms?from=<iso>&to=<iso>&limit=<n>`

Active alarms plus the journal of alarm and hold transitions, same window and limit rules
as `decisions` (retention `OVENBIRD_HISTORY_DECISION_DAYS`).

```json
{"from": "...", "to": "...", "limit": 500,
 "active": [{"code": "low_flow", "severity": "critical", "message": "...", "since": "..."}],
 "events": [{"at": "...", "code": "low_flow", "severity": "critical", "event": "raised",
             "message": "Pump_Flow 3.0 l/min with the compressor running (minimum 8.0 l/min)",
             "detail": {}},
            {"at": "...", "code": "command_hold", "severity": "warning", "event": "started",
             "message": "hold 3 within 12 h (foreign writer), latched until an operator releases it",
             "detail": {"reason": "foreign writer", "until": null, "latched": true,
                        "incident": 3}}]}
```

`foreign_writer` alarms and the `command_hold` they start carry the forensics in
`detail`: `setting` (the intent kind), `signal`, `register` (the setpoint register),
`ovenbird_value` (what ovenbird last verified, null when unknown), `seen_value`,
`seen_since` (when the pump started reporting it), `pump_keeps` (the value left in
place during the hold; null for a safety correction, which writes `correction`
instead), `hold_until` (ISO, null when latched), `latched`, `incident` (within the
escalation window), `at_hold_end` (`write_again`: ovenbird writes its own value again
when the hold ends; `await_release`: latched until `control/release-hold`) and
`controller_wants`.

`event`: `raised` / `cleared` for alarms; `started` / `expired` / `released` for
`command_hold` (`detail.until` is unix seconds, null when latched) and for the
informational `stove_mode` journal entries (wood-stove mode on; off by a manual stop;
off for any other reason, `detail.exit` says which; not alarms, never in `active`). A
history written by 0.5 may also hold informational `model_plan` entries (the retired model
plan's guard verdicts); they are returned as stored. The sun day shift journals
informational `dayshift` entries (`started` for the start of a boost or set-back,
`released` for its end and for a cancel; `detail`: `use` (`shadow` or `on`), `event`
(`boost_start`, `boost_end`, `setback_start`, `setback_end`, `cancel`), `phase`,
`offset_k` and `reasons` as in `control/dayshift`; never in `active`, never notified).
Boost and away journal informational `boost` and `away_mode` entries (`started`;
`expired` when it ran out; `released` when ended early, by `DELETE`, by away (for a
boost), a manual wood-stove start (for a boost) or switching the feature off; `detail`
the request). The summer switch journals informational `summer_mode` entries (`started`
when space heating stops, `expired` when it resumes; `detail`: `mean_c`, `setpoint`).
`recognised` for the informational `envelope_correction` entries (the HeishaMon envelope
rule corrected ovenbird's water setpoint and ovenbird adopted it; `detail`: `setting`,
`signal`, `ovenbird_value`, `seen_value`, `outside_c`, `low_c`, `high_c` (the band),
`rule_c` (the envelope curve value the rule writes) and `set_outside_band` (ovenbird's
value already lay outside the band when it was set: `envelope_mismatch`); never in
`active`).

## `POST api/v1/control/release-hold` (admin)

Ends the current foreign-writer or verification hold, timed or latched, and restarts the
escalation count. The operator action for a latched hold.

Request: body `{}` or `{"reason": "<at most 200 characters>"}`, under the request rules
above (`X-Ovenbird-Request: 1` included). The release is audited (`hold_release`).

Responses: `200` with

```json
{"released": {"reason": "foreign writer", "until": null, "latched": true, "incident": 3},
 "by": "admin from 192.168.1.20: checked the remote", "hold": null, "safety_hold": [],
 "control": <control status as in decisions/latest>}
```

(`hold` / `safety_hold` show what still restricts publishing: mode or simulation problems
and safety holds are not released by this call); `409` when publishing is not enabled or
no such hold is active; `400` for a bad body. The release is journalled (`command_hold`
`released`, with `by`).

## `POST api/v1/control/stove` (operate)

Manual wood-stove mode (needs `control_stove_enabled`). Body `{"on": true}`,
`{"on": true, "until": "<iso>"}` or `{"on": false}` / `{"on": false, "until": "<iso>"}`,
under the request rules above. `on` starts wood-stove mode at the next control tick (or
takes over an automatic episode) until `until`, default now + 8 h (at most
`control_stove_max_active_s`);
`until` at most 24 h ahead. `on: false` ends the episode; without `until` the stop is
one-shot and the detection stays blocked until the room has cooled below the exit
threshold, with `until` the detection is suppressed until then. A new request replaces
the previous one. When a manual episode ends while the room is still above the exit
threshold, the automatic detection takes it over (trigger `handover`). The request is
stored and survives a restart; it is audited (`stove_request`, detail the request).
`actor` is the role or user label only, without the client address (the request is
visible to the read role and goes into the decision records; the audit row keeps who
asked from where).

`200`:

```json
{"request": {"on": true, "until": "2026-01-14T23:00:00Z", "actor": "operator",
             "at": "2026-01-14T17:00:00Z"},
 "stove": <stove status as in decisions/latest>}
```

`400` for a bad body, an `until` in the past or more than 24 h ahead; `409` when
wood-stove mode is not enabled or the service has no control loop.

## `GET api/v1/control/boost` (read)

The boost in force and its settings:

```json
{"enabled": true, "active": true, "paused": null, "shift_k": 1.0, "target_c": 22.0,
 "remaining_s": 5400.0, "default_s": 7200.0, "default_k": 1.0,
 "request": {"offset_k": 1.0, "target_c": null, "until": "2026-01-14T19:00:00Z",
             "actor": "operator", "at": "2026-01-14T17:00:00Z"}}
```

`paused` is `stove` (a wood-stove episode) or `summer` (the summer switch) when the
controller holds the boost at the latest tick; its clock keeps running. `409` without a
control loop.

## `POST api/v1/control/boost` (operate)

A temporary room target (needs `control_boost_enabled`, on by default). Body: at most one
of `offset_k` (K from comfort, -3 to +2, not 0; negative is "cooler") and `target_c`
(°C, within the same offsets of `control_comfort_c`), neither takes
`control_boost_default_k` (1 K); at most one of `duration_s` (900 to 43200 s) and
`until` (ISO), neither takes `control_boost_default_s` (2 h). The controller shifts the
room target by the offset through the room feedback (without a trusted room value it
maps the offset to water via the curve slope, at most the controller's 5 K water clamp
of a plan, `plan_max_water_k`); the boost replaces a plan slice (the day shift) while it
runs and stays inside every safety limit. It takes effect at the next tick, ends by
itself at `until`, is stored and survives a restart, replaces an earlier boost and is
journalled (informational `boost`: `started`; `expired` at the end; `released` when it
was ended early) and audited (`boost`). A wood-stove episode or the summer switch pauses
it; a manual wood-stove start (`POST control/stove` with `on: true`) ends it.

`200`: `{"request": <the request>, "boost": <as GET control/boost>}`. `400` for a bad
body or a value out of range; `409` when boost is off, while away is set (end away
first) or without a control loop.

## `DELETE api/v1/control/boost` (operate)

Ends the boost now (journalled `released`, audited `boost_end`); body `{}` under the
request rules above. `200`:
`{"request": <the ended request or null>, "boost": <as GET control/boost>}`.

## `GET api/v1/control/away` (read)

The away period and its settings:

```json
{"enabled": true, "active": true, "phase": "away", "paused": null, "target_c": 16.0,
 "until": "2026-01-20T18:00:00Z", "comfort_from": "2026-01-20T12:00:00Z",
 "default_target_c": 16.0, "default_lead_s": 21600.0,
 "request": {"target_c": 16.0, "until": "2026-01-20T18:00:00Z",
             "comfort_lead_s": 21600.0, "comfort_from": "2026-01-20T12:00:00Z",
             "actor": "operator", "at": "2026-01-14T17:00:00Z"}}
```

`phase`: `away` (the room target is the away target) or `returning` (from
`comfort_from`, the comfort target again so the house is warm at `until`). `paused` as
for the boost. `409` without a control loop.

## `PUT api/v1/control/away` (operate)

Sets an away period (needs `control_away_enabled`, on by default). Body
`{"until": "<iso>"}`, optionally `target_c` (10 to 20 °C and below comfort, default
`control_away_target_c` 16 °C) and `comfort_lead_s` (0 to 86400 s, default
`control_away_comfort_lead_s` 6 h). `until` must lie more than the lead and at most 60
days ahead. Setting away ends a running boost (journalled). Until `until` (the return
phase included): the `room_below_floor` floor follows the away target (target minus
`safety_room_floor_k`), the day shift pauses (guard `away`) and the house basics leave the
days out (`excluded.away`). Stored, survives a restart, replaces an earlier period,
journalled (informational `away_mode`: `started`, `expired`, `released`) and audited
(`away`). A wood-stove episode or the summer switch pauses the away target as they pause a
boost.

`200`: `{"request": <the request>, "away": <as GET control/away>}`. `400` for a bad
body or value; `409` when away is off or without a control loop.

## `DELETE api/v1/control/away` (operate)

Ends the away period now; comfort applies at the next tick (journalled `released`,
audited `away_end`); body `{}` under the request rules above. `200`: `{"request": <the ended request or null>, "away": <as GET
control/away>}`.

## `GET api/v1/control/features` (read)

Every switchable feature with its state, in a fixed order; the ids are the `feature` of
the settings fields in `GET config/schema`:

```json
{"mode": "shadow",
 "features": [{"id": "weather_compensation", "state": "shadow", "enabled": true,
               "active": true, "experimental": false, "on_available": true}, ...]}
```

`id`: `weather_compensation`, `room_feedback`, `slow_start`, `minimum_run`, `pump_duty`,
`quiet`, `stove`, `dayshift`, `summer`, `away`, `boost`, `house_basics`,
`starts_alarm`. `state`: `off` (switched off, or room feedback without a room signal),
`shadow` (on, but not applied: the controller is not in `auto`, or the day shift is set
to `shadow`; `house_basics` and `starts_alarm` only observe and are never `shadow`),
`active_now` (on, applied and acting at the latest tick) or `on`. `active` is whether
it acts at the latest tick whatever the mode. `experimental` (since 0.6.0) marks a
feature shipped as an opt-in although its simulator evaluation did not pass (only
`dayshift`); `on_available` says whether it may be switched fully on: always true for the
others, for `dayshift` only while `control_dayshift_experimental_ok` is set. `409`
without a control loop.

## `GET api/v1/control/dayshift` (read)

The sun day shift (`control_dayshift_*`): on a sunny, mild day the room target rises a
little inside the day window, and in the night after such a day it drops a little, so
the house stores the day's heat and the heat pump runs less at night. The rule is
evaluated every quarter hour (`ovenbird.control.dayshift`); in `on` its offset reaches
the controller as a rule plan slice valid for 20 minutes (see the plan-slice contract in
`docs/control-interface.md`), in `shadow` it is only recorded, in `off` nothing runs.

```json
{"mode": "shadow", "configured": "shadow", "on_available": false, "experimental": true,
 "phase": "boost",
 "offset_k": 0.25, "desired_k": 0.5, "applied_k": 0.0,
 "reasons": ["sun_forecast", "outside_mild"], "guards": [],
 "evaluated_at": "2026-03-10T09:00:00Z", "valid_until": null,
 "next_change": {"at": "2026-03-10T17:00:00Z", "phase": "idle"}, "boosted_today": true,
 "windows": {"day_start": "09:00", "day_end": "17:00", "night_start": "23:00",
             "night_end": "05:00", "comfort_at": "07:00",
             "setback_end": "2026-03-11T03:00:00Z", "timezone": "UTC"},
 "forecast": {"issued_at": "2026-03-10T08:00:00Z", "hours": 54, "sun_wm2": 310.4,
              "sun_limit_wm2": 150.0, "outside_c": 8.2, "outside_min_c": 7.5,
              "outside_limit_c": 5.0, "night_min_c": 3.1, "night_limit_c": 5.0}}
```

- `mode` is the switch in effect and `configured` the setting; they are the same since
  0.6.0 (`on` is no longer run as `shadow`).
- `experimental` is true: the day shift did not pass its simulator evaluation
  (`docs/evaluation/dayshift.md`). `on_available` says whether `on` may be chosen, that
  is whether `control_dayshift_experimental_ok` is set. Both replace `locked` (0.5.x).
- `phase`: `idle`, `boost` (inside the day window, also while the offset ramps back
  after it), `setback`, `recovery` (from the end of a set-back to `comfort_at`: the room
  returns to comfort) or `blocked` (a guard, or the room cancelled this night's
  set-back).
- `offset_k` is the step-limited offset of the latest evaluation (what `on` hands to the
  controller, within `control_plan_rule_max_k`), `desired_k` the one it moves to in steps
  of at most 0.25 K per quarter hour, `applied_k` the room-target shift the controller
  applied at the latest tick (always 0 in `shadow`).
- `reasons`: `sun_forecast` and `outside_mild` (a boost); `sun_low` (the forecast mean
  irradiance over the rest of the day window, or over the hour either side of now, is
  below `sun_limit_wm2`), `room_warm` (the room reached the boosted target: no more boost
  that day, the day still counts as sunny), `outside_cold`
  (the filtered outside temperature or the forecast minimum over the rest of the window
  is below `outside_limit_c`), `outside_unknown` (no filtered outside temperature yet),
  `forecast_missing` (no forecast hours for the span); `night_after_boost` (a set-back),
  `no_boost_today` (the night after a day that did not hold the full boost for 2 h),
  `night_cold` (the forecast night minimum is below `night_limit_c`), `recovery_lead`
  (the set-back has ended so the
  room is back at comfort at `comfort_at`); `room_below_target` (before a set-back starts:
  the room is less than 0.5 K above comfort; during one: the room fell more than 0.3 K
  below the lowered target, no more set-back this night); `outside_windows`
  (neither window); `off`; and the guards.
- `guards` (also in `reasons`, and the phase is `blocked`): `forecast_stale` (no stored
  forecast issue younger than 3 h), `room_untrusted`, `stove_active`, `stove_tail` (12 h
  after a wood-stove episode), `away` (an away period is set, its return included). A guard ends a boost or set-back at once (offset 0).
- The limits relax while the shift runs: the outside limits by 1 K, the sun limit to half.
- `next_change`: the next boundary of the schedule that leads to another phase (the day
  window, its end, and for a sunny day the night's set-back, its end and
  `comfort_at`); whether it happens still depends on the forecast and the guards then;
  `null` while blocked or `off`.
- `windows`: the local times in `timezone` (`control_timezone`) and `setback_end`, the
  end of the set-back of the current or coming night (`night_end` or
  `control_dayshift_recovery_s` before `comfort_at`, the earlier).
- `forecast`: what the latest evaluation read (`null` before it and in `off`): the issue
  time of the newest stored forecast, the hours read, the mean irradiance and minimum
  temperature over the rest of today's day window (all of it once it is over), the
  filtered outside temperature, the minimum of the current or coming night, and the
  limits in force.

Recorded while not `off`: `derived/dayshift_offset_k` (the offset the controller got: 0
in `shadow` and without a slice) and `derived/dayshift_shadow_k` (the offset the rule
computed, handed over or not), both at every tick, in K. `409` without a control loop.

## `POST api/v1/control/pause` (operate) and `POST api/v1/control/resume` (admin)

Paused ↔ auto with the environment's mode as the ceiling. Pause: body `{}` or
`{"reason": "<at most 200 characters>"}`; resume: `{}`. While paused the loop decides as
`shadow` (reads and decides, never sends): nothing is queued or published, not
even a safety correction; the pause is stored and survives restarts. Resume returns to
`auto` (a pending configuration reset still holds shadow). Idempotent; audited as
`mode_pause` / `mode_resume` when the state changes.

`200`:

```json
{"mode": {"configured": "auto", "effective": "shadow", "paused": true, "reset_pending": false},
 "control": <control status as in decisions/latest>}
```

`409` (with `mode`) when `OVENBIRD_CONTROL_MODE` is not `auto`.

## `GET api/v1/decisions/series?from=<iso>&to=<iso>&step=<seconds>`

Columnar decision terms for the history chart. `step` is 0 (every tick, at most the
newest 5,000) or 300, 900, 3600 (the last tick of each bucket); default: the finest
step with at most 1,500 points.

```json
{"from": "...", "to": "...", "step": 0,
 "at": ["..."], "setpoint": [34], "pre_round": [33.69], "curve": [34.13],
 "room_feedback": [-0.44], "plan": [0], "start_ramp": [0], "cycling_floor": [0],
 "stove": [0], "other": [0], "safety_delta": [0], "safety_low": [26.8], "safety_high": [37.8],
 "reason": ["room_feedback"], "binding": [null], "ladder": ["schedule_curve_feedback"],
 "config_version": [12]}
```

Terms are the values after their own clamp (K; `curve` in °C); `stove` is the wood-stove
back-off (0 when wood-stove mode is not configured or not active); `other` = `boost` +
`override`; `safety_delta` = `safety.value − safety.raw` (the clamp); `safety_low/high`
the allowed band. Refusals and holds have `null` terms. `400` for another step.

## `GET api/v1/audit?from=<iso>&to=<iso>&limit=<n>` (admin)

Default window the last 24 h, `limit` 1..5000 (default 500, newest kept, oldest first).

```json
{"from": "...", "to": "...", "limit": 500,
 "events": [{"at": "...", "actor": "admin from 192.168.1.20", "source_ip": "192.168.1.20",
             "action": "config_apply",
             "detail": {"version": 13, "changed": [{"field": "control_comfort_c",
                        "from": 21.5, "to": 21.3}], "comment": "a bit cooler"}}]}
```

`action`: `config_apply`, `config_rollback` (detail `rollback_to`), `config_reset`
(system, at start: detail `loss` `missing`/`corrupt`/`invalid`), `config_reset_ack`,
`mode_pause` (detail `reason`, omitted without one), `mode_resume`, `hold_release`,
`pump_setting` (detail `setting`, `from`, `to`, and `comment` when given),
`stove_request` (detail `on`, `until`, `actor`, `at`),
`control_release` (twice: detail `phase: started` with `rehearsal` and `reason`, then
`phase: finished` with the run as in `control/release`; the release also writes a
`mode_pause` with reason `release control`; a dry rehearsal writes one `phase: planned`
with the plan), `snapshot_capture` (detail `items`, `outside_c`), `divergence_explain`
(detail `start`, `note`; `note` null removes the mark), `notify_test` (detail `ok`, `error`),
`auth_refused` (detail `status`, `reason`, `path`), `ha_connection` (detail `changed`,
`url`, `token` `set`/`unset`; never the token). Append-only.

## Configuration

Control settings are stored in `config.db` (versions, audit, runtime flags) and merged
under the installation's settings. Precedence, highest first: environment, options
file, store, emitter preset / default. A field set by the environment or the options
file is **locked** (read-only, with its variable name); a stored value under it is kept
but inactive. The publish gates, secrets, connections, bind addresses, the mode
(`OVENBIRD_CONTROL_MODE`, the ceiling) and the expert constants can never be stored.
Drafts live in the browser; the server only validates and applies.

### `GET api/v1/config/schema` (read)

Every settings field with its bounds and UI metadata; `Cache-Control: no-cache` (the
dynamic bounds follow the current emitter and limits).

```json
{"schema": 1,
 "groups": [{"id": "curve", "fields": ["control_curve", "control_outside_filter_s"]}],
 "fields": {"control_dwell_s": {"type": "number", "nullable": true, "min": 300, "max": 7200,
            "exclusive_min": false, "exclusive_max": false, "step": 60,
            "soft_min": 600, "soft_max": null, "unit": "s", "display": "min",
            "tier": "advanced", "group": "behaviour", "editable": true,
            "env": "OVENBIRD_CONTROL_DWELL_S", "preset_default": true}},
 "presets": {"mixed": {"control_dwell_s": 900, "control_curve": [[-10, 39], [0, 34], [15, 25]]}},
 "envelope": {"curve": [[-10, 39], [0, 34], [15, 25]], "below_k": 6, "above_k": 5}}
```

- `type`: `number`, `integer`, `boolean`, `string`, `enum` (with `options`), `list`,
  `secret`, `curve` (list of `[outside_c, water_c]`, with `min_points` 2, `max_points` /
  `max_items` 6, `outside_min`/`outside_max` −30/30 and `min`/`max` = the water range,
  minimum setpoint / maximum supply), `signal`, `signal_list`, `windows` (the quiet
  windows: list of `{"start": "HH:MM", "end": "HH:MM", "level": 1-3}`, `max_items` 4,
  `level_min`/`level_max`, `end` before `start` wraps midnight), `retention` (days of
  history to keep, unit `d`; `0` keeps it forever, `null` returns to the default),
  `mqtt_inputs` (extra MQTT topics read as signals: a list of `{"topic", "signal",
  "unit", "minimum", "maximum"}`, at most 32 inputs (`max_items` 32), topic, signal and unit at most 256
  characters, the topic without wildcards and each once, each signal id once, finite
  bounds with the minimum not above the maximum; an input never reads the board's own
  topics (`<base>/main`, `<base>/commands`, `<base>/stats`, `<base>/LWT`) nor produces a
  reserved signal id (`input_topic_reserved`, `input_signal_reserved`); the core router
  enforces the same at runtime; the signals appear in the signal picker next to the HA
  entities).
- `tier`: `basic`, `advanced` (both `editable`) or `expert` (displayed only, "fixed by
  installation"). `groups` are ordered: `curve`, `room`, `feedback`, `limits`,
  `behaviour`, `ramp`, `cycling`, `pump_duty`, `pump` (`hot_water`), `stove`, `dayshift`,
  `summer`, `manual`, `quiet`, `emitter`,
  `monitors`, `weather`, `house` (the facts the owner states about the house, for a rough
  heat-loss estimate: `house_floor_area_m2`, the heated floor area in m²; `house_volume_m3`
  50 to 5000; `house_build_period`, one of `before_1945`, `1945_1974`, `1975_1991`,
  `1992_2005`, `2006_2014`, `2015_later`; `house_window_area_m2` 0 to 200;
  `house_window_orientation`, one of `north`, `east`, `south`, `west`, `mixed`;
  `house_occupants` 0 to 12; all unset by default; and `house_basics_enabled`, on by
  default, which switches `insight/basics` on or off; the settings of the retired house model,
  `house_ua_*`, `house_time_constant_*`, `house_solar_aperture_*`, `house_internal_gain_*`,
  `house_learn_*` and `control_model_*`, and the older `house_floor_heating_share` are
  gone: a stored value is ignored with a warning in the log, a change that sets one is
  `unknown_field`), `ha`, `mqtt` (the broker
  connection of `config/mqtt` and `mqtt_inputs`), `controller`, `commands`, `safety`,
  `history` (the advanced retention fields `history_raw_days`, `history_1m_days`,
  `history_15m_days`, `history_1h_days`, `history_decision_days`; the rest of the group
  is expert) and `installation`. `dayshift` (after `stove`) holds the sun day shift (see
  `GET api/v1/control/dayshift`): `control_dayshift_use` `off` (default), `shadow` or
  `on` (experimental: valid only with `control_dayshift_experimental_ok`, a basic boolean
  defaulting to `false`, otherwise `dayshift_on_needs_ack`);
  `control_dayshift_day_start` / `_day_end` (local `HH:MM`, 09:00 and 17:00),
  `control_dayshift_boost_k` and `control_dayshift_setback_k` (0 to 1 K, 0.5 K each),
  `control_dayshift_min_outside_c` (-10 to 15 °C, 5 °C), `control_dayshift_min_sun_wm2`
  (0 to 600 W/m², 150 W/m²), `control_dayshift_night_start` / `_night_end` (23:00 and
  05:00), `control_dayshift_comfort_at` (07:00), `control_dayshift_recovery_s` (0 to 8 h,
  4 h) and `control_plan_rule_max_k` (0 to 1.5 K, 1 K: the bound of every rule plan
  slice, which also limits how far a set-back lowers the `room_below_floor` alarm). The
  times are strings of type `string`, refused with `clock_time` when not `HH:MM`. A changed retention reaches the history writer with the
  configuration (at the next controller tick) and is applied at once, no restart.
  `summer` (after `dayshift`) holds the summer switch: `control_summer_enabled` (off by
  default), `control_summer_off_c` (10 to 25 °C, 18 °C: no space heating while the slow
  outside mean is above it), `control_summer_hysteresis_k` (0.5 to 5 K, 2 K: heating
  resumes below `off_c` minus it) and `control_summer_mean_s` (6 h to 3 d, 24 h: the
  time constant of the slow mean; a full day and night, so one warm afternoon does not
  stop heating). While it holds, the controller asks for the safety minimum setpoint with
  the room feedback frozen; no other command, the pump is never switched off.
  `manual` holds boost and away (see `POST control/boost`, `PUT control/away`):
  `control_boost_enabled` (on), `control_boost_default_s` (900 to 43200 s, 2 h),
  `control_boost_default_k` (0.5 to 2 K, 1 K), `control_away_enabled` (on),
  `control_away_target_c` (10 to 20 °C, 16 °C), `control_away_comfort_lead_s` (0 to 24 h,
  6 h). `quiet` adds `control_quiet_enabled` (on; off ignores the windows),
  `control_quiet_start_enabled` (off), `control_quiet_start_minutes` (1 to 30, 10) and
  `control_quiet_start_level` (1 to 3, 2): quiet mode for the first minutes after a
  compressor start, the quieter of it and a window, held through a defrost (sent through
  the same quiet-mode path). `monitors` adds `safety_starts_alarm_enabled` (on),
  `safety_starts_per_hour_max` (1 to 20, 4) and `safety_starts_per_day_max` (1 to 200,
  30) for `compressor_starts`. `control_cycling_max_raise_k` is an advanced field of
  `cycling`.
- `feature`: the feature a field tunes (the ids of `GET control/features`), null for a
  general field. `read_only`: true for a field the API does not change (the expert tier),
  so a UI can show expert values flagged as fixed.
- `min`/`max` are hard bounds (`exclusive_*` when the bound itself is not allowed);
  `soft_min`/`soft_max` give a warning that must be acknowledged. Dynamic: the maximum
  of `control_max_supply_c` is the emitter's default (only lowering is possible here),
  `control_min_setpoint_c` at most maximum supply − 1, `control_ramp_max_below_curve_k`
  at most the envelope band below, the soft range of `control_feedback_kp` is 0.5–2 ×
  the preset's.
- `display` is the unit the UI shows (`min`, `h`) when it differs from `unit`.
- `preset_default`: unset means "the emitter preset's value"; `presets` lists them per
  emitter (for the emitter-change diff).
- `envelope`: the safety envelope of the current configuration; a curve must lie within
  `[curve − below_k, curve + above_k]` at every outside temperature.

### `GET api/v1/config` (read)

```json
{"version": 12, "applied_version": 12, "updated_at": "...", "updated_by": "admin from 192.168.1.20",
 "mode": {"configured": "auto", "effective": "auto", "paused": false, "reset_pending": false},
 "reset_pending": false, "hot_water": {"setting": "auto", "installed": true, "shown": true},
 "fields": {"control_comfort_c": {"value": 21.5, "source": "store", "locked": false,
                                  "stored": 21.5, "default": 21.0},
            "control_min_setpoint_c": {"value": 24, "source": "env", "locked": true,
                                       "stored": null, "default": 20}}}
```

`version` is the newest stored version (0 for an empty store), `applied_version` the one
the control loop runs (they differ until the next tick after an apply). `fields` covers
every settings field: `value` is effective (presets resolved), `source` `env` | `file` |
`store` | `preset` | `default`, `locked` is true for environment/options-file fields and
for every field that is not editable, `stored` the stored value (active or not),
`default` the value without environment, options file or store. Secrets appear as
`"set"`/`"unset"`.

`hot_water` says whether the app shows hot water (DHW). `setting` is the field
`hot_water` (`auto`, `on`, `off`); `installed` is the pump's `main/DHW_Installed`
(`true`/`false`, `null` until the pump reported it); `shown` is `true` for `on`, `false`
for `off` and, for `auto`, `false` only when the pump reports no tank. Display only: a DHW
run still freezes the corrections (`dhw_freeze`, `dhw_hold`) whatever the setting.

### `POST api/v1/config/validate` (operate)

Body `{"changes": {"control_comfort_c": 21.6, "control_dwell_s": null}}` (`null` removes
the stored value). Always `200` (`400` for a malformed body):

```json
{"valid": false,
 "errors": [{"field": "control_curve", "code": "outside_envelope", "message": "...",
             "params": {"at": [5.0], "by_k": [1.0]}}],
 "warnings": [{"field": "control_curve", "code": "curve_shift_large", "message": "...",
               "params": {"shift_k": 3.5, "at": 0.0, "limit_k": 3.0}}],
 "effective": {"control_comfort_c": 21.6, "control_dwell_s": 900.0}}
```

`message` is English; the UI renders from `code` and `params`. `field` is `null` for a
rule about the whole configuration. `effective` holds the effective values of the
changed fields. Every code with the `params` it carries (`path` locates a nested
value, e.g. `[0, "start"]` in the quiet windows; "-" means none):

| Code | Kind | Params | When |
|---|---|---|---|
| `unknown_field` | error | `path` (nested keys only) | not a settings field, or an unknown key inside one |
| `not_editable` | error | - | never stored, or an expert field |
| `connection_field` | error | - | a connection field in a configuration change: `ha_url`/`ha_token` are set with `PUT api/v1/config/ha`, the broker fields with `PUT api/v1/config/mqtt` |
| `ca_file_missing` | error | - | `mqtt_ca_file` is not a readable file (`config/mqtt`) |
| `password_locked` | error | `source`, `env` | the broker password comes from the deployment (`OVENBIRD_MQTT_PASSWORD` or the options file) and the change would send it elsewhere: another effective host or port, TLS switched off or another CA file (`config/mqtt`) |
| `locked` | error | `source`, `env` | set by the environment or the options file |
| `type` | error | `path` (nested values only) | wrong type |
| `missing` | error | `path` | a required key is missing |
| `below_min` | error | `min` | below the hard bound |
| `above_max` | error | `max` | above the hard bound |
| `not_allowed` | error | `allowed` | not one of the options |
| `too_many` | error | `max_length`, `actual_length`, `field_type` | too many items |
| `too_few` | error | `min_length`, `actual_length`, `field_type` | too few items |
| `too_long` | error | `max_length`, `path` | a text over its maximum length (an MQTT input's topic, signal or unit: 256 characters) |
| `invalid` | error | - | rejected by the controller's own checks |
| `clock_time` | error | `path` | not `HH:MM` |
| `curve_order` | error | - | outside not increasing or water increasing |
| `curve_outside_range` | error | `min`, `max` | an outside temperature beyond −30…30 °C |
| `curve_points` | error | `min`, `max` | not 2–6 points |
| `integral_time` | error | `min` | neither 0 nor at least 1800 s |
| `timezone` | error | - | not an IANA zone |
| `window_empty` | error | `path` | a quiet window that starts where it ends |
| `retention_min` | error | `min` | a `history_*_days` retention between 0 and 1 day (0 keeps the data forever; any other value is at least 1 day) |
| `input_bounds` | error | `path` | an MQTT input's plausibility bound that is not a finite number, or a minimum above the maximum |
| `input_topic_reserved` | error | `path`, `topic` | an MQTT input on a topic of the HeishaMon board itself: `<base>/main`, `<base>/commands` and everything below them, `<base>/stats`, `<base>/LWT` (other subtrees of the base, such as `1wire`, stay allowed) |
| `input_topic_repeated` | error | `path`, `topic` | an MQTT input topic listed twice |
| `input_signal_reserved` | error | `path`, `signal` | an MQTT input signal id reserved for the pump, Home Assistant or the service: a HeishaMon catalogue signal, `stats`, `LWT`, or an id starting with `main/`, `ha/`, `commands/` or `derived/` |
| `input_signal_repeated` | error | `path`, `signal` | two MQTT inputs with the same signal id (also when a custom id equals another input's `mqtt/<topic>`) |
| `room_signal_required` | error | - | liveness, cross-check or the automatic wood-stove detection without a room signal |
| `liveness_is_room` | error | - | the room signal listed as its own liveness |
| `crosscheck_is_room` | error | - | the room signal as its own cross-check |
| `signal_unknown` | error | `signal` | a signal the service cannot receive |
| `pump_duty_order` | error | - | idle duty above heat duty |
| `pump_duty_clamp` | error | `min`, `max` | a duty outside `command_pump_duty_min`/`_max` |
| `stove_hysteresis` | error | `max` | wood-stove exit hysteresis above the entry threshold (it would end below comfort) |
| `stove_min_above_max` | error | `max` | wood-stove minimum episode longer than the maximum |
| `stove_reference_is_room` | error | - | the room signal as the wood-stove reference room |
| `signal_not_temperature` | error | `signal` | the wood-stove reference room is not a temperature in °C (an HA entity outside `sensor`, `input_number`, `number`, or an MQTT input with another unit) |
| `min_above_max` | error | `min`, `max` | minimum setpoint not below the maximum supply (both effective) |
| `curve_range` | error | `min`, `max` | water outside [minimum setpoint, maximum supply] |
| `outside_envelope` | error | `at`, `by_k` | the curve leaves the safety envelope |
| `integral_above_output` | error | - | integrator limit above the output limit |
| `ramp_below_envelope` | error | `max` | start ramp reaching below the envelope |
| `fixed_range` | error | `min`, `max` | with weather-dependent control off, a fixed water temperature outside [minimum setpoint, maximum supply] |
| `location_pair` | error | - | latitude without longitude or the reverse |
| `location_required` | error | - | a manual or browser location without coordinates |
| `max_supply_raise` | error | `max` | the maximum supply raised above the emitter's default |
| `dayshift_windows` | error | - | the day shift windows out of order: the day window wraps midnight or is empty, or, going forward from its end, the night does not start, end and reach `control_dayshift_comfort_at` before the next day window |
| `dayshift_on_needs_ack` | error | - | `control_dayshift_use` = `on` without `control_dayshift_experimental_ok`: switching on, or taking the acknowledgement back while `on` is set |
| `warning_not_acknowledged` | error (`PUT` only) | `warning` | a warning that was not acknowledged |
| `no_change` | error (`PUT` only) | - | the changes leave the configuration as it is |
| `comment_too_long` | error (`PUT` only) | - | a comment over 200 characters |
| `below_soft_min` | warning | `value`, `soft_min` | below the usual range |
| `above_soft_max` | warning | `value`, `soft_max` | above the usual range |
| `curve_shift_large` | warning | `shift_k`, `at`, `limit_k` | the curve moves more than 3 K anywhere in −15…20 °C |
| `cycling_disabled` | warning | - | cycling protection switched off |
| `emitter_changed` | warning | `from`, `to` | a different emitter preset |
| `weather_compensation_off` | warning | - | weather-dependent control (WAR) switched off |
| `fixed_outside_envelope` | warning | `from`, `to` | the safety envelope overrides the fixed water temperature in that outside range (°C) |

Warnings are reported only for the changed fields.

### `POST api/v1/config/preview` (operate)

Body as `config/validate` plus an optional `"hours"` (1–72, default 24; `400`
otherwise). An invalid candidate returns the validation result alone (`valid: false`,
no `now`, no `open_loop_run`). A valid one, `200`:

```json
{"valid": true, "errors": [], "warnings": [], "effective": {"control_comfort_c": 21.6},
 "now": {"current": {"...": "decision record"}, "candidate": {"...": "decision record"},
         "delta_setpoint": 1},
 "open_loop_run": {"from": "...", "to": "...", "ticks": 1440, "skipped": 0,
             "identity_ok": true, "identity_ticks": 1440, "identity_mismatches": 0,
             "identity_first_mismatch": null, "open_loop": true,
             "series": {"at": ["..."], "recorded": [33], "candidate": [34],
                        "candidate_pre_round": [33.7]},
             "summary": {"mean_diff_k": 0.4, "min_diff_k": -1, "max_diff_k": 2,
                         "changes_recorded": 18, "changes_candidate": 22,
                         "writes_per_day": 22.0, "budget": 150,
                         "share_safety_clamped": 0.02, "share_feedback_limited": 0.0,
                         "ladder": {"schedule_curve_feedback": 0.99, "curve_only": 0.01},
                         "binding": {"deadband": 0.61, "dwell": 0.07}},
             "limitations": []}}
```

- `now`: the active configuration and the candidate, each stepped once on the current
  inputs from a copy of the current controller state (carried over to the candidate
  as an apply would: integrator clamped, ramp, cross-check); `null` without a control
  loop. `delta_setpoint` is candidate minus current (`null` when either has none).
- `open_loop_run`: every recorded tick of the last `hours` (service clock) replayed with the
  candidate from the recorded controller state just before the window, inputs rebuilt
  from each decision's `inputs_used`. **Open loop**: the candidate reacts to what the
  house did under the recorded control; no energy or comfort claim follows from it.
  `ticks` counts the recorded ticks, `skipped` those that could not be read or
  replayed; `series` has one entry per replayed tick.
- **Identity check**: the same replay with the active configuration must reproduce
  the recorded setpoint of every tick made under the active version (`identity_ticks`
  compared, `identity_mismatches` differing, the first at `identity_first_mismatch`).
  It re-seeds from the recorded state where the version changed (carried over as the
  apply did) and follows service restarts (state re-anchored, or fresh when the saved
  one was too old). `identity_ok: false` means "replay not exact — indication only".
- `summary`: differences candidate − recorded over ticks where both have a setpoint;
  setpoint changes in the window and per day versus the daily write budget; the share
  of ticks the safety stage clamped and the room feedback was limited; the share of
  each ladder level and binding constraint.
- `limitations`: what the replay cannot show for this candidate (another room signal
  was not recorded; room freshness is as recorded under the active sensor profile).

One preview runs at a time; the replay of 72 h takes about a second.

### `GET api/v1/config/signals` (admin)

Candidates for the signal pickers:

```json
{"ha": {"enabled": true, "link_up": true, "temperature_unit": "°C"},
 "room": [{"signal": "ha/sensor.living_room_temperature", "name": "Living room climate",
           "unit": "°C", "value": 21.9, "held_s": 7800.0, "source": "ha",
           "pump_mirror": false, "entity_id": "sensor.living_room_temperature",
           "area": "Living room", "device_id": "5f0c..."},
          {"signal": "ha/climate.living_room#current_temperature", "name": "Thermostaat",
           "unit": "°C", "value": 21.5, "held_s": 60.0, "source": "ha",
           "pump_mirror": false, "entity_id": "climate.living_room", "area": "Living room"},
          {"signal": "ha/sensor.panasonic_heat_pump_main_dhw_temp", "name": "...",
           "unit": "°C", "value": 48.0, "held_s": 30.0, "source": "ha",
           "pump_mirror": true, "entity_id": "sensor.panasonic_heat_pump_main_dhw_temp",
           "device_id": "9a1b..."}],
 "liveness": [{"signal": "ha/sensor.living_room_humidity", "name": "...", "unit": "%",
               "value": 54.0, "held_s": 120.0, "source": "ha", "pump_mirror": false,
               "entity_id": "sensor.living_room_humidity", "device_id": "5f0c..."}],
 "crosscheck": [{"signal": "main/Room_Thermostat_Temp", "name": null, "unit": "°C",
                 "value": 22, "held_s": 600.0, "source": "heishamon",
                 "pump_mirror": false}]}
```

Home Assistant candidates come from the `get_states` result the HA input re-reads every
5 min (read-only): temperature sensors (device class `temperature` or a temperature
unit) and thermostats for `room` and `crosscheck`, every `sensor.*` for `liveness`. A
thermostat (`climate.*`) is offered through its `current_temperature` attribute as the
signal `ha/climate.<name>#current_temperature`, in HA's temperature unit (converted to
°C when it arrives); only thermostats that report one are listed. `entity_id` is the
HA entity; `area` (the entity's or its device's area name) and `device_id` are present
when HA's registries could be read (one read-only read per connection), so the UI can
list the room sensor's own device first for liveness. `ha.temperature_unit` is HA's
unit system temperature unit (absent until known). MQTT inputs come
from the settings (temperature units for `room` and `crosscheck`, all for
`liveness`), `main/Room_Thermostat_Temp` from the catalogue; their values and held
times from the state store.

`pump_mirror` marks a Home Assistant entity on a device that copies the heat pump, such
as Home Assistant's own HeishaMon integration: ovenbird already reads those values over
MQTT, so the pickers list them apart, last and grouped (still selectable). A device
counts as a mirror when at least 3 of its entities hold pairwise different numbers
(a state, or a thermostat's `current_temperature`), each within 0.05 of the current
value of a different HeishaMon `main/*` signal in the state store. A number that more
than 3 `main/*` signals hold at once (the `0` and `1` of flags and modes) proves nothing
and is not counted. Entities without a device are never marked, and without HeishaMon
values nothing is. The test runs on the current values at every request, without any
list of names or models. `pump_mirror` is always false for MQTT and HeishaMon
candidates.

### `PUT api/v1/config/ha` (admin)

Sets the Home Assistant connection the service reads from: body `{"url": "...",
"token": "..."}`, either key alone, `null` removes the stored value (any other key:
`400`). The URL is HA's base URL, direct (`http://192.0.2.10:8123`) or behind a
reverse proxy (`https://ha.example.org`, a path prefix allowed); `http`, `https`,
`ws` or `wss`, with a host, without user name, password, query or fragment. Plain
`http` is fine on the LAN; certificates are always verified for `https`. The token is
a long-lived access token (no whitespace, at most 4096 characters). URL and token go
together, and a new URL needs its token in the same request (`token_required`
otherwise), so a stored token is never sent to another host. Both live in `config.db` (table `connection`, outside the configuration
versions, so a rollback never changes them; in the store snapshot like the rest), and
are **write-only**: `GET config`, exports, versions, diagnostics and the audit show the
token only as `"set"`/`"unset"`. A field set by `OVENBIRD_HA_URL`/`OVENBIRD_HA_TOKEN` or
the options file is locked and wins (the stored value stays, inactive).

The new connection applies at once: the HA input reconnects without a restart and the
next tick re-evaluates the signals. Removing the connection while a settings field
uses an `ha/` signal is refused (`signal_unknown` on that field). Nothing is written to
Home Assistant.

- `200` `{"config": <as GET config>}`;
- `422` `{"errors": [...], "warnings": []}` with the validation codes: `locked`, `type`,
  `invalid` (URL or token), `missing` (URL without token or the reverse),
  `token_required` (a new URL without its token), `no_change`,
  or a rule of the configuration the change would break;
- `400` for a malformed body.

### `POST api/v1/config/ha/test` (admin)

Tests a connection without saving it: body `{"url"?, "token"?, "signals"?}`. `url`
defaults to the effective one; the effective token is used only when the URL is the
effective one, so a stored token is never sent to another host (`token_required`
otherwise). `signals` (at most 32 `ha/` signals) defaults to the `ha/` signals of the
effective settings. Read-only: `GET <url>/api/`, then the WebSocket `auth`,
`get_config` and `get_states`; at most 5 s per step, one test at a time. Admin only,
like changing the connection: the test makes the service connect to a URL of the
client's choice, which an operate client must not be able to steer. Always `200`:

```json
{"ok": false, "url": "http://192.0.2.10:8123", "reachable": true, "auth_ok": true,
 "ha_version": "2026.11.1", "latency_ms": 18.4, "temperature_unit": "°C", "metric": true,
 "entities": [{"signal": "ha/sensor.living_room_temperature",
               "entity_id": "sensor.living_room_temperature", "found": false, "state": null,
               "value": null, "unit": null, "problem": "not found in Home Assistant"}],
 "error": null, "error_code": null}
```

`ok` is true when HA answered, accepted the token and every entity was found without a
`problem` (unavailable, not a number, no `current_temperature`, or a room temperature
without a unit outside a metric unit system). `error` is a human-readable English text,
`error_code` one of `invalid_url`, `not_configured`, `token_required`, `unreachable`,
`auth_failed`, `http_error` (another status, e.g. a redirect: use the final URL),
`protocol`, `timeout`, `websocket`. The token never appears in the result or the logs.

### `GET api/v1/config/mqtt`

The broker link and the last broker change made in the app:

```json
{"connected": true, "host": "192.0.2.20", "port": 1883, "base": "panasonic_heat_pump",
 "heishamon_messages": 144, "commands_enabled": false,
 "apply": {"state": "applied", "message": "connected; HeishaMon data arrives",
           "at": "2026-11-24T10:15:02+00:00"}}
```

`heishamon_messages` counts the `<base>/main/*` deliveries of the current session.
`apply.state` is `idle` (no change since the start), `applying` (the watch below runs),
`applied` or `reverted` (with the reason in `message`).

### `POST api/v1/config/mqtt/test` (admin)

Tests broker settings without saving them: body with any of `host`, `port`, `username`,
`password`, `tls`, `ca_file`, `client_id`, `base` (the HeishaMon base topic); an absent
key keeps the effective value, `null` or `""` the default. The password never goes to
another broker: when the effective host or port changes, TLS is switched off or the CA
file changes, a stored password is dropped unless `password` is in the body again, and a
password set by the deployment refuses the candidate (`422` `password_locked`; change
the broker in the deployment). The test opens its own subscribe-only session (own
client id, so the running session stays), subscribes to `<base>/main/#` and waits for a
live HeishaMon value: a retained one alone does not count (it may come from a board
that is long gone), HeishaMon publishes on change after every 5 s query; at most 30 s,
one test at a time, nothing is published. Always `200` for a valid candidate:

```json
{"ok": true, "host": "192.0.2.20", "port": 1883, "base": "panasonic_heat_pump",
 "connected": true, "heishamon": true, "topic": "panasonic_heat_pump/main/Heatpump_State",
 "latency_ms": 23, "error": null, "error_code": null}
```

`error_code` is one of `unreachable`, `tls`, `auth_failed`, `refused` (another
CONNACK refusal), `timeout` (no connection in time) and `no_heishamon` (connected, but
no live `main/*` value on that base; `error` says when only retained values came). An invalid candidate answers `422` with the codes of
`PUT config/mqtt`. A successful test is remembered for 10 minutes and clears
`mqtt_connection_reverted`. The password never appears in the result or the logs.

### `PUT api/v1/config/mqtt` (admin)

Applies broker settings: the same body as the test, and it must be exactly the
candidate of a successful test in the last 10 minutes (`409` `test_required`
otherwise). The values live in `config.db` (table `connection`, like the HA connection:
outside the configuration versions, the password write-only, shown as `"set"`/`"unset"`
in `GET config`, exports and the audit). A field set by `OVENBIRD_MQTT_*`,
`OVENBIRD_HEISHAMON_BASE` or the options file is locked and wins ("set by the
deployment"); changing it answers `422` `locked`.

The change applies at once: it is audited (`mqtt_connection`, without the password),
the ingest ends its session and connects with the new settings at once (also while it
waits out a reconnect delay), and a watch waits up to 60 s for the session to be up
and a live (not retained) HeishaMon `main/*` value to arrive. Without that, the
previous broker fields are put back on the current state (a configuration version or
HA connection changed in the meantime stays; audited as `mqtt_connection_reverted` by
`ovenbird`), the ingest reconnects to it and the warning `mqtt_connection_reverted`
stays active until the next successful test or change. When putting it back fails,
`apply.state` is `failed` and the critical alarm `mqtt_revert_failed` stays active
until the next successful test or change. The previous connection and an "unconfirmed"
marker are kept in `config.db` until the watch decides, so a restart during the
window watches the new broker again after the start. While commands are enabled the
broker cannot be changed here (`409` `commands_enabled`): the command link and the
publish guard keep the broker they started with, so change it in the deployment and
restart.

- `200` `{"config": <as GET config>, "mqtt": <as GET config/mqtt>}`;
- `409` `commands_enabled`, `apply_pending` (the last change is still being watched)
  or `test_required`;
- `422` `{"errors": [...], "warnings": []}` with `unknown_field`, `locked`, `type`,
  `invalid` (a host, user name or client id with spaces or too long),
  `ca_file_missing`, `no_change`, a field rule (port 1 to 65535, the base topic
  without wildcards) or a rule of the configuration the change would break.

### `PUT api/v1/config` (admin)

Body `{"base_version": 12, "changes": {...}, "comment": "<at most 200 characters>",
"acknowledge": ["curve_shift_large"]}`. Re-validates, refuses unacknowledged warnings,
writes the version and its audit row, snapshots the store and hands the new settings to
the control loop, which swaps them in **between ticks**: the controller state carries
over (integrator clamped to the new limit, a disabled ramp ends, a changed cross-check
forgets its offset; the issued setpoint and the dwell timer survive), so the setpoint
moves only through deadband and dwell or a safety bound. The store's staleness policy,
the adapter's setpoint clamp, the safety monitor's maximum and the HA subscription set
follow (a room-entity change reconnects the HA session; feedback is off until the
first fresh value). The first decision made with it carries the new `config_version`,
and a `config` WebSocket message confirms.

- `200` `{"version": 13, "applies": "next_tick", "config": <as GET config>}`;
- `409` `{"detail", "version": <current>}` for a stale `base_version`;
- `422` `{"errors": [...], "warnings": [...]}` for invalid, locked, unchanged or
  unacknowledged changes;
- `429` `{"detail", "retry_after"?}`: at most one apply per 60 s and 30 per 24 h,
  counted for valid applies only. Both are measured on the **service clock**: on the
  dev stack's scaled clock (`OVENBIRD_CLOCK_SPEED`, 60 by default) one apply per
  simulated minute is one per real second, and the 30 per simulated day are used up
  within about 24 real minutes (`retry_after` is in simulated seconds);
- `400` for a malformed body.

### `GET api/v1/config/versions?limit=<n>` (read) and `GET api/v1/config/versions/{n}` (read)

`limit` 1..500 (default 50), newest first:

```json
{"versions": [{"version": 13, "created_at": "...", "actor": "admin from 192.168.1.20",
               "origin": "ui", "comment": "a bit cooler", "applied_at": "...",
               "changed": [{"field": "control_comfort_c", "from": 21.5, "to": 21.3}]}]}
```

`origin`: `ui`, `rollback`, `seed` (`OVENBIRD_CONFIG_SEED`, version 1 of an empty
store) or `reset` (an empty document written at start when the newest version no
longer validated). `changed` compares with the previous version's stored values
(`null` = not stored). `versions/{n}` adds `values` (the stored document); `404` when
unknown.

### `POST api/v1/config/rollback` (admin)

Body `{"version": 9, "base_version": 13, "comment"?, "acknowledge"?}`: a new version with
version 9's stored values (locked fields excepted), through the same validation and
responses as `PUT`; audited as `config_rollback`. `404` for an unknown version.

### `GET api/v1/config/export` (admin)

A download (`Content-Disposition: attachment`):

```json
{"ovenbird_config": 1, "app_version": "0.6.0", "exported_at": "...", "version": 13,
 "values": {"control_comfort_c": 21.6}, "effective": {"<every non-secret field>": "..."}}
```

Import happens in the browser: the file's `values` become a draft that goes through
validate and apply. The same format is the seed file.

### `POST api/v1/config/reset-ack` (admin)

Body `{}`. When `config.db` was missing after having existed (and no snapshot could
restore it), was corrupt (moved aside as `config.db.corrupt-<time>`) or its newest
version no longer validated, the service starts with the installation's values in
shadow with the `config_reset` alarm; this acknowledges it: the alarm clears and
control returns to the configured mode (unless paused). `200` `{"mode", "config"}`;
`409` when no reset is pending. Audited as `config_reset_ack`.

## `GET api/v1/weather?back_h=24&ahead_h=48` (read)

Measured, filtered and forecast outside temperature (`back_h` up to 168, `ahead_h` up
to 72; `422` beyond). The forecast is **opt-in** (`weather_enabled`; the coordinates
leave the house, rounded to 0.01°). It is shown only; it is not a controller input.

```json
{"enabled": true, "provider": "open-meteo", "issued": "...", "age": 1200.0, "stale": false,
 "location": {"latitude": 52.09, "longitude": 5.12, "source": "ha_zone_home"},
 "now": {"measured_c": 2, "filtered_c": -0.3, "forecast_c": 1.4, "curve_c": 34.1},
 "measured": {"step": 900, "points": [["...", 2.0]]},
 "filtered": {"step": 900, "points": [["...", -0.3]]},
 "forecast": {"step": 3600, "points": [["...", 1.4, 0.0, 100.0, 3.2]]},
 "forecast_past": {"lead_h": 24, "points": [["...", 2.1]]},
 "error": {"lead_h": [6, 24], "bias_k": [0.3, 0.8], "mae_k": [0.9, 1.4], "n": [160, 140]},
 "curve_outlook": {"points": [["...", 33.2]]}}
```

- `provider`: `open-meteo` (`https://api.open-meteo.com/v1/forecast`, hourly
  temperature, radiation, cloud cover and wind, one day back and three ahead, no API
  key) or `simulated` (simulation mode: derived from the simulator's weather plus
  lead-time noise, no network). A forecast is fetched every hour (service clock, with
  backoff after a failure) and stored **as issued** in `history.db` (retention as the
  1 h rollup), so the error statistics are lead-time correct.
- `location.source`: `manual` or `browser` (the stored `weather_latitude`/
  `_longitude`), else `ha_zone_home` (Home Assistant's `zone.home`).
- `issued` and `age` (s) of the newest issue; `stale` after 3 h.
- `now`: the current `Outside_Temp` (integer, `null` when not fresh), the controller's
  filtered value, the forecast interpolated at now and the active curve at the
  filtered value.
- `measured`: `Outside_Temp` 15 min means; `filtered`: the controller's filtered
  outside temperature (last tick per 15 min).
- `forecast`: the newest issue from the start of the current hour to `ahead_h`:
  `[time, temperature °C, radiation W/m², cloud cover %, wind m/s]` (a value is `null`
  when the provider has none).
- `forecast_past`: what was forecast 24 h ahead for each past hour of the window.
- `error`: forecast minus measured (the 30 min around the hour) at 6 h and 24 h lead
  over the issues of the last 14 days: `bias_k`, `mae_k` (`null` without pairs) and
  the number of pairs `n`.
- `curve_outlook`: the active curve on the forecast, run through the controller's
  outside filter from the current filtered value ("curve only, before room
  correction").

While off: `{"enabled": false, "provider", "reason", "location"}` (`location` when one
is known).

## `GET api/v1/pump/settings` (read)

What HeishaMon reports of the pump's settings, and the operator's three writable ones:

```json
{"writable": true, "refusals": [], "model": "32 D4 0B 88 84 73 90 0C 85 84",
 "profile": {"name": "WH-MXC12J9E8",
             "source": "Panasonic service manual PAPAMY2110029CE (WH-MXC09J3E8/WH-MXC12J9E8), 14.2.2 Deice Operation"},
 "settings": [{"id": "heat_delta", "signal": "main/Heat_Delta", "value": 5, "unit": "K",
               "label": null, "fresh": true, "age": 12.0, "supported": true,
               "access": "write", "owner": "operator", "command": "SetFloorHeatDelta",
               "min": 3, "max": 10,
               "last_write": {"at": "...", "by": "admin from 192.168.1.20", "from": 5,
                              "to": 4, "status": "verified"}},
              {"id": "max_pump_duty", "signal": "main/Max_Pump_Duty", "value": 159,
               "unit": null, "label": null, "fresh": true, "age": 40.0,
               "supported": true, "access": "read", "owner": "controller"}]}
```

- Writable (`access: "write"`, always the first three rows): `heat_delta`
  (`SetFloorHeatDelta`, 3–10 K), `pump_flowrate_mode` (`SetPumpFlowrateMode`, 0
  DeltaT / 1 Max flow), `heating_off_outdoor` (`SetHeatingOffOutdoorTemp`, 10–35 °C).
- Read-only: `max_pump_duty`, `quiet_mode_level` (owner `controller`: ovenbird's own
  settings), `quiet_mode_priority`, `powerful_mode_time`, `heating_control`,
  `heater_on_outdoor`, `heater_delay_time`, `heater_start_delta`,
  `heater_stop_delta`, `room_heater_state`, `heating_mode`, `z1_curve_target_high`,
  `z1_curve_target_low`, `z1_curve_outside_high`, `z1_curve_outside_low` (owner
  `operator`: the remote or the installer) and `operating_mode_state`, `zones_state`,
  `pump_duty`, `pump_flow`, `internal_heater_state`, `error` (owner `pump`: states).
- `label` is the catalogue's enum meaning (e.g. `max_flow`, `sound`, `direct`), `null`
  otherwise. `supported` is false when this model does not report the topic or
  reports an invalid value (HeishaMon's `-1` for an unsupported enum); `value` is
  then `null`.
- `writable` and `refusals`: why no write is possible now (paused, mode, hold,
  defrost, DHW run, a write in progress); `model` is `Heat_Pump_Model`.
- `profile`: the model profile those ID bytes select (`name`, `source`: the manual
  and section its facts come from), `null` for a model without one. Only ID bytes
  verified on a real unit have a profile; the safety monitors use it to tell a defrost
  that stops the water pump by design from one that should not.
- `last_write`: the newest operator write of the setting (`status` is its latest
  command status), from memory or after a restart from the audit trail and the
  command journal; `null` when there was none.

## `POST api/v1/pump/settings/{id}` (admin)

Body `{"value": 4, "expect": 5, "comment"?: "<at most 200 characters>"}`, under the
request rules above. The value goes through the command adapter like a controller
command — the same publish guard, a **second closed allowlist** (these three settings,
their topics and clamps), serial queue and spacing, effect verification against the
read-back topic with retries, daily write budget and journal — but is **refused, not
clamped**, written only when `expect` equals the fresh reported value
(compare-and-set), never during a defrost, a DHW run or any hold, one write at a time.
A failed verification raises `verification_failed` and does **not** hold setpoint
control. Accepted writes are audited (`pump_setting`).

- `202` `{"command": <the queued command event, see commands>}`; the progress
  (`sent`, `verified`, ...) follows in `commands` and `last_write`;
- refusals `{"detail": {"code", "message", "params"}}`:
  - `404` `unknown_setting` (any other id, the read-only ones included);
  - `400` `bad_comment`;
  - `422` `not_an_integer`, `out_of_range` (params `min`, `max`), `expect_required`;
  - `409` `not_publishing` (the publish guard refuses: not `auto`, paused or shadow,
    commands not allowed), `hold` (a board, mode, foreign-writer, verification or
    safety hold), `defrost`, `dhw`, `state_unknown` (`Defrosting_State` or
    `ThreeWay_Valve_State` not fresh), `not_fresh` (the setting is not freshly
    reported, or not by this model), `value_changed` (params `reported`), `unchanged`
    (already the reported value), `in_flight` (another write is queued or in flight);
  - `429` `rate_limited` (one write per setting per 10 min; params `retry_after`),
    `day_limit` (six writes per 24 h; params `limit`, `retry_after`), `write_budget`
    (the daily command budget is used up; params `limit`). Measured on the service
    clock and kept across restarts (from the journal).

## `GET api/v1/insight/daily?days=7` (read)

Daily figures for the last `days` local days (1..90, default 7; `422` otherwise),
oldest first, today last. A day runs from local midnight to the next one in the
service's time zone (`control_timezone`, `timezone` in the body; it lasts 23 or 25 h
on a daylight saving switch); today is taken from the service clock (the simulated
time on the dev stack).

```json
{"timezone": "Europe/Amsterdam", "band_below_k": 0.5,
 "room_signal": "ha/sensor.living_room_temperature",
 "days": [{"date": "2026-01-14", "from": "2026-01-13T23:00:00Z",
           "to": "2026-01-14T23:00:00Z", "hours": 24.0, "partial": false,
           "coverage": 0.98, "electric_kwh": 9.6, "heat_kwh": 39.2, "cop": 4.08,
           "dhw_electric_kwh": null, "dhw_heat_kwh": null,
           "compressor_starts": 4, "run_s": 51000, "defrosts": 3, "defrost_s": 1260,
           "dhw_runs": 0, "dhw_s": 0, "outside_mean_c": 3.1, "outside_min_c": 0.4,
           "room_mean_c": 21.4, "room_min_c": 20.9, "comfort_c": 21.5,
           "below_comfort_kh": 2.1, "setpoint_mean_c": 31.7, "setpoint_changes": 21,
           "writes": 21}]}
```

Every figure comes from the 1 min rollups of the history (retention
`OVENBIRD_HISTORY_1M_DAYS`, 90 days; older days have no data). A figure is `null` when
its source signal has no data that day.

- `from`/`to`: the day's bounds in UTC; `hours` its length; `partial`: today (not over
  yet).
- `coverage`: share of the day (of its elapsed part for today) for which both heating
  power estimates have data. Gaps are not filled: the energy is what was measured.
- `electric_kwh`, `heat_kwh`: the pump's heating estimates `Heat_Power_Consumption` and
  `Heat_Power_Production` integrated over time; `cop` = heat / electricity (null when
  no electricity was used). `dhw_electric_kwh`, `dhw_heat_kwh`: the same for
  `DHW_Power_*` (null when the pump does not report them).
- `compressor_starts`: `Compressor_Freq` rising to at least 1 Hz (also across a data
  gap when it was off before and runs after); `run_s`: seconds at or above 1 Hz.
  `defrosts`/`defrost_s` from `Defrosting_State`, `dhw_runs`/`dhw_s` from
  `ThreeWay_Valve_State`. Transitions are seen at 1 min resolution.
- `outside_mean_c`/`outside_min_c`: `Outside_Temp` (time-weighted mean, lowest value).
- `room_mean_c`/`room_min_c`: the configured room signal (`room_signal`, null without
  one). `comfort_c`: the current comfort target; `below_comfort_kh`: degree-hours
  below `comfort_c − band_below_k`. The value a signal holds since its last report
  is counted once the next report arrives (as in `history`), so today's room figures
  can lag behind for a room sensor that reports on change only.
- `setpoint_mean_c`: mean of the pump's `Z1_Water_Target_Temp`; `setpoint_changes`:
  how often it changed.
- `writes`: command events with status `sent` (all MQTT writes, retries and operator
  writes included); null for days starting before the command journal's retention
  (`OVENBIRD_HISTORY_DECISION_DAYS`) or without a journal.

## `GET api/v1/insight/basics` (read)

The house basics: an estimate of the heat loss of the house at the current weather and
of the heat the house gets from the heat pump at a water temperature. With
`house_basics_enabled` off the body is `{"enabled": false, ...}` with `computed_at`,
`heat_loss`, `loss_now`, `heat_pump` and `by_weather` `null`, and nothing is read. The
fits use the 15 min rollups of the last 365 complete local days (`control_timezone`) and
are cached: they are computed again at most once an hour, when a local day closes or
when the history path, room signal or time zone changes (`computed_at`). The live values
(room, outside, heat now, the last 24 h) are read on every request.

```json
{"enabled": true, "computed_at": "2026-01-20T11:00:00Z", "timezone": "Europe/Amsterdam",
 "room_signal": "ha/sensor.living_room_temperature", "design_outside_c": -10.0,
 "heat_loss": {"status": "credible", "reasons": [], "h_w_per_k": 182.4,
   "h_low_w_per_k": 171.0, "h_high_w_per_k": 193.8, "offset_w": 640,
   "balance_offset_k": 3.5, "balance_c": 17.5, "days_used": 44, "points_used": 22,
   "outlier_points": 0, "near_balance_points": 0, "span_k": 14.2, "outside_min_c": -1.5,
   "outside_max_c": 12.7, "room_mean_c": 21.0, "residual_w": 55,
   "first_date": "2025-12-01", "last_date": "2026-01-19",
   "excluded": {"low_coverage": 1, "stove": 4, "no_heating": 3, "away": 0},
   "points": [{"first_date": "2025-12-01", "last_date": "2025-12-02", "delta_k": 12.4,
               "heat_w": 1620, "outside_c": 8.6, "room_c": 21.0, "use": "used"}]},
 "loss_now": {"room_source": "measured", "outside_source": "filtered",
   "forecast_available": true,
   "now": {"at": "2026-01-20T11:02:10Z", "outside_c": 2.0, "room_c": 21.0, "delta_k": 19.0,
           "loss_w": 2826, "low_w": 2790, "high_w": 2862, "beyond_data": false},
   "night": {"at": "2026-01-21T05:00:00Z", "outside_c": -3.0, "room_c": 21.0,
             "delta_k": 24.0, "loss_w": 3738, "low_w": 3660, "high_w": 3816,
             "beyond_data": true},
   "design": {"at": null, "outside_c": -10.0, "room_c": 21.0, "delta_k": 31.0,
              "loss_w": 5014, "low_w": 4840, "high_w": 5188, "beyond_data": true}},
 "heat_pump": {
   "delivered": {"now_w": 3120, "now_reason": null, "mean_24h_w": 2710,
                 "coverage_24h": 0.998},
   "emitter": {"status": "provisional", "reasons": ["few_hours"], "k_w_per_k": 402.5,
     "k_low_w_per_k": 380.1, "k_high_w_per_k": 424.9, "hours_used": 64, "days_used": 12,
     "span_k": 6.1, "flow_l_min": 20.0, "room_c": 21.0, "setpoint_min_c": 24.0,
     "setpoint_max_c": 45.0,
     "table": [{"supply_c": 24.0, "mean_water_c": 23.6, "heat_w": 1046, "low_w": 988,
                "high_w": 1103, "loss_now_w": 2826, "margin_w": -1780}],
     "balance_supply_c": 29.0, "balance_mean_water_c": 28.0, "balance_in_range": true}},
 "by_weather": [{"from_c": 2.0, "to_c": 4.0, "days": 6, "heat_w": 2580,
                 "electric_w": 690, "cop": 3.74, "few_days": false}]}
```

**`heat_loss`**: least squares of the mean space-heating power `P` against the room
minus outside temperature `dT`, `P = H x dT - G`. `h_w_per_k` is `H` (W/K) with its
95 % band `h_low_w_per_k`..`h_high_w_per_k` (the slope's standard error and Student's
t); `offset_w` is `G` (internal and solar gains on average); `balance_offset_k` = `G/H`
and `balance_c` = `room_mean_c - G/H`, the outside temperature at which the house needs
no heating. `P` is the loop heat `derived/heat_delivered_w` (flow x spread): hot-water
runs are not in it and a defrost's draw from the loop is netted.

- A point (`points`, oldest first) is a 48 h window of two consecutive qualifying local
  days, averaged, so heat stored in the floor one day and given back the next mostly
  cancels; windows never share a day. A day qualifies when at least 80 % of it has data
  (loop heat or hot water, outside and room), it needed real heating (mean loop heat at
  least 250 W and the room at least 4 K above outside) and no wood-stove episode
  (journal `stove_mode`) touched it or the 12 h before it, as the stove heats the room
  sensor and its heat stays in the room overnight, and no away period (journal
  `away_mode`, its return included) touched it. `excluded` counts complete days with
  data that did not qualify, by the first reason that applies (days without any data
  are not counted). `use`: `used`, `outlier` (one robust pass drops windows beyond 3.5
  robust standard deviations: a holiday, an open window, a stove the journal missed)
  or `near_balance` (less than 3 K above the fitted `G/H`: part of such a day needs no
  heat, so its mean falls below the line).
- `days_used` = 2 x `points_used`; `span_k`: range of `dT` over them; `residual_w`: the
  residual standard deviation of a window.
- `status`: `collecting` (no number: `no_room_signal` without a room signal,
  `too_few_days` under 10 days, `span_too_small`
  under 3 K, `slope_not_positive`, `slope_implausible` above 2000 W/K, `too_uncertain`
  when the band reaches zero), `provisional` (`few_days` under 30 days, `narrow_span`
  under 10 K: a number with a wide band) or `credible`.
- Limits: no irradiance is modelled, so when the milder days are also the sunnier ones
  (autumn) `H` reads high, and in a winter of clear cold days low; the room is the
  control sensor's room, so `H` describes the house as that sensor sees it; a stove
  outside the journal or a long set-back adds scatter.

**`loss_now`**: the heat loss from `H` and `G` with the 95 % band of the fitted line
(it widens away from the data; `beyond_data` when `dT` lies above every window used),
`null` while `heat_loss` is collecting. `now` uses the room now (`room_source`
`measured`, else the comfort target, `comfort`) and the controller's filtered outside
temperature (`outside_source` `filtered`, else the fresh measurement `measured`; `now`
is `null` without either). `night` is the loss at the lowest forecast temperature of
the coming night (from now, or 18:00, until the next local 09:00; `at` is that hour),
`null` when the stored forecast is stale or missing (`forecast_available`). `design`
is the load at the design outside temperature `design_outside_c` (−10 °C, a constant:
there is no setting for it) with the room at the comfort target.

**`heat_pump.delivered`**: `now_w` is `derived/heat_delivered_w` now (`null` with
`now_reason` `hot_water` during a hot-water run, else `unknown`); `mean_24h_w` the
mean loop heat of the last 24 h (1 min rollups, hot water counted as zero) and
`coverage_24h` its share with data.

**`heat_pump.emitter`**: least squares through the origin of the loop heat against the
mean water temperature (inlet and outlet averaged) minus the room, on the clock hours in
which the compressor ran (at least 1 Hz) for the house throughout, without hot water or
a defrost, in the second hour of a run or later and outside a wood-stove episode and its
tail: `Q = K x (T_water - T_room)`, `k_w_per_k` with its 95 % band (the standard error
is clustered by local day, as the hours of one day are not independent). `status`:
`collecting` (`no_room_signal`, `too_few_hours` under 24 hours or 3 days, and the same
guards as above, `slope_implausible` above 5000 W/K), `provisional` (`few_hours` under
100 hours or 7 days, `narrow_span` when `T_water - T_room` spans under 5 K) or
`credible`. `table` gives, for supply temperatures across the allowed setpoint range
(`setpoint_min_c`..`setpoint_max_c`: its ends and every 5 K between), the expected
steady heat into the house `heat_w` (`low_w`..`high_w` from the band of `K`) with the
mean water temperature it implies, `Q = K (T_s - T_room) / (1 + K / 2W)` with `W` the
loop's heat per K of spread at the mean measured flow `flow_l_min` (without flow data
the mean water is the supply), next to `loss_now_w` (`now.loss_w`) and `margin_w` =
`heat_w - loss_now_w`. `balance_supply_c`/`balance_mean_water_c` is the water
temperature at which the heat equals the loss now (`null` without both fits or when the
house needs no heat), `balance_in_range` whether it lies in the setpoint range. These
are **steady-state** figures: an under-floor system takes hours to reach them after a
change, so they say where the house settles, not what the next hour brings.

**`by_weather`**: per 2 K bin of the daily outside mean (`from_c` included, `to_c` not),
coldest first, over complete days with at least 80 % loop-heat data and no wood stove:
`days`, `heat_w` (mean loop heat), `electric_w` (mean `Heat_Power_Consumption`, `null`
without data) and `cop` = heat / electricity on the days with both. Unlike
`insight/daily`, which uses the pump's own heat estimate, the heat here is the measured
loop heat, so the COP can differ. `few_days`: fewer than 3 days in the bin.

## Shadow mode and the supervised trial

### `GET api/v1/shadow/divergence?from=<iso>&to=<iso>&step=<s>&threshold_k=1.0` (read)

What ovenbird would set against what the pump runs: per minute, ovenbird's setpoint
from the decision journal (a decision is carried for at most two control intervals)
against the 1 min rollup of `main/Z1_Water_Target_Temp` (its last value). A minute
without either is a gap: not compared, never counted as agreement. `writer` is
`ovenbird` when the pump's value equals the last *verified* `water_setpoint` command,
otherwise `other` (Node-RED, the pump panel, the envelope rule; their writes are not
journalled). Default window the last 24 h, at most 31 days (`400`); `step` 60, 300,
900 or 3600 (default the finest with at most 1,500 points).

```json
{"from": "...", "to": "...", "step": 60, "threshold_k": 1.0,
 "timezone": "Europe/Amsterdam", "signal": "main/Z1_Water_Target_Temp",
 "summary": {"minutes": 1440, "compared_minutes": 1402, "gap_minutes": 38,
             "coverage": 0.974, "mean_abs_k": 0.41, "max_abs_k": 3.0, "bias_k": -0.12,
             "hours_over": 1.5, "episodes": 2, "longest_episode_min": 55},
 "days": [{"date": "2026-01-17", "from": "...", "to": "...", "...": "as summary"}],
 "episodes_total": 2,
 "episodes": [{"start": "...", "end": "...", "minutes": 55, "max_abs_k": 3.0,
               "max_diff_k": -3.0, "ovenbird_c": 31, "pump_c": 34.0,
               "reason": "curve", "reason_at_max": "room_trim", "mode": "shadow",
               "writer": "other", "ended_by": "converged"}],
 "series": {"at": ["..."], "ovenbird": [31], "pump": [34.0], "diff": [-3.0],
            "max_abs": [3.0], "writer": ["other"], "mode": ["shadow"]}}
```

An episode is a run of minutes with `|ovenbird - pump| > threshold_k`; `ended_by`
`converged`, `gap` (data stopped) or `open` (still running). `episodes` holds the
newest 500. `diff` is `ovenbird - pump` (negative: ovenbird would run cooler). Every
episode carries `explained`: `null`, or `{"note", "by", "at", "start"}` when an admin
marked it (an explanation covers the episode whose minutes contain its `start`).

### `POST api/v1/shadow/episodes/explain` (admin)

Body `{"start": "<the episode's start, ISO 8601 with zone>", "note": "<at most 500
characters>"}` marks the episode as explained (the checklist's `divergence` item then
no longer counts it); `{"start": "...", "explained": false}` removes the mark. Kept in
`config.db` (at most 500 marks), audited `divergence_explain`. `200`
`{"explained": {"start", "start_ts", "note", "by", "at"} | null}`; `400` without a
`start` or (when not removing) a `note`.

### `GET api/v1/trial/status?from&to&baseline_from&baseline_to` (read)

The go-live checklist and the trial summary, computed from live facts on every call.

```json
{"at": "...", "mode": "shadow", "configured_mode": "shadow", "ready": false,
 "ready_for_cutover": false,
 "not_ready": [{"id": "shadow_days", "message": "9.2 of 14 days in shadow"}],
 "counts": {"ok": 6, "warn": 3, "fail": 1},
 "groups": {"go_live": {"ready": false, "counts": {"ok": 5, "warn": 2, "fail": 1},
                        "ids": ["shadow_days", "...", "pump_snapshot"]},
            "trial": {"ready": false, "counts": {"ok": 1, "warn": 1, "fail": 0},
                      "ids": ["envelope_proof", "rollback_rehearsal"]}},
 "checklist": [{"id": "shadow_days", "phase": "go_live", "status": "warn",
                "message": "9.2 of 14 days in shadow",
                "evidence": {"days": 9.2, "required_days": 14.0, "first": "...", "last": "...",
                             "journal_days": 90}}],
 "summary": {"source": "go_live", "state": "running", "days": 2.4, "min_days": 7.0,
             "trial": {"from": "...", "to": "...", "days": 7.0, "room_mean_c": 20.9,
                       "room_min_c": 20.1, "room_hours": 167.5, "outside_mean_c": 4.1,
                       "runs": {"...": "as insight/runs total"}, "pump_errors": 0,
                       "writes": 84, "writes_per_day": 12.0,
                       "setpoint_changes_per_day": 13.1},
             "baseline": {"...": "the same for the baseline period"},
             "criteria": [{"id": "room_mean", "trial": 20.9, "baseline": 21.0,
                           "delta": -0.1, "limit": 0.5, "status": "ok"}],
             "criteria_met": true, "met": false}}
```

Checklist (`status` `ok`/`warn`/`fail`, each `message` says what is missing). Two
groups (`phase`): `go_live`, everything that can be done in shadow (`ready` when all
of them are `ok`; `not_ready` lists the rest with their messages), and `trial`, what
can only be shown once ovenbird controls (`ready_for_cutover` when every item is `ok`).
`counts` covers all items.

| id | phase | ok when |
|---|---|---|
| `shadow_days` | go_live | at least 14 days in shadow in the decision journal (ticks, gaps not counted) |
| `divergence` | go_live | the last 14 days compared with at least 80 % coverage and no episode of 120 min or longer that is not marked as explained (`shadow/episodes/explain`; unexplained ones are `warn`); `fail` without data |
| `envelope_rule` | go_live | declared installed (`OVENBIRD_ENVELOPE_RULE_INSTALLED`) |
| `notifications` | go_live | the notifier's `health.state` is `ok` (the same verdict as `notifications/status`; `fail` when `failing` or not configured, `warn` when `untested`) and the dead-man ping configured, succeeding and not held back |
| `release_plan` | go_live | a dry rehearsal (or a real one) planned or restored every setting (`outcome: ok`) |
| `alarms` | go_live | no active alarm (`warn` with warnings, `fail` with a critical one) |
| `room` | go_live | the room value is fresh, plausible and at full authority |
| `pump_snapshot` | go_live | an armed, complete snapshot that is not stale (captured in shadow, or the go-live one) |
| `envelope_proof` | trial | the envelope rule seen correcting the pump while ovenbird is the only controller (`state: proven`) |
| `rollback_rehearsal` | trial | the last real rehearsed release restored everything within 300 s |

Trial summary: the trial period defaults to the go-live snapshot (origin `go_live`;
a snapshot captured in shadow does not count) until now (or until a complete release;
at most 30 days; `source: go_live`), else the last 7 days (`default`); `from`/`to`
override (`query`). The baseline is the same length right before it, or
`baseline_from`/`baseline_to`. Criteria: `room_mean` (|delta| ≤ 0.5 K), `room_min`
(info), `short_runs` (the share of compressor runs under 20 min not above the
baseline's), `pump_errors` (0 raised `pump_error` alarms), `writes_per_day` (sent
commands, at most `OVENBIRD_COMMAND_DAILY_BUDGET`), `setpoint_changes_per_day` (info:
changes of the pump's water target, the comparable figure for a controller whose
writes are not journalled). A criterion without data is `unknown`; `criteria_met` when
all are `ok` or `info`. `state`: `no_trial` (no go-live: the default period compares
the previous controller with itself), `running` (`days` below `min_days`, 7),
`ended_early` (released before that), `complete`, or `not_a_trial` (a queried period
outside the go-live snapshot's trial). **`met` is true only when `state` is
`complete` and `criteria_met`**; show "the cut-over criteria are met" only then.

### `GET api/v1/insight/runs?days=7` (read)

Compressor run lengths per local day from the 1 min rollups of `main/Compressor_Freq`
(the running rule of `insight/daily`); a run touching a gap or the end of the data is
`censored` and left out; off time only between two complete runs. `days` 1..90.

```json
{"timezone": "Europe/Amsterdam", "short_run_min": 20.0, "signal": "main/Compressor_Freq",
 "total": {"runs": 41, "censored": 1, "short_runs": 6, "short_share": 0.146,
           "median_min": 48.0, "mean_min": 61.3, "longest_min": 240.0, "min_off_min": 12.0,
           "histogram": [{"from_min": 0, "to_min": 10, "runs": 2}, "...",
                         {"from_min": 240, "to_min": null, "runs": 1}]},
 "days": [{"date": "2026-01-17", "from": "...", "to": "...", "partial": false,
           "...": "as total"}]}
```

## Replay

What ovenbird would have sent over a recorded period with a chosen configuration
(replay level 1: exact and model-free). Every stored decision of the period is stepped
again from its `inputs_used`, in one pass with two controllers: one with the **chosen
configuration** (the active one, a stored version, or a draft on top of the active
one), started from the recorded controller state just before the period, and one per
tick with **the tick's own version** (the identity check). **Open loop**: the house
followed the recorded control, so a replay makes no comfort or energy claim; it shows
what ovenbird would have *sent*, next to what it recorded and what the pump actually
had (`main/Z1_Water_Target_Temp`, as in `shadow/divergence`).

A period is at most the decision retention plus a day (`history_decision_days`; at most
92 days, also when decisions are kept forever). A replay runs as a job in a worker thread,
one at a time: starting a new one cancels the one still running. On a developer laptop
30 days (43,200 decisions) take about 13 s; slower hardware takes proportionally longer,
hence the job and its progress.

### `GET api/v1/replay/coverage?from=<iso>&to=<iso>` (read)

Where stored decisions exist, for the period picker. Default window: the longest period
ending now.

```json
{"from": "...", "to": "...", "timezone": "Europe/Amsterdam", "interval_s": 60.0,
 "retention_days": 30.0, "max_days": 31.0,
 "oldest": "2026-10-25T00:01:00Z", "newest": "2026-11-24T10:15:00Z",
 "days": [{"date": "2026-11-23", "from": "...", "to": "...", "decisions": 1438,
           "expected": 1440, "first": "...", "last": "..."}],
 "versions": [{"version": 11, "from": "...", "to": "...", "decisions": 20160}]}
```

`expected` is the day's length divided by the control interval; `version` `null` marks
decisions from before the configuration store.

### `POST api/v1/replay` (operate)

Body `{"from": "<iso>", "to": "<iso>", "config": "active" | "version" | "draft",
"version": <n>, "changes": {"field": value}, "threshold_k": 1.0, "step": 60}`:
`version` with `"config": "version"`, `changes` (validated like `config/validate`, on
top of the active configuration) with `"draft"`; `threshold_k` (above 0, at most 20) and
`step` (60, 300, 900 or 3600; default the finest with at most 1,500 points) are optional.
`202` with the job (below, `state` `running`); `400` for a missing or too long period, an
unknown `config`, a draft that does not validate, a bad `step` or `threshold_k`; `404` for
an unknown or no longer valid version; `409` for `version`/`draft` without a
configuration store.

### `GET api/v1/replay/{id}` (read)

The job: `phase` (`replay`, `compare`, `done`) and `progress` (0-1) while `running`, then
`done` with the `result`, `failed` with an `error`, or `cancelled`. A finished job is kept
for an hour or until the next replay starts (`404` after).

```json
{"id": "9f2c...", "state": "done", "phase": "done", "progress": 1.0,
 "from": "...", "to": "...",
 "config": {"kind": "draft", "version": 11, "changes": {"control_comfort_c": 21.8}},
 "started_at": "...", "finished_at": "...", "error": null,
 "result": {
   "from": "...", "to": "...", "config": {"...": "as above"},
   "ticks": 43200, "skipped": 0, "open_loop": true, "threshold_k": 1.0, "step": 3600,
   "timezone": "Europe/Amsterdam", "signal": "main/Z1_Water_Target_Temp",
   "identity": {"ok": true, "ticks": 43200, "mismatches": 0, "first_mismatch": null,
                "unknown": 0,
                "versions": [{"version": 11, "ticks": 43200, "mismatches": 0,
                              "first_mismatch": null}]},
   "summary": {"minutes": 43200, "compared_minutes": 43010, "gap_minutes": 190,
               "coverage": 0.996, "mean_abs_k": 0.6, "max_abs_k": 4.0, "bias_k": 0.3,
               "hours_over": 21.5, "above_pump_min": 900, "below_pump_min": 390,
               "differs_recorded_min": 5200, "above_recorded_min": 5100,
               "below_recorded_min": 100, "mean_diff_recorded_k": 0.2,
               "changes_recorded": 610, "changes_replayed": 655, "changes_pump": 580,
               "writes": 655, "writes_per_day": 21.8, "max_writes_day": 34,
               "days_over_budget": 0, "budget": 150, "budget_use": 0.227,
               "sent_recorded": 0, "share_safety_clamped": 0.04,
               "share_feedback_limited": 0.0,
               "ladder": {"schedule_curve_feedback": 0.99, "curve_only": 0.01},
               "reason": {"room_feedback": 0.51, "deadband_hold": 0.38},
               "binding": {"deadband": 0.38, "safety_min": 0.05},
               "episodes": 12, "longest_episode_min": 95},
   "days": [{"date": "2026-11-23", "from": "...", "to": "...", "writes": 22,
             "changes_recorded": 20, "sent_recorded": 0}],
   "episodes_total": 12,
   "episodes": [{"start": "...", "end": "...", "minutes": 95, "max_abs_k": 4.0,
                 "max_diff_k": 4.0, "ovenbird_c": 36, "pump_c": 32.0,
                 "recorded_c": 35, "reason": "room_feedback",
                 "reason_at_max": "room_feedback", "mode": "shadow", "writer": "other",
                 "ended_by": "converged"}],
   "series": {"at": ["..."], "recorded": [35], "replayed": [36], "pump": [32.0]},
   "limitations": [], "run_s": 12.9}}
```

- Minutes follow `shadow/divergence`: a decision's setpoint is carried for at most two
  control intervals, a minute without the pump's 1 min rollup is a gap. `series` holds
  the last value per `step` of the recorded setpoint, the replayed one and the pump's.
  `recorded`, `replayed` and an episode's `ovenbird_c` and `recorded_c` are the setpoints
  as issued, whole degrees; the value before rounding is never part of the result (a
  decision's `record` keeps it).
- `identity`: each tick stepped with the settings of its own version must reproduce
  its recorded setpoint; it re-seeds where the version changes and follows restarts as
  the preview does. `ok` is `null` when no tick could be compared (`unknown` counts
  ticks of a version without valid settings or not replayable). `ok: false` means the
  replay is an indication only.
- `summary`: against the pump (`compared_minutes`, `coverage`, `mean_abs_k`,
  `max_abs_k`, `bias_k`, `hours_over`, `above_pump_min`/`below_pump_min` with the
  replayed setpoint more than `threshold_k` above or below the pump's target) and
  against the recording (`differs_recorded_min`, `above_recorded_min`,
  `below_recorded_min`, `mean_diff_recorded_k`); setpoint changes of the recording,
  the replay and the pump; `writes` are the replayed setpoint's changes (the writes
  ovenbird would make once the pump follows it), `max_writes_day` and
  `days_over_budget` against the daily write budget (`budget_use` the busiest day's
  share); `sent_recorded` counts ovenbird's own `sent` water-setpoint commands of the
  period; ladder, reason and binding-constraint shares of the replayed ticks.
- `episodes`: runs of minutes with the replayed setpoint more than `threshold_k` from
  the pump's target (newest 500), with the replayed reason and the recorded setpoint
  at the largest difference (`recorded_c`).
- `limitations`: as in `config/preview`.

### `POST api/v1/replay/{id}/cancel` (operate)

Body `{}`. Asks a running job to stop (it ends `cancelled` within a batch of
decisions); returns the job. `404` for an unknown or expired job.

## Release control

### `GET api/v1/control/snapshot` (read)

The pump state recorded at go-live (the first `auto` tick with publishing permitted,
before anything is sent; again after a complete release, and in place of a snapshot
captured in shadow). A value that was not fresh is filled in at the first tick where it
is.

```json
{"snapshot": {"taken_at": "...", "origin": "go_live", "by": null,
              "previous_mode": "shadow", "own_values_possible": false,
              "register": "setcurves_target_high", "complete": true, "released_at": null,
              "outside_c": 4.5, "age_s": 86400.0, "stale": false, "stale_after_s": 2592000.0,
              "items": [{"kind": "water_setpoint", "signal": "main/Z1_Water_Target_Temp",
                         "value": 32}, {"kind": "max_pump_duty", "...": "..."}],
              "facts": {"main/Heating_Mode": 1.0, "main/Z1_Curve_Target_High_Temp": 40.0}},
 "armed": true, "publishing": true, "can_capture": false, "capture_refusal": "in_use"}
```

`own_values_possible` warns that the snapshot was taken right after a restart in `auto`
(the values may already be ovenbird's). `armed`: a release would use it (an incomplete
release does not use it up). `origin`: `go_live` or `manual` (captured by an admin in
shadow; `by` names who, without the address). `outside_c` the outside temperature when
it was taken, `age_s` its age, `stale` after 7 days (`manual`) or 30 days (`go_live`).
`capture_refusal` says why `POST control/snapshot` would be refused now.

### `POST api/v1/control/snapshot` (admin)

Body `{}`. Captures a snapshot from the pump's current values while ovenbird does not
control (shadow, paused, off), to rehearse against before go-live; the go-live records
its own and replaces it. `200` with the body of `GET control/snapshot`. `409` with
`detail.code`: `controlling` (ovenbird writes, so the values may be its own),
`in_use` (an armed go-live snapshot has not been restored yet), `in_progress` (a
release runs). Audited `snapshot_capture`.

### `POST api/v1/control/release` (admin)

Hands control back: the pause is stored first (with `synchronous = FULL`, so a restart
or a power cut comes back paused; when it cannot be stored nothing changes and the
answer is `503 storage_failed`), the controller stops (the loop runs as `shadow`,
`control.releasing: true`, `resume` is `409`), and every snapshot value that differs
from what the pump reports now is restored through the command adapter: the same
allowlist (`water_setpoint`, `max_pump_duty`, `quiet_mode`), clamps, spacing, budget
and verification as every command, refused during a hold (a safety hold allows only
lowering the setpoint). The water setpoint is also kept inside the envelope band at
the current outside temperature (`clamped` says so), so the HeishaMon rule does not
rewrite it at once. A setting with one of ovenbird's own commands still in flight is
always restored after that command has settled (`waited_for`). Settings ovenbird does
not manage are left alone. When every item has settled and nothing is in flight, the
pump's values are read once more (an item no longer at its target ends `changed`), or
the timeout passes, and the pause takes effect. Only an `ok` release uses up the
snapshot; after an `incomplete` one it stays armed, so a resume keeps it and the next
release restores the same values. The run is stored when it starts and at every step:
after a restart in the middle it reads `outcome: interrupted` and the alarm
`release_interrupted` (warning) is raised until a release finishes ok or control is
resumed.

Request `{}` or `{"rehearsal": true, "reason": "<at most 200 characters>"}`;
`{"rehearsal": true, "dry": true}` is a **dry rehearsal**: it plans the release against
the snapshot (targets after the clamps, refusals, settings already in place) without
sending, storing a pause or using up the snapshot, also in shadow; it counts for the
`release_plan` checklist item, a real rehearsal for `rollback_rehearsal`. `202` while
restoring, `200` when nothing had to be sent (always for a dry rehearsal):

```json
{"release": {"started_at": "...", "finished_at": null, "done": false, "outcome": "running",
             "rehearsal": true, "dry": false, "by": "admin: drill", "reason": "drill",
             "paused_before": false, "duration_s": 0.0, "within_limit": true,
             "snapshot_taken_at": "...", "snapshot_origin": "go_live",
             "snapshot_age_s": 86400.0, "outside_c": -12.0, "interrupted": false,
             "items": [{"kind": "water_setpoint", "snapshot": 30, "before": 35,
                        "target": 33, "clamped": "clamped from 30 to the envelope band 33-40 at -12 °C outside",
                        "waited_for": null, "status": "queued", "ok": false,
                        "detail": "...", "at": "..."}]},
 "control": {"...": "as decisions/latest control, releasing true"}}
```

Item `status`: `queued`, `sent`, `retry`, then `verified`, `unchanged`, `not_managed`,
`planned` (dry) (the good ends) or `missing`, `refused`, `failed`, `dropped`,
`timeout`, `changed`. `outcome` `running`, `ok`, `incomplete` or (read back after a
restart) `interrupted`. `by` is the actor without the client address. Refusals with
`detail.code`: `409` `in_progress`, `not_publishing` (shadow or commands not allowed;
not for a dry rehearsal), `reset_pending`, `no_snapshot`; `503` `storage_failed`.
Commands journal with `detail` starting `release: <actor>: `.

### `GET api/v1/control/release` (read)

`{"release": <the running or last run>, "last_rehearsal": <run or null>,
"last_dry_rehearsal": <plan or null>, "timeout_s": 252.0}`, kept across restarts.

## Notifications

Configured only by environment or options file (never the configuration store):
`OVENBIRD_NOTIFY_NTFY_URL` (no credentials, query or fragment), `_NTFY_TOPIC`,
`_NTFY_TOKEN`, `_MIN_SEVERITY`, `_EVENTS`, `_LANGUAGE` (`en`/`nl`), `_DEADMAN_URL`
(`https` unless `_DEADMAN_ALLOW_HTTP`), `_DEADMAN_INTERVAL_S` (see the service README).

Per alarm the notifier keeps what the phone was told (kept across restarts) and one
message still to deliver: a raise is sent at once, a clearing once the alarm has stayed
clear for `clear_hold_s` (600 s), so a flapping alarm sends one raise and never ends
as "resolved" while it is active; a raise after a sent clearing is never dropped; an
alarm that came and went before its raise could be delivered is sent once as "came and
went". At start the active alarms are replayed. Failed sends are retried with back-off
(30 s doubling to 15 min; warning and critical until delivered or superseded). Rate
limits per hour are per severity (`rate_limits`; critical has its own budget, clearings
and events count as info); an alarm over the limit waits (`deferred`), an event is
dropped (`suppressed`). Titles and bodies are human-readable in `_LANGUAGE`: the
alarm's name, then the severity, "You:" what to do, what ovenbird does, and the
service's details.

### `GET api/v1/notifications/status` (read)

```json
{"ntfy": {"configured": true, "server": "ntfy.sh", "token": true, "min_severity": "warning",
          "events": false, "language": "en", "sent": 3, "suppressed": 0, "dropped": 0,
          "deferred": 0, "retries": 0, "queued": 0,
          "last_sent": {"at": "...", "title": "ovenbird · Low flow"},
          "last_error": null,
          "last_test": {"at": "...", "ok": true, "error": null, "by": "admin"},
          "rate_limit_per_hour": 20,
          "rate_limits": {"critical": 30, "warning": 20, "info": 20},
          "clear_hold_s": 600.0, "test_spacing_s": 30.0},
 "deadman": {"configured": true, "server": "hc-ping.com", "interval_s": 300, "pings": 288,
             "last_ok": "...", "last_error": null, "last_skip": null,
             "healthy": true, "unhealthy_reason": null},
 "health": {"state": "ok", "reason": null, "failing_since": null, "failures_in_row": 0,
            "pending": [], "deadman_state": "ok"}}
```

Never the topic, the token or the dead-man URL; only the server host names. Errors are
redacted before they are shortened; `last_test.by` is the actor without its address.
`health` is the single verdict the System tile and the checklist's `notifications` item
both use: `state` `not_configured`, `untested` (no test and nothing delivered yet),
`ok`, or `failing` (the last send failed, or the last test failed and nothing was
delivered since; `reason` says why); `pending` the alarm codes not yet delivered;
`deadman_state` `not_configured`, `waiting` (no ping yet), `ok`, `failing`, `skipped`
(held back because the service is unhealthy: `last_skip`). `last_sent`, `last_error`
and the failure count survive restarts. After 3 failed sends in a row the alarm
`notify_failing` (warning, never sent itself) is raised; the next delivered message
clears it.

### `POST api/v1/notifications/test` (operate)

Body `{}`. Sends a test message now; `200` `{"test": <last_test>, "status": <as above>}`
(also when sending failed: `test.ok` false with a redacted `error`). At most one test
per 30 s and 10 per hour, its own limit (it never uses the alarms' budget): `429`
`{"detail": {"code": "test_rate", "message": "...", "retry_after_s": 12}}` with
`Retry-After`. `409` without ntfy. Audited `notify_test`. Operate rather than admin so
the Home Assistant integration can test the channel; the limit keeps a misused token
from exhausting the ntfy quota.

## Data

What `history.db` holds, how large it is and how to take it out. The series and journal
exports and the yearly archive's list are open to the `read` role, like `history` and
`decisions`; compaction, the archive and the yearly archive's downloads and deletion need
`admin`.

`history.db` keeps raw samples (on change), 1 min, 15 min and 1 h rollups per signal,
the journals (decisions, commands, alarms) and the issued forecasts. A decision row
keeps its JSON texts deflated in one BLOB with a per-database dictionary (an earlier
decision; a new one each day), about an eighth of the plain text; the API returns the
texts unchanged. Retention per resolution is a setting (Settings → Data). Rows freed by
retention go back to the file system by incremental vacuum; a database from before this
format is compacted once at start (when a quarter or more of it is free pages) or with
`POST api/v1/history/compact`. The backup snapshot `history.snapshot.db` is a full copy,
so the data directory holds about twice the database size.

### `GET api/v1/history/signals` (read)

Every signal with stored history and its range per resolution (`step` 0 is raw, else
the rollup step in seconds; `points` the stored rows; resolutions without data are left
out).

```json
{"signals": [{"id": "main/Outlet_Temp", "unit": "°C", "kind": "number",
              "resolutions": [{"step": 0, "first": "...", "last": "...", "points": 18000},
                              {"step": 60, "first": "...", "last": "...", "points": 57600}]}]}
```

### `GET api/v1/history/storage` (read)

Sizes in bytes and the projection at the retention in effect.

```json
{"files": {"database": 152027136, "wal": 4128, "snapshot": 152027136, "free": 51539607552},
 "tables": [{"name": "rollup", "bytes": 78610432, "rows": 2662741},
            {"name": "rollup_step_bucket", "bytes": 34877440, "rows": null}],
 "resolutions": [{"id": "raw", "retention_days": 14.0, "rows": 185553, "oldest": "...",
                  "newest": "...", "bytes": 4739072, "bytes_per_day": 116542.7}],
 "projected_bytes": 267002601, "growth_bytes_per_year": 78329328,
 "reclaimable_bytes": 0, "auto_vacuum": "incremental",
 "presets": [{"id": "short", "values": {"history_raw_days": 7.0, "history_1m_days": 31.0,
                                         "history_15m_days": 366.0, "history_1h_days": 0.0,
                                         "history_decision_days": 31.0},
              "projected_bytes": 98123456, "growth_bytes_per_year": 4500000}],
 "preset": "standard",
 "compaction": {"pending": false, "running": false, "last_at": "...",
                "freed_bytes": 223551488, "error": null}}
```

- `resolutions`: `raw`, `60`, `900`, `3600`, `journal` (decisions, commands, alarms;
  `history_decision_days`; the command-hold rows since the last release stay whatever
  their age, so a restart still knows a latched hold and its escalation count) and `forecast` (follows the 1 h retention). `retention_days`
  null keeps it forever. `bytes` splits the rollup table over the steps by rows;
  `bytes_per_day` is the size over the time the data covers (null under an hour).
- `projected_bytes`: the size once every limited resolution is full (its daily rate ×
  its days) plus what is kept forever at its present size and the indexes and small
  tables; `growth_bytes_per_year` what the forever-kept resolutions add per year.
- `presets`: the simple retention choices of Settings → Data with their values (`0`
  keeps forever) and the same projection at their retention: `short` (a month of
  detail: raw 7, 1 min 31, 15 min 366 days, 1 h forever, decisions 31), `standard` (the
  defaults: raw 14, 1 min 90, 15 min and 1 h forever, decisions 30), `long` (a year of
  detail: raw 31, 1 min 366, 15 min and 1 h forever, decisions 366) and `unlimited`
  (everything forever). `preset` is the one the retention in effect matches, `null` for a
  custom combination.
- `tables` and the byte figures are empty/null where SQLite lacks the `dbstat` table.
- `reclaimable_bytes`: free pages inside the file; `auto_vacuum` `none` until the first
  compaction, `incremental` after it (and for databases created since).
- `compaction` is null when the service runs without a history writer. The figures are
  cached for 30 s.

### `POST api/v1/history/compact` (admin)

Body `{}`. Asks the history writer to rebuild the file (`VACUUM`, switching it to
incremental auto-vacuum) between two batches; writes queue meanwhile (seconds for a few
hundred MB) and the backup snapshot is refreshed afterwards. It needs free space of twice
the database plus `history_min_free_mb`, else `compaction.error` says so. Answers `202`:

```json
{"accepted": true, "compaction": {"pending": true, "running": false, "last_at": null,
                                  "freed_bytes": null, "error": null}}
```

`accepted` is false while one is pending or running. Audited as `history_compact`.
`409` when the service writes no history.

### `GET api/v1/export/series?signals=<ids>|all&from=<iso>&to=<iso>&step=raw|60|900|3600&layout=long|wide&format=csv|ndjson` (read)

Signal history as a streamed download, read a UTC day at a time; no cap on signals,
points or range (the range is clamped to the data present, so an open range is cheap).
`signals` is a comma-separated list or `all` (default; every stored signal, by id); an
id without stored history is `400`. `from` defaults to the beginning, `to` to now;
`step` defaults to `900`.

- `layout=long` (default): one line per value. CSV columns
  `at,signal,unit,value` (raw) or `at,signal,unit,value,min,max` (rollups); NDJSON
  objects with the same keys.
- `layout=wide`: one line per time, a column per signal in request order (CSV header
  `at,<id>,<id>,...`; NDJSON `{"at": "...", "values": {"<id>": 21.5}}`). Raw lines are
  sparse: a cell is filled only where that signal changed.

Raw values are the stored changes, the first preceded by the value each signal held at
`from` (as in `history`); rollup values are the time-weighted mean (numbers) or last
value (enums, flags) of each bucket that has data, `at` its start; empty buckets are left
out. Values are rounded to 4 decimals. Media type `text/csv; charset=utf-8` or
`application/x-ndjson`, `Content-Disposition: attachment;
filename="ovenbird-series-<step>-<layout>-<from>.<format>"`, `Cache-Control: no-store`;
with `Accept-Encoding: gzip` the body is gzip-encoded (`Content-Encoding: gzip`). CSV
cells get the formula guard of the CSV exports.

### `GET api/v1/export/journal/{kind}?from=<iso>&to=<iso>&format=csv|ndjson` (read)

`kind` is `decisions`, `commands`, `alarms` or `forecast`; every row in the window,
oldest first, streamed a few hundred rows at a time (no row cap). `from` defaults to the
beginning, `to` to now. CSV columns as in the CSV exports above; `forecast` has
`issued_at,target_at,temp_c,radiation_wm2,cloud_pct,wind_ms` (window on the issue
time). NDJSON lines are the API objects of `decisions` (with the full `record`, which the
CSV leaves out), `commands` and `alarms`. Headers and gzip as for `export/series`.

### `GET api/v1/export/archive` (admin)

A zip download (`ovenbird-archive-<time>.zip`) with:

- `history.db`: a fresh copy of the whole history database made with SQLite's online
  backup (consistent while the writer runs; open it with any SQLite tool);
- `config.json`: the configuration export (`GET api/v1/config/export`: stored values and
  the effective non-secret settings; passwords and tokens are never in it);
- `manifest.json`: `{"ovenbird_archive": 1, "app_version", "created_at",
  "history_schema", "range": {"from", "to"}, "signals": [{"id", "unit", "kind"}],
  "files", "source", "notice"}`.

**Privacy:** the archive (like any export of the series) reveals occupancy: weeks of room
temperatures, heating and hot-water use show when the house is lived in, heated or
empty, and signal ids name Home Assistant entities. Share it with care. It is built in
the data directory (needs twice the database size free, else `507`), one at a time
(`409` while another is built), and the temporary files are removed after the download.

### Yearly archive

With `history_archive_enabled` (on by default; Settings → Data or System → Data) every
calendar month, in the installation's time zone (`control_timezone`), is frozen into
`archive/YYYY-MM.zip` in the data directory, independent of the retention: a zip of the
export archive's form (`history.db`, `config.json`, `manifest.json`) whose `history.db`
holds the month's 1 min, 15 min and 1 h rollups, decisions (packed, with their
dictionaries), commands, alarms, the forecasts issued in it and the signal table (no raw
samples; same schema, so the tools that read an archive's `history.db` read it).
`config.json` is the export form (`version` and `values` of the last version) plus
`versions`: every configuration version the month's decisions ran with, applied in it or
active at its start.

**Freeze timing.** A month is built progressively in its working copy
`archive/YYYY-MM.db`: between two writer batches, every 15 minutes, the history writer
copies what `history.db` gained (rollup buckets once they have ended, journal rows
10 minutes after they were written) and copies the last 6 hours again (a rollup bucket
still changes while a held value is integrated). Every `history_*_days` retention is at
least one day, so data reaches the archive long before retention removes it; after a
start, or when the archive is switched on, it catches up oldest first in short steps while
retention waits. Six hours after a month has ended it is frozen: zip written to a
temporary file, synced and renamed, then the working copy removed (a crash leaves one or
the other, never a torn file). Months the live history still holds are caught up as far
as it reaches; what retention had already removed shows in the manifest as missing days.
A month without any data is not written. The working copy and the frozen month leave
out raw samples and the rollup index that only serves retention.

Rows are matched on what they hold, never on `history.db`'s row ids (those are handed
out again once the newest rows are gone, e.g. after a damaged `history.db` was started
afresh): signals by name, rollups by resolution, signal and bucket, decision
dictionaries by creation time and content, decisions, commands and alarms by all their
columns (they get their own ids in the month file), forecasts by issue and target time.

**Freezing in slices.** The zip (deflate level 6) is written 1 MB at a time between
writer batches, within the step's 0.5 s budget, then read back: `manifest.json` and
`config.json` must read back as written and `history.db` is decompressed (CRC checked)
and compared byte for byte with the working copy, which passed SQLite's `PRAGMA
quick_check` before the build. Only then is the zip renamed into place and the working
copy removed; a zip that does not verify is deleted and the freeze starts over, the
working copy kept. Retention waits while a month is being frozen. A full month of 42
signals and a decision per minute (a 142 MB working copy) freezes in some 7 s spread
over about 13 steps, none holding the writer for more than about 1 s.

**Failures.** A failed step (an error, less free space than `history_min_free_mb`) is
retried every 15 minutes and keeps retention waiting, so nothing the archive has not
copied is removed. After 4 failures in a row the warning `archive_failing` is raised
(the message names the error); the next good step clears it. Retention waits at most
**3 days** from the first failure in a row; after that it runs again (logged as an
error) and data it removes before the archive works again is missing from the
archive. `state.error` and `state.behind` show the current state.

**Damage.** A working copy SQLite reports as damaged (not a database, `malformed`, a
failed `PRAGMA quick_check`; checked at every start and before every freeze) is moved
aside to `archive/YYYY-MM.db.corrupt-<time>` and rebuilt from what `history.db` still
holds; days retention already removed are missing from that month. The warning
`archive_rebuilt` says so and clears after 24 hours. The `.corrupt` file is kept for a
manual recovery and can be deleted. A damaged `history.db` itself never touches the
working copy. At start the `.archive-*` folders a crash left behind in the data
directory (downloads being built) are removed.

Size: a harness run of 41 days (42 signals, a decision per minute) gives about 30 MB per
full month, some 390 MB a year: the packed decisions about 60 % of it (they are already
compressed), the rollups the rest.

The month's `manifest.json`: `{"ovenbird_archive": 1, "kind": "month", "period":
"2026-10", "timezone", "from", "to", "frozen", "complete", "archived_to",
"app_version", "created_at", "history_schema", "resolutions": ["60", "900", "3600"],
"coverage": {"60" | "900" | "3600" | "decisions": {"rows", "first", "last", "days",
"missing_days": ["2026-10-01"]}, "commands" | "alarms" | "forecast": {"rows", "first",
"last"}}, "signals", "config_versions", "files", "notice"}`; `complete` means 1 min data
and decisions on every day of the month.

### `GET api/v1/archive` (read)

What the archive holds, newest first.

```json
{"enabled": true, "timezone": "Europe/Amsterdam",
 "state": {"last_run_at": "...", "error": null, "behind": false,
           "archived_to": "2026-11-24T10:05:00Z"},
 "months": [{"period": "2026-11", "state": "open", "bytes": 61865984, "days_total": 30,
             "from": "...", "to": "...", "complete": null, "days": null,
             "decision_days": null, "missing_days": null, "created_at": null,
             "archived_to": "2026-11-24T10:05:00Z"},
            {"period": "2026-10", "state": "frozen", "bytes": 6123456, "days_total": 31,
             "from": "...", "to": "...", "complete": false, "days": 28,
             "decision_days": 28, "missing_days": 3, "created_at": "...",
             "archived_to": "..."}],
 "years": [{"id": "2026", "kind": "year", "period": "2026", "months": ["2026-10"],
            "open_months": ["2026-11"], "of": 12, "bytes": 6123456, "complete": false,
            "first": "2026-10", "last": "2026-10"}],
 "seasons": [{"id": "2026-27", "kind": "season", "period": "2026/27", "...": "as years"}],
 "total_bytes": 67989440, "bytes_per_year": 79820000, "notice": "..."}
```

`state` is `null` without a history writer; `behind` while it catches up, `error` when
the last step failed (it retries every 15 minutes). `open` is the month being built
(its size is the uncompressed working copy). `bytes_per_year` is the frozen months' size
per day with 1 min data times 365 (`null` before the first frozen month). A year or
season lists the frozen `months` its download holds; `complete` when all of them are
there and complete.

### `GET api/v1/archive/months/{month}` (admin)

`month` is `YYYY-MM`. A frozen month is its file (`ovenbird-archive-YYYY-MM.zip`); the
open month is built as it stands (`ovenbird-archive-YYYY-MM-partial.zip`, `frozen`
false in its manifest). `400` for a malformed month, `404` for one not in the archive.

### `GET api/v1/archive/years/{year}` (admin) and `GET api/v1/archive/seasons/{season}` (admin)

A calendar year (`2026`) or heating season, August to July (`2026-27`): a zip
(`ovenbird-archive-2026.zip`, `ovenbird-archive-season-2026-27.zip`) of the frozen
months' files as they are plus a combined `manifest.json`: `{"ovenbird_archive": 1,
"kind": "year" | "season", "period": "2026" | "2026/27", "timezone", "from", "to",
"app_version", "created_at", "months": [{"period", "file", "bytes", "complete", "days",
"days_total"}], "missing_months", "coverage": {"months", "of", "first", "last"},
"partial", "notice"}`. A partial year is allowed; `partial` says so and `coverage` how
much it holds. Built in the data directory like the export archive (`507` without the
space, `409` while another is built); `404` when the period has no frozen month.

**Privacy:** as the export archive: the months reveal occupancy. Share them with care.

### `POST api/v1/archive/delete` (admin)

Body `{"period": "2026-10"}` (a month) or `{"period": "2026"}` (every frozen month of a
year). Deleted months are remembered (`archive/state.json`) and never frozen again.
Returns `{"deleted": ["2026-10"], "archive": {...GET archive...}}`; `404` when nothing
frozen matches, `409` for the open month (it can be deleted once frozen), `400` for a
malformed period. Audited as `archive_delete`.

## System

### `GET api/v1/system/about` (read)

```json
{"version": "0.6.0", "api_version": 1, "service_time": "...",
 "timezone": "Europe/Amsterdam", "started_at": "...", "uptime_s": 86400.0,
 "service_starts": 7, "previous_start": "...", "failing_components": {},
 "restored_state": true, "setpoint_register": "setcurves_target_high",
 "control_interval_s": 60.0,
 "control": {"mode": "shadow", "configured_mode": "auto", "interval_s": 60.0, "ticks": 1440,
             "last_tick_at": "...", "publishing": true, "paused": true, "releasing": false,
             "restored_state": true},
 "connections": {"mqtt": {"connected": true, "tls": false, "heishamon_base": "panasonic_heat_pump",
                          "heishamon_alive": true},
                 "ha": {"configured": true, "connected": true}, "integration_token": true},
 "simulation": false, "clock_speed": 1.0,
 "safety_net": {"envelope_rule": {"installed": true, "state": "proven", "count": 1,
                                  "first_at": "...",
                                  "last": {"at": "...", "from_c": 55.0, "to_c": 36.0,
                                           "outside_c": 5.0, "low_c": 33.5, "high_c": 38.5},
                                  "adopted": 0},
                "envelope_now": {"outside_c": 5.0, "low_c": 33.5, "high_c": 38.5},
                "max_supply_c": 45.0, "min_setpoint_c": 24.0,
                "envelope_below_k": 3.0, "envelope_above_k": 2.0,
                "ovenbird_corrections": {"...": "adapter corrections", "total": 0}}}
```

The envelope rule runs on the HeishaMon board; the service cannot see it. `state`:
`not_declared`, `declared` (`OVENBIRD_ENVELOPE_RULE_INSTALLED=true`) or `proven`: a
change of the pump's water target from outside the envelope band (by more than 0.5 K)
to exactly the value the rule writes there that no known writer explains was seen
(ovenbird did not send it in the last 10 min and ovenbird was the only controller:
`auto` with publishing, so never in shadow or while paused, when another controller writes), or
the command adapter recognised the rule correcting ovenbird's own value (an
`envelope_correction` journal entry; one correction seen both ways counts once); kept
across restarts. `adopted` is the adapter's `envelope_corrections` since start (null
without a publishing adapter). `service_starts` counts starts of this data directory.

### `GET api/v1/diagnostics?format=json|zip&items=100` (admin)

A redacted bundle for issue reports (a download): `version`, `about`, `health`,
`config` (`effective`: every setting, secrets as `set`/`unset`), `control`, the newest
`items` (1..1000) `decisions`, `commands` and `alarms`, `notifications`, `release`,
`trial` and `signals`. `format=zip` puts each part in its own `<part>.json`.

Never in it: passwords, tokens, the ntfy topic, the dead-man URL, the audit trail; any
string containing a configured secret value is replaced by `[redacted]`. Removed as
well: `weather_latitude`/`_longitude`, `mqtt_host`, `mqtt_username`, `mqtt_client_id`,
`mqtt_ca_file`, `ha_url`, `admin_username`, `http_allowed_origins`, `command_brokers`,
`config_seed`, `weather_sim_file` (`[removed]` when set), every `by`, `actor`, `user`
and coordinate value (`[removed]`), the actor in command details (`release: [removed]:
…`), every IPv4/IPv6 address in any string (`[address]`) and the data and UI
directories (`<data_dir>`, `<ui_dir>`). What is left: the version, the other effective
settings (curve, limits, room signal and Home Assistant entity ids, HeishaMon base
topic, ports, time zone), health, the journals (values, reasons, alarm messages), the
notification counters with the ntfy and dead-man host names, the release and trial
status (snapshot values, outside temperatures) and the current signals.

## `WS api/v1/ws`

Authenticated like every request, or with a single-use pass from `POST api/v1/live/ticket`
as `?ticket=` (see Roles and request rules).

Server → client messages, JSON:

- `{"type": "snapshot", "data": <snapshot as above>}` — on connect, then at most every 5 s
  when something changed (coalesced; slow clients are disconnected).
- `{"type": "health", "data": <health as above>}` — on change.
- `{"type": "decision", "data": <decision as in api/v1/decisions>}` — after every
  controller tick (coalesced like the others).
- `{"type": "config", "data": {"version": 13, "applied_at": "..."}}` — when a new
  configuration version is in effect (at the first tick after the apply).

Client → server messages are ignored in v1.
