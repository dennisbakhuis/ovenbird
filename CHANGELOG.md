# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project aims to follow
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added

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
- House facts as starting points for the model: build period, share of floor heating,
  occupants, heated volume, window area and orientation (`house_build_period`,
  `house_floor_heating_share`, `house_occupants`, `house_volume_m3`, `house_window_area_m2`,
  `house_window_orientation`). The measurements overrule them.
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

### Changed

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
