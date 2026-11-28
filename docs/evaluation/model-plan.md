# Model plan: offline evaluation

> Both planners evaluated here were removed in 0.6.0, with the house model. See
> [house-model-attempt.md](../notes/house-model-attempt.md). The code is at the tag
> `v0.5.0`.

Status: no planner passes the gate. Do not switch the model plan on from this evidence.

The model plan lets a learned house model and a weather forecast nudge the controller.
Two planners exist. This page says what was measured in simulation, how, and what is
still open. All numbers are from the simulated reference plant and its synthetic weather.
They are not data from any real house.

- **v1, target shift** (`plan_offset`): moves the room target, at most 0.5 K down and
  0.3 K up. It is the planner the service runs, in `shadow` only.
- **v2, water feed-forward** (`plan_water`): moves the water setpoint ahead of forecast
  sun, by default at most 3 K down, with an optional raise after the sun. It exists in
  the core package and in this evaluation. The service does not use it.

## Why the first evaluation was replaced

The first evaluation ran one simulation per cell. The effects it had to judge were of
the size of 0.5 Kh per day, and a single run could not resolve that: the loop rounds the
outside temperature and the setpoint, so a change of 0.1 K in the weather moved a single
cell by up to 15 Kh below comfort over a week. Its pass and fail verdicts per cell were
noise. The evaluation was rebuilt with many paired weather replicas per cell, intervals
and a three-valued gate.

## Method

**Scenarios (8).** `sunny_cold`, `sunny_mild`, `cloudy`, `cold_front` (an 8 K drop on
day 4), `missing_sun` (sun forecast, not arriving), `unforecast_sun` (sun arriving,
not forecast), `mixed_week` (clear with probability 0.5 per day) and `false_sun_cold`
(forecast sun on a cold day that stays dull). Each run is 8 simulated days; the first
day is dropped.

**Replicas.** 24 weather replicas per cell, the same weather with and without the plan
(paired). A replica draws its own mean outside temperature (± 1.5 K), daily swing,
drift, sun timing and size, cold-front timing and starting slab temperature. The outside
sensor has noise of 0.3 K before rounding and the room sensor 0.05 K before its 0.2 K
step. Every draw depends only on the seed, the replica and the day, so the baseline is
shared by all planners.

**Model variants.** `correct`, UA × 0.7 and UA × 1.4 (credible: a model that passed
the learner's gates could be this wrong), and solar aperture × 0.5 and × 2 (stress: a
model that fails the sun gate). "Correct" means the plant's own structure with its true
parameters.

**Forecast variants.** `perfect`, `noisy`, and, with the correct model where the forecast
has sun, the sun shifted by −2 h and +2 h (stress).

**Cells.** 94 cells: 42 credible (credible models, perfect or noisy forecast, not
`false_sun_cold`) and 52 stress.

**Statistic.** Per cell, the mean over replicas of with minus without, per day.
Electricity and setpoint writes are relative. The interval is a bootstrap over replicas,
widened to a Student-t level for 24 replicas (95 %).

**Gate.** Each criterion on each cell gives PASS (interval upper end within the margin),
FAIL (lower end above the margin) or INCONCLUSIVE. Margins, per day:

| criterion | margin |
| --- | --- |
| degree-hours below comfort − 0.5 K | +0.15 Kh |
| degree-hours below comfort (21 °C on the reference plant) | +0.5 Kh |
| compressor starts | +0.5 |
| electricity | +2 % |
| setpoint writes | +20 % |

Cells whose starts check is INCONCLUSIVE after 24 replicas get replicas 24 to 47 once
(fixed in advance). Both looks use a Pocock level so the extension does not inflate the
error rate. All other criteria are judged on the first 24 replicas.

**Benefit.** Per replica, the mean over the 12 sunny credible cells (`sunny_cold`,
`sunny_mild`) of Δ(degree-hours above 21.5 °C) + 2 × Δ(degree-hours below 21 °C), in
Kh per day. Negative is better. It holds when the upper end of the interval is below 0.

**Verdict.** A planner is unlocked only when all of these hold:

1. no cell (credible or stress) FAILs;
2. every credible cell PASSes both comfort criteria;
3. the cost criteria (starts, electricity, writes) pass on the mean over the credible
   cells;
4. the benefit holds.

Cost criteria are pooled because a harmless planner cannot pass 42 cells times three cost
criteria. With the true difference at 0, the chance noise alone leaves about 1.2 to 1.6
credible cells INCONCLUSIVE on starts after the extension and 0.2 to 0.5 on writes. The comfort
criteria are not pooled: they are the ones that matter to the owner, and they are
quiet under noise (see the calibration).

