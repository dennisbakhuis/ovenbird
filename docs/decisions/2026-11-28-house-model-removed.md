# The house model is removed

Date: 2026-11-28. Source: [house-model-attempt.md](../notes/house-model-attempt.md),
[model-plan.md](../evaluation/model-plan.md).
Supersedes: [The learned house model in the controller](2026-11-27-learned-model-in-controller.md)
(2026-11-27) and [The model plan after the evaluation](2026-11-28-model-plan-after-evaluation.md)
(2026-11-28).

## Decision

1. **The house model goes in 0.6.0.** The three-node model, the nightly learner, its
   trust gates, champion and challenger, pins and bounds, the what-if views and both
   model planners (v1 room-target shift, v2 water offset) are removed, with the switch
   `control_model_use` and its settings. The scientific stack leaves the image.
2. **House basics replace it.** A simple estimate in pure Python from the daily
   aggregates: the heat loss and the outside temperature at which no heating is needed,
   from a regression of daily heat on the indoor–outdoor difference, next to the heat
   the pump delivers.
3. **Kept:** the generic plan hook in the controller (`PlanSlice`), the closed-loop
   evaluation harness and its three-valued gate, and the daily aggregates.
4. **The attempt is documented** in
   [house-model-attempt.md](../notes/house-model-attempt.md). The code stays at the
   tag `v0.5.0`.

## Why

- Only the heat-loss figure was robustly identifiable. The model's own heat-loss gate
  already required agreement with a four-parameter daily energy signature, so the
  simple method was the referee.
- Room prediction had little to show. The dynamics gate asked only for skill above zero
  against "the room stays as it is" over 6 h; the 24 h skill was reported only. In a
  room the controller holds flat there is little to predict.
- Steering never passed. v1 was BLOCKED (2 credible cells INCONCLUSIVE on comfort, 4
  stress cells FAIL); a 0.5 K target shift is 1 K of water through `kp`, which is the
  setpoint rounding step. v2 was BLOCKED at every setting tried (at best 15 credible
  cells INCONCLUSIVE on comfort, 13 stress cells FAIL). `on` was never unlocked.
- The cost was high: the image grew from about 146 MB to about 356 MB, the service ran a
  nightly learner child process, the learner's file format was defined in three places
  and an experimental planner lived inside the controller.

## Alternatives rejected

- **Keep the model for insight only, without the planners.** It still needs the
  learner, the scientific stack and the file format, for a heat-loss figure the simple
  estimate gives as well.
- **Keep v1 in `shadow`.** Shadow data for a planner that cannot pass its gate on this
  house decides nothing.
- **Tune v2 further.** Every setting tried traded the benefit against comfort and
  compressor starts; the stress cases with a wrong aperture or shifted sun stayed open.

## Consequences

- The settings of the model plan and the learner are retired; the 0.6.0 upgrade notes
  list them. A 0.5.0 settings database must still load.
- The house-model API endpoints go with the model. Model files already in
  `<data_dir>/models` are no longer read.
- A new attempt needs a house with more temperature swing, a PV or tariff signal that
  gives a reason to move heat in time, and a longer history; then the evaluation on a
  plant fitted to that house and a reviewed shadow period. See the note.
- The rule of [The learner proposes, the owner approves](2026-11-14-learning-proposes-owner-approves.md)
  stays: any suggestion ovenbird makes is a draft the owner applies.
