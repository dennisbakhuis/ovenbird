# The learner proposes, the owner approves

Date: 2026-11-14 (design). Source: [design.md](../design.md), "Learning loop".
Superseded in part by: [The learned house model in the controller](2026-11-27-learned-model-in-controller.md)
(2026-11-27). The first sentence below no longer holds for the bounded room-target plan
of that record, when `control_model_use` is `on`. Everything else here stays in force.
Updated by: [The house model is removed](2026-11-28-house-model-removed.md)
(2026-11-28). The house model is removed in 0.6.0; the rule that a suggestion is a draft
the owner applies stays in force for every suggestion ovenbird makes.

## Decision

Nothing the self-learning house model produces changes control by itself. It becomes a
configuration draft labelled "Suggested by the house model", which the owner reviews.

## Why

A learned model can be wrong in ways the safety limits do not catch. A visible draft keeps
the owner in control and every change auditable.

## Consequences

- The learner writes proposals only. Applying a proposal uses the normal config
  validate, apply and rollback path.
