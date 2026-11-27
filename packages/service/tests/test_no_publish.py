"""The publishing guarantee.

1. No publish in shadow (the default): no publishing connection is ever built.
2. Publishing happens only through the command adapter: exactly one publish call in
   the package (``CommandLink.send`` in ``control/adapter/publish.py``), and only that module
   names command topics; the ingest client stays subscribe-only.
3. The adapter and its link refuse unless all three conditions hold: mode ``auto``,
   ``OVENBIRD_ALLOW_COMMANDS=true`` and the broker in ``OVENBIRD_COMMAND_BROKERS``.
"""

from __future__ import annotations

import ast
import dataclasses
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

import ovenbird
from ovenbird.config import Settings
from ovenbird.control.adapter import AdapterConfig, Command, CommandLink
from ovenbird.control.guard import CommandsRefusedError, PublishGuard
from ovenbird.mqtt import MqttIngest, ReadOnlyMqttClient
from ovenbird.service import build_service
from ovenbird.testing import inbound, pump_messages
from ovenbird_core.control import IntentKind, OvenbirdConfig, SafetyLimits

PACKAGE_DIR = Path(ovenbird.__file__).parent
PUBLISHER = PACKAGE_DIR / "control" / "adapter" / "publish.py"
COMMAND_TOPIC = re.compile(r"commands/|\bSet[A-Z]\w+")
FORBIDDEN_CALLS = {"publish", "will_set", "publish_multiple", "single", "multiple"}
ALLOWED_CLIENT_USE = {"__aenter__", "__aexit__", "subscribe", "messages"}
ALL_THREE: dict[str, Any] = {
    "control_mode": "auto",
    "allow_commands": True,
    "mqtt_host": "mosquitto",
    "command_brokers": ("mosquitto",),
}
MISSING = [
    ("control_mode", "shadow"),
    ("control_mode", "off"),
    ("allow_commands", False),
    ("command_brokers", ()),
    ("command_brokers", ("mosquitto:1884",)),
    ("mqtt_host", "homeassistant.local"),
    ("clock_speed", 60.0),
    ("clock_start", "2026-11-07T00:00:00Z"),
]


def test_wrapper_exposes_no_publish_capability() -> None:
    public = {name for name in dir(ReadOnlyMqttClient) if not name.startswith("_")}
    assert public == {"subscribe", "messages"}
    assert not any(
        "publish" in name.lower() or "will" in name.lower() for name in dir(ReadOnlyMqttClient)
    )
    assert ReadOnlyMqttClient.__slots__ == ("_client",)


class SpyClient:
    def __init__(self, **kwargs: Any) -> None:
        self.kwargs = kwargs
        self.used: set[str] = set()
        self.published: list[tuple[str, str, int, bool]] = []

    def __getattribute__(self, name: str) -> Any:
        if name not in {"kwargs", "used", "published", "__dict__", "__class__"}:
            object.__getattribute__(self, "used").add(name)
        return object.__getattribute__(self, name)

    async def __aenter__(self) -> SpyClient:
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    async def subscribe(self, topic: str, qos: int = 0) -> None:
        return None

    async def publish(self, topic: str, payload: str, qos: int = 0, retain: bool = False) -> None:
        self.published.append((topic, payload, qos, retain))

    @property
    def messages(self) -> Any:
        async def stream() -> Any:
            message = inbound("panasonic_heat_pump/main/Outside_Temp", "3")

            class Delivered:
                topic = message.topic
                payload = message.payload
                retain = False

            yield Delivered()

        return stream()


async def test_wrapper_uses_only_subscribe_capabilities(
    make_settings: Callable[..., Settings],
) -> None:
    spies: list[SpyClient] = []

    def factory(**kwargs: Any) -> SpyClient:
        spy = SpyClient(**kwargs)
        spies.append(spy)
        return spy

    client = ReadOnlyMqttClient(make_settings(**ALL_THREE), client_factory=factory)
    async with client:
        await client.subscribe("panasonic_heat_pump/#")
        received = [message async for message in client.messages()]
    assert [message.topic for message in received] == ["panasonic_heat_pump/main/Outside_Temp"]
    (spy,) = spies
    assert spy.kwargs["will"] is None
    assert spy.used <= ALLOWED_CLIENT_USE


def _python_files() -> list[Path]:
    return sorted(PACKAGE_DIR.rglob("*.py"))


