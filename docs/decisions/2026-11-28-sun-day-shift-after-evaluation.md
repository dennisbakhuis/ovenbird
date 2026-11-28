# The sun day shift after the evaluation

Date: 2026-11-28. Source: [evaluation/dayshift.md](../evaluation/dayshift.md),
[control-interface.md](../control-interface.md), "Sun day shift".

## Decision

1. **`on` stays locked** (`DAYSHIFT_ON_LOCKED = True` in
   `ovenbird.config.validation.dayshift`). No swept setting passes the gate in every
   scenario. `shadow` stays available. *Superseded the same day by item 6.*
2. **The setting defaults stay** (boost 0.5 K, set-back 0.5 K, recovery lead 4 h). No
   other setting passes either, so there is nothing better to switch to.
3. **Three fixes go into the rule** because of the evaluation. They are defaults of the
   core `DayShiftParams`, not settings:
   - the sun must be there now: the forecast irradiance from an hour before to an hour
     after the evaluation must reach the sun limit (`sun_low` otherwise);
   - a set-back starts only while the room is at least 0.5 K above comfort
     (`room_below_target` otherwise);
   - once the room reaches the boosted target, the boost ends for that day
     (`room_warm`); the day still counts as sunny.
4. **Earlier fixes stay**: a night may set back only after at least 2 h at the full
   boost; every window is local time in `control_timezone`; replay rebuilds the slice a
   recorded `on` tick applied.
5. **The pure rule moves to the core package** (`ovenbird_core.control.dayshift`), so the
   simulator runs the service's own function. `ovenbird.control.dayshift` re-exports it
   and reads the settings.
6. **Owner's decision (2026-11-28): `on` ships as an experimental opt-in.** The lock and
   `DAYSHIFT_ON_LOCKED` are removed. A new setting `control_dayshift_experimental_ok`
   (default `false`, basic) records that the owner accepts the day shift is experimental;
   `control_dayshift_use` = `on` is valid only with it (`dayshift_on_needs_ack`), and
   taking it back while `on` is set is refused the same way. In `on` the runner hands its
   slices to the controller. `GET control/dayshift` and `GET control/features` say
   `experimental` and `on_available` instead of `locked`. The evaluation's verdict is
   unchanged.

## Why

- The gate is calibrated: a provider that never plans passes with every difference
  exactly zero, and a constant -1 K shift fails comfort in all 11 scenarios.
- With the defaults and the fixes, `large_windows` overheats by +8.8 Kh per week above
  comfort + 1.5 K [7.4, 10.1], against a margin of 1.0 Kh. `sunny_mild`, `cold_snap`,
  `low_mass` and `small_windows` are inconclusive on comfort, starts or overheating.
- The boost carries both the benefit and the risk: the heat it stores is what shortens
  the night run (-4.9 h of compressor running over 7 nights [-7.1, -2.9] in
  `sunny_mild`, of 41.4 h), and the same heat overheats a house with much sun. A warm
  stop early enough to prevent that removes the benefit.
- The set-back carries the comfort risk. Before the warm-room condition it made the
  mornings colder (+1.0 Kh below comfort 07-09 per week in `sunny_mild`, every comfort
  criterion failed in `small_windows`). With it, a set-back alone is nearly harmless but
  has no measurable benefit.
- The fixes are worth keeping although the gate still fails: they turn the failures in
  `cloudy_mild` (acting on overcast days), `sun_missing` and `small_windows` into passes
  or inconclusives, at the price of a smaller benefit (-4.9 h instead of -7.6 h).

- On the opt-in (item 6): the risk the gate found is overheating in a house with large
  sun-facing windows, which the owner can recognise and watch for; a heavy house improved
  on every criterion. Leaving the choice to the owner, with the risk stated in the app
  where `on` is chosen, lets such a house use it without claiming that it passed. The
  default stays `off`, and the acknowledgement is one combination rule instead of a
  forced change, so a stored configuration can never be `on` without it.

## Alternatives rejected

- **Ship with the set-back at 0 (boost only).** The boost fails overheating in
  `low_mass` and `large_windows` on its own.
- **Ship with the boost at 0 (set-back only, lead 5 h).** Inconclusive, not a pass
  (`large_windows` overheating, and `cold_snap` with 0.5 K), and no measurable benefit
  (+0.1 h [-1.1, +1.3] of night running in `sunny_mild` with 1 K). A feature that does
  nothing measurable is not worth unlocking.
- **An earlier warm stop (0.25 or 0.5 K below the boosted target).** Screened with 16
  replicas: less overheating, but no night benefit left.
- **Wider margins.** They were fixed before the first full run; widening them after
  seeing the results would make the gate meaningless.
- **Unlock `on` for everyone (item 6).** Nothing shows it helps a typical house, and it
  overheats one kind of house; an explicit, informed opt-in is the most it can claim.
- **Clear the acknowledgement by switching `on` off automatically (item 6).** A refused
  combination is simpler and never changes the mode behind the owner's back.

## Consequences

- `room_warm` is a new day shift reason. The API's `DayShiftReasonName` in
  `api/models/control.py` must list it, or a `shadow` status with that reason fails
  validation.
- A rule that would pass needs to know how much the sun heats the room by itself, which
  a forecast and a fixed room threshold cannot tell. Dropping the experimental mark
  (item 6) needs a new evaluation
  with the same gate: on the simulator first, then on a plant fitted to the house, then
  shadow data from the real installation reviewed by the owner.
- The evaluation is `python -m ovenbird_sim.evaluate dayshift`; its quick mode runs in
  the normal tests and a slow test checks the calibration and that the defaults do not
  pass at 16 replicas.
