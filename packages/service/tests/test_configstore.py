from __future__ import annotations

import json
import math
import sqlite3
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from ovenbird.config import ConfigError, Settings, load_settings
from ovenbird.configstore import (
    EDITABLE,
    NEVER_IN_STORE,
    Actor,
    ConfigManager,
    ConfigRefusedError,
    ConfigStore,
    Origin,
    Source,
    StoreLoss,
    provided_sources,
    schema_payload,
)
from ovenbird.configstore.fields import FIELDS, STORED_CONNECTION, Tier
from ovenbird.testing import FakeClock

ADMIN = Actor("admin from 127.0.0.1", "127.0.0.1")


@pytest.fixture
def base(make_settings: Callable[..., Settings]) -> Settings:
    """Default test settings."""
    return make_settings()


def open_manager(settings: Settings, clock: FakeClock | None = None) -> ConfigManager:
    """Open a config manager with env and file provided sources locked."""
    return ConfigManager.open(settings, clock or FakeClock(), locked=provided_sources())


def apply(manager: ConfigManager, clock: FakeClock, **changes: Any) -> dict[str, Any]:
    """Advance past the rate limit and apply changes with all warnings acknowledged."""
    clock.advance(61.0)
    warnings = [w.code for w in manager.validate(changes).warnings]
    return manager.apply(manager.version or 0, changes, ADMIN, acknowledge=warnings)


class TestPrecedence:
    """Which source wins for a field, and how that is reported."""

    def test_store_value_applies_and_is_reported(self, base: Settings) -> None:
        """A stored value overrides the default, is reported as store and survives a reopen."""
        clock = FakeClock()
        manager = open_manager(base, clock)
        apply(manager, clock, control_comfort_c=21.6)
        view = manager.payload()["fields"]["control_comfort_c"]
        assert view == {
            "value": 21.6,
            "source": "store",
            "locked": False,
            "stored": 21.6,
            "default": 21.0,
        }
        assert manager.settings.control_comfort_c == 21.6
        assert open_manager(base).settings.control_comfort_c == 21.6

    def test_environment_locks_and_wins(
        self, monkeypatch: pytest.MonkeyPatch, make_settings: Callable[..., Settings]
    ) -> None:
        """An environment variable beats the stored value, locks the field and refuses edits."""
        clock = FakeClock()
        manager = open_manager(make_settings(), clock)
        apply(manager, clock, control_dwell_s=1200)
        manager.close()
        monkeypatch.setenv("OVENBIRD_CONTROL_DWELL_S", "1800")
        locked = open_manager(make_settings(), clock)
        view = locked.payload()["fields"]["control_dwell_s"]
        assert view["source"] == "env"
        assert view["locked"] is True
        assert view["value"] == 1800.0
        assert view["stored"] == 1200.0
        assert locked.settings.control_dwell_s == 1800.0
        result = locked.validate({"control_dwell_s": 900})
        assert [(e.field, e.code) for e in result.errors] == [("control_dwell_s", "locked")]
        assert result.errors[0].params["env"] == "OVENBIRD_CONTROL_DWELL_S"

    def test_options_file_locks(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        make_settings: Callable[..., Settings],
    ) -> None:
        """Values from the options file lock their fields and rank below the environment."""
        options = tmp_path / "options.json"
        options.write_text(json.dumps({"control_comfort_c": 20.5}))
        monkeypatch.setenv("OVENBIRD_OPTIONS_FILE", str(options))
        manager = open_manager(make_settings())
        view = manager.payload()["fields"]["control_comfort_c"]
        assert (view["source"], view["locked"], view["value"]) == ("file", True, 20.5)
        assert provided_sources()["control_comfort_c"] is Source.FILE
        monkeypatch.setenv("OVENBIRD_CONTROL_COMFORT_C", "22")
        assert provided_sources()["control_comfort_c"] is Source.ENV

    def test_preset_and_default_sources(self, base: Settings) -> None:
        """Unset fields report preset or default as source with the matching value."""
        fields = open_manager(base).payload()["fields"]
        assert fields["control_dwell_s"] == {
            "value": 900.0,
            "source": "preset",
            "locked": False,
            "stored": None,
            "default": 900.0,
        }
        assert fields["control_curve"]["value"] == [[-10.0, 39.0], [0.0, 34.0], [15.0, 25.0]]
        assert fields["control_comfort_c"]["source"] == "default"
        assert fields["control_interval_s"]["locked"] is True
        assert fields["admin_password"]["value"] == "unset"

    def test_store_value_follows_emitter_presets(self, base: Settings) -> None:
        """Changing the emitter in the store switches the preset-derived field values."""
        clock = FakeClock()
        manager = open_manager(base, clock)
        apply(manager, clock, control_emitter="radiators")
        fields = manager.payload()["fields"]
        assert fields["control_dwell_s"]["value"] == 600.0
        assert fields["control_max_supply_c"]["value"] == 55.0


