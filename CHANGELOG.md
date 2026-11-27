# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project aims to follow
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added

- Model plan in shadow: the learned house model looks at the forecast sun and outside
  temperature over the next hours (6 h by default) and computes every quarter hour how far
  the room target should be set back before free heat arrives or raised before a loss
  arrives, at most 0.5 K down and 0.3 K up by default. The switch `control_model_use`
  (Settings → Model plan) is `off` (default), `shadow` (computed and recorded, with no effect
  on any decision, which stay byte-identical to `off`) or `on`. `on` is locked for now: it is
  refused (`model_use_on_locked`) until the offline evaluation and a shadow period of two
  weeks have been reviewed. A plan is only made while the model is promoted, credible,
  recently re-validated and accurate enough (`control_model_max_rmse_k`), the forecast is
  fresh, the room value is trusted and no wood-stove episode runs or ended less than 12 h
  ago; the blocking guards are shown. New settings `control_model_max_setback_k`,
  `control_model_max_preheat_k`, `control_model_horizon_h` and `control_model_max_rmse_k`;
  `GET api/v1/insight/house/control` reports the switch, the guards, the latest evaluation
  and the computed offsets of the last 7 days (history signals
  `derived/model_plan_offset_k` and `derived/model_plan_applied`; guard changes are
  journalled as informational `model_plan` events). The weather forecast is no longer
  display-only in the design: it is a controller input only when the model plan is `on`.
- What-if on the House page: what the house needs to hold a comfort temperature at an
  outside temperature, with sun and a wood stove, from the learned model or, without one,
  from the house facts: the heat, the loop and supply temperatures against your curve and
  the supply limit, the outside temperature where heating stops, and how the room cools with
  the heating off (`GET api/v1/insight/house/whatif`; `house_model_missing` says which facts
  an estimate needs).
- The room as measured against what the model predicted 24 hours earlier, for the last 14
  days (`GET api/v1/insight/house/series`; the learner writes `series-<model>.json`; the
  prediction is out-of-sample, so it starts after the first day of the held-out block).
- Live heat balance of the house: heat pump, loss, sun, internal gains and what the building
  stores right now (`GET api/v1/insight/house/balance`).
- The app names the deice mode of a running defrost when the heat pump model is known:
  "Defrosting · mode 2" on Home and on the Pump page, with what it means for the water
  pump (mode 1: reverse cycle, water pump running; mode 2: hot gas, water pump off by
  design). `api/v1/snapshot` carries the live `defrost` (active, mode, start, inlet and
  outdoor temperature at the start, the `defrost_stuck` limit).
- System → About this installation shows the heat pump model and whether ovenbird knows
  its defrost facts.
- The service runs the house model learner itself: a low-priority child process that refits
  the model every `house_learn_interval_h` (a week by default) in the night window, or at
  once with Run now (`POST api/v1/insight/house/run`). New settings `house_learn_enabled`
  and `house_learn_interval_h` (Settings → House). The separate learner container stays
  possible; run one of the two, not both.
- House page tabs (Overview, Model, Learning), a run card with the learner's state, next
  scheduled run and Run now, and a learning timeline of the models so far.
- House in the desktop navigation, with Settings as an icon.
- House facts as starting points for the model: build period, occupants, heated volume,
  window area and orientation (`house_build_period`, `house_occupants`, `house_volume_m3`,
  `house_window_area_m2`, `house_window_orientation`). The measurements overrule them.
- Pin or limit what the model learns: a minimum and maximum for the heat loss, the time
  constant, the solar aperture and the internal gains (`house_ua_*`, `house_time_constant_*`,
  `house_solar_aperture_*`, `house_internal_gain_*`); equal values pin the quantity. A
  minimum above its maximum is refused (`house_bounds_order`). The next learner run applies it.
- Learning settings: days to learn from and to test on, the tolerance for a new model and
  the days to leave out (`house_learn_fit_days`, `house_learn_test_days`,
  `house_learn_tolerance_k`, `house_learn_excluded_days`; `house_fit_days_short`,
  `date_format`, `date_future`, `date_repeated`). Days can also be left out from the
  room-error chart on the House page.
- The house settings can be edited on the House page (facts on Overview, limits on Model,
  learning settings on Learning) through the same review-and-apply bar as Settings, which
  now also shows on the House page. The settings are in three groups, `house`,
  `house_bounds` and `house_learning`.
- The house model says whether the weather so far was enough to learn from: the insight's
  `excitation` block counts heating days (at least 5 K indoor-outside difference and the
  heat pump running at least a fifth of the day) and the range of outside temperatures in
  the fit window, and `credibility.needed` says how many heating days and how much more
  outside-temperature spread are still missing.
