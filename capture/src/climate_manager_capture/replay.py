"""Replay a capture into the local dev broker as if HeishaMon were live.

Three command modes decide what happens on ``commands/*``:

- ``overlay`` (default): the integration under test may send commands. They
  are applied with HeishaMon semantics (integer parsing, 10-deep queue, side-effect
  on the next query tick, no echo) and from then on the replayer *owns* the
  affected ``main/*`` topics — recorded values for them (including the
  300 s dump repeats and the recorded controller's later decisions) are suppressed.
- ``ignore``: no overlay; recorded commands are dropped. Exercises the
  integration's delivery-failure path.
- ``passthrough``: recorded commands are replayed too; nothing is overlaid.
  Useful for watching the recorded controller's decisions in the dev stack.

Replay is not a plant model: outlet temperatures, power, and compressor
behaviour stay exactly as recorded regardless of what was commanded.
"""

from __future__ import annotations

import argparse
import logging
import signal
import sys
import threading
import time
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from types import FrameType
from typing import Any, Final

import paho.mqtt.client as mqtt_client

from .capture import (
    CaptureReader,
    Record,
    format_duration,
    is_retained,
    parse_when,
    topic_suffix,
)
from .heishamon import QUERY_INTERVAL_S, CommandSemantics, command_name

_LOGGER = logging.getLogger("climate_manager.capture.replay")

LOCAL_HOSTS: Final = frozenset({"localhost", "127.0.0.1", "::1", "mosquitto"})
DEFAULT_DROP: Final = ("stats", "log")
#: Wall-clock cap on the overlay's query grid so a side-effect always lands
#: inside the integration's 5 s confirmation window.
OVERLAY_MAX_INTERVAL_S: Final = 4.5
HEARTBEAT_CAPTURE_S: Final = 300.0
SLEEP_CHUNK_S: Final = 0.1


class CommandMode(StrEnum):
    """What the replayer does with ``commands/*`` traffic."""

    OVERLAY = "overlay"
    IGNORE = "ignore"
    PASSTHROUGH = "passthrough"


@dataclass(frozen=True)
class ReplayConfig:
    """Resolved replay settings."""

    capture: Path
    host: str = "localhost"
    port: int = 1884
    base: str = "panasonic_heat_pump"
    source_base: str = "panasonic_heat_pump"
    start: str | None = None
    end: str | None = None
    speed: float | None = 1.0
    loop: bool = False
    commands: CommandMode = CommandMode.OVERLAY
    overlay_release: float | None = None
    drop: frozenset[str] = frozenset(DEFAULT_DROP)
    prime: bool = True
    allow_remote: bool = False


@dataclass
class ReplayStats:
    """Counters reported in heartbeats and at exit."""

    published: int = 0
    suppressed: int = 0
    dropped: int = 0
    commands_replayed: int = 0
    side_effects: int = 0
    passes: int = 0
    owned: set[str] = field(default_factory=set)


Publish = Callable[[str, str, bool], None]


class UnsafeBrokerError(RuntimeError):
    """Raised when the target broker is not a known local dev broker."""


def check_broker(host: str, allow_remote: bool) -> None:
    """Refuse non-local brokers unless explicitly allowed."""
    if host in LOCAL_HOSTS or allow_remote:
        return
    raise UnsafeBrokerError(
        f"refusing to replay into {host!r}: a live controller would retry these commands and "
        "the real pump would obey. Pass --allow-remote-broker if you really mean it."
    )


class ReplayScheduler:
    """Turn capture timestamps into wall-clock due times.

    Parameters
    ----------
    speed
        Capture seconds per wall second; ``None`` means as fast as possible.
    clock
        Wall-clock source.
    """

    def __init__(self, speed: float | None, clock: Callable[[], float]) -> None:
        if speed is not None and speed <= 0:
            raise ValueError("speed must be positive")
        self._speed = speed
        self._clock = clock

    def schedule(self, records: Iterable[Record]) -> Iterator[tuple[float, Record]]:
        """Yield ``(due_wall_time, record)`` anchored on the first record."""
        anchor_wall: float | None = None
        anchor_t = 0.0
        for record in records:
            if anchor_wall is None:
                anchor_wall = self._clock()
                anchor_t = record.t
            if self._speed is None:
                yield self._clock(), record
            else:
                yield anchor_wall + (record.t - anchor_t) / self._speed, record