def _publish_sites(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    sites: list[str] = []

    def visit(node: ast.AST, scope: tuple[str, ...]) -> None:
        if isinstance(node, ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
            scope = (*scope, node.name)
        if isinstance(node, ast.Call):
            func = node.func
            name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", None)
            if name in FORBIDDEN_CALLS or name == "Will":
                sites.append(f"{'.'.join(scope)}:{name}")
        elif isinstance(node, ast.Attribute) and node.attr in FORBIDDEN_CALLS:
            sites.append(f"{'.'.join(scope)}:.{node.attr}")
        for child in ast.iter_child_nodes(node):
            if isinstance(node, ast.Call) and child is node.func:
                continue
            visit(child, scope)

    visit(tree, ())
    return sites


def test_only_the_command_link_publishes() -> None:
    sites = {
        path.relative_to(PACKAGE_DIR).as_posix(): _publish_sites(path) for path in _python_files()
    }
    assert sites.pop("control/adapter/publish.py") == ["CommandLink.send:publish"]
    assert {name: found for name, found in sites.items() if found} == {}


def _string_constants(path: Path) -> list[int]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    docstrings = {
        id(node.body[0].value)
        for node in ast.walk(tree)
        if isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef)
        and node.body
        and isinstance(node.body[0], ast.Expr)
    }
    return [
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and id(node) not in docstrings
        and COMMAND_TOPIC.search(node.value)
    ]


def test_only_the_adapter_names_command_topics() -> None:
    offenders = {
        path.name: lines
        for path in _python_files()
        if path != PUBLISHER and (lines := _string_constants(path))
    }
    assert offenders == {}
    assert _string_constants(PUBLISHER) != []


def _link(settings: Settings, spies: list[SpyClient]) -> CommandLink:
    def factory(**kwargs: Any) -> SpyClient:
        spy = SpyClient(**kwargs)
        spies.append(spy)
        return spy

    guard = PublishGuard.from_settings(settings)
    topics = AdapterConfig.from_settings(settings, _safety()).topics()
    return CommandLink(settings, guard, topics, client_factory=factory)


def _safety() -> SafetyLimits:
    return OvenbirdConfig.preset("mixed").safety


@pytest.mark.parametrize(("field", "value"), MISSING)
def test_link_refuses_without_each_condition(
    make_settings: Callable[..., Settings], field: str, value: object
) -> None:
    spies: list[SpyClient] = []
    with pytest.raises(CommandsRefusedError):
        _link(make_settings(**{**ALL_THREE, field: value}), spies)
    assert spies == []


async def test_link_publishes_allowlisted_topics_unretained_and_rechecks_the_guard(
    make_settings: Callable[..., Settings],
) -> None:
    spies: list[SpyClient] = []
    settings = make_settings(**ALL_THREE)
    link = _link(settings, spies)
    (spy,) = spies
    assert spy.kwargs["will"] is None
    good = Command(
        IntentKind.WATER_SETPOINT,
        31,
        "panasonic_heat_pump/commands/SetCurves",
        '{"zone1":{"heat":{"target":{"high":31}}}}',
        "curve",
    )
    async with link:
        await link.send(good)
        other = dataclasses.replace(good, topic="panasonic_heat_pump/commands/SetHeatpump")
        with pytest.raises(CommandsRefusedError, match="allowlisted"):
            await link.send(other)
        object.__setattr__(link._guard, "allow_commands", False)
        with pytest.raises(CommandsRefusedError, match="ALLOW_COMMANDS"):
            await link.send(good)
    assert spy.published == [(good.topic, good.payload, 1, False)]


def _service(make_settings: Callable[..., Settings], **overrides: Any) -> Any:
    calls: list[str] = []

    def command_connect() -> Any:
        calls.append("connect")
        raise AssertionError("no publishing connection may be built")

    service = build_service(make_settings(**overrides), command_connect=command_connect)
    return service, calls


def _feed(service: Any) -> None:
    ingest = MqttIngest(service.settings, service.runtime)
    for message in pump_messages(Z1_Water_Target_Temp="25"):
        ingest.ingest(message)


def test_shadow_service_has_no_publisher_and_records_would_be_commands(
    make_settings: Callable[..., Settings],
) -> None:
    service, calls = _service(make_settings, **{**ALL_THREE, "control_mode": "shadow"})
    assert service.worker is None
    assert [c.name for c in service.components] == [
        "mqtt",
        "history",
        "ha",
        "control",
        "safety",
        "weather",
        "learner",
        "learner-run",
        "mqtt-trial",
    ]
    _feed(service)
    row = service.control.tick()
    assert row.mode == "shadow"
    assert '"action":"send"' in row.arbiter
    assert row.commands == "[]"
    assert calls == []
    status = service.control.status()
    assert status["publishing"] is False
    assert status["adapter"] is None


@pytest.mark.parametrize(("field", "value"), MISSING)
def test_auto_without_all_conditions_has_no_publisher(
    make_settings: Callable[..., Settings], field: str, value: object
) -> None:
    service, calls = _service(make_settings, **{**ALL_THREE, field: value})
    assert service.worker is None
    assert "commands" not in [c.name for c in service.components]
    _feed(service)
    service.control.tick()
    assert calls == []


async def test_all_three_conditions_build_the_only_publisher(
    make_settings: Callable[..., Settings],
) -> None:
    service = build_service(make_settings(**ALL_THREE))
    assert service.worker is not None
    assert [c.name for c in service.components][-1] == "commands"
    assert isinstance(service.worker.connect(), CommandLink)
    _feed(service)
    row = service.control.tick()
    assert '"status":"queued"' in row.commands