def _numeric_bounds(settings: Settings) -> list[tuple[str, float, float, str, bool]]:
    """Return name, min, max, type and exclusivity of each bounded numeric editable field."""
    schema = schema_payload(settings)["fields"]
    found = []
    for name in sorted(EDITABLE):
        entry = schema[name]
        if entry["type"] in {"number", "integer"} and entry["min"] is not None:
            found.append((name, entry["min"], entry["max"], entry["type"], entry["exclusive_min"]))
    return found


def test_every_editable_field_is_in_the_schema(base: Settings) -> None:
    """The schema covers every setting once, in groups, with presets and envelope."""
    schema = schema_payload(base)
    assert set(schema["fields"]) == set(Settings.model_fields)
    grouped = [name for group in schema["groups"] for name in group["fields"]]
    assert sorted(grouped) == sorted(Settings.model_fields)
    for name in EDITABLE:
        assert schema["fields"][name]["editable"] is True
        assert schema["fields"][name]["tier"] in {"basic", "advanced"}
    assert schema["presets"]["mixed"]["control_dwell_s"] == 900.0
    assert schema["envelope"] == {
        "curve": [[-10.0, 39.0], [0.0, 34.0], [15.0, 25.0]],
        "below_k": 6.0,
        "above_k": 5.0,
    }


@pytest.mark.parametrize("edge", ["below", "above"])
def test_every_editable_bound_is_enforced(base: Settings, edge: str) -> None:
    """Every bounded editable field refuses values past its limit and accepts values at it."""
    manager = open_manager(base)
    bounds = _numeric_bounds(base)
    assert len(bounds) >= 20
    for name, low, high, kind, exclusive in bounds:
        step = 1 if kind == "integer" else 0.5
        value = low - step if edge == "below" else high + step
        result = manager.validate({name: int(value) if kind == "integer" else value})
        assert not result.valid, (name, value)
        assert any(error.field == name for error in result.errors), (name, result.errors)
        lowest = low + 0.05 if exclusive else low
        inside = manager.validate({name: int(lowest) if kind == "integer" else lowest})
        inside_errors = [
            e for e in inside.errors if e.field == name and e.code in {"below_min", "above_max"}
        ]
        assert inside_errors == [], (name, low, inside.errors)


