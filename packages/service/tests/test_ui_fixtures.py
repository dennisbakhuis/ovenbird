"""The dev stack's configuration, and the UI fixtures generated from it.

``tests/fixtures/ui/{config,schema,codes}.json`` are what the UI's mock mode and its
i18n completeness tests read (copied to ``ui/mock/fixtures/``). They are generated
from the dev compose environment and ``dev/config-seed.json``; set
``UPDATE_UI_FIXTURES=1`` to rewrite them after a change.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

import pytest
import yaml

from ovenbird.config import load_settings
from ovenbird.configstore import ConfigManager, provided_sources, schema_payload
from ovenbird.configstore.effective import VALIDATION_ERRORS, VALIDATION_WARNINGS, Source
from ovenbird.configstore.fields import GROUP_ORDER, Tier
from ovenbird.configstore.store import Origin
from ovenbird.control.adapter import CommandStatus
from ovenbird.control.alarms import (
    ENVELOPE_JOURNAL_CODE,
    HOLD_JOURNAL_CODE,
    AlarmCode,
    AlarmEventKind,
    Severity,
)
from ovenbird.control.dayshiftrun import JOURNAL_CODE as DAYSHIFT_JOURNAL_CODE
from ovenbird.control.envelope import STATES as ENVELOPE_STATES
from ovenbird.control.monitors import MonitorStatus
from ovenbird.hacheck import ERROR_CODES
from ovenbird.mqttcheck import ERROR_CODES as MQTT_ERROR_CODES
from ovenbird.notify.notifier import HEALTH_STATES
from ovenbird.pump.settings import OWNERS, REFUSAL_CODES, SETTING_IDS
from ovenbird.stove.request import STOVE_JOURNAL_CODE
from ovenbird.testing import FakeClock
from ovenbird.trial.checklist import CHECK_IDS, CHECK_STATUSES, PHASES
from ovenbird.trial.release import CAPTURE_REFUSALS, ITEM_STATUSES, ORIGINS, OUTCOMES
from ovenbird.trial.release import REFUSAL_CODES as RELEASE_REFUSALS
from ovenbird.trial.summary import CRITERION_IDS, SUMMARY_STATES
from ovenbird.weather.service import STATUSES
from ovenbird_core.control import BINDINGS, TERMS, LadderLevel, Mode, ReasonCode

ROOT = Path(__file__).resolve().parents[3]
COMPOSE = ROOT / "dev" / "docker-compose.yml"
SEED = ROOT / "dev" / "config-seed.json"
FIXTURES = Path(__file__).parent / "fixtures" / "ui"
UI_FIXTURES = ROOT / "ui" / "mock" / "fixtures"
GENERATED_NAMES = ("config.json", "schema.json", "codes.json")
UPDATE_ENV = "UPDATE_UI_FIXTURES"
INTERPOLATION = re.compile(r"\$\{([A-Z0-9_]+)(:?-)([^}]*)\}")
AUDIT_ACTIONS = (
    "config_apply",
    "config_rollback",
    "config_reset",
    "config_reset_ack",
    "mode_pause",
    "mode_resume",
    "hold_release",
    "pump_setting",
    "stove_request",
    "control_release",
    "snapshot_capture",
    "divergence_explain",
    "notify_test",
    "auth_refused",
    "ha_connection",
    "mqtt_connection",
    "mqtt_connection_reverted",
    "archive_delete",
)


def interpolate(value: str) -> str:
    """Resolve compose ``${VAR:-default}`` expressions to their defaults, repeatedly."""

    def default(match: re.Match[str]) -> str:
        """Return the fully resolved default of an interpolation match."""
        return interpolate(match.group(3))

    previous = None
    while previous != value:
        previous, value = value, INTERPOLATION.sub(default, value)
    return value


def compose_environment() -> dict[str, str]:
    """Return the dev ovenbird service environment with interpolations resolved."""
    compose = yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))
    environment = compose["services"]["ovenbird"]["environment"]
    return {name: interpolate(str(value)) for name, value in environment.items()}


@pytest.fixture
def dev_manager(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> ConfigManager:
    """Open a config manager over the dev compose environment and seed."""
    for name, value in compose_environment().items():
        if name.startswith("OVENBIRD_") and value != "":
            monkeypatch.setenv(name, value)
    monkeypatch.setenv("OVENBIRD_CONFIG_SEED", str(SEED))
    monkeypatch.setenv("OVENBIRD_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("OVENBIRD_UI_DIR", "/opt/ovenbird/ui")
    clock = FakeClock(1_794_009_600.0)
    return ConfigManager.open(load_settings(), clock, locked=provided_sources())


def test_compose_keeps_only_installation_values_in_the_environment() -> None:
    """The dev compose environment sets no control tuning except the mode and names the seed."""
    environment = compose_environment()
    control = sorted(
        name
        for name in environment
        if name.startswith("OVENBIRD_CONTROL_") and name != "OVENBIRD_CONTROL_MODE"
    )
    assert control == []
    assert environment["OVENBIRD_CONFIG_SEED"] == "/seed/config-seed.json"


def test_the_dev_stack_starts_with_the_seed(dev_manager: ConfigManager) -> None:
    """The dev stack starts at version 1 from the seed with expected sources and locks."""
    settings = dev_manager.settings
    assert dev_manager.version == 1
    latest = dev_manager.store.latest()
    assert latest is not None
    assert latest.origin is Origin.SEED
    assert settings.control_comfort_c == 21.5
    assert settings.control_room_signal == "room_temperature"
    assert settings.control_room_profile == "on_change"
    assert settings.control_room_liveness_signals == ("room_humidity",)
    assert settings.control_min_setpoint_c == 24.0
    assert settings.controller_config().pump_duty is not None
    assert settings.house_floor_area_m2 == 130
    assert not dev_manager.hold.active
    fields = dev_manager.payload()["fields"]
    assert fields["control_comfort_c"]["source"] == "store"
    assert fields["control_comfort_c"]["locked"] is False
    assert fields["control_mode"]["source"] == "env"
    assert fields["allow_commands"]["locked"] is True


def codes() -> dict[str, list[str]]:
    """Return every code set the UI must know, as lists of values."""
    return {
        "reason": [code.value for code in ReasonCode],
        "binding": sorted(BINDINGS),
        "ladder": [level.value for level in LadderLevel],
        "term": list(TERMS),
        "mode": [mode.value for mode in Mode],
        "alarm": [code.value for code in AlarmCode],
        "alarm_event": [kind.value for kind in AlarmEventKind],
        "alarm_journal": [
            HOLD_JOURNAL_CODE,
            STOVE_JOURNAL_CODE,
            ENVELOPE_JOURNAL_CODE,
            DAYSHIFT_JOURNAL_CODE,
        ],
        "severity": [severity.value for severity in Severity],
        "monitor_status": [status.value for status in MonitorStatus],
        "command_status": [status.value for status in CommandStatus],
        "validation_error": list(VALIDATION_ERRORS),
        "validation_warning": list(VALIDATION_WARNINGS),
        "config_source": [source.value for source in Source],
        "config_origin": [origin.value for origin in Origin],
        "config_tier": [tier.value for tier in Tier],
        "config_group": list(GROUP_ORDER),
        "audit_action": list(AUDIT_ACTIONS),
        "pump_setting": list(SETTING_IDS),
        "pump_owner": list(OWNERS),
        "pump_refusal": list(REFUSAL_CODES),
        "weather_check": list(STATUSES),
        "trial_check": list(CHECK_IDS),
        "trial_check_status": list(CHECK_STATUSES),
        "trial_criterion": list(CRITERION_IDS),
        "release_item_status": list(ITEM_STATUSES),
        "release_refusal": list(RELEASE_REFUSALS),
        "release_outcome": list(OUTCOMES),
        "snapshot_origin": list(ORIGINS),
        "snapshot_capture_refusal": list(CAPTURE_REFUSALS),
        "trial_phase": list(PHASES),
        "trial_summary_state": list(SUMMARY_STATES),
        "notify_health": list(HEALTH_STATES),
        "envelope_rule_state": list(ENVELOPE_STATES),
        "ha_test_error": list(ERROR_CODES),
        "mqtt_test_error": list(MQTT_ERROR_CODES),
    }


def _portable(payload: dict[str, Any], data_dir: Path) -> dict[str, Any]:
    """Return a payload as JSON with machine-specific paths replaced by container paths."""
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    text = text.replace(str(data_dir), "/data").replace(str(SEED), "/seed/config-seed.json")
    result: dict[str, Any] = json.loads(text)
    return result


def generated(manager: ConfigManager) -> dict[str, dict[str, Any]]:
    """Return the fixture payloads generated from a config manager, keyed by file name."""
    data_dir = manager.settings.data_dir
    return {
        "config.json": _portable(manager.payload(), data_dir),
        "schema.json": _portable(schema_payload(manager.settings), data_dir),
        "codes.json": codes(),
    }


def test_ui_fixtures_are_current(dev_manager: ConfigManager) -> None:
    """Committed UI fixtures match the generated ones; ``UPDATE_UI_FIXTURES=1`` rewrites them."""
    update = os.environ.get(UPDATE_ENV) == "1"
    FIXTURES.mkdir(parents=True, exist_ok=True)
    for name, payload in generated(dev_manager).items():
        path = FIXTURES / name
        text = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        if update or not path.exists():
            path.write_text(text, encoding="utf-8")
        assert path.read_text(encoding="utf-8") == text, f"{name} is stale; set {UPDATE_ENV}=1"


@pytest.mark.parametrize("name", GENERATED_NAMES)
def test_ui_mock_fixture_matches_the_generated_one(name: str) -> None:
    """The copy under ``ui/mock/fixtures`` is byte-identical to the generated fixture."""
    assert (UI_FIXTURES / name).read_bytes() == (FIXTURES / name).read_bytes(), (
        f"ui/mock/fixtures/{name} differs; run make ui-fixtures"
    )


def test_every_code_set_is_closed() -> None:
    """Every code set is non-empty and free of duplicates, and holds known members."""
    sets = codes()
    for name, values in sets.items():
        assert values, name
        assert len(values) == len(set(values)), name
    assert "config_reset" in sets["alarm"]
    assert "outside_envelope" in sets["validation_error"]
    assert "curve_shift_large" in sets["validation_warning"]
