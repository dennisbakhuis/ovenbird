# ovenbird-harness

Fast closed-loop runs of the whole ovenbird service against the simulated plant
(phase 2 of `docs/design.md`). Depends on
`ovenbird-core`, `ovenbird` (service) and `ovenbird-sim`; nothing here touches a
network: the broker is an in-memory stand-in, Home Assistant a fake driven in process.

## B1: stepped full run (`make fullrun`, `make fullrun-faults`)

`python -m ovenbird_harness.fullrun` steps the service's own components on one manual
clock: every 5 s the simulated HeishaMon advances the plant (the example house or a fitted
one) and its publications
go through the real `MqttIngest`; the room temperature and humidity go through a fake
Home Assistant into the real `HaInput` (subscription snapshot, change diffs,
`get_states` re-reads every 5 min with `last_reported`, `unavailable`); the command
worker steps once (adapter tick, publish through the real `CommandLink` and its
guard); the safety monitors run; every 12th cycle the control loop ticks. Controller,
adapter, monitors and alarm board come from `ovenbird.service.build_control`, so
persistence (controller state, write budget, holds) is restored exactly as in the
service. History is written by the real writer thread into `history.db` (live schema).

Default span: the local `RECORDING_FROM` → `RECORDING_TO` (see `capture/README.md`,
"Local settings"), else one example week 2025-11-10 06:00 → 2025-11-17 06:00 UTC, with the example house
(`ovenbird_sim.heishamon.reference`; a fitted plant with `--params` or
`OVENBIRD_REFERENCE_PLANT`), recorded weather
(`capture/captures/weather`) and recorded HA liveness (`capture/captures/datalake`:
the room sensor's `unavailable` periods and the humidity reports). These are local
and git-ignored; without them the run falls back to a synthetic
cold week and modelled humidity reports. The stepper ticks the control loop every
60 s and the monitors every 5 s and refuses settings that ask for other intervals.

Command line flags:

| Flag | Default | Meaning |
| --- | --- | --- |
| `--from`, `--to` | local `RECORDING_FROM`/`RECORDING_TO`, else 2025-11-10T06:00, 2025-11-17T06:00 | simulated span (UTC) |
| `--out` | `capture/captures/fullrun` | output directory (`plain/` or `faults/` below it) |
| `--params` | `$OVENBIRD_REFERENCE_PLANT` | fitted plant (e.g. `capture/captures/models/plant_params.json`); unset or `''` for the example house |
| `--weather-dir` | `capture/captures/weather` | recorded weather; missing: synthetic cold week |
| `--datalake` | `capture/captures/datalake` | recorded HA liveness |
| `--faults` | off | inject every fault scenario |
| `--fault NAME` | none | inject one scenario (repeatable) |
| `--at TIME` | none | start the `--fault` scenarios at `TIME` instead of a slot; without `--from`/`--to` the span is a warm-up day before, the window and a 2 h tail after |
| `--sweep N` | off | run each scenario (`--fault`, or all) alone at `N` start times (see below) |
| `--jobs J` | cores − 2 | worker processes of the sweep |
| `--keep-history` | off | keep `history.db` of passed sweep runs (failed runs always keep it) |
| `--room-via` | `ha` | `ha` (fake Home Assistant) or `mqtt` (board topic) |
| `--room-profile` | `on_change` | `on_change` or `periodic` |
| `--room-crosscheck` | `main/Room_Thermostat_Temp` | plausibility cross-check signal; `''` disables |
| `--comfort` | local `COMFORT_C`, else 21.0 | comfort room temperature |
| `--min-setpoint` | local `MIN_SETPOINT_C`, else 24 | minimum water setpoint |
| `--seed` | 0 | sensor noise seed |
| `--log-level` | `CRITICAL` | level of the service's loggers |

Outputs in `<out>/plain` or `<out>/faults` (default `capture/captures/fullrun`):
`history.db`, `summary.json`, `summary.html` (ladder shares, held-value share, commands
and writes per day against the budget, starts per day, run lengths and the share below
20 min, room mean/min/hours below band, alarms, holds, refusals, fault outcomes,
invariant results, wall time). Exit code 1 on any invariant violation or failed fault
expectation.

### Invariants (`ovenbird_harness.invariants`)

Derived from `ovenbird_core.control.ovenbird` and `ovenbird.control.adapter`, checked on
every stored decision, command event and publish: safety limits and the envelope
(through `SafetyLimits.bounds` and through an independent formula), integers only,
binding named whenever the setpoint differs from the rounded `pre_round` and bypass
bindings that are real (`cycling_floor` only inside the minimum-run window with the
setpoint at the floor, a safety bound only at that bound), deadband and dwell (with the
ramp exceptions), no setpoint decrease and an unchanged integrator and ramp cap in
defrost/DHW, no pump-duty intent, queued or sent command during a defrost
(`max_pump_duty_commands_in_defrost`, always reported), heat pump duty whenever the
compressor runs or DHW is active, integrator clamp, every queued or sent value equal to
the intent of its decision, one command in flight, every sent command verified or
explained, budget, and every publish permitted by the guard, allowlisted, QoS 1, not
retained, spaced, to simulated firmware. Every 5 s the plant is checked too: the setpoint
register is back within the clamp range within 120 s, the outlet stays within the maximum
supply plus 5 K, and the heat duty reaches the board within 90 s of a compressor start
unless commands were blocked (a defrost inside those 90 s suspends the rule, since no duty
command goes out during a defrost; its end, with the compressor still running, starts the
90 s again). A configuration applied through the store is followed from
its first decision (`apply_jump`: that decision changes the setpoint only through the new
deadband and dwell or a hard constraint, and keeps the dwell timer of an unchanged
setpoint). The summary's `observations` count the paths the run exercised (ladder levels,
refusals and holds by reason, bindings, command events, safety corrections, decisions in
defrost and DHW, plant starts checked).