@pytest.mark.parametrize(
    ("changes", "field", "code"),
    [
        ({"control_feedback_ti_s": 600}, "control_feedback_ti_s", "integral_time"),
        ({"control_curve": [[-10, 39]]}, "control_curve", "curve_points"),
        ({"control_curve": [[0, 34], [-10, 39]]}, "control_curve", "curve_order"),
        ({"control_curve": [[-10, 33], [15, 34]]}, "control_curve", "curve_order"),
        ({"control_curve": [[-40, 39], [15, 25]]}, "control_curve", "curve_outside_range"),
        ({"control_curve": [[-10, 41], [15, 25]]}, "control_curve", "curve_range"),
        ({"control_curve": [[-10, 39], [5, 37], [15, 25]]}, "control_curve", "outside_envelope"),
        ({"control_timezone": "Mars/Olympus"}, "control_timezone", "timezone"),
        (
            {"control_feedback_integral_limit_k": 2.5, "control_feedback_output_limit_k": 2.0},
            "control_feedback_integral_limit_k",
            "integral_above_output",
        ),
        ({"control_min_setpoint_c": 40}, "control_min_setpoint_c", "min_above_max"),
        ({"control_max_supply_c": 45}, "control_max_supply_c", "max_supply_raise"),
        ({"control_pump_duty_idle": 170}, "control_pump_duty_idle", "pump_duty_order"),
        ({"control_room_signal": "nowhere"}, "control_room_signal", "signal_unknown"),
        (
            {"control_room_liveness_signals": ["x"]},
            "control_room_liveness_signals",
            "room_signal_required",
        ),
        ({"weather_latitude": 52.1}, "weather_longitude", "location_pair"),
        ({"weather_location_source": "manual"}, "weather_latitude", "location_required"),
        (
            {"control_quiet_windows": [{"start": "22:00", "end": "22:00", "level": 1}]},
            "control_quiet_windows",
            "window_empty",
        ),
        (
            {"control_quiet_windows": [{"start": "25:00", "end": "06:00", "level": 1}]},
            "control_quiet_windows",
            "clock_time",
        ),
        (
            {"control_quiet_windows": [{"start": "22:00", "end": "06:00", "level": 1}] * 5},
            "control_quiet_windows",
            "too_many",
        ),
        ({"control_emitter": "underfloor"}, "control_emitter", "not_allowed"),
        ({"control_comfort_c": "warm"}, "control_comfort_c", "type"),
        ({"no_such_field": 1}, "no_such_field", "unknown_field"),
        ({"control_interval_s": 30}, "control_interval_s", "not_editable"),
    ],
)
def test_rules_report_field_and_code(
    base: Settings, changes: dict[str, Any], field: str, code: str
) -> None:
    """Each validation rule reports the offending field with its specific error code."""
    result = open_manager(base).validate(changes)
    assert (field, code) in [(e.field, e.code) for e in result.errors], result.errors


def test_curve_inside_the_envelope_is_accepted(base: Settings) -> None:
    """A heating curve within the safety envelope validates and is echoed as floats."""
    result = open_manager(base).validate({"control_curve": [[-10, 40], [0, 35], [15, 25]]})
    assert result.valid, result.errors
    assert result.effective == {"control_curve": [[-10.0, 40.0], [0.0, 35.0], [15.0, 25.0]]}


@pytest.mark.parametrize("name", sorted(NEVER_IN_STORE))
def test_never_in_store_is_refused(base: Settings, name: str) -> None:
    """Fields that must never be stored are refused with the matching error code."""
    result = open_manager(base).validate({name: True})
    code = "connection_field" if name in STORED_CONNECTION else "not_editable"
    assert [(e.field, e.code) for e in result.errors] == [(name, code)]


def test_never_in_store_is_disjoint_from_editable() -> None:
    """Stored-never fields do not overlap editable ones and expert fields are not editable."""
    assert not EDITABLE & NEVER_IN_STORE
    assert {"allow_commands", "command_brokers", "simulation", "admin_password"} <= NEVER_IN_STORE
    assert all(meta.tier is not Tier.EXPERT for name, meta in FIELDS.items() if name in EDITABLE)


def test_a_planted_document_cannot_enable_publishing(base: Settings) -> None:
    """Publishing settings written straight into the store are ignored on load."""
    manager = open_manager(base)
    manager.store.append(
        {"allow_commands": True, "command_brokers": ["localhost"], "control_comfort_c": 20.0},
        actor="intruder",
        origin=Origin.UI,
        now_ts=1.0,
    )
    manager.close()
    reopened = open_manager(base)
    assert reopened.settings.allow_commands is False
    assert reopened.settings.command_brokers == ()
    assert reopened.settings.control_comfort_c == 20.0


