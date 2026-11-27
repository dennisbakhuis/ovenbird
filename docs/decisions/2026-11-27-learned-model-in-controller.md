# The learned house model in the controller

Date: 2026-11-27. Source: [design.md](../design.md), "Planner" and "Learning loop".
Supersedes in part: [The learner proposes, the owner approves](2026-11-14-learning-proposes-owner-approves.md).
Amended by: [The model plan after the evaluation](2026-11-28-model-plan-after-evaluation.md)
(2026-11-28). A water feed-forward, rejected below, was built and evaluated; neither planner
is unlocked and `on` stays locked. The rest of this record stays in force.

## Decision

1. **One bounded path.** The learned model may act inside the controller through one
   path only: a model planner that produces a room-target offset through the existing
   plan hook (`PlanSlice`). The offset comes from the model's predicted effect of the
   forecast sun and forecast outside temperature over the next hours. The bounds are
   configuration, with defaults: set back at most 0.5 K, pre-heat at most 0.3 K, horizon
   6 h. Start ramp, cycling floor, wood-stove pause and the safety clamp are unchanged
   and still apply after the plan. There is no direct water-temperature term from the
   model, and no automatic change of the curve or the PI gains.
2. **A switch, `control_model_use`.** `off` (default): no model plan. `shadow`: the
   plan is computed and logged but has no effect; the decisions are byte-identical to
   `off`. `on`: the plan is applied. `on` is allowed only after both:
   - an offline evaluation with deliberately wrong models and with missing-sun
     forecasts shows no meaningful worsening of undershoot or compressor starts;
   - two weeks of live shadow data, reviewed by the owner.
3. **Guards.** Any failed guard means no plan, and the reason is shown. The guards: the
   model is promoted (the champion), credible, and recently re-validated with a held-out
   24 h room error below a configured limit; the forecast is fresh; the room value is
   trusted; no wood-stove episode is active and its recovery tail has passed.
4. **Where the fit runs.** The fit runs inside the ovenbird image, as a supervised
   low-priority child process of the service (one container): weekly at night and on
   request. Limits for the child: 30 min wall time and 768 MB memory. This replaces the
   separate learner container as the default; the separate image stays possible. The
   controller package (core) stays pure Python. Model files stay untrusted JSON, read
   through the existing checks.
5. **What the owner can set.** The owner can state facts about the house as weak priors,
   and can pin or bound four learned quantities only: heat loss (UA), time constant,
   solar aperture and internal gains.

## What stays in force from 2026-11-14

Superseded: the sentence "Nothing the self-learning house model produces changes control
by itself", and only for the bounded plan offset of point 1 with `control_model_use` on.

Still in force: everything else the learner produces goes through draft, review and
apply. Curve proposals, PI gains and any other configuration change become a draft
labelled "Suggested by the house model", applied through the normal validate, apply and
rollback path.

## Why

- Sun and outside temperature in the next hours are what the room feedback reacts to
  late. The model sees them coming; a small shift of the room target is enough to use
  that.
- A room-target offset has a known worst case. Whatever the model error, the comfort
  effect is at most the bound: the PI tracks a target at most 0.5 K below or 0.3 K above
  comfort. All other protections act after it, unchanged.
- `shadow` gives live evidence at no risk, and its decisions can be compared with `off`
  byte for byte.
- The guards stop a stale, unvalidated or event-disturbed model from acting. A failed
  guard falls back to normal control, which is the state the controller is in today.
- Measured on 2026-11-27: the building-only fit on a 41-day simulated history took 11 s
  of one CPU thread and 237 MB peak memory on a development laptop (fit 6.9 s, daily
  errors 2.5 s, load 0.9 s). That is small enough to run next to the service.
- The four quantities the owner can pin or bound are the ones the fit identifies.
  Internal conductances are not pinnable because they are not separately identifiable.

## Alternatives rejected

- **Direct water feed-forward from the model.** It needs a heat-pump and emitter model
  on top of the building model, and its error has no bound in room terms.
- **Fitting inside the service process.** A long fit, a memory peak or a crash in the
  scientific stack would put the control loop at risk. A child process with limits keeps
  it apart.
- **A second container as the default.** This was the previous default. It means an
  extra image, extra mounts and a schedule for every user, for a fit that takes seconds.

## Consequences

- New settings: `control_model_use` and the plan bounds and horizon; a held-out error
  limit for re-validation; owner priors, pins and bounds for the four quantities.
- The production image carries the scientific stack for the fit. Core does not import
  it.
- How the model plan combines with the rule planner (phase 5) is not decided yet.