- How well the model predicts, in plain numbers: the skill against "the room stays as it
  is" at 1 to 24 hours (`validation.skill`), and the typical error and bias of the 24-hour
  prediction over the days the model had not seen (`series_rmse_k`, `series_bias_k`, and
  `rmse_k`, `bias_k` in `insight/house/series`).
- Every learner run re-checks the champion on the newest data (`champion_revalidation` in
  the run status). The service uses that result: a champion that no longer predicts
  better than persistence stops counting as credible for the what-if cool-down and the
  model plan, and one whose UA no longer agrees with the signature for the score, the
  proposal and the what-if.
- Parameters fitted at a limit are listed (`at_bound`, an owner limit or the model's own
  range), with the house's total heat capacity. When the owner set bounds or pins, the
  learner also fits without them and flags when the limits cost clearly more than
  0.05 K or 15 % of room error (`validation.constraint_cost`).
- The room series marks wood-stove and left-out periods (`events`), leaves the prediction
  out where those touch it, starts at the first prediction and is rewritten for the
  champion on every run.
- The live heat balance notes the 12 h after a wood-stove episode (`stove_tail`) and shows
  no storage then.
- A capped wood-stove episode without a recorded end is reported as a warning in the run
  status and in the insight (`warnings`).
- Experimental water planner (`plan_water`) in the core package: it lowers the water
  setpoint ahead of forecast sun, by the sun's heat as an outside-temperature rise moved
  down the heating curve (lead 1.5 h, 0.5 K steps, at most 3 K down by default, an optional
  raise after the sun). A model plan slice can now carry a water offset
  (`PlanSlice.water_offset_k`); the controller bounds it (`max_lower_water_k`,
  `max_raise_water_k`) and removes its effect when the room is below comfort by more than
  a sensor step (`authority_full_k`, `authority_zero_k`). Decisions then carry
  `model_plan_water_requested_k`, `model_plan_water_applied_k` and `model_plan_authority`.
  The service does not use it: it still issues only room-target slices, in `shadow`, and
  `on` remains locked.

### Changed

- The offline evaluation of the model plan was rebuilt (`python -m ovenbird_sim.evaluate
  model-plan`): 8 scenarios, 24 paired weather replicas per cell with sensor noise, wrong
  model variants and shifted forecasts (94 cells), intervals over replicas and a gate with
  three outcomes (PASS, INCONCLUSIVE, FAIL). Neither the target shift nor the water planner
  passes it. The report is `docs/evaluation/model-plan.md`; the decision record is
  `docs/decisions/2026-11-28-model-plan-after-evaluation.md`.
- The house model is a chain: heat flows from the loop through the emitter (the fast node:
  floor, screed, radiators) into the building (the slow node) and out. Eight parameters are
  learned; the direct loop-to-room path, the share of sun onto the emitter and the day-curve
  of the internal gains are held, because the data cannot tell them apart. Stored models
  load unchanged. The insight shows the structure (`structure`), the capacity per node
  (`capacities_kwh_per_k`: loop, emitter, building) and the emitter's time constant
  (`emitter_time_constant_h`). Internal gains are reported as net free heat that cannot be
  separated from the heat loss (`internal_gains_w.identified` false, with how much the UA
  moves per 100 W); gains at 0 and the held parameters are no longer listed in `at_bound`.
- The reported heat-loss range is the envelope of the bootstrap interval and the UAs of
  the rolling-origin train-window fits (`ua.interval_90`, with `bootstrap_interval_90` and
  `fold_w_per_k`); the insulation score uses it.