def test_warnings_need_acknowledgement(base: Settings) -> None:
    """Applying a change with unacknowledged warnings is refused until all are acknowledged."""
    clock = FakeClock()
    manager = open_manager(base, clock)
    clock.advance(61)
    changes = {"control_comfort_c": 25.0, "control_cycling_enabled": False}
    codes = {w.code for w in manager.validate(changes).warnings}
    assert codes == {"above_soft_max", "cycling_disabled"}
    with pytest.raises(ConfigRefusedError) as refused:
        manager.apply(0, changes, ADMIN, acknowledge=["above_soft_max"])
    assert refused.value.status == 422
    assert [e["code"] for e in refused.value.body["errors"]] == ["warning_not_acknowledged"]
    result = manager.apply(0, changes, ADMIN, acknowledge=sorted(codes))
    assert result["version"] == 1


def test_curve_shift_warning(base: Settings) -> None:
    """A large shift of the curve from the default raises a warning but stays valid."""
    result = open_manager(base).validate({"control_curve": [[-10, 40], [0, 38.5], [15, 25]]})
    assert result.valid
    assert [w.code for w in result.warnings] == ["curve_shift_large"]
    assert result.warnings[0].params["shift_k"] == 4.5


def test_stale_base_rate_and_no_change(base: Settings) -> None:
    """Apply refuses a stale base version, a too-fast second apply and a no-op change."""
    clock = FakeClock()
    manager = open_manager(base, clock)
    first = manager.apply(0, {"control_comfort_c": 21.5}, ADMIN)
    assert first["version"] == 1
    with pytest.raises(ConfigRefusedError) as stale:
        manager.apply(0, {"control_comfort_c": 21.4}, ADMIN)
    assert (stale.value.status, stale.value.body["version"]) == (409, 1)
    with pytest.raises(ConfigRefusedError) as rate:
        manager.apply(1, {"control_comfort_c": 21.4}, ADMIN)
    assert rate.value.status == 429
    clock.advance(61)
    with pytest.raises(ConfigRefusedError) as same:
        manager.apply(1, {"control_comfort_c": 21.5}, ADMIN)
    assert [e["code"] for e in same.value.body["errors"]] == ["no_change"]


def test_daily_apply_limit(base: Settings) -> None:
    """At most 30 applies are accepted per day, after which the limit resets."""
    clock = FakeClock()
    manager = open_manager(base, clock)
    for index in range(30):
        clock.advance(61)
        manager.apply(index, {"control_comfort_c": 20.0 + index * 0.1}, ADMIN)
    clock.advance(61)
    with pytest.raises(ConfigRefusedError) as limit:
        manager.apply(30, {"control_comfort_c": 19.0}, ADMIN)
    assert limit.value.status == 429
    clock.advance(86_400)
    assert manager.apply(30, {"control_comfort_c": 19.0}, ADMIN)["version"] == 31


def test_versions_audit_rollback_and_snapshot(base: Settings) -> None:
    """Versions, audit, rollback and snapshot stay consistent and tables are append-only."""
    clock = FakeClock()
    manager = open_manager(base, clock)
    apply(manager, clock, control_comfort_c=21.5)
    apply(manager, clock, control_comfort_c=22.0, control_dwell_s=1200)
    clock.advance(61)
    result = manager.rollback(1, 2, ADMIN, comment="back")
    assert result["version"] == 3
    assert manager.settings.control_comfort_c == 21.5
    assert manager.settings.control_dwell_s is None
    versions = manager.versions_payload(10)["versions"]
    assert [v["version"] for v in versions] == [3, 2, 1]
    assert versions[0]["origin"] == "rollback"
    assert versions[0]["changed"] == [
        {"field": "control_comfort_c", "from": 22.0, "to": 21.5},
        {"field": "control_dwell_s", "from": 1200.0, "to": None},
    ]
    events = manager.store.audit_events(0, math.inf, 10)
    assert [e.action for e in events] == ["config_apply", "config_apply", "config_rollback"]
    assert events[-1].detail["rollback_to"] == 1
    assert events[0].actor == ADMIN.name
    assert manager.store.snapshot_path.is_file()
    with sqlite3.connect(manager.store.snapshot_path) as snap:
        assert snap.execute("SELECT MAX(version) FROM config_version").fetchone()[0] == 3
    with pytest.raises(sqlite3.DatabaseError, match="append-only"):
        manager.store._conn.execute("UPDATE config_version SET doc = '{}'")
    with pytest.raises(sqlite3.DatabaseError, match="append-only"):
        manager.store._conn.execute("DELETE FROM audit")