class Replayer:
    """Drive one capture through a publish callback with overlay semantics.

    Parameters
    ----------
    reader
        Source capture.
    config
        Replay settings.
    publish
        ``publish(topic, payload, retain)`` sink.
    clock, sleep
        Injectable for tests.
    """

    def __init__(
        self,
        reader: CaptureReader,
        config: ReplayConfig,
        publish: Publish,
        *,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._reader = reader
        self._config = config
        self._publish = publish
        self._clock = clock
        self._sleep = sleep
        self._lock = threading.Lock()
        self.stats = ReplayStats()
        self.stop_requested = False
        wall_interval = QUERY_INTERVAL_S / (config.speed or 1.0)
        self.semantics = CommandSemantics(
            clock,
            query_interval=min(wall_interval, OVERLAY_MAX_INTERVAL_S),
            secondary=True,
        )

    def on_command(self, topic: str, payload: str) -> None:
        """Handle a command published by the integration under test."""
        name = command_name(topic)
        if name is None:
            return
        with self._lock:
            accepted = self.semantics.receive(name, payload)
        _LOGGER.info("command %s = %r (%s)", name, payload, "queued" if accepted else "ignored")

    def pump_overlay(self) -> None:
        """Release due side-effects and expire stale ownership."""
        if self._config.commands is not CommandMode.OVERLAY:
            return
        with self._lock:
            effects = self.semantics.due()
            if self._config.overlay_release is not None:
                released = self.semantics.release_stale(self._clock(), self._config.overlay_release)
                for suffix in released:
                    _LOGGER.info("overlay released %s", suffix)
            self.stats.owned = set(self.semantics.owned)
        for effect in effects:
            self._publish(f"{self._config.base}/{effect.suffix}", effect.payload, True)
            self.stats.side_effects += 1
            _LOGGER.info("side-effect %s = %s", effect.suffix, effect.payload)

    def _target_topic(self, record: Record) -> str | None:
        suffix = topic_suffix(record.topic, self._config.source_base)
        if suffix is None:
            return record.topic
        if suffix in self._config.drop:
            self.stats.dropped += 1
            return None
        if suffix.startswith("commands/"):
            if self._config.commands is CommandMode.PASSTHROUGH:
                self.stats.commands_replayed += 1
                return f"{self._config.base}/{suffix}"
            self.stats.dropped += 1
            return None
        if suffix in self.semantics.owned:
            self.stats.suppressed += 1
            return None
        return f"{self._config.base}/{suffix}"

    def handle(self, record: Record) -> None:
        """Publish one recorded message subject to drop/ownership rules."""
        topic = self._target_topic(record)
        if topic is None:
            return
        self._publish(topic, record.payload, is_retained(record.topic, record.payload))
        self.stats.published += 1

    def prime(self, start: float) -> None:
        """Publish the retained state as it stood at ``start``."""
        snapshot = self._reader.snapshot_at(start)
        count = 0
        for topic, payload in snapshot.items():
            target = self._target_topic(Record(start, topic, payload))
            if target is None:
                continue
            self._publish(target, payload, True)
            count += 1
        self._publish(f"{self._config.base}/LWT", "Offline", True)
        _LOGGER.info("primed %d retained topics as of %s", count, _iso(start))

    def resolve_window(self) -> tuple[float, float]:
        """Turn the configured ``start``/``end`` into timestamps."""
        first, last = self._reader.bounds()
        start = parse_when(self._config.start, first) if self._config.start else first
        end = parse_when(self._config.end, first) if self._config.end else last + 1e-3
        if end <= start:
            raise ValueError("replay window is empty")
        return start, end

    def _wait_until(self, due: float) -> None:
        while not self.stop_requested:
            self.pump_overlay()
            remaining = due - self._clock()
            if remaining <= 0:
                return
            self._sleep(min(SLEEP_CHUNK_S, remaining))

    def run_once(self, start: float, end: float) -> None:
        """Replay one pass over ``[start, end)``."""
        scheduler = ReplayScheduler(self._config.speed, self._clock)
        next_heartbeat = start + HEARTBEAT_CAPTURE_S
        for due, record in scheduler.schedule(self._reader.iter_records(start, end)):
            self._wait_until(due)
            if self.stop_requested:
                return
            self.handle(record)
            if record.t >= next_heartbeat:
                self._heartbeat(record.t)
                next_heartbeat = record.t + HEARTBEAT_CAPTURE_S
        self.pump_overlay()

    def _heartbeat(self, capture_t: float) -> None:
        _LOGGER.info(
            "heartbeat capture=%s published=%d suppressed=%d side_effects=%d owned=%s",
            _iso(capture_t),
            self.stats.published,
            self.stats.suppressed,
            self.stats.side_effects,
            sorted(self.stats.owned) or "-",
        )

    def run(self) -> None:
        """Replay according to the config, looping if requested."""
        start, end = self.resolve_window()
        _LOGGER.info(
            "replay window %s → %s (%s) speed=%s commands=%s",
            _iso(start),
            _iso(end),
            format_duration(end - start),
            "max" if self._config.speed is None else f"{self._config.speed:g}x",
            self._config.commands.value,
        )
        if self._config.prime:
            self.prime(start)
        while not self.stop_requested:
            self.run_once(start, end)
            self.stats.passes += 1
            if not self._config.loop:
                break
            _LOGGER.info("loop: restarting from %s", _iso(start))


def _iso(t: float) -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(t))