- Credibility is three gates, one per use (`credibility.gates`, and `gates` on
  `insight/house`): heat loss (the score, the curve proposal, the what-if steady state and
  the balance: signature, heating weather, the UA range within 30 %, signature and model
  UA within 20 %, the UA stable within 15 % across train windows), dynamics (the what-if
  cool-down and the room-target planner: better than persistence over 6 h) and sun (the
  water planner: at least 5 sunny held-out days, the sun term helping on sunny hours and
  the measured sun response within a factor 1.5 of the model's). `credible` is the heat-loss
  gate; the 24 h skill is reported, not gated. The rule of ten days below 5 °C stays dropped.
  The what-if marks its cool-down with the dynamics gate (`drift.credible`).
- Promotion: a credible (heat-loss) new model replaces one that is not; a new model that is
  not credible never replaces a credible champion, also not after a settings change; nor
  does one that fails the dynamics or sun gate the champion passes on the same days; the
  same house on newer data (its UA and time constant inside the champion's 90 % intervals)
  replaces the champion; otherwise the new model must not be worse than the champion,
  scored on the days the champion had not seen when there are enough of them. Every run
  re-validates all three gates of the champion (`champion_revalidation.gates`).

- The sensor pickers list Home Assistant entities that only copy the heat pump (such as
  Home Assistant's own HeishaMon integration) last, grouped as "Heat pump, via Home
  Assistant". They stay selectable. A device counts as such a copy when at least three
  of its entities hold the current values of three different HeishaMon `main/*` signals;
  `api/v1/config/signals` marks them `pump_mirror`.
- Settings → Home Assistant says that the heat pump itself is read over MQTT.
- The image carries numpy and scipy for the learner and grows from about 146 MB to about
  356 MB.

## [0.4.1] - 2026-11-26

### Fixed

- The Home Assistant input never subscribed: the subscription went out with a lower
  request id than the registry reads before it, which Home Assistant rejects
  (`id_reuse`). The link stayed down and the room temperature stayed empty.

### Changed

- Low water flow during a defrost has its own warning, `low_flow_defrost`, instead of the
  critical `low_flow` alarm. Some heat pumps stop their water pump while defrosting by
  design. A model profile, recognised from HeishaMon's `Heat_Pump_Model`, carries the
  deice facts from the service manual: on the WH-MXC12J9E8 deice mode 2 (hot-gas bypass,
  water inlet below 27 °C) runs with the water pump off for up to 30 minutes.
- New setting **No flow during defrost** (Settings → Monitors): Automatic (default) only
  logs a mode 2 event under Activity → Alarms, Log only also logs it for an unknown model,
  Alarm always raises the warning. Low flow in deice mode 1 always raises it.
- `defrost_stuck` allows a mode 2 defrost its full length plus 5 minutes.
- `api/v1/pump/settings` reports the active pump profile.
- The settings group Room monitor is now called Monitors.

## [0.4.0] - 2026-11-25

First public release. ovenbird is a standalone controller for air-to-water heat pumps
behind a HeishaMon board. It is pre-alpha: it runs fully simulated and in shadow, and has
not controlled a real pump yet.

### Control

- The water setpoint is a sum of named terms: the heating curve (weather-dependent control,
  with its own switch and a fixed water temperature when it is off), room correction (a
  separate switch, PI on the room error with stuck-warm protection for send-on-change
  sensors), the start ramp, the cycling floor, quiet mode and wood-stove mode (automatic
  and manual, capped at 8 h). Clamps, rounding with hysteresis, dwell and a daily write
  budget sit on top.
- Safety limits that follow the emitter type and the outside temperature: a safety envelope
  that a HeishaMon rule can also enforce when ovenbird is down, a hard maximum supply,
  foreign-writer detection, holds during defrost and hot-water runs, and alarms.
- Optional pump-duty control (off by default) and an optional outside thermometer for the
  heating curve; the safety envelope keeps the pump's own sensor, and a stale, implausible
  or deviating thermometer falls back to it. Extra MQTT sensors can never stand in for the
  pump's own signals or topics.
- Every decision is recorded with its inputs, terms, binding constraint and a
  plain-language explanation.

### Modes

- **Shadow** (the default for a new installation): ovenbird reads and decides every
  minute but never sends, and System → Compare shows the difference with the pump's
  current controller. The other modes are Auto, Manual (a setpoint override) and Off;
  Auto can be paused. A trial checklist and a release step guard the switch to Auto, and
  nothing is sent unless the deployment enables commands.

### App

- Web UI (EN and NL, light and dark) with Home, Setpoint, Weather, Pump, House, Activity,
  System and Settings, help topics and a glossary.
- Settings are versioned with review, preview and rollback. Home Assistant (address and
  token), the MQTT broker (tested before it is saved, with automatic return to the previous
  broker) and extra MQTT sensors are set in the app; sensors are chosen from a live list.
- Hot water can be hidden when the pump has no tank.
- **System → Replay** replays the stored decisions of a period with the active settings,
  an older version or a draft, and shows where ovenbird would have sent something else.
  No comfort or energy claims: the house followed the recorded control.
- **System → Data**: storage report, retention presets (Short, Standard, Long, Unlimited),
  streamed exports of series and journals, a full archive, and a yearly archive that
  freezes every month and downloads per calendar year or heating season.
- House insight: a house model learned from the history proposes heating-curve changes for
  review, and gives an indicative insulation score.

### Integration and tooling

- Home Assistant app. Read-only MQTT discovery entities and a Home Assistant integration
  for writes are planned.
- Container image, deployment guide (`docs/deploy.md`) and `make shadow-check`.
- Simulated HeishaMon and plant model, a closed-loop harness with fault scenarios, a golden
  decision log that every change must reproduce, the open-loop run over recordings, and a
  converter that turns a recording into a history database for Replay.
