# Heat-pump controller — clean-slate design (two review rounds merged)

## Context

A Panasonic Aquarea (heating only, via a HeishaMon board on MQTT) is controlled today by a
Node-RED flow. Goal: an **open-source** controller, designed
from scratch, that keeps running when Home Assistant restarts, has its own UI, shows up inside
HA, heats smartly (schedules, weather forecast, dynamic prices, solar pre-heat), and can be
**open-loop runs on recorded data** with every decision explainable. Everything except HeishaMon is
optional and configured in a setup wizard. Existing code in this repo is deleted; `capture/`
stays (recorder deployed; the recording is the modelling and open-loop dataset).

Reviews (2026-11-14): round 1 — security, control/HVAC, software architecture,
reliability/HA platform, energy optimisation/UX; round 2 — Aquarea/HeishaMon practitioner
(checked against HeishaMon's documented and observed behaviour), data scientist, open-source maintainer, red team.

Owner decisions: Python 3.14 + asyncio; Svelte 5 + TypeScript UI; this repository;
production = standalone container (optional HA app); full UI incl. history and house
insight; optional inputs from HA entities by default (MQTT alternative); emitter type is a
setting; rule planner live first, LP optimiser in shadow until it wins; goal is a *better*
controller, not a copy of the existing one. Round-2 decisions: **core control first** (smart features
right after cut-over); **supervised winter trials** this winter with the existing controller on standby;
HA write path via a **custom integration** (MQTT discovery entities stay read-only);
identification experiments **free-float night + setpoint steps** (no live A/B blocks).

## Example installation

The tracked tree describes an example installation, not a real one. The values of the
install a recording was made on stay next to the recording in the git-ignored local
settings (`capture/README.md`, "Local settings") and in a local note under `docs/local/`
(git-ignored).

- House and pump: the simulator's example house (`ovenbird_sim.heishamon.reference`), a
  130 m² semi-detached Dutch house to the building code of the 2000s (UA about 145 W/K,
  time constant about 50 h), underfloor heating downstairs and radiators upstairs, with a
  5 kW Panasonic Aquarea J monobloc (WH-MDC05J3E5).
- Room sensor: `sensor.living_room_temperature` (a Zigbee temperature and humidity sensor
  via HA), sensor profile **`on_change`**: step 0.1 K, no heartbeat, liveness from
  `sensor.living_room_humidity`, silence limit 24 h. With a fixed 1800 s staleness rule
  such a sensor looks stale most of the time; with this profile room feedback stays active.
- Comfort 21.0 °C on that sensor, acceptable down to 0.5 K lower; emitter preset `mixed`;
  minimum water setpoint 24 °C.
- Pump duty on: 159 heating / 102 idle (example values, 50 % and 20 % on the common
  dashboard scale `64 + 1.9 × %`; toggle and values configurable). **During a defrost no
  pump-duty command is sent**: the pump drives its
  own duty then and ignores the setting, and returns to the setting by itself within
  seconds after the defrost (verified on recorded data).
- Stuck-warm rule (phase-2 gate): the room feedback's cooling authority is the smaller of
  a ramp on the proof-of-life age (full to 3 h, zero from 8 h) and a ramp on the held time
  (full to 12 h, zero at the 24 h silence limit); a stale room value keeps a positive
  integrator, fading over 24 h. The plausibility cross-check against
  `main/Room_Thermostat_Temp` is on (latched until the room value has changed and agrees
  with it again).
- **No outcome claims yet.** Counterfactual comparisons on recorded data do not support a
  claim on energy or compressor starts yet: held-out folds still fail, cycling fidelity is
  short and part of the simulated heat lies outside the COP map's joint support. Known events (wood-stove fires, `ovenbird_sim.data.events`) are
  left out of the fits and gates and reported.

## How the current system works (reference)

As seen in the recorded data:
- Pump in **Direct mode** (`Heating_Mode`=1). The existing controller computes the water
  setpoint and writes `SetCurves {"zone1":{"heat":{"target":{"high":N}}}}` (every recorded
  command); `Z1_Heat_Request_Temp` / `Z1_Water_Target_Temp` follow. The stored curve is
  unused.
- The setpoint follows the outside temperature with a correction on the room temperature;
  while the compressor runs most commands are small corrections of it.
- `SetMaxPumpDuty` with a running and an idle value, also sent during defrosts, without
  effect (the pump drives its own duty during a defrost).
- Absent: minimum run times, forecast, prices, PV.
- Pump's own start/stop rule: the flow's comment documents on at inlet ≤ SP − 4 and off at
  outlet ≥ SP + 2 for 3 min. The plant model fits its own start and stop margins per install;
  the example house uses generic inverter values (`ovenbird_sim.heishamon.reference`).

## Supported configurations (v1)

One heating zone, heating only, Direct mode, °C, no buffer tank or mixing valves; tested on
one Aquarea J monobloc first. Not supported in v1: zone 2, cooling, buffer tanks, bivalent/backup
heater logic, DHW optimisation. **DHW**: the controller never writes DHW; DHW runs
(`ThreeWay_Valve_State`) are treated like defrost (all feedback frozen). The wizard reads
`main/*` (`Heat_Pump_Model`, zones, operating mode, buffer) and refuses or warns on
unsupported topology. Capabilities per model are data-driven.

## Core design principles

1. **Direct mode; the controller owns the water setpoint**, as a sum of named terms.
   Register chosen by a phase-0 spike: in Direct mode write `SetZ1HeatRequestTemperature`
   and `SetCurves target.high` and see which `Z1_Water_Target_Temp` follows; prefer the heat
   request register (keeps the stored curve intact). Every write gated on a fresh
   `Heating_Mode` (a "30" in compensation mode means +30 K shift); mode change → hold + alarm.
   HeishaMon does no range check (a `SetCurves` value goes to the pump unchecked), so the adapter sends only
   clamped integers. Write budget per day is a KPI with an alarm (EEPROM wear is unproven
   but cheap to bound).
2. **Fallback = stateless envelope rule on HeishaMon** (rules cannot see MQTT, so no
   heartbeat): a `setTimer` loop computes a conservative curve from `@Outside_Temp` and
   rewrites the setpoint only when it is outside [curve − X, curve + Y] or above the hard
   maximum. Works with WiFi/broker/service down. The core clamps to the same envelope; the
   controller recognises rule corrections via `Z1_Water_Target_Temp` (not a foreign writer),
   checks the rule is alive, and the wizard installs it. Validated in a phase-0 spike.
3. **Single writer**: foreign-writer detection by read-back mismatch (covers another
   controller such as a Node-RED flow, the Panasonic remote, a CZ-TAW1) → hold + alarm;
   broker ACLs as documented hardening. In shadow, the existing controller is the expected
   writer (no alarm).
4. **Pure core, async shell**: `step(state, inputs, now) → (state, commands, decisions)`;
   live, shadow, open-loop run, counterfactual replay and simulation run the same core.
5. **Every decision is explainable** (see Decision record).
6. **Degradation ladder**: optimiser plan → rule plan → schedule + curve + room feedback →
   curve only (room temp stale, e.g. HA restarting) → HeishaMon envelope (service down).
7. **Features follow inputs**: each optional input unlocks features; missing ones degrade.

## Safety limits (emitter-aware)

- Hard max supply temperature per emitter type: screed default 40 °C, wizard warns > 45 °C;
  alarm on `Main_Outlet_Temp` overshoot as well as on the setpoint; docs recommend a
  mechanical floor limit thermostat.
- Flow: alarm on `Pump_Flow` below a model-dependent minimum while the compressor runs;
  docs require at least one always-open loop (closed radiator valves → H62).
- Never `SetHeatpump 0` as a control action (frost); "off" is a low setpoint.
- Defrost and DHW: freeze PI, start ramp and setpoint decreases; exclude from COP and
  energy-signature fits. Pump duty: during a defrost the pump sets its own duty and ignores
  the setting, so no pump-duty command is sent at all (neither direction; the desired duty
  is kept and applies again after the defrost); a DHW run counts as running (the heat duty
  stays, never lowered to idle).
- Monitor `Error`, `Room_Heater_State`, `Internal_Heater_State` (alarm + cost the backup
  heater), surface `Heating_Off_Outdoor_Temp` (pump summer cut-off).
- Refuse control when `Operating_Mode_State` is not heat.

## Control design (real-time loop, every 60 s)

Setpoint = **curve(outside, time-filtered)** + **room feedback** + **plan term** + **start
ramp**, then clamps, rounding with hysteresis, deadband ≥ 1 K and dwell.
- Curve: piecewise-linear, user-editable; initial points imported from the pump's stored
  curve.
- Room feedback: PI on room error (target = schedule comfort + plan room offset), clamped
  ±3 K water, anti-windup, frozen during defrost/DHW and when room temp is stale or
  implausible: the held offset (positive integrator plus the P part of one sensor step,
  at most 0.4 K) then stays applied, fading to zero over 24 h, and cooling integrated
  since the sensor's last proof of life is undone. Integer output with rounding
  hysteresis to avoid limit cycles.
- Plan term: planner works in **room-temperature offsets**; with a room sensor they shift
  the PI target, without one they map to water via the curve's sensitivity.
- Start ramp (on by default for high-mass emitters): setpoint tracks just under outlet for
  the first N min after a compressor start, bounded at curve − N K, defrost-aware,
  model-specific (T-CAP vs others).
- Cycling: never let the setpoint trigger the pump's stop rule inside a minimum-run window;
  prefer fewer, longer runs. KPI: share of runs < 20 min.
- Optional: idle pump duty (never lowered while the compressor runs or a DHW run is active;
  no duty command during a defrost; idle
  circulation must continue); quiet mode by schedule and as a capacity cap above a
  configurable outside temperature.
- Startup sends nothing until fresh `main/*` data has arrived.
- Wood-stove mode (owner note): one heating loop and the room sensor in the
  living room, so a wood stove there drives the PI to −3 K and winds the integrator down
  while the hall and bedroom still need heat. Opt-in (`control_stove_*`): when the room
  sits ≥ 1.5 K above comfort (or rises ≥ 1 K within 30 min while above comfort), or on a
  manual request, the room PI pauses with its integrator held (it resumes from the same
  value), the cross-check is suspended (no `room_implausible`), and the setpoint is the
  curve lowered by a fixed back-off (3 K, or down to the safety minimum). The pump is
  never switched off; ramp, cycling, safety, defrost and DHW work as before. A reference
  room (the hall) below its floor shrinks the back-off. The episode lasts while the
  room stays above the exit threshold (1 K below the entry threshold, at least 60 min)
  with an 8 h hard cap, and ends at once when the room sensor stops being trusted.
  Owner decision (2026-11-18): after the cap only a new fast rise starts another episode
  until the room has cooled once; after a loss of trust the sensor must be trusted again
  for 15 min first. Plausibility (improvement-round gate, F-13 to F-15): a sensor that
  fails high is not taken for a stove: a rise of 2 K within 10 min is a sensor fault (a
  stove warms a room by about 1 K per 10 min at most), which ends an automatic episode
  and keeps the detection off until the room has cooled; with a reference room an
  automatic episode needs the living room at least 1 K above it; the cross-check keeps
  running during an episode with its threshold widened by 4 K, so a sensor far off is
  still flagged, and a manual request never clears its verdict or hands an implausible
  value to the detection; the fast rise is measured from the comfort target and must
  pass the level before a dip, so the rebound after airing is no stove. A configured
  reference room without a fresh temperature halves the back-off and raises
  `stove_reference_missing`. See `docs/control-interface.md` (Wood-stove mode).
- Boost and away (on request only): a manual room-target shift in its own input slot
  (`ControlInputs.room_override`, kinds `room_target` and `away`), so it coexists with a
  stove request. It runs through the room PI like a plan slice (without a trusted room it
  maps through the curve slope) and replaces the plan while it runs; every limit stays.
  A stove episode or the summer switch pauses it (its clock runs on); a manual stove
  start ends a boost; away ends a boost and refuses a new one, so the two never stack.
  Away returns to comfort a lead time before its end, and until the end the
  comfort-floor alarm follows the away target, the day shift pauses and the house basics
  skip the days.
- Summer switch (opt-in): a 24 h exponential mean of the curve's outside value (one full
  day and night, so a warm afternoon or a mild night does not toggle it; it waits one
  time constant of samples before it may switch) above 18 °C stops space heating the safe
  way: the setpoint goes to the safety minimum and the room PI is frozen, exactly as the
  stove's "to minimum"; no new command, never `SetHeatpump 0`. Below 16 °C (2 K
  hysteresis) heating resumes. The pump's own `Heating_Off_Outdoor_Temp` stays reported
  only.