def _parse_speed(text: str) -> float | None:
    if text.lower() == "max":
        return None
    return float(text)


def _build_argparser() -> argparse.ArgumentParser:
    """Construct the CLI argument parser."""
    parser = argparse.ArgumentParser(description="Replay a capture into the dev MQTT broker.")
    parser.add_argument("--capture", required=True, help="captures/<name> directory.")
    parser.add_argument("--host", default="localhost")
    parser.add_argument("--port", type=int, default=1884)
    parser.add_argument("--base", default="panasonic_heat_pump", help="Target topic base.")
    parser.add_argument(
        "--source-base", default="panasonic_heat_pump", help="Topic base used in the capture."
    )
    parser.add_argument("--from", dest="start", help="ISO datetime or +offset (e.g. +6h).")
    parser.add_argument("--to", dest="end", help="ISO datetime or +offset.")
    parser.add_argument("--speed", type=_parse_speed, default=1.0, help="Multiplier or 'max'.")
    parser.add_argument("--loop", action="store_true")
    parser.add_argument(
        "--commands",
        type=CommandMode,
        choices=list(CommandMode),
        default=CommandMode.OVERLAY,
    )
    parser.add_argument(
        "--overlay-release",
        type=float,
        default=None,
        help="Seconds after the last command before an owned topic follows the capture again.",
    )
    parser.add_argument(
        "--drop",
        default=",".join(DEFAULT_DROP),
        help="Comma-separated topic suffixes never replayed.",
    )
    parser.add_argument("--no-prime", action="store_true")
    parser.add_argument("--allow-remote-broker", action="store_true")
    parser.add_argument("--verbose", "-v", action="store_true")
    return parser


def config_from_args(args: argparse.Namespace) -> ReplayConfig:
    """Build a :class:`ReplayConfig` from parsed CLI arguments."""
    return ReplayConfig(
        capture=Path(args.capture),
        host=args.host,
        port=args.port,
        base=args.base,
        source_base=args.source_base,
        start=args.start,
        end=args.end,
        speed=args.speed,
        loop=args.loop,
        commands=args.commands,
        overlay_release=args.overlay_release,
        drop=frozenset(s.strip() for s in args.drop.split(",") if s.strip()),
        prime=not args.no_prime,
        allow_remote=args.allow_remote_broker,
    )


def run(config: ReplayConfig) -> int:
    """Connect to the broker and replay.

    Returns
    -------
    int
        Process exit code.
    """
    check_broker(config.host, config.allow_remote)
    reader = CaptureReader(config.capture)
    client = mqtt_client.Client(
        callback_api_version=mqtt_client.CallbackAPIVersion.VERSION2,  # type: ignore[attr-defined]
        client_id="climate-manager-replay",
    )
    client.will_set(f"{config.base}/LWT", payload="Offline", qos=0, retain=True)

    def _publish(topic: str, payload: str, retain: bool) -> None:
        client.publish(topic, payload, qos=0, retain=retain)

    replayer = Replayer(reader, config, _publish)

    def _on_message(
        _client: mqtt_client.Client, _userdata: Any, msg: mqtt_client.MQTTMessage
    ) -> None:
        replayer.on_command(msg.topic, msg.payload.decode("utf-8", errors="replace"))

    def _signal_handler(_signum: int, _frame: FrameType | None) -> None:
        _LOGGER.info("stop signal received")
        replayer.stop_requested = True

    signal.signal(signal.SIGINT, _signal_handler)
    signal.signal(signal.SIGTERM, _signal_handler)

    client.connect(config.host, config.port, keepalive=60)
    client.loop_start()
    if config.commands is CommandMode.OVERLAY:
        client.on_message = _on_message
        client.subscribe(f"{config.base}/commands/#", qos=0)
    try:
        replayer.run()
    finally:
        client.publish(f"{config.base}/LWT", "Offline", qos=0, retain=True)
        time.sleep(0.2)
        client.loop_stop()
        client.disconnect()
        stats = replayer.stats
        _LOGGER.info(
            "replay finished: passes=%d published=%d suppressed=%d side_effects=%d",
            stats.passes,
            stats.published,
            stats.suppressed,
            stats.side_effects,
        )
    return 0


def main(argv: list[str] | None = None) -> int:
    """CLI entry point."""
    args = _build_argparser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    if not args.verbose:
        logging.getLogger("paho").setLevel(logging.WARNING)
    try:
        return run(config_from_args(args))
    except UnsafeBrokerError as exc:
        _LOGGER.error("%s", exc)
        return 2


if __name__ == "__main__":
    sys.exit(main())
