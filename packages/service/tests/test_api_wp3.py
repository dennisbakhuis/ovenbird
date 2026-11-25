"""API of the preview, the signal pickers, the weather and the pump settings: roles and rules."""

from __future__ import annotations

import asyncio
import base64
import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from ovenbird.api.app import create_app
from ovenbird.config import Settings
from ovenbird.configstore import ConfigManager
from ovenbird.control import ControlLoop
from ovenbird.ha import EntityState
from ovenbird.pump.settings import PumpSettings
from ovenbird.replay.engine import coverage_payload
from ovenbird.runtime import Runtime
from ovenbird.service import build_control
from ovenbird.signals import signal_candidates
from ovenbird.testing import FakeClock
from ovenbird.weather import OpenMeteoProvider, WeatherService
from ovenbird_core import HeishaSignal, ParseError, ParseErrorKind, Reading, SourceKind
from ovenbird_core.heishamon import Heartbeat

TOKEN = "operate-token-" + "x" * 24
PASSWORD = "pw-123"
PUBLISH: dict[str, Any] = {
    "control_mode": "auto",
    "allow_commands": True,
    "mqtt_host": "mosquitto",
    "command_brokers": ("mosquitto",),
}
MARK = {"X-Ovenbird-Request": "1"}
INGRESS = ("172.30.32.2", 50000)
FIXTURE = Path(__file__).parent / "fixtures" / "weather" / "open_meteo_forecast.json"
PUMP_VALUES: dict[str, Any] = {
    HeishaSignal.HEATING_MODE: 1,
    HeishaSignal.OPERATING_MODE_STATE: 0,
    HeishaSignal.DEFROSTING_STATE: 0,
    HeishaSignal.THREEWAY_VALVE_STATE: 0,
    HeishaSignal.HEAT_DELTA: 5,
    HeishaSignal.PUMP_FLOWRATE_MODE: 1,
    HeishaSignal.HEATING_OFF_OUTDOOR_TEMP: 20,
    HeishaSignal.MAX_PUMP_DUTY: 159,
    HeishaSignal.QUIET_MODE_PRIORITY: 0,
    HeishaSignal.ROOM_THERMOSTAT_TEMP: 22,
}


def basic(user: str = "admin", password: str = PASSWORD) -> dict[str, str]:
    token = base64.b64encode(f"{user}:{password}".encode()).decode()
    return {"Authorization": f"Basic {token}"}


BEARER = {"Authorization": f"Bearer {TOKEN}"}


async def no_sleep(_: float) -> None:
    return None


class FakeHa:
    def __init__(self) -> None:
        self.home = (52.091, 5.118)
        self.index = {
            "sensor.living_room_temperature": EntityState(
                "21.9",
                {"unit_of_measurement": "°C", "friendly_name": "Living room climate"},
                last_changed=1_800_000_000.0 - 7800.0,
            ),
            "sensor.living_room_humidity": EntityState(
                "54", {"unit_of_measurement": "%", "friendly_name": "Living room humidity"}
            ),
            "climate.living_room": EntityState(
                "heat",
                {"current_temperature": 69.8, "friendly_name": "Thermostaat"},
                last_updated=1_800_000_000.0 - 60.0,
            ),
            "climate.attic": EntityState("off", {"friendly_name": "Attic"}),
        }
        self.temperature_unit: str | None = "°F"

    def area_of(self, entity_id: str) -> str | None:
        return "Living room" if "living_room" in entity_id else None

    def device_of(self, entity_id: str) -> str | None:
        return "dev-1" if entity_id.startswith("sensor.living_room") else None


@dataclass
class Stack:
    manager: ConfigManager
    runtime: Runtime
    loop: ControlLoop
    clock: FakeClock
    pumps: PumpSettings
    weather: WeatherService

    def client(self, **kwargs: Any) -> TestClient:
        settings = self.manager.settings
        ha = FakeHa()
        app = create_app(
            self.runtime,
            settings,
            control=self.loop,
            config=self.manager,
            pumps=self.pumps,
            weather=self.weather,
            signals=lambda: signal_candidates(settings, self.runtime, ha),  # type: ignore[arg-type]
        )
        return TestClient(app, **kwargs)

    def report(self, values: dict[str, Any]) -> None:
        now = self.clock()
        for signal, value in values.items():
            self.runtime.apply(Reading(signal, value, None, now, SourceKind.HEISHAMON))
        self.runtime.apply(Heartbeat(now, retained=False))