- Quiet after a start (opt-in): quiet mode for the first minutes of a compressor run, the
  quieter of it and a window, through the same quiet-mode intent; held through a defrost.
- Compressor starts are counted from `Compressor_Freq` (a restart around a defrost is no
  start) and warn (`compressor_starts`) above 4 per hour in two consecutive hours or 30
  per day.

## Planner

- **Rule planner** (**not built**; permanent fallback): price rank + forecast PV surplus + comfort band →
  room offsets; anticipates solar gain.
- **Sun day shift** (built in 0.6.0, `off` by default, `shadow` available, `on` an
  experimental opt-in after the evaluation did not pass; see [the decision](decisions/2026-11-28-sun-day-shift-after-evaluation.md)
  and [the evaluation](evaluation/dayshift.md)): a rule that raises the room target a little
  on a sunny, mild day and lowers it in the night after, through the plan hook.
- **Model plan** (removed in 0.6.0): a planner on a learned house model never passed its
  evaluation. See the [note](notes/house-model-attempt.md) and
  [the decision](decisions/2026-11-28-house-model-removed.md). The plan hook (`PlanSlice`)
  and the evaluation harness stay.
- **LP optimiser** (**not built**; experimental, shadow until it wins): HiGHS via scipy; 15-min steps to
  end of published prices; uses the fitted model (below); COP per step incl. defrost
  penalty; separate import/export; terminal constraint; start penalty.
