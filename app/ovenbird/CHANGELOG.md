# Changelog

## 0.6.0 - 2026-11-28

- Removed: the house model, its weekly learner, the model plan and the What if views. The
  image shrinks from about 356 to about 146 MB. Stored settings of the model are ignored;
  files in the data directory's `models/` folder stay and can be deleted by hand.
- New House page: heat loss, balance temperature and the heat from the heat pump, from
  the daily figures (needs about 10 heating days).
- New and off by default: sun day shift, summer switch, quiet after a compressor start.
  The sun day shift is experimental: it records only (`shadow`) unless you tick that you
  want to try it, which makes `On` available. In the simulator it made houses with large
  sun-facing windows too warm. Boost and away are on the Home page. Settings has a
  Features section.
- The version is shown next to the logo (on the phone at the top of More).
- New warning for too many compressor starts.
- Fixed: "Live connection lost" no longer shows on every page load.
- Set the time zone (`control_timezone`) for the day shift and the quiet windows.

## 0.5.0 - 2026-11-27

- New House page with the learned house model: facts, limits, learning settings, three trust
  checks, what-if and heat balance. The model is refitted weekly at night inside the app
  (low priority, off with `house_learn_enabled`); the image grows from 146 to about 356 MB.
- Model plan: off by default, `shadow` computes a bounded room-target shift without effect.
- Deice mode shown during a defrost; Home Assistant's copies of the heat pump are grouped
  in the sensor pickers. Settings is an icon in the top bar.

## 0.4.1 - 2026-11-26

- Fixed: the Home Assistant connection never subscribed to the sensors, so the room
  temperature stayed empty.
- Low water flow during a defrost has its own warning, aware of the heat pump's deice
  mode, and can be logged only (Settings → Monitors → No flow during defrost).

## 0.4.0 - 2026-11-25

- First public release of ovenbird as a Home Assistant app: ingress web UI, shadow mode by
  default, the MQTT broker set in the app options, Home Assistant sensors chosen in the
  app, Replay of stored decisions, data export and a yearly archive. Pre-alpha.