## How to reproduce

Code state: the branch state at the time of writing, with uncommitted changes. Record
`git rev-parse HEAD` and `git status` next to any run you want to compare with this page.
The result files have the same seed and options, so the same code gives the same tables.

Commands, from the repository root (fish):

```fish
uv run python -m ovenbird_sim.evaluate model-plan --planner v1 --out out/mp-v1
uv run python -m ovenbird_sim.evaluate model-plan --planner v2 --out out/mp-v2
uv run python -m ovenbird_sim.evaluate model-plan --planner v2 \
    --param gain=0.5 --param max_lower_water_k=1.5 --param max_raise_water_k=1 \
    --out out/mp-v2-gentle-rec
uv run python -m ovenbird_sim.evaluate model-plan --planner none --out out/mp-none
uv run python -m ovenbird_sim.evaluate model-plan --planner noise --out out/mp-noise
uv run python -m ovenbird_sim.evaluate model-plan --planner const_water --param offset_k=-3 --out out/mp-cw
uv run python -m ovenbird_sim.evaluate model-plan --planner const_room --out out/mp-cr
uv run python -m ovenbird_sim.evaluate model-plan --help
```

- The defaults are the ones used here: seed 0, 24 replicas, extension to 48, 8 days,
  all 8 scenarios, the 5 model variants and 94 cells. The three 12-replica runs in the
  settings table add `--replicas 12 --max-replicas 12`, with the `--param` values of
  their row.
- Runtime on a 12-core machine shared with other jobs: 12 to 18 minutes per planner
  (v1 1059 s for 2688 runs, v2 717 s for 3312, v2 gentle with recovery 896 s for 3768).
  The 12-replica runs took 5 to 7 minutes. `--quick` takes about a minute.
- Every run writes `model_plan.json` (all KPIs, intervals, verdicts) and
  `model_plan_tables.md` (the full tables for all 94 cells, with the diagnostics) to
  `--out`. Those are the place to look up a single cell.
- The command exits with status 0 only when the planner is unlocked.

## Calibration of the gate

A gate is only worth something if it fails what should fail and passes what should pass.
Four planners with known behaviour were run on the same grid before any real planner.

| planner | what it is | result |
| --- | --- | --- |
| `none` | does nothing | every KPI of every pair identical; 94 of 94 cells PASS |
| `noise` | baseline against baseline with another sensor-noise seed | no FAIL in any cell; 0 of 188 comfort checks INCONCLUSIVE; 4 credible cells INCONCLUSIVE on a cost criterion only; pooled credible mean passes every criterion (starts +0.06 [−0.11, +0.24], writes +1.7 % [−1.8, +5.1]) |
| `const_water`, −3 K | constant water lowering, no gate | 38 of 42 credible cells FAIL; pooled below +3.12 [+2.94, +3.27] Kh/day |
| `const_room`, −0.3 K | constant room-target shift, forecast-blind | 42 of 42 credible cells FAIL; pooled below +1.87 [+1.74, +2.00] Kh/day |

The noise result is from the corrected run. A first noise run reused the same weather
for two pairs of scenarios and was rerun. A constant water offset of −1 K also fails 36 credible cells. A plain
constant setback cannot buy the benefit v1 shows: v1 reduces the time above the band with
a pooled change below comfort of +0.04 Kh per day, where the constant shift costs +1.87.

## Results: v1 (target shift)

Defaults, 24 replicas (48 where starts were extended). Verdict: BLOCKED.

- Credible cells: 40 PASS, 2 INCONCLUSIVE, 0 FAIL. The 2 are `sunny_mild` with UA × 0.7,
  perfect and noisy forecast, on degree-hours below comfort (+0.51 and +0.40 Kh per day,
  upper ends above the 0.5 margin).
- Stress cells: 41 PASS, 7 INCONCLUSIVE, 4 FAIL. All 4 FAILs are in `false_sun_cold`,
  below comfort (+0.65 to +0.78 Kh per day at the point estimate): aperture × 2 with a
  perfect forecast, the correct model with sun shifted by +2 h, and UA × 0.7 with a
  perfect and a noisy forecast.
- Credible mean: below comfort +0.04 [−0.02, +0.10] Kh per day, starts −0.17
  [−0.31, −0.03] per day, electricity −0.8 %, writes −4.5 %. All pass.