def stack(settings: Settings) -> Stack:
    clock = FakeClock()
    manager = ConfigManager.open(settings, clock, locked={})
    runtime = Runtime(clock=clock)
    loop, _ = build_control(
        manager.settings,
        runtime,
        None,
        sleep=no_sleep,
        hold=manager.hold,
        config_version=manager.version,
    )
    manager.attach(loop, loop.alarms)
    pumps = PumpSettings(runtime, loop.guard, loop.adapter, manager, manager.settings.history_path)
    weather = WeatherService(
        manager.settings,
        clock,
        OpenMeteoProvider(lambda _: FIXTURE.read_bytes()),
        history_path=manager.settings.history_path,
    )
    rig = Stack(manager, runtime, loop, clock, pumps, weather)
    rig.report(PUMP_VALUES)
    return rig


@pytest.fixture
def open_settings(make_settings: Callable[..., Settings]) -> Settings:
    return make_settings(**PUBLISH, operate_token=TOKEN)


@pytest.fixture
def secured(make_settings: Callable[..., Settings]) -> Settings:
    return make_settings(
        **PUBLISH, operate_token=TOKEN, http_host="0.0.0.0", admin_password=PASSWORD
    )


@pytest.fixture
def ingress(make_settings: Callable[..., Settings]) -> Settings:
    return make_settings(**PUBLISH, ingress=True)


def body_for(path: str) -> dict[str, Any]:
    if path.endswith("/config/preview"):
        return {"changes": {"control_comfort_c": 21.4}, "hours": 1}
    if "/pump/settings/" in path:
        return {"value": 4, "expect": 5}
    if path.endswith("/replay"):
        return {"from": "2027-01-14T00:00:00Z", "to": "2027-01-15T00:00:00Z"}
    return {}


ENDPOINTS: list[tuple[str, str, str]] = [
    ("POST", "/api/v1/config/preview", "operate"),
    ("POST", "/api/v1/replay", "operate"),
    ("GET", "/api/v1/replay/coverage", "read"),
    ("GET", "/api/v1/config/signals", "admin"),
    ("GET", "/api/v1/weather", "read"),
    ("GET", "/api/v1/pump/settings", "read"),
    ("POST", "/api/v1/pump/settings/heat_delta", "admin"),
]
RANK = {"read": 0, "operate": 1, "admin": 2}


def call(client: TestClient, method: str, path: str, headers: dict[str, str]) -> int:
    if method == "GET":
        return client.get(path, headers=headers).status_code
    return client.request(
        method, path, json=body_for(path), headers={**headers, **MARK}
    ).status_code


@pytest.mark.parametrize(("method", "path", "needed"), ENDPOINTS)
@pytest.mark.parametrize(
    ("mode", "credentials", "role"),
    [
        ("open", {}, "read"),
        ("open", BEARER, "operate"),
        ("secured", BEARER, "operate"),
        ("secured", basic(), "admin"),
        ("ingress", {}, "admin"),
    ],
)
def test_role_matrix(
    request: pytest.FixtureRequest,
    mode: str,
    credentials: dict[str, str],
    role: str,
    method: str,
    path: str,
    needed: str,
) -> None:
    settings = request.getfixturevalue({"open": "open_settings"}.get(mode, mode))
    rig = stack(settings)
    kwargs = {"client": INGRESS} if mode == "ingress" else {}
    with rig.client(**kwargs) as client:
        status = call(client, method, path, credentials)
    if RANK[role] >= RANK[needed]:
        assert status not in {401, 403}, (status, role, path)
    else:
        assert status == 403, (status, role, path)


@pytest.mark.parametrize(("method", "path", "needed"), ENDPOINTS)
def test_without_credentials_nothing_is_served(
    secured: Settings, method: str, path: str, needed: str
) -> None:
    with stack(secured).client() as client:
        assert call(client, method, path, {}) == 401
    del needed


@pytest.mark.parametrize("source", ["secured", "ingress"])
@pytest.mark.parametrize(
    ("headers", "status"),
    [
        ({"Content-Type": "application/json"}, 403),
        ({**MARK, "Content-Type": "application/x-www-form-urlencoded"}, 415),
        ({**MARK, "Content-Type": "application/json", "Origin": "https://evil.example"}, 403),
        ({**MARK, "Content-Type": "application/json", "Sec-Fetch-Site": "cross-site"}, 403),
    ],
)
@pytest.mark.parametrize(
    "path", ["/api/v1/pump/settings/heat_delta", "/api/v1/config/preview", "/api/v1/replay"]
)
def test_request_rules(
    request: pytest.FixtureRequest,
    source: str,
    headers: dict[str, str],
    status: int,
    path: str,
) -> None:
    rig = stack(request.getfixturevalue(source))
    auth = basic() if source == "secured" else {}
    kwargs = {"client": INGRESS} if source == "ingress" else {}
    content = json.dumps(body_for(path))
    with rig.client(**kwargs) as client:
        response = client.post(path, content=content, headers={**auth, **headers})
    assert response.status_code == status, response.text
    assert rig.loop.adapter is not None
    assert rig.loop.adapter.operator_writes == {}