- Tariff model (**not built**) generic (markup, tax, VAT, fixed/dynamic) with an NL post-saldering preset.
  Prices default from an HA price entity; ENTSO-E (needs a personal token) optional (**not built**).
- Reason codes as plan data, incl. "why not heating". Forecasts used in open-loop runs must be
  **lead-time correct** (as issued at decision time) — no peeking at the future.

## Evaluation modes

| Mode | Inputs | Sends | Legitimate claims |
|---|---|---|---|
| **Open-loop run** | recorded capture (+ as-issued prices/forecasts when available) | never | decision given recorded state, reasons, ladder levels, robustness to real data quirks, planner output — **no outcome claims** (open loop: integrator and ramp react to the recorded control's outcomes) |
| **Counterfactual replay** | fitted model driven by recorded weather, run twice: our controller vs the **recorded setpoints** | to the model | paired differences in energy, starts, comfort with intervals — only if the baseline gate passes |
| **Shadow** | live | never | what it would decide now, vs the existing controller live |
| **Live** | live | yes | before/after vs periods under the existing controller, normalised on degree-days and irradiance (weaker evidence than A/B; stated as such) |
| **Experiment** | live, scripted | yes, within safety limits and the envelope | identification data (free-float night, setpoint steps) |

- **Baseline** (controller-agnostic, not a target): the fitted plant driven by the recorded
  applied water setpoint of every tick, whatever wrote it
  (`ovenbird_sim.evaluate.closedloop.RecordedSetpoints`); compared with the measured room
  temperature, heat and starts.
- **Model, two layers**: pump + hydronics (water/emitter node, pump start/stop rule, minimum
  modulation, defrost, COP map over outside/outlet/Hz) and building (2-state room + mass,
  irradiance × fitted aperture, time-of-day gains). Integer outside temperature treated as a
  quantised measurement, cross-checked with the Open-Meteo archive. Identification with a
  continuous-discrete Kalman filter + prediction-error fit, physical priors.
- **Validation**: rolling origin (two 14-day test blocks tiling the end of the data, each
  fitted only on the days before it), 1/6/24 h free-run RMSE, daily heat error,
  starts/day error. Baseline gate: the plant on the recorded setpoints reproduces the
  recorded daily heat ±10 %, starts ±20 %, room RMSE bound, in-sample and on every fold —
  otherwise no claims.
- **Emitter and frost**: the emitter capacity is tied to the loop's recorded cooling in
  compressor-off periods (one time constant for all weather; the 5-min
  free-run fit alone left it free over two decades and made the plant stay off too
  long). Defrost follows frost deposition on the coil: coil temperature fitted on the
  outside-pipe sensor, deposition from humidity and the ice saturation pressure, one
  capacity per defrost; the old empirical rate could not be fitted on a block with one
  defrost.
- **Equal comfort**: ovenbird's target is chosen where the comfort check (mean ±0.05 K,
  occupied P10 ±0.1 K, degree-hours below the baseline P10) is best met. Matching the
  mean alone left ovenbird's tail colder: it holds the room flatter, about 0.15 K colder
  in the early morning and 0.2 K warmer in the afternoon than the recorded control, under
  which the room rises in cold weather.
