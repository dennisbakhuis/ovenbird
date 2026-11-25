"""Run a :class:`~ovenbird_sim.heishamon.board.SimulatedHeishaMon` against an MQTT broker.

The runner connects with HeishaMon's last will (``LWT`` ``Offline``, retained),
subscribes to ``<base>/commands/#`` and runs one query cycle every
``query_interval / speed`` real seconds, anchored to the monotonic clock so a slow
cycle does not accumulate drift. Brokers other than local ones are refused unless
explicitly allowed: the simulator must never reach the live HeishaMon's broker.

When the recorded weather runs out (``at_end`` ``stop``, the default) the runner says
so in one log line, publishes ``LWT`` ``Offline`` (retained) so ovenbird sees the
HeishaMon go away, disconnects and returns :data:`END_OF_WEATHER`; the command line
then idles instead of exiting, so a container with a restart policy does not restart
the simulation from its start. ``loop`` wraps the weather instead
(:class:`~ovenbird_sim.heishamon.weather.LoopedWeather`, built by the command line).

With a fault injection prefix it also subscribes to ``<prefix>/#``. With a state file
the pump registers are written there (atomically) whenever they change, so a
restarted simulator comes back with the registers the pump had, like a real pump
whose HeishaMon reboots.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import secrets
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

import aiomqtt

from ovenbird_sim.heishamon.board import Publication, SimulatedHeishaMon
from ovenbird_sim.heishamon.registers import Registers, registers_to_json
from ovenbird_sim.heishamon.weather import weather_end

LOGGER = logging.getLogger("ovenbird_sim.heishamon")
LOCAL_HOSTS: Final = frozenset({"localhost", "127.0.0.1", "::1", "mosquitto"})
RECONNECT_DELAY_S: Final = 2.0
STATUS_EVERY_S: Final = 3600.0
END_OF_WEATHER: Final = "end_of_weather"
FINISHED: Final = "finished"


class RemoteBrokerError(RuntimeError):
    """The broker is not a local one and remote brokers were not allowed."""


def check_broker(host: str, *, allow_remote: bool = False) -> None:
    """Refuse non-local brokers unless ``allow_remote``.

    Raises
    ------
    RemoteBrokerError
        For any host outside :data:`LOCAL_HOSTS` without ``allow_remote``.
    """
    if host.strip().lower() in LOCAL_HOSTS or allow_remote:
        return
    raise RemoteBrokerError(
        f"refusing broker {host!r}: the simulated HeishaMon publishes main/* and answers "
        "commands, which must never reach a live installation; pass --allow-remote-broker "
        "only for a dedicated test broker"
    )


@dataclass(frozen=True, slots=True)
class RunnerConfig:
    """Connection and pacing.

    Parameters
    ----------
    host, port
        Broker.
    speed
        Simulated seconds per real second.
    duration_s
        Simulated seconds to run; ``None`` runs until cancelled.
    allow_remote
        Allow a broker outside :data:`LOCAL_HOSTS`.
    status_every_s
        Simulated seconds between status log lines.
    state_file
        Where the registers are saved whenever they change; ``None`` disables it.
    """

    host: str = "localhost"
    port: int = 1883
    speed: float = 1.0
    duration_s: float | None = None
    allow_remote: bool = False
    status_every_s: float = STATUS_EVERY_S
    state_file: Path | None = None

    def __post_init__(self) -> None:
        """Validate the pacing."""
        if not self.speed > 0:
            raise ValueError("speed must be positive")


def status_line(board: SimulatedHeishaMon) -> str:
    """One human line describing the simulated plant."""
    obs = board.observation
    if obs is None:
        return f"{board.now:%Y-%m-%d %H:%M} no cycle yet"
    s = board.stats
    return (
        f"{board.now:%Y-%m-%d %H:%M} outside {obs.outside_temp} °C, room {obs.room_temp:.1f} °C, "
        f"target {board.water_target} °C, outlet {obs.outlet_temp:.2f} °C, "
        f"compressor {obs.compressor_freq} Hz, starts {board.state.starts}, "
        f"commands applied {s.commands_applied} (ignored {s.commands_ignored}, "
        f"dropped {s.commands_dropped})"
    )


def save_registers(path: Path, registers: Registers) -> None:
    """Write ``registers`` to ``path`` atomically (temporary file, then rename)."""
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(registers_to_json(registers), encoding="utf-8")
    os.replace(temporary, path)


class RegisterSaver:
    """Save the board's registers whenever they differ from the last saved ones.

    Parameters
    ----------
    path
        State file; ``None`` disables saving.
    """

    def __init__(self, path: Path | None) -> None:
        self.path = path
        self._saved: Registers | None = None

    def __call__(self, registers: Registers) -> None:
        """Save ``registers`` when changed; I/O errors are logged, not raised."""
        if self.path is None or registers == self._saved:
            return
        try:
            save_registers(self.path, registers)
        except OSError as exc:
            LOGGER.warning("cannot save registers to %s: %s", self.path, exc)
            return
        self._saved = registers


async def _receive(client: aiomqtt.Client, board: SimulatedHeishaMon) -> None:
    async for message in client.messages:
        payload = message.payload
        raw = payload if isinstance(payload, bytes | bytearray) else str(payload).encode()
        topic = str(message.topic)
        accepted = board.receive(topic, bytes(raw))
        prefix = board.config.inject_prefix
        if prefix is not None and topic.startswith(f"{prefix}/"):
            verdict = "applied" if accepted else "rejected"
            LOGGER.warning("injection %s %r %s", topic, bytes(raw)[:80], verdict)
        elif accepted:
            LOGGER.info("command %s %r queued", message.topic, bytes(raw)[:80])


async def _publish(client: aiomqtt.Client, publications: list[Publication]) -> None:
    for item in publications:
        await client.publish(item.topic, item.payload, qos=0, retain=item.retain)


def weather_ended(board: SimulatedHeishaMon) -> bool:
    """Whether the next cycle would start past the end of the board's weather."""
    end = weather_end(board.weather)
    return end is not None and board.now.timestamp() > end


