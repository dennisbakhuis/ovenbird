# Sun day shift: simulator evaluation

Status: no setting passes the gate. Since 0.6.0 `on` is an experimental opt-in: it is
valid only together with `control_dayshift_experimental_ok` (see "After the evaluation"
at the end).

The sun day shift raises the room target a little on a sunny, mild day and lowers it in
the night after. The aim: let the sun and cheap daytime heat warm the house, and need
less heat pump at night. This page says how the rule was tested in the simulator, what
the tests showed, what was changed in the rule because of them, and why `on` did not
pass. All numbers come from the simulated plant and its synthetic weather. None of
them is a value of a real house.

## What was tested

The rule is `ovenbird_core.control.dayshift.decide`, the same function the service runs.
The simulator calls it every quarter hour with what the service would give it: the
controller's filtered outside temperature, the stored forecast and the room value the
controller sees. Its offset reaches the controller as a rule plan slice, valid 20
minutes, as in the service.

Every run is paired with a baseline: the same controller without the shift, on the same
weather, forecast error, sensor noise and starting slab temperature. The shift is the
only difference within a pair, so the differences are small but clean.

- 32 weather replicas per scenario (the gate needs at least 16).
- 8 simulated days per run, the first one warm-up: every number is over the 7 days
  after it.
- All clocks are local time in Europe/Amsterdam. The runs start at local midnight on
  2026-03-02: early March, mild days with real sun are common and the heating still
  runs. A window read in the wrong zone shows as an hour's shift.
- The forecast has a seeded error that grows with the lead time, and a day-level error
  of the sun (a factor around 1, spread about 40 %).
- The pump's outside sensor gets noise before its rounding to whole degrees; the room
  sensor is the example install's send-on-delta device.

### Scenarios

| Scenario | Weather and house | The rule should |
| --- | --- | --- |
| `sunny_mild` | clear days around 8 °C | act (the intended case) |
| `sunny_cold` | clear days around -1 °C | do nothing |
| `cloudy_mild` | overcast days around 8 °C | do nothing |
| `mixed_week` | each day clear or overcast at random | act on the clear days |
| `sun_missing` | sun forecast, clouds arrive | not hurt comfort |
| `sun_unforecast` | clouds forecast, sun arrives | not hurt comfort |
| `cold_snap` | sunny mild days; in three nights the outside falls 7 K, not in the forecast | not hurt the morning |
| `low_mass`, `high_mass` | sunny mild, all heat capacities x0.5 and x2 | not hurt comfort |
| `large_windows`, `small_windows` | sunny mild, solar aperture x2 and x0.5 | not overheat, not hurt comfort |

### Arms

- `none`: a plan provider that never plans. Every difference must be exactly zero (the
  pairing check).
- `noise`: no plan, but the sensor noise from another seed. Shows how often noise alone
  trips the gate.
- `const_setback`: a constant -1 K offset day and night. The gate must fail it on
  comfort, or it cannot see harm.
- One rule arm per setting: boost 0.5 or 1.0 K, set-back 0.5 or 1.0 K, recovery lead 4 or
  5 h; the boost alone (set-back 0); the set-back alone (boost 0, lead 4 or 5 h).
- `fixes 0`: the default setting with this evaluation's rule fixes off. For comparison
  only, never a candidate.

### Criteria and gate

Per scenario, the mean over replicas of the paired difference (shift minus baseline) per
7 days, with a 95 % bootstrap interval over replicas. The margins were fixed before the
first full run:

| Criterion | Largest acceptable rise per 7 days |
| --- | --- |
| Degree-hours below comfort, 07-23 | 1.0 Kh |
| Degree-hours below comfort - 0.5 K, 07-23 | 0.5 Kh |
| Degree-hours below comfort, 07-09 (morning) | 0.5 Kh |
| Degree-hours below comfort - 0.5 K, 07-09 | 0.25 Kh |
| Degree-hours above comfort + 1.5 K | 1.0 Kh |
| Compressor starts | 3.5 |

