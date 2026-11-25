# Simulation first

Date: 2026-11-14. Source: [design.md](../design.md), "Phases".

## Decision

The complete system must run fully simulated on the recorded dataset before anything
touches the live setup. No live-pump spikes, experiments or deployments until that
simulated run is successful. Production then runs in the owner's cluster, not on the NAS.

## Why

A wrong setpoint on a live pump costs comfort and possibly hardware. A recorded dataset
allows unlimited, repeatable runs at no risk.

## Consequences

- The plant model, the simulated HeishaMon and the harness are first-class packages.
- Live steps (shadow, trials, cut-over) each need the owner's explicit go.
- The recorder on the NAS stays the only live component.