def test_export_has_no_secret(make_settings: Callable[..., Settings]) -> None:
    """The config export contains no passwords or tokens."""
    settings = make_settings(
        admin_password="pw-123-secret",
        operate_token="t" * 40,
        mqtt_password="broker-secret",
        http_host="0.0.0.0",
    )
    clock = FakeClock()
    manager = open_manager(settings, clock)
    apply(manager, clock, control_comfort_c=21.5)
    body = manager.export()
    text = json.dumps(body)
    assert "pw-123-secret" not in text
    assert "t" * 40 not in text
    assert "broker-secret" not in text
    assert not {"admin_password", "operate_token", "mqtt_password", "ha_token"} & set(
        body["effective"]
    )
    assert body["ovenbird_config"] == 1
    assert body["values"] == {"control_comfort_c": 21.5}


class TestStartup:
    """Config manager behaviour on first start, seeding and store loss."""

    def test_seed_becomes_version_one(
        self, tmp_path: Path, make_settings: Callable[..., Settings]
    ) -> None:
        """A valid seed file becomes version one once and is not re-applied."""
        seed = tmp_path / "seed.json"
        seed.write_text(json.dumps({"ovenbird_config": 1, "values": {"control_comfort_c": 21.5}}))
        manager = open_manager(make_settings(config_seed=seed))
        assert manager.version == 1
        assert manager.settings.control_comfort_c == 21.5
        assert manager.store.latest() is not None
        assert manager.store.latest().origin is Origin.SEED  # type: ignore[union-attr]
        manager.close()
        again = open_manager(make_settings(config_seed=seed))
        assert again.version == 1

    def test_invalid_seed_stops_the_start(
        self, tmp_path: Path, make_settings: Callable[..., Settings]
    ) -> None:
        """An out-of-range, malformed or missing seed aborts startup with an error."""
        seed = tmp_path / "seed.json"
        seed.write_text(json.dumps({"ovenbird_config": 1, "values": {"control_comfort_c": 99}}))
        with pytest.raises(ConfigError, match="seed"):
            open_manager(make_settings(config_seed=seed))
        seed.write_text("{}")
        with pytest.raises(ConfigError, match="export"):
            open_manager(make_settings(config_seed=seed, data_dir=tmp_path / "d2"))
        with pytest.raises(ConfigError, match="FileNotFoundError"):
            open_manager(
                make_settings(config_seed=tmp_path / "missing.json", data_dir=tmp_path / "d3")
            )

    def test_first_start_is_not_a_loss(self, base: Settings) -> None:
        """A fresh data directory is not reported as store loss and holds nothing back."""
        manager = open_manager(base)
        assert manager.loss is None
        assert not manager.hold.active

    def test_missing_store_starts_in_shadow(self, base: Settings) -> None:
        """A vanished store without snapshot reverts to defaults and needs a reset ack."""
        clock = FakeClock()
        manager = open_manager(base, clock)
        apply(manager, clock, control_comfort_c=21.5)
        manager.close()
        for name in ("config.db", "config.db-wal", "config.db-shm", "config.snapshot.db"):
            (base.data_dir / name).unlink(missing_ok=True)
        lost = open_manager(base)
        assert lost.loss is StoreLoss.MISSING
        assert lost.hold.reset_pending
        assert lost.settings.control_comfort_c == 21.0
        lost.close()
        assert open_manager(base).hold.reset_pending

    def test_snapshot_restores_a_missing_store(self, base: Settings) -> None:
        """A missing store is restored from its snapshot without loss."""
        clock = FakeClock()
        manager = open_manager(base, clock)
        apply(manager, clock, control_comfort_c=21.5)
        manager.close()
        (base.data_dir / "config.db").unlink()
        restored = open_manager(base)
        assert restored.loss is None
        assert restored.settings.control_comfort_c == 21.5

    def test_corrupt_store_is_quarantined(self, base: Settings) -> None:
        """A corrupt store file is set aside and flagged as loss."""
        open_manager(base).close()
        (base.data_dir / "config.snapshot.db").unlink(missing_ok=True)
        (base.data_dir / "config.db").write_bytes(b"not a database" * 100)
        corrupt = open_manager(base)
        assert corrupt.loss is StoreLoss.CORRUPT
        assert corrupt.hold.reset_pending
        assert list(base.data_dir.glob("config.db.corrupt-*"))

    def test_invalid_version_is_followed_by_a_reset_version(
        self, monkeypatch: pytest.MonkeyPatch, make_settings: Callable[..., Settings]
    ) -> None:
        """A stored version that no longer validates is followed by an empty reset version."""
        clock = FakeClock()
        manager = open_manager(make_settings(), clock)
        apply(manager, clock, control_min_setpoint_c=30)
        manager.close()
        monkeypatch.setenv("OVENBIRD_CONTROL_MAX_SUPPLY_C", "30")
        invalid = open_manager(make_settings())
        assert invalid.loss is StoreLoss.INVALID
        assert invalid.hold.reset_pending
        latest = invalid.store.latest()
        assert latest is not None
        assert (latest.version, latest.origin, latest.values) == (2, Origin.RESET, {})
        assert invalid.settings.control_min_setpoint_c is None

    def test_reset_ack_and_pause_persist(self, base: Settings) -> None:
        """Acknowledging a reset needs a pending reset and is audited."""
        manager = open_manager(base)
        with pytest.raises(ConfigRefusedError) as none:
            manager.reset_ack(ADMIN)
        assert none.value.status == 409
        manager.hold.reset_pending = True
        manager.store.runtime_set("reset_pending", "missing")
        manager.reset_ack(ADMIN)
        assert not manager.hold.reset_pending
        assert [e.action for e in manager.store.audit_events(0, math.inf, 5)] == [
            "config_reset_ack"
        ]