A check passes when the upper bound of its interval is within the margin, fails when the
lower bound is beyond it, and is inconclusive otherwise. Inconclusive blocks as much as a
failure. In `sunny_cold` and `cloudy_mild` the rule must not apply any offset at all.

`on` may be unlocked only when the gate is calibrated (`none` passes, `const_setback`
fails comfort in every scenario), the run is complete, and the final defaults pass every
check in every scenario. Also reported, not gated: compressor run time 23-07,
electricity, mean COP, setpoint writes, and the electricity moved from the night
(23-07) to the day, in kWh. No cost is claimed.

## How to reproduce

```
uv run python -m ovenbird_sim.evaluate dayshift --out <dir> --replicas 32
uv run python -m ovenbird_sim.evaluate dayshift --out <dir> --quick
```

The full run is 6688 simulations, about 35 minutes on 11 cores. `--quick` is the smoke
run the normal test suite uses (two scenarios, two short replicas); it never unlocks
anything. The slow test runs the calibration and the defaults at 16 replicas. The output
is `dayshift.json` (every number) and `dayshift_tables.md` (the tables below and one
table per arm).

## What the first full run showed, and the fixes

The first full run (same design, 32 replicas) tested the rule as it was handed over. Every
setting failed. With the defaults (boost 0.5 K, set-back 0.5 K, lead 4 h):

- **The morning got colder.** In `sunny_mild` the room was below comfort for 1.0 Kh more
  between 07:00 and 09:00 per week [0.5, 1.5], twice the margin. In `small_windows`
  (little sun to store) every comfort criterion failed and the compressor started 8.6
  times more per week. The set-back spent heat the sun had not stored.
- **It acted on cloudy days.** In `cloudy_mild` the forecast's sun error was enough to
  start boosts on overcast days, so the must-idle check failed.
- **It overheated houses that get a lot of sun.** `large_windows` +9.4 Kh above comfort
  + 1.5 K per week, `low_mass` +4.8 Kh.

Three fixes went into the rule because of this (the defaults of the core
`DayShiftParams`, not new settings):

1. **The sun must be there now.** Besides the forecast for the rest of the day window,
   the forecast irradiance from an hour before to an hour after now must reach the sun
   limit. Sun that the clouds overtake ends the boost.
2. **A set-back starts only in a warm room**: at least 0.5 K above comfort when it
   starts (`room_below_target` otherwise). It then spends heat the sun stored, not the
   next morning's comfort.
3. **Warm stop**: once the room reaches the boosted target, the boost ends for that day
   (`room_warm`). The day still counts as sunny.

Earlier fixes, from the review before the evaluation and kept:

- A night may set back only after the day held the full boost for at least 2 h (one
  boosted quarter hour used to be enough). The time counts per evaluation, at most 15
  minutes per step, so a gap in the evaluations does not count.
- Every window is read in `control_timezone`. The tests check Amsterdam, New York, UTC
  and the autumn clock change; the evaluation runs in Europe/Amsterdam.
- Replay rebuilds the slice a recorded tick applied (ladder `rule_plan`) from the
  record: the recorded room target minus comfort, or without a room sensor the `plan`
  term over the curve slope. An open-loop replay of an `on` day now reproduces its
  setpoints. A candidate replays the shift the house had; the forecast the rule read is
  not recorded, so a candidate's own shift cannot be recomputed.

Screens with 16 replicas tried an earlier warm stop (0.25 and 0.5 K below the boosted
target) and a set-back threshold of 0.3 K. The earlier warm stop removed most of the
overheating but also all of the night benefit: with the room held at comfort, a stop at
comfort ends nearly every boost at once. A 0.3 K threshold left the morning
inconclusive.

## Calibration

- `none`: PASS, every paired difference exactly zero. The pairing is clean.
- `noise`: no failure, but INCONCLUSIVE in `small_windows` (morning comfort, starts).
  Noise alone can make one scenario in eleven inconclusive. The gate is strict rather
  than lenient.
- `const_setback` (-1 K day and night): FAILs comfort in 11 of 11 scenarios.

The gate is calibrated: it passes what does nothing and fails what clearly harms.

## Results with the final rule and the defaults

