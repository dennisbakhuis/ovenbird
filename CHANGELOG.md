# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project aims to follow
[Semantic Versioning](https://semver.org/).

## [Unreleased]

## [0.5.0] - 2026-11-27

### Added

- House page with five tabs: Overview, Model, Control, Learning and What if. House is in
  the desktop navigation.
- The service runs the house model learner itself, as a low-priority child process that
  refits the model every `house_learn_interval_h` (a week by default) in the night window,
  or at once with Run now (`POST api/v1/insight/house/run`; state in
  `GET api/v1/insight/house/run`). Settings `house_learn_enabled` and
  `house_learn_interval_h`. A run card on the House page shows the state, the next run and
  the last failure, and a timeline shows the models so far. The separate learner container
  stays possible for source builds; a lock file lets it run next to the built-in learner.
- House facts as starting points for the model: build period, occupants, heated volume,
  window area and orientation. The measurements overrule them.
- Pins and limits for what the model learns: a minimum and maximum for the heat loss, the
  time constant, the solar aperture and the internal gains. Equal values pin the quantity.
  A minimum above its maximum is refused (`house_bounds_order`). The next learner run
  applies them. Parameters fitted at a limit are listed (`at_bound`), and when the limits
  cost clearly more than 0.05 K or 15 % of room error the learner flags it
  (`validation.constraint_cost`).
- Learning settings: days to learn from and to test on, the tolerance for a new model and
  the days to leave out. Days can also be left out from the room-error chart. All house
  settings are edited on the House page through the same review-and-apply bar as Settings.
- Three trust checks, one per use (`credibility.gates`): heat loss (the score, the curve
  proposal and the heat balance), room dynamics (the what-if cool-down and the room-target
  plan) and sun response (not used yet; kept for a later version of the model plan). The page says in plain numbers how well the
  model predicts: skill against "the room stays as it is" at 1 to 24 hours, and the typical
  error and bias of the 24-hour prediction on days the model had not seen. It also says
  whether the weather so far was enough to learn from (`excitation`, `credibility.needed`).
- Every learner run re-checks the model in use on the newest data
  (`champion_revalidation`). A model that stops predicting better than "the room stays as
  it is" no longer counts as credible.
- What if: what the house needs to hold a comfort temperature at an outside temperature,
  with sun and a wood stove, from the learned model or, without one, from the house facts
  (`GET api/v1/insight/house/whatif`).
- Heat balance: heat pump, loss, sun, internal gains and what the building stores right
  now (`GET api/v1/insight/house/balance`). It notes the 12 hours after a wood-stove
  episode and shows no storage then.
- The room against what the model predicted 24 hours earlier, for the last 14 days
  (`GET api/v1/insight/house/series`). It marks wood-stove and left-out periods.
- Model plan in shadow (Settings → Model plan, `control_model_use`). The learned model looks
  at the forecast sun and outside temperature over the next hours and computes every quarter
  hour how far the room target should be set back before free heat arrives or raised before
  a loss arrives, at most 0.5 K down and 0.3 K up by default. `off` is the default; `shadow`
  computes and records the plan with no effect on any decision; `on` is locked and refused
  (`model_use_on_locked`). A plan is only made while the model is promoted, credible,
  recently re-validated and accurate enough, the forecast is fresh, the room value is
  trusted and no wood-stove episode runs or ended less than 12 hours ago (the recovery tail survives a
  restart). The Control tab shows the verdict and the blocking guards, and
  `GET api/v1/insight/house/control` the switch, the guards and the computed offsets of the
  last 7 days. New settings
  `control_model_max_setback_k`, `control_model_max_preheat_k`, `control_model_horizon_h`
  and `control_model_max_rmse_k`. The forecast steers only when the model plan is `on`.
- Offline evaluation of the model plan (`python -m ovenbird_sim.evaluate model-plan`):
  8 scenarios with paired weather replicas, sensor noise, wrong models and shifted
  forecasts, and a gate with three outcomes. Neither the target shift nor the experimental
  water planner in the core package passes it, so the service issues only room-target
  slices. See `docs/evaluation/model-plan.md` and
  `docs/decisions/2026-11-28-model-plan-after-evaluation.md`.
- The app names the deice mode of a running defrost when the heat pump model is known:
  "Defrosting · mode 2" on Home and on the Pump page, with what it means for the water
  pump. `api/v1/snapshot` carries the live `defrost`.
- System → About this installation shows the heat pump model and whether ovenbird knows its
  defrost facts.
- A capped wood-stove episode without a recorded end is reported as a warning in the run
  status and the insight.
- The CI workflow builds the container image.

### Changed

- The sensor pickers list Home Assistant entities that only copy the heat pump (such as
  Home Assistant's own HeishaMon integration) last, grouped as "Heat pump, via Home
  Assistant". They stay selectable. `api/v1/config/signals` marks them `pump_mirror`.
- Settings is an icon in the top bar. Settings → Home Assistant says that the heat pump
  itself is read over MQTT.
- The house model is a chain: heat flows from the loop through the emitter (floor, screed,
  radiators) into the building and out. Eight parameters are learned and the rest is held.
  Stored models load unchanged. Internal gains are reported as net free heat that cannot be
  separated from the heat loss.
- The reported heat-loss range is the envelope of the bootstrap interval and the fits on
  earlier training windows (`ua.interval_90`); the insulation score uses it.
- A new model replaces the one in use when it is credible and the old one is not, when it
  is the same house on newer data, or when it is not worse on days the old one had not
  seen. A model that is not credible never replaces a credible one.
- The image carries numpy and scipy for the learner and grows from about 146 MB to about
  356 MB.

### Security

- The learner child process no longer imports from the data directory, so a file planted
  there is never run. It also takes a lock, so two learners never write the models together.

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
