# The house model: what we tried and why we stopped

Status: abandoned. Shipped in 0.5.0 (2026-11-27), removed in 0.6.0. Decision:
[2026-11-28](../decisions/2026-11-28-house-model-removed.md). The code is kept at the
git tag `v0.5.0`.

## What we wanted

The room feedback acts late: only once the sun has already warmed the room, or a cold
front has cooled it. The idea was to learn a physical model of the house from its own
history and use it to explain the house (heat loss, cooling speed, sun gain), to answer
what-if questions, and to steer ahead of forecast sun and cold.

## What was built

### The model

A chain of three heat stores, called *nodes*. Each node has a temperature and a *heat
capacity* (joules per kelvin). Heat flows between neighbours through a *conductance*
(watts per kelvin of temperature difference).

1. **Loop**: the water in the heating circuit. The measured heat from the pump enters here.
2. **Emitter**: floor loop and screed, or radiators. The fast node, about an hour.
3. **Building**: room air, furniture, inner walls. The slow node, days. The room sensor
   reads it.

Heat flows loop → emitter → building → outside. Eight parameters were fitted: the three
capacities, the loop–emitter and emitter–building conductances, the *heat-loss
coefficient* UA (watts lost per kelvin between inside and outside, ventilation
included), the *solar aperture* (an effective window area: watts per W/m² of sun on a
horizontal surface) and constant *internal gains* (free heat from people and
appliances). A direct loop-to-room path, the sun's share onto the floor and a daily
swing of the gains were held fixed, because the data could not tell them apart. The
gains could not be separated from UA either: both set the outside temperature at which
no heating is needed. They were reported as "net free heat".

The *time constant* is roughly capacity divided by conductance: how long the house
takes to lose about two thirds of a temperature difference.

### The nightly learner

The *learner* ran as a low-priority child process of the service, weekly at night or
on request, limited to 30 minutes and 512 MB.

- **Fit.** The last 60 days of 1-minute history. Driven by measured heat, outside
  temperature and sun, the model was simulated freely over daily windows. A
  least-squares optimiser moved the parameters until simulated loop and room
  temperatures matched the measured ones.
- **Validation.** *Rolling origin*: fit only on days before a 14-day test block, then
  predict that block from an origin every 3 hours, 1 to 24 hours ahead. *Skill* is
  1 − (model error / persistence error), where *persistence* is the forecast "the room
  stays as it is". Above zero is better than persistence.
- **Uncertainty.** 20 refits on resampled sets of whole days (a *day-block bootstrap*).

**Champion and challenger.** The model in use was the *champion*. Each run fitted a
*challenger* on the days before the latest 14. Both predicted those days. The challenger
won only if it was not worse and lost no trust gate the champion passed. Every run
re-checked the champion on new data.

**Three trust gates**, one per use:

- *Heat loss*: for the insulation score, curve proposal and what-if steady state. Enough
  heating weather (20 heating days in the fit window, 30 for the signature, a 10 K
  span), a UA range within 30 %, a UA stable across training windows, and agreement
  within 20 % with a simple *energy signature*: a daily regression with four
  parameters, heat = UA × (inside − outside) − sun term − free gains + storage term.
- *Dynamics*: for the cool-down what-if and planner v1. Skill above zero over the first
  6 hours. The 24-hour skill was shown, not gated.
- *Sun*: for planner v2. At least 5 sunny test days and a measured sun response within a
  factor 1.5 of the model's.

**Owner input.** House facts (build period, volume, windows, occupants) were weak
starting values. *Pins and bounds* fixed or limited UA, the time constant, the aperture
and the gains. *Left-out days* were masked from fit and scoring, like wood-stove
periods.

**What if.** The House page showed the heat and water temperature needed to hold a
comfort temperature at a chosen outside temperature, sun and stove heat, how fast the
room cools with the heating off, the live heat balance, and the room against the
model's prediction of 24 hours earlier.

### The planners

Both used a generic *plan hook*: a time-limited slice handed to the controller, which
still applies its start ramp, cycling rules, stove pause and safety clamps afterwards.

- **v1, room-target shift.** The model predicted how far forecast sun and outside
  temperature would push the room over 6 hours, and the room target moved against it:
  at most 0.5 K down, 0.3 K up. It ran in `shadow` only: computed and recorded, never
  applied.