Boost 0.5 K, set-back 0.5 K, lead 4 h, with the three fixes. Paired difference per 7
days, mean [95 % interval]. P/I/F = pass, inconclusive, fail.

| Scenario | Below comfort 07-23 (Kh) | Below comfort 07-09 (Kh) | Above +1.5 K (Kh) | Starts | Run 23-07 (h) | Night to day (kWh) | Gate |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `sunny_mild` | +0.65 [-0.06, +1.32] | +0.44 [-0.04, +0.92] | +0.12 [+0.07, +0.19] | +2.1 [-0.9, +4.8] | -4.9 [-7.1, -2.9] | 1.04 | I |
| `sunny_cold` | 0 | 0 | 0 | 0 | 0 | 0 | P (idle) |
| `cloudy_mild` | 0 | 0 | 0 | 0 | 0 | 0 | P (idle) |
| `mixed_week` | +0.13 [-0.13, +0.38] | +0.09 [-0.09, +0.26] | +0.12 [+0.04, +0.22] | -0.0 [-1.7, +1.7] | -1.0 [-1.9, -0.2] | 0.48 | P |
| `sun_missing` | -1.03 [-1.65, -0.42] | +0.09 [-0.28, +0.49] | 0 | +0.6 [-1.6, +3.0] | -1.0 [-2.3, +0.1] | 0.69 | P |
| `sun_unforecast` | 0 | 0 | 0 | 0 | 0 | 0 | P |
| `cold_snap` | +0.64 [+0.13, +1.14] | +0.53 [+0.19, +0.88] | +0.31 [+0.05, +0.59] | +3.8 [+1.5, +6.2] | -4.2 [-5.8, -2.7] | 0.74 | I |
| `low_mass` | -0.22 [-0.36, -0.07] | -0.05 [-0.12, +0.02] | +1.55 [+1.00, +2.18] | +0.4 [-0.3, +1.2] | -0.2 [-0.6, +0.2] | 0.00 | I |
| `high_mass` | -3.01 [-3.26, -2.75] | -1.88 [-2.05, -1.71] | 0 | -0.4 [-0.9, +0.1] | -6.2 [-7.1, -5.3] | 1.33 | P |
| `large_windows` | -1.10 [-1.51, -0.69] | -0.76 [-1.03, -0.47] | +8.77 [+7.44, +10.09] | +0.3 [-2.1, +2.8] | -0.7 [-1.7, +0.4] | 0.12 | **F** |
| `small_windows` | -0.14 [-0.78, +0.53] | +0.16 [-0.21, +0.56] | 0 | +2.7 [+0.2, +5.1] | -3.0 [-4.6, -1.5] | 0.64 | I |

Below comfort - 0.5 K the rise is at most +0.18 Kh, inconclusive for the morning in
`sunny_mild` and a pass elsewhere. Total electricity rises by up to 3.8 %; the mean COP
changes by less than 0.1.

Verdict of the defaults: **FAIL**. `large_windows` overheats far beyond the margin;
`sunny_mild` (comfort, starts), `cold_snap` (comfort, starts), `low_mass`
(overheating) and `small_windows` (morning, starts) are inconclusive.

### The sweep

