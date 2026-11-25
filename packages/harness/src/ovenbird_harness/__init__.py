"""Fast closed-loop runs of the assembled ovenbird service against the simulated plant.

The harness drives the service's own components (MQTT ingest, Home Assistant input,
control loop, command adapter and worker, safety monitors, alarms, history writer and
persistence) on a manually stepped clock, feeds them from the simulated HeishaMon and
a fake Home Assistant, and checks invariants over every decision and command.
"""