async def _stop_at_end(client: aiomqtt.Client, board: SimulatedHeishaMon) -> None:
    end = weather_end(board.weather) or 0.0
    LOGGER.error(
        "recorded weather ends at %s (simulated %s): the simulated HeishaMon stops "
        "(--at-end stop), publishes LWT Offline and idles; restart with a later --start, "
        "fresh weather or --at-end loop",
        datetime.fromtimestamp(end, UTC).isoformat(),
        board.now.isoformat(),
    )
    will = board.will()
    await client.publish(will.topic, will.payload, qos=0, retain=will.retain)


async def run(
    board: SimulatedHeishaMon,
    config: RunnerConfig,
    *,
    client_factory: Callable[..., Any] = aiomqtt.Client,
) -> str:
    """Run the board until the duration ends, the weather runs out or the task is cancelled.

    Parameters
    ----------
    board
        The simulated board.
    config
        Connection and pacing.
    client_factory
        Builds the MQTT client from keyword arguments (injectable for tests).

    Returns
    -------
    str
        :data:`FINISHED` after the duration, :data:`END_OF_WEATHER` when the recorded
        weather ran out (``LWT`` ``Offline`` published).
    """
    check_broker(config.host, allow_remote=config.allow_remote)
    will = board.will()
    interval = board.config.query_interval_s / config.speed
    last_status = -config.status_every_s
    save = RegisterSaver(config.state_file)
    while True:
        try:
            async with client_factory(
                hostname=config.host,
                port=config.port,
                identifier=f"heishamon-sim-{secrets.token_hex(3)}",
                will=aiomqtt.Will(will.topic, will.payload, qos=0, retain=will.retain),
                clean_session=True,
            ) as client:
                await client.subscribe(board.command_filter, qos=0)
                if board.inject_filter is not None:
                    await client.subscribe(board.inject_filter, qos=0)
                LOGGER.info(
                    "simulated HeishaMon on %s:%d at %.0fx from %s (%s)",
                    config.host,
                    config.port,
                    config.speed,
                    board.now.isoformat(),
                    board.weather.name,
                )
                receiver = asyncio.create_task(_receive(client, board))
                try:
                    anchor = time.monotonic()
                    first = board.cycles
                    while config.duration_s is None or board.elapsed_s < config.duration_s:
                        if weather_ended(board):
                            await _stop_at_end(client, board)
                            return END_OF_WEATHER
                        await _publish(client, board.cycle())
                        save(board.registers)
                        if board.elapsed_s - last_status >= config.status_every_s:
                            last_status = board.elapsed_s
                            LOGGER.info("%s", status_line(board))
                        due = anchor + (board.cycles - first) * interval
                        await asyncio.sleep(max(0.0, due - time.monotonic()))
                    return FINISHED
                finally:
                    receiver.cancel()
                    with contextlib.suppress(asyncio.CancelledError, aiomqtt.MqttError):
                        await receiver
        except aiomqtt.MqttError as exc:
            LOGGER.warning("MQTT %s; reconnecting in %.0f s", exc, RECONNECT_DELAY_S)
            await asyncio.sleep(RECONNECT_DELAY_S)