- **Uncertainty**: day-block bootstrap ensemble; paired differences with 90 % intervals;
  "equal comfort" = matched degree-hours below band. **Refuse to claim** when the interval
  spans zero, the controller leaves the recorded envelope, or the claim needs data that was
  not recorded (PV/P1 cost claims for this period).
- **Attribution**: setpoint waterfall per decision; outcome attribution by term ablation
  (16 on/off combinations) in counterfactual replay.
- Open-loop CLI: `climate-manager open-loop --capture … --config my.toml [--from --to]` →
  result DB (same schema as live) + HTML report; reproducible (config hash, version, range).

### Shadow mode and the supervised trial (service)
- **Divergence**: per minute, ovenbird's would-be setpoint (decision journal) against the
  pump's `Z1_Water_Target_Temp` (1 min rollups); gaps stay gaps, episodes above 1 K carry
  ovenbird's reason, the writer is ovenbird only when the value equals its last verified
  command (`api/v1/shadow/divergence`).
- **Go-live checklist** from live facts (`api/v1/trial/status`): 14 shadow days, divergence
  reviewed, envelope rule declared and seen acting, notifications tested with a live
  dead-man ping, a rehearsed release within 5 min, no open critical alarm, a trusted
  room value, a go-live snapshot. The trial summary compares the trial period with an
  equal baseline period on the cut-over criteria (room mean ±0.5 K, short-run share not
  worse, no pump errors, writes per day within the budget).