- **v2, water offset.** Forecast sun, read as an equivalent rise in outside temperature,
  lowered the water setpoint along the heating curve, by default at most 3 K. It faded
  out when the room fell below comfort. It was never wired into the service.

`control_model_use` (`off`, `shadow`, `on`) switched it. `on` stayed locked.

### The evaluation

The planners were tested in closed loop on the simulated reference house
([report](../evaluation/model-plan.md)). Eight weather scenarios were combined with
deliberately wrong models (UA × 0.7 or × 1.4, aperture × 0.5 or × 2) and wrong
forecasts (noisy, sun 2 hours off, sun that never came): 94 *cells*, 42 *credible*
(errors the gates would let through) and 52 *stress*. Each cell ran 24 weather
*replicas*, with and without the plan. Comfort is in *degree-hours* (Kh): 1 K too cold
for 1 hour is 1 Kh. Each criterion gave PASS, FAIL or INCONCLUSIVE (the interval
straddles the margin). The gate was calibrated first: doing nothing passed every cell,
a constant setback failed nearly every credible one.

## What we found

**Steering did not pass.**

| planner | credible FAIL / comfort INCONCLUSIVE | stress FAIL | below comfort, Kh/day | starts/day | benefit, Kh/day |
| --- | --- | --- | --- | --- | --- |
| v1 | 0 / 2 | 4 | +0.04 | −0.17 | −0.675 |
| v2, defaults | 23 / 9 | 35 | +0.55 | +0.94 | −1.422 |
| v2, half gain, 1.5 K down, 1 K up | 0 / 15 | 13 | +0.26 | +0.12 | −1.014 |

*Benefit* is less time above the comfort band plus, counted double, less time below it;
negative is better. v1 was harmless but weak: 0.5 K of target becomes 1 K of water
through the room feedback, and 1 K is the setpoint rounding step, so it could barely
act. v2 could act, but a wrong water offset shows up directly as a cold room and extra
compressor starts. Every variant stayed blocked.

**Only the heat loss was robust.** The heat-loss gate needed the four-parameter
signature to agree, so the simple method was the referee. The capacities and inner
conductances were not separately identifiable.

**Room prediction looked better than it was.** The controller holds the room nearly
flat, so persistence is hard to beat and there is little to predict. The dynamics gate
asked only for skill above zero. The data are closed loop too: the controller adds heat
when the room cools, which can bias the fit.

**The evaluation flattered the model.** Its "correct" model had the simulator's own
structure. A model fitted to a real house is wrong in structure as well.

**The cost was high.** The image grew from about 146 MB to about 356 MB. The service
gained a nightly child process with limits, locks and a schedule. The learner's file
format was defined in three places, and an experimental planner lived inside the
controller.

## Why we stopped

The one reliable output, the heat loss, comes as well from a much simpler method. The
rest was not identifiable or not good enough to steer with, at a large cost in code.

## What replaces it

From 0.6.0, the *house basics*: a simple estimate in pure Python from the daily
aggregates. A regression of daily heat on the indoor–outdoor difference gives the heat
loss and the outside temperature at which no heating is needed, shown next to the heat
the pump delivers. No scientific libraries, no learner process.

Kept from the attempt: the plan hook in the controller, the closed-loop evaluation
harness with its three-valued gate, and the daily aggregates.

## What a new attempt would need

- **A house with more swing**: night setbacks or large sun gains, so the room moves.
- **A reason to move heat in time**: PV surplus or a dynamic tariff. Without one,
  steering ahead only trims overshoot.
- **Longer history**: a full heating season, with high spring sun as well as low autumn
  sun.
- **A real-house test**: the gate repeated on a plant fitted to the actual house, with
  the inconclusive comfort cells resolved and the stress cases answered, then a
  reviewed shadow period.

## Where the code lives

At tag `v0.5.0` (`git show v0.5.0:<path>`):

- model maths: `packages/core/src/ovenbird_core/housemodel.py`
- planners: `packages/core/src/ovenbird_core/control/planner.py`
- fit: `packages/sim/src/ovenbird_sim/identify/`
- learner and gates: `packages/sim/src/ovenbird_sim/learn/`
- evaluation: `packages/sim/src/ovenbird_sim/evaluate/` (`modelplan.py`, `plangate.py`)
- service: `packages/service/src/ovenbird/insight/` (`house.py`, `learnrun.py`,
  `whatif.py`), `packages/service/src/ovenbird/control/modelplan.py`
