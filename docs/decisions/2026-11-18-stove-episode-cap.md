# Wood stove: one episode per cooling cycle

Date: 2026-11-18. Source: [design.md](../design.md), wood-stove mode.

## Decision

After the hard cap of a stove episode, only a new fast room rise starts another
episode, and only once the room has cooled. After a loss of trust in the room sensor, the
sensor must be trusted again for 15 min first.

## Why

One heating loop and the room sensor are in the living room. A stove there pushes the room
PI to its lower limit while the hall and bedroom still need heat. A stuck or failed sensor
must not look like a stove for days.

## Consequences

- Stove mode is opt-in (`control_stove_*`) and has a hard cap.
- A sensor that fails high is treated as a fault, not a stove.

## Update 2026-11-20: cap default 8 h

The owner set the default of `control_stove_max_active_s` to 8 h (was 24 h). It stays a
user setting, bounded by 1 h to 24 h, so 8 h is accepted. A long fire can keep the living
room above the exit level for more than a day; with the new default a long burn ends
stove mode after 8 h (`max_active`).

After the cap nothing changes: the level trigger waits until the room has been below the
exit threshold once, and only a new fast rise starts another episode. A long burn
therefore gives an 8 h episode and then normal room control, with the stove still warm.