- **Release control**: at go-live (the first publishing `auto` tick, before the arbiter)
  the pump state is recorded; `control/release` stores the pause first, restores the
  snapshot through the normal adapter (allowlist, clamps, budget, verification; nothing
  else is ever written) and then pauses, so the previous controller takes over. A rehearsal is the same
  release, recorded for the checklist.
- **Safety net visibility**: the envelope rule cannot be observed directly; it is
  declared by the owner and proven by recognising its correction (a change from outside
  the band to inside it that ovenbird did not send), e.g. in the stop-the-service test.
- **Notifications**: ntfy for alarms (rate-limited, de-duplicated) and an external
  dead-man ping only while the control loop is healthy; secrets only from env/options.

### Decision record
Inputs (value, age, source, forecast issue time), ladder level, controller state
(integrator, ramp phase, timers), each term before and after clamps, pre-rounding setpoint,
binding constraint, distance to the nearest threshold that would flip the decision, command
or "no change, because …", reason code, actor (planner/user/token).

## Inputs (all optional except HeishaMon)

| Signal | Typical source | Unlocks |
|---|---|---|
| HeishaMon `main/*` (required) | MQTT | control, monitoring, heat delivered |
| Room temperature | HA entity | room feedback, comfort band, pre-heat, heat-loss fit |
| Grid power (P1) | HA entity | true solar surplus |
| PV power | HA entity | surplus estimate, irradiance proxy, PV-forecast calibration |
| Heat-pump electricity | HA entity / HeishaMon s0 | real COP and cost (pump estimates flagged) |
| Prices (**not built**) | HA price entity / ENTSO-E | price-aware planning, cost |
| Weather forecast | built-in Open-Meteo | forecast-aware planning |

HA connection: one read-only WebSocket client; `last_updated`/`last_reported` give age.
HeishaMon liveness from the 5 s `stats` cadence, not `LWT`.

## House insight

House basics (0.6.0, `GET api/v1/insight/basics`, [contract](api-v1.md)): two plain estimates in
pure Python from the daily and 15 min aggregates, no learning step. The *heat loss*
is a least-squares fit of the mean heating power against the room-minus-outside difference,
`P = H x dT - G`, over 48 h windows of qualifying days (wood-stove and away days left out),
shown with its 95 % band, the balance temperature and the loss now, tonight and on the
design day. The *heat pump* part shows the heat delivered now and over 24 h and what the
floor can give at each water temperature. Heat delivered is flow x (outlet - inlet) x
`c_p`, with the inlet/outlet offset calibrated on pump-on/compressor-off periods. Limits: with
one room sensor the figure is **apparent** (ventilation and infiltration included, the house as
that sensor sees it) and no sun is modelled. No number is shown before about 10 qualifying
heating days.

The learned three-node house model, its learner, the insulation score and the curve
proposal of 0.5.0 were removed in 0.6.0: see the [note](notes/house-model-attempt.md).

## Security, reliability, HA presence

