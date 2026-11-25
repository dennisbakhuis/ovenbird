"""MQTT recorder: subscribe to the live broker and append every message to a capture.

The recorder is strictly read-only on the broker — this module contains no
code path that sends anything, and the recommended broker account has a
read-only ACL on top. Configuration comes from CLI flags with environment
variable fallbacks so the same container runs on a laptop and on a NAS.
"""

from __future__ import annotations

import argparse
import logging
import os
import signal
import socket
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from types import FrameType
from typing import Any, Final

import paho.mqtt.client as mqtt_client

from .capture import CaptureWriter, Record, format_duration

_LOGGER = logging.getLogger("climate_manager.capture.record")

DEFAULT_TOPICS: Final = ("panasonic_heat_pump/#", "climate_manager_capture/#")
HEARTBEAT_FILE: Final = ".heartbeat"
HEALTH_TOUCH_SECONDS: Final = 30.0


@dataclass(frozen=True)
class RecorderConfig:
    """Resolved recorder settings."""

    host: str
    port: int
    username: str | None
    password: str | None
    topics: tuple[str, ...]
    out: Path
    name: str
    max_hours: float | None
    heartbeat_seconds: float


def _env(name: str, default: str | None = None) -> str | None:
    value = os.environ.get(name)
    return value if value not in (None, "") else default


def _build_argparser() -> argparse.ArgumentParser:
    """Construct the CLI argument parser (every flag has an env fallback)."""
    parser = argparse.ArgumentParser(
        description="Record HeishaMon MQTT traffic to a capture directory.",
    )
    parser.add_argument("--host", default=_env("MQTT_HOST", "localhost"))
    parser.add_argument("--port", type=int, default=int(_env("MQTT_PORT", "1883") or 1883))
    parser.add_argument("--username", default=_env("MQTT_USERNAME"))
    parser.add_argument("--password", default=_env("MQTT_PASSWORD"))
    parser.add_argument(
        "--topics",
        nargs="*",
        default=None,
        help="Subscription filters (env TOPICS, comma-separated). Default: %(default)s",
    )
    parser.add_argument("--out", default=_env("CAPTURE_DIR", "captures"))
    parser.add_argument("--name", default=_env("CAPTURE_NAME", "live"))
    parser.add_argument(
        "--max-hours",
        type=float,
        default=float(_env("MAX_HOURS", "0") or 0) or None,
        help="Stop after this many hours (env MAX_HOURS); default runs forever.",
    )
    parser.add_argument(
        "--heartbeat-seconds",
        type=float,
        default=float(_env("HEARTBEAT_SECONDS", "300") or 300),
    )
    parser.add_argument("--verbose", "-v", action="store_true")
    return parser


def _resolve_topics(cli_topics: list[str] | None) -> tuple[str, ...]:
    if cli_topics:
        return tuple(cli_topics)
    env_topics = _env("TOPICS")
    if env_topics:
        return tuple(t.strip() for t in env_topics.split(",") if t.strip())
    return DEFAULT_TOPICS


def config_from_args(args: argparse.Namespace) -> RecorderConfig:
    """Build a :class:`RecorderConfig` from parsed CLI arguments."""
    return RecorderConfig(
        host=args.host,
        port=args.port,
        username=args.username,
        password=args.password,
        topics=_resolve_topics(args.topics),
        out=Path(args.out),
        name=args.name,
        max_hours=args.max_hours,
        heartbeat_seconds=args.heartbeat_seconds,
    )


def run(config: RecorderConfig) -> int:
    """Connect, subscribe, and write every message until stopped.

    Returns
    -------
    int
        Process exit code (``0`` on a clean stop, including ``--max-hours``).
    """
    writer = CaptureWriter(
        config.out,
        config.name,
        header={
            "broker": f"{config.host}:{config.port}",
            "filters": list(config.topics),
            "recorder": socket.gethostname(),
        },
    )
    heartbeat_path = writer.path / HEARTBEAT_FILE
    stop_requested = False
    connected = False

    def _on_connect(
        client: mqtt_client.Client,
        _userdata: Any,
        _flags: Any,
        reason_code: Any,
        _properties: Any = None,
    ) -> None:
        nonlocal connected
        if getattr(reason_code, "is_failure", False):
            _LOGGER.error("connect refused: %s", reason_code)
            return
        connected = True
        _LOGGER.info("connected to %s:%d; subscribing %s", config.host, config.port, config.topics)
        for topic in config.topics:
            client.subscribe(topic, qos=0)

    def _on_disconnect(
        _client: mqtt_client.Client,
        _userdata: Any,
        _flags: Any,
        reason_code: Any,
        _properties: Any = None,
    ) -> None:
        nonlocal connected
        connected = False
        if not stop_requested:
            _LOGGER.warning("disconnected (%s); paho will reconnect", reason_code)

    def _on_message(
        _client: mqtt_client.Client, _userdata: Any, msg: mqtt_client.MQTTMessage
    ) -> None:
        payload = msg.payload.decode("utf-8", errors="replace")
        writer.write(Record(time.time(), msg.topic, payload, bool(msg.retain)))

    client = mqtt_client.Client(
        callback_api_version=mqtt_client.CallbackAPIVersion.VERSION2,  # type: ignore[attr-defined]
        client_id=f"climate-manager-recorder-{socket.gethostname()}",
        clean_session=True,
    )
    if config.username:
        client.username_pw_set(config.username, config.password)
    client.on_connect = _on_connect
    client.on_disconnect = _on_disconnect
    client.on_message = _on_message
    client.reconnect_delay_set(min_delay=1, max_delay=60)

    def _signal_handler(_signum: int, _frame: FrameType | None) -> None:
        nonlocal stop_requested
        _LOGGER.info("stop signal received; closing capture")
        stop_requested = True

    signal.signal(signal.SIGINT, _signal_handler)
    signal.signal(signal.SIGTERM, _signal_handler)

    started = time.time()
    deadline = started + config.max_hours * 3600 if config.max_hours else None
    _LOGGER.info(
        "recorder starting: broker=%s:%d capture=%s filters=%s max_hours=%s",
        config.host,
        config.port,
        writer.path,
        list(config.topics),
        config.max_hours,
    )
    client.connect_async(config.host, config.port, keepalive=30)
    client.loop_start()

    last_heartbeat = last_touch = time.time()
    last_count = 0
    heartbeat_path.touch()
    try:
        while not stop_requested:
            now = time.time()
            if deadline is not None and now >= deadline:
                _LOGGER.info("max-hours reached; stopping")
                stop_requested = True
                break
            if connected and now - last_touch >= HEALTH_TOUCH_SECONDS:
                heartbeat_path.touch()
                last_touch = now
            if now - last_heartbeat >= config.heartbeat_seconds:
                count = writer.records_written
                rate = (count - last_count) / max(1.0, (now - last_heartbeat) / 60)
                _LOGGER.info(
                    "heartbeat up=%s connected=%s records=%d (%.0f/min) bytes=%d file=%s",
                    format_duration(now - started),
                    connected,
                    count,
                    rate,
                    writer.bytes_written,
                    writer.active_file.name if writer.active_file else "-",
                )
                last_heartbeat, last_count = now, count
            time.sleep(1.0)
    finally:
        client.loop_stop()
        client.disconnect()
        writer.close()
        _LOGGER.info("capture closed: %d records", writer.records_written)
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
    return run(config_from_args(args))


if __name__ == "__main__":
    sys.exit(main())
