# The model plan after the evaluation

Date: 2026-11-28. Source: [model-plan.md](../evaluation/model-plan.md),
[design.md](../design.md), "Planner".
Amends: [The learned house model in the controller](2026-11-27-learned-model-in-controller.md)
(2026-11-27), point 1 and the alternative "Direct water feed-forward from the model".
Superseded by: [The house model is removed](2026-11-28-house-model-removed.md)
(2026-11-28). Neither planner is kept; both are removed in 0.6.0.

## Decision

1. **The target-shift planner (v1) stays the wired implementation.** The service runs it
   behind `control_model_use` in `shadow` only. Its settings and bounds are those of
   2026-11-27.
2. **A water feed-forward (v2) was built and evaluated.** The 2026-11-27 record rejected
   it. It was built anyway because a room-target shift has little authority below 0.5 K:
   the controller's `kp` turns 0.5 K of target into 1 K of water, which is the setpoint
   rounding step. v2 lowers the water setpoint ahead of forecast sun by the sun's heat
   expressed as an outside-temperature rise, moved down the heating curve. It is
   bounded (default at most 3 K down, 0.5 K steps, optional raise after the sun up to
   `max_raise_water_k`), and the controller scales it by the room authority: it removes
   the offset when the measured room is below comfort by more than a sensor step.
3. **Neither planner is unlocked.** The evaluation did not pass the gate for either one
   (see the numbers below). `control_model_use` `on` stays locked
   (`ON_LOCKED` in `ovenbird.config.validation.modelplan`).
4. **What the evaluation showed**, on the simulated reference plant, 24 replicas per
   cell, 94 cells (42 credible):
   - v1: no credible cell FAILs, 2 credible cells are INCONCLUSIVE on comfort, 4 stress
     cells FAIL (all `false_sun_cold`). Benefit −0.675 Kh per day, credible mean below
     comfort +0.04 Kh per day.
   - v2 at full strength (default settings): 23 credible cells FAIL, credible mean
     below comfort +0.55 Kh per day, starts +0.94 per day (FAIL). Benefit −1.422 Kh per
     day: much larger than v1's, but it costs comfort and compressor starts.
   - v2 with half gain, at most 1.5 K down and 1 K up after the sun: no credible FAIL,
     credible mean below comfort +0.26 Kh per day, starts +0.12 per day, benefit −1.014
     Kh per day. Still BLOCKED: 15 credible cells INCONCLUSIVE on comfort and 13 stress
     cells FAIL.
5. **Conditions for unlocking `on`** (any planner), all of them:
   - the evaluation verdict passes: no cell FAILs, every credible cell passes both
     comfort criteria, the cost criteria pass on the credible mean, and the benefit
     holds. For this the INCONCLUSIVE credible comfort cells need to be resolved (more
     replicas or a tighter design) and the stress FAILs with a wrong aperture or a
     shifted sun need an answer;
   - the evaluation is repeated on a plant fitted to the owner's house;
   - two weeks of live shadow data on the real installation, reviewed by the owner (as
     in 2026-11-27).

## What stays in force from 2026-11-27

Everything except the sentence in the alternatives that rejects a direct water
feed-forward: the model plan is one bounded path through the plan hook, with the switch,
the guards and the fit in the image as described there. A water path would be a second
slice kind on the same hook, with its own bounds, and it needs this record's conditions
before it is switched on.

## Why

- A room-target shift of at most 0.5 K reaches the water only through `kp` (1 K of water)
  and the setpoint rounding, so its authority is small. That is why v1's benefit is
  small.
- A water offset acts on the heat directly and leaves the room feedback untouched: a
  correct plan makes no room error. That is why v2's benefit is larger: 1.5 to 2.1 times v1's in the runs above.
- The same directness is the cost. A water offset that is wrong is not absorbed by the
  target bound, it shows up as a room deficit and as extra compressor starts. The authority
  fade limits the deficit but does not remove it.
- The gate was calibrated first: a planner that does nothing passes exactly, a noise
  planner never FAILs a cell, a constant −3 K water offset fails 38 of 42 credible cells
  and a constant −0.3 K room shift fails all 42. A result is therefore not noise.
- Neither planner passes, so the decision to keep `on` locked follows from the 2026-11-27
  condition: no meaningful worsening of undershoot or compressor starts, shown with wrong
  models and wrong forecasts.

## Alternatives rejected

- **Unlock v1 because it has no credible FAIL.** Two credible cells are INCONCLUSIVE and
  four stress cells FAIL. The condition of 2026-11-27 asks for no worsening with wrong
  models and missing-sun forecasts, and `false_sun_cold` is that case.
- **Unlock v2 at half gain with recovery.** It has the largest benefit among the
  candidates with no credible FAIL, but 15 credible comfort cells are INCONCLUSIVE and
  13 stress cells FAIL.
- **Wire v2 into the service in `shadow` now.** Possible, but shadow data for a planner
  that is expected to change is of little use. The evaluation comes first.

## Consequences

- The v2 planner (`plan_water`) and the water slice (`PlanSlice.water_offset_k`) stay in
  the core package and in the evaluation. The service does not call `plan_water`: it
  issues only room-offset slices.
- The controller can apply a water slice (bounds, authority fade). The controller's decision
  extras carry `model_plan_water_requested_k`, `model_plan_water_applied_k` and
  `model_plan_authority` for water slices. Nothing in the service produces them today.
- No setting, API field or persisted state changes. The water bounds and the authority
  fade are settings of the core configuration group `model_plan`; the service does not
  expose them.
- The evaluation page [model-plan.md](../evaluation/model-plan.md) is replaced. Its numbers
  are from the simulated reference plant only.
