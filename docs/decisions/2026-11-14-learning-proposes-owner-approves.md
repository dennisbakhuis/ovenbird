# The learner proposes, the owner approves

Date: 2026-11-14 (design). Source: [design.md](../design.md), "Learning loop".

## Decision

Nothing the self-learning house model produces changes control by itself. It becomes a
configuration draft labelled "Suggested by the house model", which the owner reviews.

## Why

A learned model can be wrong in ways the safety limits do not catch. A visible draft keeps
the owner in control and every change auditable.

## Consequences

- The learner writes proposals only. Applying a proposal uses the normal config
  validate, apply and rollback path.
