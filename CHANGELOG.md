# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project aims to follow
[Semantic Versioning](https://semver.org/).

## [0.6.0] - 2026-11-28

The house model of 0.5.0 is removed and replaced by a simple heat-loss estimate; the sun
day shift, boost, away, a summer switch and a few smaller features arrive, each with its
own switch. Upgrade notes: [docs/deploy.md](docs/deploy.md#upgrading-from-050).

### Added

- House basics (`GET api/v1/insight/basics`, setting `house_basics_enabled`, on by
  default): the heat loss of the house in W/K with its band, the outside temperature at
  which no heating is needed, the loss now, tonight and on the design day, the heat the
  heat pump delivers now and over 24 h, and the heat the floor can give at each water
  temperature. Pure Python from the 15 min rollups, with no learning step; it shows no
  number until about 10 qualifying heating days are in the history. Days with a
  wood-stove episode or an away period are left out.
- Sun day shift (`control_dayshift_*`, off by default): on a sunny, mild day the room
  target rises a little inside a day window (0.5 K, 09:00 to 17:00) and in the night
  after it drops a little (0.5 K from 23:00), ending 4 h before the comfort time (07:00)
  so the floor heating has the room back by then. The rule needs the sun to be there now
  and not only forecast, needs 2 h at the full boost before a night may set back, ends
  the boost for the day once the room reaches the boosted target (reason `room_warm`)
  and starts a set-back only while the room is at least 0.5 K above comfort. `shadow`
  records what it would do (`derived/dayshift_shadow_k`, journal `dayshift`) without
  changing any decision. `on` applies it, but is experimental: no setting passed the
  simulator evaluation (a house with large sun-facing windows overheats;
  [docs/evaluation/dayshift.md](docs/evaluation/dayshift.md);
  `python -m ovenbird_sim.evaluate dayshift`), so `on` is valid only together with the new
  setting `control_dayshift_experimental_ok` (off by default; `dayshift_on_needs_ack`
  otherwise, also when the acknowledgement is taken back while `on` is set). In
  Settings → Features a checkbox under the switch states the risk, `On` is offered only
  once it is ticked, and an "Experimental" pill marks the feature while it is on.
  `GET api/v1/control/dayshift` and `GET api/v1/control/features` say `experimental` and
  `on_available`. Replay rebuilds the shift of a recorded `on` tick. State in `GET api/v1/control/dayshift`. The bound of every rule plan slice is
  now a setting, `control_plan_rule_max_k`, and a set-back lowers the comfort-floor alarm
  with it.
- Boost (`POST`/`GET`/`DELETE api/v1/control/boost`, operate): a temporary room target,
  -3 to +2 K from comfort or an absolute target, for 15 min to 12 h (defaults
  `control_boost_default_k` 1 K, `control_boost_default_s` 2 h). It replaces a plan slice,
  survives a restart, is journalled (`boost`) and audited; a wood-stove episode or the
  summer switch pauses it, a manual stove start ends it.
- Away (`PUT`/`GET`/`DELETE api/v1/control/away`, operate): the room held at
  `control_away_target_c` (16 °C) until an end time, back to comfort
  `control_away_comfort_lead_s` (6 h) before it. While set, the comfort-floor alarm
  follows the away target, the day shift pauses (guard `away`) and the house basics leave
  the days out (`excluded.away`). Setting away ends a boost; a boost is refused while away.
- Boost and away on the Home page: the controls to start and end them, and a note when
  one is paused.
- Summer switch (`control_summer_*`, off by default): above 18 °C of a 24 h outside mean
  the controller asks for the safety minimum setpoint with the room feedback frozen
  (reason `summer`, journal `summer_mode`); heating resumes 2 K below the limit.
- Quiet mode after a compressor start (`control_quiet_start_*`, off by default, 10 min at
  level 2), and `control_quiet_enabled` to ignore the quiet windows.
- `compressor_starts` warning: more than 4 starts in each of two consecutive hours or
  more than 30 in 24 h (`safety_starts_*`); a defrost's restart is not counted.
- `GET api/v1/control/features`: every switchable feature with `off`, `shadow`, `on` or
  `active_now`. The settings schema gives each field its `feature` and a `read_only` flag
  for the expert tier.
- Settings has a Features section: one switch per feature and a pill that shows what it
  is doing right now; Overview counts the features that are on.
- Retired journal and audit codes of 0.5.0 (`model_plan`, `house_learn_run`) show a
  neutral "Retired" text in the app instead of the raw code.
- The service version is shown next to the logo in the top bar ("v0.6.0") and, on the
  phone, at the top of the More page; both link to System, where the About card is.

### Removed

- The house model of 0.5.0: the three-node model with its eight parameters, the nightly
  learner (a child process of the service, `make learn`, the separate learner container
  and its `Dockerfile` target) and its trust gates, champion and challenger, pins and
  bounds, the insulation score and the curve proposal. What was tried and why it stopped:
  [docs/notes/house-model-attempt.md](docs/notes/house-model-attempt.md) and
  [docs/decisions/2026-11-28-house-model-removed.md](docs/decisions/2026-11-28-house-model-removed.md).
  The code is kept at the git tag `v0.5.0`.
- The planners built on it: the model plan (`control_model_use` and the
  `control_model_*` settings, `derived/model_plan_*`) and the experimental water planner
  in the core package. The generic plan hook stays.
- The endpoints `GET api/v1/insight/house`, `.../house/history`, `.../house/run` (`GET`
  and `POST`), `.../house/whatif`, `.../house/balance`, `.../house/series`,
  `.../house/control` and `POST .../house/proposal/draft`.
- The settings groups of the learner and the model: `house_learn_*`, the pins and limits
  of the heat loss, the time constant, the solar aperture and the internal gains, the
  learning days, tolerance and left-out days. They are ignored on load; the facts about
  the house stay. Model files in `<data_dir>/models` are no longer read.
- The House tabs Model, Control, Learning and What if, the what-if and the model plan
  card. The scientific libraries numpy and scipy left the image.

### Changed

- The House page shows the house basics instead of the model: the heat loss with its
  band, the loss now, tonight and on the design day, the heat from the heat pump and
  what each water temperature gives, the days left out and the heat by outside
  temperature.
- The image is smaller again, from about 356 MB to about 146 MB.
- `control_cycling_max_raise_k` is an advanced setting (was expert).
- Internal: the version has one source, the installed package metadata, and
  `make bump VERSION=x.y.z` sets the remaining places ([docs/releasing.md](docs/releasing.md));
  a check in `make lint` requires numpy docstrings; one polling helper serves the UI;
  several refactors; far fewer sleeps in the tests.

### Fixed

- The "Live connection lost" banner no longer shows on every page load: it waits for the
  first connection attempt to finish.

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