def test_pause_needs_an_auto_installation(make_settings: Callable[..., Settings]) -> None:
    """Pause is refused in shadow installs and persists across restarts in auto installs."""
    shadow = open_manager(make_settings())
    with pytest.raises(ConfigRefusedError) as refused:
        shadow.pause(ADMIN)
    assert refused.value.status == 409
    auto = make_settings(control_mode="auto")
    manager = open_manager(auto)
    assert manager.pause(ADMIN, "testing")["mode"] == {
        "configured": "auto",
        "effective": "shadow",
        "paused": True,
        "reset_pending": False,
    }
    manager.close()
    reopened = open_manager(auto)
    assert reopened.hold.paused
    assert reopened.resume(ADMIN)["mode"]["effective"] == "auto"
    reopened.close()
    assert not open_manager(auto).hold.paused


def test_store_schema_is_versioned(base: Settings) -> None:
    """The config store uses schema version 2 in WAL mode."""
    store, loss = ConfigStore.open(base.data_dir)
    assert loss is None
    assert store._conn.execute("PRAGMA user_version").fetchone()[0] == 2
    assert store._conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    store.close()


def test_load_settings_rejects_a_curve_outside_the_envelope() -> None:
    """Loading settings refuses a curve that leaves the safety envelope."""
    with pytest.raises(ConfigError, match="envelope"):
        load_settings(control_curve=((-10.0, 45.0), (15.0, 25.0)), control_max_supply_c=50.0)


def test_merge_does_not_reread_the_environment(
    base: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Applying changes does not re-read environment variables set after startup."""
    clock = FakeClock()
    manager = ConfigManager.open(base, clock, locked={})
    monkeypatch.setenv("OVENBIRD_CONTROL_DWELL_S", "1800")
    apply(manager, clock, control_comfort_c=21.5)
    assert manager.settings.control_comfort_c == 21.5
    assert manager.settings.control_dwell_s is None


def test_config_db_commits_are_durable(base: Settings) -> None:
    """The config database commits with full synchronous durability in WAL mode."""
    store, _ = ConfigStore.open(base.data_dir)
    try:
        assert store._conn.execute("PRAGMA synchronous").fetchone()[0] == 2
        assert store._conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    finally:
        store.close()