- Security: allowlist + integer clamps in the adapter; API auth (v1: one admin login +
  ingress trust in app mode + an operate-scoped token for the HA integration; finer roles later); secrets outside versioned config; hardened
  container; audit trail; ACLs as hardening guide.
- Reliability: config.db / history.db separate, WAL, integrity checks; TaskGroup
  supervision; liveness vs readiness; ntfy + external dead-man ping; MQTT discovery hygiene.
- HA presence: MQTT discovery entities are **read-only** — Energy-dashboard-ready sensors
  (electricity in, heat out with correct `device_class`/`state_class`), status/reason/plan
  sensors, problem binary sensors. **Writes go through the custom integration** (HACS,
  `custom_components/<domain>/` at repo root, tests in its own `integration/` uv project):
  climate entity with presets (comfort/eco/away/boost), override/boost/away services,
  repairs for problems, sidebar link to the UI; talks to the API with an operate-scoped
  token; checks `api_version`. Manual URL + token config; Supervisor discovery when installed
  as app.

## Open-source project

Name without "Panasonic"/"Aquarea"; Apache-2.0 (no code copied from other projects); SemVer 0.x
until cut-over proven; stable/beta channels; changelog; mkdocs site with a **safety page**
(what it can write, limit layers, failure behaviour) and a migration guide;
wizard import of the pump's stored curve; three config tiers (wizard,
advanced UI, file/env for secrets) with versioned export/import; one-click redacted
diagnostics bundle required by issue templates; no telemetry; EN + NL from day one.
New installs start in **shadow** (24–48 h) → "what I would have done" report → explicit
go-live checklist → "Release control" restores the pre-go-live pump state snapshot.

## Data worth collecting

1. Keep the recorder running into the heating season.
2. Add PV and P1 to the recording.
3. Snapshot prices and forecasts **as issued** (hourly) — not reconstructable later.
4. Room temperature on a fixed cadence (periodic republish), extra rooms if available.
5. A real electricity meter on the heat pump if possible.

Winter-only window (Dec–Feb), agreed by the owner: **free-float night** (setpoint at the
envelope minimum — never off — for 6–12 h on a cold, overcast night) and **setpoint steps**
(randomised ±3 K water-setpoint blocks of a few hours over a few days). Run by the service's
scripted *experiment mode* while the existing controller is paused, inside the safety limits and envelope,
with abort on comfort floor (room below a set minimum) or any alarm.

## Phases

**Simulation first (owner decision, 2026-11-14):** the complete system must run fully
simulated on the recorded dataset before anything touches the live setup. No live-pump
spikes, experiments or deployments until that simulated run is successful. Production
then runs in the owner's cluster (not on the NAS; the NAS only hosts the recorder).

0. Workspace, CI, image; project basics. Start collecting the data above (recorder only).
1. Read-only slice: adapter + state + history + one live page; compose + HA app packaging
   (read-only, safe for early testers); HA entity inputs.
