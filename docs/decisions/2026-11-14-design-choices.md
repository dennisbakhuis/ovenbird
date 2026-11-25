# Core design choices

Date: 2026-11-14 (design review rounds 1 and 2). Source: [design.md](../design.md), "Context".

## Decision

- Python 3.14 with asyncio; Svelte 5 and TypeScript for the UI.
- Production is a standalone container, with an optional Home Assistant app.
- Inputs from HA entities are optional and the default; MQTT is the alternative.
- Emitter type is a setting.
- A rule planner runs live first. The LP optimiser stays in shadow until it wins.
- Core control comes first; smart features follow after cut-over.
- Supervised winter trials this winter, with Node-RED on standby.
- The HA write path is a custom integration. MQTT discovery entities stay read-only.
- Identification experiments are a free-float night and setpoint steps, with no live A/B blocks.

## Why

The goal is a better controller, not a copy of Node-RED. It must keep running when Home
Assistant restarts, and it must be explainable and testable on recorded data.

## Consequences

- Everything except HeishaMon is optional and configured in a setup wizard.
- Experiments run only in scripted experiment mode, inside the safety limits.