def test_pump_settings_shape(open_settings: Settings) -> None:
    rig = stack(open_settings)
    with rig.client() as client:
        body = client.get("/api/v1/pump/settings").json()
    assert body["writable"] is True
    assert body["refusals"] == []
    rows = {row["id"]: row for row in body["settings"]}
    heat = rows["heat_delta"]
    assert heat == {
        "id": "heat_delta",
        "signal": "main/Heat_Delta",
        "value": 5,
        "unit": "K",
        "label": None,
        "fresh": True,
        "age": 0.0,
        "supported": True,
        "access": "write",
        "owner": "operator",
        "command": "SetFloorHeatDelta",
        "min": 3,
        "max": 10,
        "last_write": None,
    }
    assert rows["pump_flowrate_mode"]["label"] == "max_flow"
    assert rows["heating_off_outdoor"]["unit"] == "°C"
    assert (rows["max_pump_duty"]["access"], rows["max_pump_duty"]["owner"]) == (
        "read",
        "controller",
    )
    assert rows["quiet_mode_priority"]["label"] == "sound"
    assert rows["heater_delay_time"]["supported"] is False
    assert [r for r in body["settings"] if r["access"] == "write"] == [
        rows["heat_delta"],
        rows["pump_flowrate_mode"],
        rows["heating_off_outdoor"],
    ]


def test_an_unsupported_enum_is_not_supported(open_settings: Settings) -> None:
    rig = stack(open_settings)
    rig.runtime.apply(
        ParseError(
            HeishaSignal.HEATING_CONTROL,
            ParseErrorKind.UNKNOWN_ENUM,
            "-1",
            "firmware reports -1 (unknown)",
            rig.clock(),
            retained=False,
        )
    )
    with rig.client() as client:
        rows = {row["id"]: row for row in client.get("/api/v1/pump/settings").json()["settings"]}
    assert rows["heating_control"]["supported"] is False
    assert rows["heating_control"]["value"] is None


def test_an_admin_write_is_queued_audited_and_journalled(secured: Settings) -> None:
    rig = stack(secured)
    with rig.client() as client:
        response = client.post(
            "/api/v1/pump/settings/heat_delta",
            json={"value": 4, "expect": 5, "comment": "test"},
            headers={**basic(), **MARK},
        )
        assert response.status_code == 202, response.text
        command = response.json()["command"]
        assert command["kind"] == "heat_delta"
        assert command["status"] == "queued"
        assert command["topic"] == "panasonic_heat_pump/commands/SetFloorHeatDelta"
        assert command["payload"] == "4"
        assert command["detail"].startswith("operator: admin from testclient: heat_delta 5 → 4")
        body = client.get("/api/v1/pump/settings", headers=basic()).json()
        heat = next(row for row in body["settings"] if row["id"] == "heat_delta")
        assert heat["last_write"]["from"] == 5
        assert heat["last_write"]["to"] == 4
        assert heat["last_write"]["status"] == "queued"
        assert body["writable"] is False
        events = client.get(
            "/api/v1/audit",
            params={"from": "2000-01-01T00:00:00Z", "to": "2100-01-01T00:00:00Z"},
            headers=basic(),
        ).json()["events"]
        again = client.post(
            "/api/v1/pump/settings/pump_flowrate_mode",
            json={"value": 0, "expect": 1},
            headers={**basic(), **MARK},
        )
    assert events[-1]["action"] == "pump_setting"
    assert events[-1]["detail"] == {"setting": "heat_delta", "from": 5, "to": 4, "comment": "test"}
    assert again.status_code == 409
    assert again.json()["detail"]["code"] == "in_flight"


@pytest.mark.parametrize(
    ("path", "body", "status", "code"),
    [
        ("/api/v1/pump/settings/heat_delta", {"value": 11, "expect": 5}, 422, "out_of_range"),
        ("/api/v1/pump/settings/heat_delta", {"value": 4.5, "expect": 5}, 422, "not_an_integer"),
        ("/api/v1/pump/settings/heat_delta", {"value": 4, "expect": 6}, 409, "value_changed"),
        ("/api/v1/pump/settings/max_pump_duty", {"value": 4, "expect": 5}, 404, "unknown_setting"),
        (
            "/api/v1/pump/settings/heat_delta",
            {"value": 4, "expect": 5, "comment": 3},
            400,
            "bad_comment",
        ),
    ],
)
def test_refusals(
    ingress: Settings, path: str, body: dict[str, Any], status: int, code: str
) -> None:
    rig = stack(ingress)
    with rig.client(client=INGRESS) as client:
        response = client.post(path, json=body, headers=MARK)
    assert response.status_code == status
    assert response.json()["detail"]["code"] == code