2. **Fully simulated system on the recorded dataset**: core control + safety limits +
   **open-loop** CLI and report; model fitting and counterfactual replay;
   a simulated HeishaMon (plant model) so the whole service — control, UI, history — runs
   end to end in the dev stack against simulated data. Gate: a successful, explainable
   simulated run on the captured weeks. **Closed 2026-11-15** (gate review and re-check:
   close with notes; a dwell edge case fixed): the stepped
   full-span run over the recording has zero invariant violations, 14 fault
   scenarios pass, B2 replays decision for decision on the MQTT and HA paths. Carried to
   phase 3: one fallback when the room value is not trusted (blend the held offset, since
   2026-11-20 the positive integrator plus one sensor step of P, at reduced authority and
   when implausible), a held-phase comfort check and an early
   warning after 8 h without proof of life, and the counterfactual work before any outcome
   claim (held-out gate, per-replicate plant resampling, steady-start sensitivity, joint
   COP support, idle circulation convention). Done 2026-11-18: rolling-origin held-out
   gate, building and heat-pump layers resampled on the same days per replicate,
   steady-start variants in the sensitivity, COP joint-support refusal, idle draw
   reported as a convention (10 W of idle draw moves the electricity difference by
   0.01 kWh/day); the cycling calibration stays at the point estimate per replicate.
   **Fault sweep (2026-11-15):** every fault scenario now also runs alone at 8 (and 12)
   start times over the span (`fullrun --sweep 8`, spread over the day and the span's
   weather); before the fixes a minority of the runs failed, none of them a regression. Done: the untrusted-room
   fallback (cooling feedback at authority `a` is `u_lim·a + (1−a)·H` with the held offset
   `H`; an implausible value keeps `H`, fading over 24 h like a stale one); cooling the
   integrator did since the last proof of life is undone once the device has been silent
   past the alive-decay start or its value goes stale or implausible (a stuck-warm reading
   no longer winds down the learned offset, also when the cross-check flags it first); the early warning `room_sensor_quiet` at 8 h without proof of life;
   held-phase checks (comfort floor, no cooling once the authority is gone); the adapter verifies a write whose value the pump already
   reported when no change follows within the verify timeout (HeishaMon publishes only
   changes; this made `mode_change` fail with `verification_failed`); the plant-duty rule
   waits out a defrost that follows a start; scenarios no longer depend on their slot
   (`command_lost` arms on the first queued command, nudged by an operator comfort
   change on a steady night; the restart and pump-setting checks are midnight-safe), so
   `Scenario.follows` is gone. **Held offset (2026-11-20):** on days where the room sits
   a few tenths of a kelvin below comfort with the integrator near zero (the P part carries it inside the
   integrator dead zone), a curve-only fallback ran the house clearly below comfort until
   the sensor reported again (after a sunny day the integrator is even negative and the
   fallback was the bare curve). The fallback now holds
   `H = min(output_limit, max(0, I) + min(held_step_max_k, kp·step))`: the warm edge of the
   dead zone, since an open loop cannot see the room drifting low; `held_step_max_k`
   (0.4 K, controller-only) keeps a coarse sensor's step from becoming a large bias (the
   mean P part inside the dead zone stays within about one sensor step). The mark at the last
   proof of life is kept while the value is lost and carried over a configuration change
   like the integrator. On `room_sensor_dies_warm` over many start times the hours below the comfort
   band fell markedly while the warmest room barely rose; every scenario passes the
   8-point sweep. Still open: no
   constant estimate predicts the need well (every estimator tried, including long-run
   means of the feedback, missed it by a wide margin because it swings with sun and
   weather), and a stuck reading less than 1.5 K above the real room cools at full
   authority for up to 3 h before the cross-check or the alive ramp acts; the fault
   checks keep asserting what the design guarantees under a fallback (no cooling once
   the authority is gone, the held offset once stale, the comfort floor, the early
   warning, a stuck-warm loss of at most 0.8 K from the room at the start, a 2 h HA
   outage within one sensor step of the band or the starting room) and report the hours
   below the band.
3. **Live preparation** (only after phase 2 passes, each step with the owner's go): live
   spikes (setpoint register, HeishaMon envelope rule, foreign-writer read-back);
   deployment to the owner's cluster in shadow next to the existing controller (≥ 14 days); experiment
   mode for the two identification experiments.
4. **Supervised winter trials** with the existing controller on standby (4 h daytime → 24 h → 1 week)
   → cut-over.
5. Custom HA integration (climate entity, presets, services) + schedules + rule planner
   (prices, forecast, solar; **not built**) + Plan / Comfort / House insight pages → **v1**.
6. LP optimiser (experimental; **not built**), HA app polish, docs for other users, public release.

## Definition of done

**Cut-over**: open-loop run clean on the full recording; counterfactual gate passed; ≥ 14 days
shadow incl. defrosts without unexplained divergence; envelope fallback proven by killing
the service at night-time load; rollback rehearsed < 5 min; alerts and dead-man ping live;
7 live days incl. frost: room within ±0.5 K of the existing controller's baseline, share of
runs < 20 min not worse, no pump errors. The existing controller then disabled (kept
installed 30 days).

**v1**: cut-over done + custom HA integration + schedules and rule planner live, decision
log, open-loop CLI, status UI, setup reproducible by a second user from the docs.

## Verification

- Core unit + property tests (limits, envelope, dwell, arbiter idempotence); simulation KPI
  gates; nightly open-loop run of the full recording (report artefact); 1–2 day fixture per PR.
- Adapter contract tests against Mosquitto with the capture replayer; spike results recorded.
- Chaos (v1 set): `kill -9`, broker loss, HA restart.
- Integration: pytest-homeassistant-custom-component in `integration/`; HA restart in the
  dev stack does not interrupt control.
- Live: supervised trials and the cut-over criteria in the definition of done.