- Benefit: −0.675 [−0.887, −0.477] Kh per day. It holds. Time above the band falls by
  0.38 Kh per day in `sunny_cold` and 1.30 in `sunny_mild` (credible cells pooled), with no
  added time below comfort.
- Why it stops there: a target shift of 0.5 K is 1 K of water through the controller's
  `kp`, which is the setpoint rounding step. The planner has little authority below that.

## Results: v2 (water feed-forward), default settings

Gain 1, at most 3 K down, no recovery, 24 replicas. Verdict: BLOCKED.

- Credible cells: 13 PASS, 6 INCONCLUSIVE, 23 FAIL. 18 cells FAIL on comfort (below
  comfort).
- Stress cells: 35 FAIL.
- Credible mean: below comfort +0.55 [+0.47, +0.62] Kh per day (INCONCLUSIVE against
  +0.5), starts +0.94 [+0.77, +1.12] per day (FAIL), electricity −0.7 %, writes
  +22.4 % [+18.7, +26.3] (INCONCLUSIVE against +20 %).
- Benefit: −1.422 [−1.729, −1.116] Kh per day. About twice v1's, and it holds. It is paid
  for in comfort and compressor starts.

## v2 settings tried

Credible mean = mean over the 42 credible cells. Comfort FAIL counts credible cells that
FAIL on comfort. "Comfort INC" counts credible cells INCONCLUSIVE on comfort without a
comfort FAIL. Rows 3 to 5 are v2 with the settings shown, as `--param`.

| setting | replicas | credible mean: below / starts / writes | credible FAIL / comfort INC | stress FAIL | benefit, Kh/day | verdict |
| --- | --- | --- | --- | --- | --- | --- |
| v1 defaults | 24 | +0.04 / −0.17 / −4.5 % | 0 / 2 | 4 | −0.675 [−0.887, −0.477] | BLOCKED |
| v2 defaults (gain 1, down 3 K) | 24 | +0.55 / +0.94 / +22.4 % | 23 / 9 | 35 | −1.422 [−1.729, −1.116] | BLOCKED |
| gain 0.5, down 1.5 K | 12 | +0.41 / +0.36 / +11.2 % | 7 / 20 | 17 | −0.737 [−1.134, −0.355] | BLOCKED |
| gain 0.3, down 1.0 K | 12 | +0.22 / +0.10 / +3.8 % | 0 / 19 | 5 | −0.591 [−1.156, −0.128] | BLOCKED |
| gain 0.5, down 1.5 K, raise 1 K | 12 | +0.27 / +0.12 / +4.6 % | 0 / 20 | 12 | −0.780 [−1.303, −0.382] | BLOCKED |
| gain 0.5, down 1.5 K, raise 1 K | 24 | +0.26 / +0.12 / +4.4 % | 0 / 15 | 13 | −1.014 [−1.327, −0.736] | BLOCKED |

The 12-replica rows are screening runs, not gate results: their intervals are wider and
the starts extension is off. The last row is the full run of the same setting.

In the full run of gain 0.5 with recovery, no cell FAILs among the credible ones and
every pooled criterion passes with room. It is still BLOCKED: 15 credible cells are
INCONCLUSIVE on comfort, and 13 stress cells FAIL. This setting is the most promising
candidate: it keeps about 70 % of v2's default benefit at a credible mean below comfort
of +0.26 Kh per day.

## Credible cells per scenario

Mean over the six credible cells of a scenario (UA × 0.7, correct and UA × 1.4, each with
a perfect and a noisy forecast). Change with the plan minus without, Kh or starts per
day, mean over the first 24 replicas, with a 95 % t interval over replicas. These
intervals are descriptive: the gate judges each cell, not this pool. Outcome counts are
the gate outcomes of the six cells (P PASS, I INCONCLUSIVE) on all criteria.
`false_sun_cold` has no credible cell. Full tables:
`model_plan_tables.md` of a run.

v1 (defaults):

| scenario | Δ below 21 °C | Δ above 21.5 °C | Δ starts/day | cells |
| --- | --- | --- | --- | --- |
| sunny_cold | +0.12 [−0.03, +0.27] | −0.38 [−0.64, −0.11] | −0.27 [−0.66, +0.11] | 6 P |
| sunny_mild | +0.04 [−0.08, +0.16] | −1.30 [−1.65, −0.95] | −0.10 [−0.30, +0.09] | 4 P, 2 I |
| cloudy | +0.02 [−0.09, +0.12] | −0.11 [−0.17, −0.05] | −0.17 [−0.41, +0.07] | 6 P |
| cold_front | −0.18 [−0.24, −0.12] | −0.04 [−0.06, −0.02] | +0.02 [−0.09, +0.13] | 6 P |
| missing_sun | +0.21 [+0.09, +0.34] | −0.24 [−0.32, −0.16] | −0.42 [−0.71, −0.14] | 6 P |
| unforecast_sun | +0.05 [−0.12, +0.22] | −0.15 [−0.38, +0.08] | −0.06 [−0.42, +0.29] | 6 P |
| mixed_week | +0.02 [−0.09, +0.12] | −0.41 [−0.64, −0.17] | −0.19 [−0.54, +0.16] | 6 P |