### Fault scenarios (`ovenbird_harness.faults`)

`heishamon_restart`, `broker_drop`, `ha_link_down` (alarm raised and cleared, the room
inside the band, or within one sensor step of the room at the start when that was lower),
`room_sensor_silent` (30 h; `room_sensor_quiet` 8 h after the last proof of life and
`room_sensor_silent` at the 24 h limit, no cooling on the held value from 8 h, the held
positive integrator once stale, the house above the comfort floor in both phases; the
band hours of both phases are reported), `room_sensor_dies_warm` (a reading 1.5 K above comfort, then
nothing for 30 h: the cooling authority follows the proof-of-life and held-time ramps, no
cooling from 8 h, `room_sensor_quiet` at 8 h, the room loses at most 0.8 K from its start
or comfort, whichever is lower, and never reaches the comfort floor; hours below the band
are reported), `foreign_writer` (the alarm clears only with ovenbird's value back in the
board register), `ovenbird_restart` (state and budget restored, also across midnight; no
value the pump already holds is re-sent), `config_apply` (an operator applies comfort
+0.3 K and the 0 °C curve point +1 K through `ConfigManager.apply`, reverted after 6 h: in
effect at the next tick, every decision carries the version, setpoint and dwell timer
carried over, the controller uses the new comfort and curve, versioned and audited),
`pump_setting_write` (an admin writes the heating delta-T: queued, sent, verified,
journalled, audited and counted against that day's budget; a second write during a defrost
is refused, the board reporting one for a single cycle when the plant has none within 2 h;
the original value restored), `command_lost` (from the first command the controller
queues, after 1 h of none an operator comfort +1 K nudge that is reverted afterwards, the
board loses commands until one fails: retries, `verification_failed`, a hold,
nothing sent during it, the alarm clears afterwards), `mode_change` (30 min in
compensation mode:
refusal with `mode_mismatch`), `topic_stale` (`Outside_Temp` silenced 30 min: hold with
`inputs_missing`), `dhw_run` (45 min DHW: integrator frozen, no decrease, heat duty,
narrated), `setpoint_above_max` (a foreign write 5 K above the maximum: safety correction
within 2 min, register back within 3 min) and `ha_reread_fails` (2 h of failing
`get_states`: `ha_link_down`, held values back on the 1800 s limit),
`room_sensor_fails_high` (wood-stove mode on, the room sensor reads 3.7 K high for 8 h
with the step reported at once: taken for a sensor fault within 2 min, no wood-stove
episode, `room_implausible` within the cross-check's sustain time, no cooling feedback
while it holds, the room above the comfort floor, the alarm cleared within 1 h after the
sensor recovers; the `RoomFeed.bias` hook), one per slot after a
warm-up day or at `--at`. Every expectation is `pass` or `fail`; one that cannot be evaluated (for
example no decision held longer than 6 h under `on_change`) fails, and any status other
than `pass` fails the run. The stepped system opens the run's configuration store
(`config.db` next to `history.db`) and builds everything from its effective settings, also
after a restart.

