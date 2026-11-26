# Changelog

## 0.4.1 - 2026-11-26

- Fixed: the Home Assistant connection never subscribed to the sensors, so the room
  temperature stayed empty.
- Low water flow during a defrost has its own warning, aware of the heat pump's deice
  mode, and can be logged only (Settings → Monitors → No flow during defrost).

## 0.4.0 - 2026-11-25

- First public release of ovenbird as a Home Assistant app: ingress web UI, shadow mode by
  default, the MQTT broker set in the app options, Home Assistant sensors chosen in the
  app, Replay of stored decisions, data export and a yearly archive. Pre-alpha.