v2, gain 0.5, down 1.5 K, raise 1 K (24 replicas):

| scenario | Δ below 21 °C | Δ above 21.5 °C | Δ starts/day | cells |
| --- | --- | --- | --- | --- |
| sunny_cold | +0.47 [+0.29, +0.65] | −1.55 [−1.82, −1.28] | +0.32 [−0.11, +0.76] | 2 P, 4 I |
| sunny_mild | +0.53 [+0.38, +0.68] | −2.48 [−2.82, −2.14] | −0.03 [−0.30, +0.24] | 6 I |
| cloudy | +0.07 [−0.04, +0.17] | −0.10 [−0.16, −0.03] | +0.04 [−0.27, +0.35] | 6 P |
| cold_front | +0.00 [+0.00, +0.00] | +0.00 [+0.00, +0.00] | +0.00 [+0.00, +0.00] | 6 P |
| missing_sun | +0.22 [+0.08, +0.36] | −0.31 [−0.40, −0.22] | −0.07 [−0.38, +0.24] | 6 P |
| unforecast_sun | +0.12 [−0.03, +0.27] | −0.32 [−0.58, −0.06] | +0.14 [−0.20, +0.48] | 4 P, 2 I |
| mixed_week | +0.40 [+0.26, +0.55] | −1.34 [−1.60, −1.08] | +0.44 [+0.06, +0.82] | 6 I |

v2 removes 1.9 to 4 times as much time above the band as v1 in the two sunny scenarios. It pays
with +0.4 to +0.5 Kh per day below comfort in the two sunny scenarios and `mixed_week`,
close to the 0.5 Kh margin, so those cells cannot be called safe. In the same scenarios
v1 stays within +0.12.

## Conclusion

- **No planner may be switched on from this evaluation.** Both are BLOCKED. `on` stays
  locked.
- **v1 stays the planner behind `control_model_use`, in `shadow` only.** It never FAILs a
  credible cell and its pooled cost is below zero. Two credible cells (`sunny_mild`, UA × 0.7)
  are INCONCLUSIVE on comfort, and four `false_sun_cold` stress cells FAIL. Its benefit is
  real but smaller.
- **v2 with half gain and recovery is the most promising candidate.** At full strength it
  costs comfort and compressor starts. With gain 0.5, at most 1.5 K down and 1 K up after
  the sun it has no credible FAIL, a credible mean below comfort of +0.26 Kh per day and
  +0.12 starts per day, and a benefit of −1.014 Kh per day. v2 is not wired into the
  service.

What is needed before `on` can be considered for any planner:

1. Resolve the credible cells that are INCONCLUSIVE on comfort: more replicas, or a
   tighter design (fewer, better-chosen cells), with the margin and the verdict rule
   unchanged.
2. Fix the stress FAILs with a wrong solar aperture and with the sun shifted by 2 h,
   in particular `false_sun_cold`, or show that the model gates keep such models and
   forecasts out.
3. Repeat the evaluation on a plant fitted to the owner's house, with a model learned
   from that plant's history.
4. A shadow period on the real installation, reviewed by the owner (two weeks at least,
   as in the 2026-11-27 decision).

## Limits

- One plant, the simulated reference house. The numbers say nothing about another house's
  magnitude.
- Weather and forecast errors are synthetic: draws from fixed distributions. Real
  forecast errors are correlated and can be larger.
- "Correct model" has the plant's own structure and true parameters. A fitted model of a
  real house is always wrong in structure too. UA and aperture errors only stand in for it.
- No hot water and no wood stove. The service blocks the plan during a wood-stove
  episode, but this evaluation does not test that.
- Eight days per run: slow effects over weeks or seasons are not covered.
- The per-scenario table is pooled by a simple method for reading, not the gate's.
  The gate result for any one cell is in the full tables.
- The decision record is
  [2026-11-28](../decisions/2026-11-28-model-plan-after-evaluation.md).