The room device sits behind the `RoomFeed` protocol (`ovenbird_harness.homeassistant`):
`DeviceFeed` runs the shared sensor model (`ovenbird_sim.evaluate.sensors.RoomSensorDevice`,
by default the example send-on-delta device, the recorded install's calibrated one
when the Datalake covers the span) and adds the humidity entity
(recorded reports when the Datalake covers the span, modelled otherwise), the recorded
`unavailable` periods and the fault hooks. The service runs with the
`on_change` profile and the humidity entity as liveness signal (`--room-profile
periodic` for the 1800 s rule).

### Sweep (`--sweep N`, `ovenbird_harness.sweep`)

A scenario that passes at its slot may still fail on a colder night or a milder
afternoon. `--sweep N` runs every scenario (or the `--fault` ones) alone, each in its own
run at `N` start times: the days spread evenly over the span (after a warm-up day, leaving
the window and the tail), the hour of the day stepping by 24/`N` h, so 8 starts cover
00:00, 03:00, …, 21:00 UTC and a range of outside temperatures. Every run has a warm-up day before its start and the window plus a 2 h tail
after it, and runs in a process pool (`--jobs`). Outputs in `<out>/sweep`: one directory
per scenario and start (`summary.json`; `history.db` only of failed runs unless
`--keep-history`), `sweep.json` (every run with its status, failed checks, invariant
violations, notes and the outside temperature over the window) and the matrix on stdout.
Exit code 1 when any run fails. The full sweep (`--sweep 8`, 120 runs) takes about
2.5 min on 10 processes.

## B2: validation against the asyncio/MQTT service (`make fullrun-replay`)

`python -m ovenbird_harness.validate`:

- **exact replay**, twice: runs the assembled service (`build_service`) against the
  simulator through an in-memory broker at 120×, records every inbound message and every
  tick of the loop, worker and monitors with its service-clock instant, replays the stream
  through the stepped components and requires identical decision rows. Once on the MQTT
  path with a periodic room sensor, once on the Home Assistant path: the board's on-change room
  sensor and humidity reach the service through an in-memory Home Assistant WebSocket API
  (`ovenbird_harness.haserver`), and the HA input's sessions, `get_states` requests and
  messages are recorded and replayed too. A tap on a method that no longer exists, or a
  recording without tick, adapter and message events, is an error;
- **statistical** (MQTT path, periodic sensor): KPIs (starts/day, ladder shares, setpoint
  histogram, room mean) of B1 against two real-service repeats over 48 h at 600× (from
  2025-11-10T06:00 on the example house by default), within a
  tolerance set by the spread of the repeats with floors of 0.01 (ladder), 0.02
  (histogram) and 0.02 K (room). Every run must cover at least 48 h, one defrost and 8
  starts (`coverage`).

Flags: `--from`, `--params`, `--weather-dir`, `--out` (default: a new temporary
directory, never `capture/captures`), `--replay-speed` (120), `--replay-seconds` (30),
`--hours` (48), `--speed` (600), `--skip-replay`, `--skip-kpis`, `--log-level`.

## Tests

`uv run pytest packages/harness` runs short versions of all of the above on the
example house and the synthetic cold week (no local data needed), including a cheap
sweep (`mode_change`, `ovenbird_restart` and `pump_setting_write` alone at midnight and at
13:00 UTC). Set `OVENBIRD_HARNESS_LONG=1` for the long variants (the plain full span, the
B2 KPI comparison and the full sweep at 8 start times on the recorded data).
