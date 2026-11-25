# No pump-duty command during a defrost

Date: 2026-11-15. Source: [CHANGELOG.md](../../CHANGELOG.md), [design.md](../design.md), "Example installation".

## Decision

During a defrost ovenbird sends no pump-duty command and keeps its desired duty for
afterwards. The adapter drops a queued duty while a defrost is reported. A DHW run keeps
the heat duty like a running compressor.

## Why

In recorded data the pump drives its own duty during a defrost and ignores the setting:
`Pump_Duty` sits at a fixed high value for most defrost samples, while `Max_Pump_Duty`
keeps the setting. The pump returns to the setting by itself within seconds after the
defrost. The recorded controller still sent duty commands during defrosts, without effect.

## Consequences

- Fewer useless commands on the bus.
- The duty is decided from the compressor state when that is known.
