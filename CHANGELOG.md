# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project aims to follow
[Semantic Versioning](https://semver.org/).

## [Unreleased]

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