def test_writes_are_refused_while_paused_and_in_shadow(
    ingress: Settings, make_settings: Callable[..., Settings]
) -> None:
    rig = stack(ingress)
    rig.manager.hold.paused = True
    with rig.client(client=INGRESS) as client:
        response = client.post(
            "/api/v1/pump/settings/heat_delta", json={"value": 4, "expect": 5}, headers=MARK
        )
        body = client.get("/api/v1/pump/settings").json()
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "not_publishing"
    assert body["writable"] is False
    assert body["refusals"] == ["control is paused"]
    shadow = stack(make_settings(ingress=True))
    with shadow.client(client=INGRESS) as client:
        response = client.post(
            "/api/v1/pump/settings/heat_delta", json={"value": 4, "expect": 5}, headers=MARK
        )
    assert response.status_code == 409
    assert "control mode is shadow" in response.json()["detail"]["message"]


def test_preview_now_and_open_loop_run(open_settings: Settings) -> None:
    rig = stack(open_settings)
    with rig.client(headers=BEARER) as client:
        response = client.post(
            "/api/v1/config/preview",
            json={"changes": {"control_comfort_c": 21.4}, "hours": 24},
            headers=MARK,
        )
        invalid = client.post(
            "/api/v1/config/preview",
            json={"changes": {"control_comfort_c": 99}},
            headers=MARK,
        )
        hours = client.post(
            "/api/v1/config/preview",
            json={"changes": {}, "hours": 100},
            headers=MARK,
        )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["valid"] is True
    assert body["now"]["current"]["controller"] == "ovenbird"
    assert body["now"]["candidate"]["schema"] == 1
    assert body["open_loop_run"]["open_loop"] is True
    assert body["open_loop_run"]["identity_ok"] is True
    assert body["open_loop_run"]["ticks"] == 0
    assert set(body["open_loop_run"]["summary"]) >= {"mean_diff_k", "writes_per_day", "budget"}
    assert invalid.json()["valid"] is False
    assert "open_loop_run" not in invalid.json()
    assert hours.status_code == 400


def test_signal_candidates(secured: Settings) -> None:
    rig = stack(secured)
    with rig.client() as client:
        body = client.get("/api/v1/config/signals", headers=basic()).json()
    assert body["ha"] == {"enabled": False, "link_up": False}
    room = {item["signal"]: item for item in body["room"]}
    assert room["ha/sensor.living_room_temperature"] == {
        "signal": "ha/sensor.living_room_temperature",
        "name": "Living room climate",
        "unit": "°C",
        "value": 21.9,
        "held_s": 7800.0,
        "source": "ha",
        "entity_id": "sensor.living_room_temperature",
        "area": "Living room",
        "device_id": "dev-1",
    }
    assert room["ha/climate.living_room#current_temperature"] == {
        "signal": "ha/climate.living_room#current_temperature",
        "name": "Thermostaat",
        "unit": "°F",
        "value": 69.8,
        "held_s": 60.0,
        "source": "ha",
        "entity_id": "climate.living_room",
        "area": "Living room",
    }
    assert "ha/climate.attic#current_temperature" not in room
    liveness = {i["signal"] for i in body["liveness"]}
    assert "ha/sensor.living_room_humidity" in liveness
    assert not any(signal.startswith("ha/climate.") for signal in liveness)
    assert "ha/sensor.living_room_humidity" not in room
    assert "ha/climate.living_room#current_temperature" in {i["signal"] for i in body["crosscheck"]}
    crosscheck = {item["signal"]: item for item in body["crosscheck"]}
    assert crosscheck["main/Room_Thermostat_Temp"]["value"] == 22
    assert crosscheck["main/Room_Thermostat_Temp"]["source"] == "heishamon"


def test_weather_endpoint(open_settings: Settings, make_settings: Callable[..., Settings]) -> None:
    rig = stack(open_settings)
    with rig.client() as client:
        body = client.get("/api/v1/weather").json()
        bad = client.get("/api/v1/weather", params={"ahead_h": 500})
    assert body["enabled"] is False
    assert bad.status_code == 422


def test_replay_coverage_reads_the_history_off_the_event_loop(
    open_settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[bool] = []
    real = coverage_payload

    def fake(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            seen.append(False)
        else:
            seen.append(True)
        return real(*_args, **_kwargs)

    monkeypatch.setattr("ovenbird.api.replay_api.coverage_payload", fake)
    with stack(open_settings).client() as client:
        client.get("/api/v1/replay/coverage")
    assert seen == [False]