| Setting | Gate | Fails | Run 23-07 in `sunny_mild` (h) |
| --- | --- | --- | --- |
| boost 0.5 / set-back 0.5 / lead 4 h (defaults) | FAIL | `large_windows` overheating | -4.9 [-7.1, -2.9] |
| boost 0.5 / set-back 0.5 / lead 5 h | FAIL | `low_mass`, `large_windows` overheating | -2.5 [-4.2, -0.9] |
| boost 0.5 / set-back 1 / lead 4 h | FAIL | `large_windows` overheating | -4.8 [-7.0, -2.7] |
| boost 0.5 / set-back 1 / lead 5 h | FAIL | `low_mass`, `large_windows` overheating | -3.3 [-5.0, -1.7] |
| boost 1 (any set-back, any lead) | FAIL | overheating in 5 or 6 scenarios | -4.8 to -6.6 |
| boost 0.5 / set-back 0 | FAIL | `low_mass`, `large_windows` overheating | -1.8 [-3.6, -0.0] |
| boost 1 / set-back 0 | FAIL | overheating in 5 scenarios | -1.6 [-3.7, +0.3] |
| boost 0 / set-back 0.5 / lead 4 h | FAIL | `large_windows` overheating | -0.4 [-1.9, +1.1] |
| boost 0 / set-back 0.5 / lead 5 h | INCONCLUSIVE | - | -0.4 [-1.7, +0.8] |
| boost 0 / set-back 1 / lead 4 h | FAIL | `large_windows` overheating | -0.5 [-2.2, +1.3] |
| boost 0 / set-back 1 / lead 5 h | INCONCLUSIVE | - (`large_windows` overheating +0.50 [-0.16, +1.16]) | +0.1 [-1.1, +1.3] |
| defaults, fixes off (the rule before) | FAIL | 6 scenarios: comfort, idle, overheating | -7.6 [-9.8, -5.4] |

No setting passes in every scenario, so the defaults stay as they are and `on` stays
locked.

## What it means

- **The boost carries the benefit and the overheating risk.** The heat the boost puts
  into the floor on a sunny day is what shortens the night run, and it is the same heat
  that overheats a house that already gets much sun. A warm stop early enough to prevent
  the overheating removes the benefit with it.
- **The set-back carries the comfort risk.** Without the warm-room condition it made the
  mornings colder; with it, it is nearly harmless but alone has no measurable benefit:
  after a day without a boost the room is seldom 0.5 K above comfort.
- **The night effect, in plain numbers.** In `sunny_mild` the baseline compressor runs
  41.4 h over 7 nights (about 5.9 h a night). With the defaults it runs 36.5 h: about 40
  minutes less a night, and about 1 kWh of electricity a week moves from the night to
  the day (night use 15.4 to 14.3 kWh). No night went without the heat pump, in any arm.
  A stated cost saving would need a tariff and is not claimed.
- Where the house stores heat well (`high_mass`) the shift helps every criterion: 6.2 h
  less night running and 3.0 Kh less below comfort. That is one simulated house, not a
  reason to unlock.

## What would be needed to unlock

- A boost that knows how much the sun will heat the room by itself, so it holds back in
  a house with large windows or little mass. A forecast and a fixed room threshold
  cannot tell those houses apart; a fitted house model could, and there is none now.
- Or an owner-specific gate: the evaluation repeated on a plant fitted to the house,
  then shadow data from the real installation reviewed by the owner.

## Limits

- One simulated plant (the reference house, its heating curve, the example room
  sensor), varied in mass and window area. Real houses differ in ways not modelled:
  where the sun falls, curtains, people and appliances, room-to-room differences.
- Synthetic March weather around one temperature per scenario. No real forecasts; the
  forecast error is a model of one.
- The room sensor is the one the controller uses. A set-back relies on it; with a badly
  placed sensor the warm-room condition can be wrong.
- 7 days per replica. Slow effects across weeks (the slab's long memory) are only
  partly seen.
- Electricity and COP come from the simulator's heat pump model; the night-to-day shift
  is in kWh only.

## After the evaluation

The verdict stands: no setting passes the gate, and the numbers above are unchanged. On
2026-11-28 the owner decided to ship `on` anyway, as an experimental opt-in
([decision record](../decisions/2026-11-28-sun-day-shift-after-evaluation.md)):

- `on` is valid only with `control_dayshift_experimental_ok` set (Settings → Features:
  a checkbox under the day shift's switch). Without it the configuration is refused with
  `dayshift_on_needs_ack`, also when the acknowledgement is taken back while `on` is
  set. The default stays `off`.
- Why: the risk is not the same in every house. The failure is overheating in a house
  with large sun-facing windows, which an owner can see and judge; a heavy house came out
  better on every criterion. The owner of such a house can now try it on their own house
  instead of waiting for a fitted model. `shadow` remains the way to watch first.
- Why not unlocked for everyone: nothing here shows that it helps a typical house, so
  it stays opt-in, off by default and marked experimental in the app and the API.
