"""House basics: the heat-loss and emitter fits recover a synthetic house, and the endpoint."""

from __future__ import annotations

import math
import random
import shutil
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from ovenbird.api.app import create_app
from ovenbird.config import Settings
from ovenbird.history import AlarmRow, open_history
from ovenbird.history.journal import write_journal
from ovenbird.insight import basics
from ovenbird.insight.basics import (
    BasicsCache,
    BasicsFit,
    Exclusions,
    LiveInputs,
    LossPoint,
    compute_fit,
    fit_heat_loss,
    fit_line,
    fit_origin,
    robust_line,
    steady_heat,
    table_temperatures,
)
from ovenbird.runtime import Runtime
from ovenbird.testing import FakeClock
from ovenbird_core import heat_power_w

ZONE = "UTC"
ROOM = "room_temperature"
HEAT = "derived/heat_delivered_w"
COMPRESSOR = "main/Compressor_Freq"
VALVE = "main/ThreeWay_Valve_State"
DEFROST = "main/Defrosting_State"
OUTSIDE = "main/Outside_Temp"
INLET = "main/Main_Inlet_Temp"
OUTLET = "main/Main_Outlet_Temp"
FLOW = "main/Pump_Flow"
ELECTRIC = "main/Heat_Power_Consumption"
QUARTER = 900
QUARTERS = 96
START = date(2026, 1, 1)
H_TRUE = 180.0
G_TRUE = 600.0
K_TRUE = 400.0
COP_TRUE = 4.0
FLOW_L_MIN = 20.0


@dataclass
class House:
    """A synthetic house written as 15 min rollups.

    Parameters
    ----------
    days
        Days written, starting at :data:`START`.
    h, g, k
        Heat-loss figure, free heat and emitter figure.
    span_k
        Peak-to-peak swing of the daily outside mean.
    noise_w
        Standard deviation of the daily heat noise.
    stove_days
        Days with a wood-stove evening (journalled).
    gap_days
        Days with half of the heat data missing.
    seed
        Seed of the noise.
    """

    days: int = 60
    h: float = H_TRUE
    g: float = G_TRUE
    k: float = K_TRUE
    span_k: float = 16.0
    noise_w: float = 60.0
    stove_days: tuple[int, ...] = ()
    gap_days: tuple[int, ...] = ()
    seed: int = 7

    def outside(self, day: int) -> float:
        """Daily outside mean of day ``day``."""
        return 6.0 + self.span_k / 2.0 * math.sin(day / 5.0)

    def write(self, path: Path) -> None:
        """Write the rollups and the stove journal to ``path``."""
        rng = random.Random(self.seed)
        names = [HEAT, COMPRESSOR, VALVE, DEFROST, OUTSIDE, ROOM, INLET, OUTLET, FLOW, ELECTRIC]
        ids = {name: idx + 1 for idx, name in enumerate(names)}
        capacity = heat_power_w(FLOW_L_MIN, 0.0, 1.0)
        rows: list[tuple[Any, ...]] = []
        for day in range(self.days):
            start = datetime.combine(START + timedelta(days=day), datetime.min.time(), UTC)
            base = int(start.timestamp())
            room = 21.0 + rng.gauss(0.0, 0.1)
            outside = self.outside(day)
            daily = max(0.0, self.h * (room - outside) - self.g + rng.gauss(0.0, self.noise_w))
            water_rise = 6.0 + 0.3 * (room - outside)
            run_heat = self.k * water_rise
            on = min(QUARTERS, max(0, round(daily * QUARTERS / run_heat)))
            run_heat = daily * QUARTERS / on if on else 0.0
            for q in range(QUARTERS):
                bucket = base + q * QUARTER
                running = q < on
                heat = run_heat if running else 0.0
                water = room + (heat / self.k if running else 2.0) + rng.gauss(0.0, 0.05)
                spread = heat / capacity
                values = {
                    COMPRESSOR: 40.0 if running else 0.0,
                    VALVE: 0.0,
                    DEFROST: 0.0,
                    OUTSIDE: outside,
                    ROOM: room,
                    INLET: water - spread / 2.0,
                    OUTLET: water + spread / 2.0,
                    FLOW: FLOW_L_MIN,
                    ELECTRIC: heat / COP_TRUE,
                }
                if not (day in self.gap_days and q >= QUARTERS // 2):
                    values[HEAT] = heat
                for name, value in values.items():
                    rows.append(
                        (
                            QUARTER,
                            ids[name],
                            bucket,
                            value * QUARTER,
                            float(QUARTER),
                            value,
                            value,
                            value,
                            float(bucket + QUARTER),
                        )
                    )
        alarms = []
        for day in self.stove_days:
            evening = datetime.combine(START + timedelta(days=day), datetime.min.time(), UTC)
            begin = evening.timestamp() + 18 * 3600
            alarms.append(AlarmRow(begin, "stove_mode", "info", "started", "stove", "{}"))
            alarms.append(AlarmRow(begin + 4 * 3600, "stove_mode", "info", "expired", "", "{}"))
        conn = open_history(path)
        try:
            conn.executemany(
                "INSERT INTO signal (id, name, unit, kind) VALUES (?, ?, NULL, 'number')",
                [(ids[name], name) for name in names],
            )
            conn.executemany("INSERT INTO rollup VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", rows)
            conn.commit()
            write_journal(conn, [], [], alarms)
        finally:
            conn.close()


def end_of(house: House) -> datetime:
    """Return midday of the day after the last day written."""
    return datetime.combine(
        START + timedelta(days=house.days), datetime.min.time(), UTC
    ) + timedelta(hours=12)


@pytest.fixture(scope="module")
def default_db(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Return a history with the default synthetic house, written once per module."""
    path = tmp_path_factory.mktemp("basics") / "history.db"
    House().write(path)
    return path


def fit_default(path: Path) -> BasicsFit:
    """Fit the default house in ``path``."""
    return compute_fit(path, now=end_of(House()), timezone=ZONE, room_signal=ROOM)


def fitted(tmp_path: Path, house: House) -> BasicsFit:
    """Write ``house`` and fit it."""
    path = tmp_path / "history.db"
    house.write(path)
    return compute_fit(path, now=end_of(house), timezone=ZONE, room_signal=ROOM)


def live(**overrides: Any) -> LiveInputs:
    """Return live inputs with invented values."""
    values: dict[str, Any] = {
        "room_c": 21.0,
        "comfort_c": 21.0,
        "outside_c": 2.0,
        "outside_source": "filtered",
        "heat_now_w": 2500.0,
        "hot_water": False,
        "setpoint_min_c": 24.0,
        "setpoint_max_c": 45.0,
    }
    values.update(overrides)
    return LiveInputs(**values)


def test_the_heat_loss_and_the_emitter_of_a_synthetic_house_are_recovered(
    default_db: Path,
) -> None:
    """H, G and K fall inside their bands; the status is credible."""
    fit = fit_default(default_db)
    loss = fit.heat_loss
    assert loss.status == "credible"
    assert loss.reasons == ()
    line = loss.fit
    assert line is not None
    half = line.t * line.slope_se
    assert line.slope - half <= H_TRUE <= line.slope + half
    assert half < 0.1 * H_TRUE
    assert -line.intercept == pytest.approx(G_TRUE, rel=0.25)
    assert loss.days_used >= 50
    emitter = fit.emitter
    assert emitter.status in {"credible", "provisional"}
    assert emitter.fit is not None
    k_half = emitter.fit.t * emitter.fit.slope_se
    assert emitter.fit.slope - k_half <= K_TRUE <= emitter.fit.slope + k_half
    assert emitter.flow_l_min == pytest.approx(FLOW_L_MIN)


def test_stove_and_low_coverage_days_are_left_out(tmp_path: Path) -> None:
    """A stove evening excludes its day and the next (tail); a half-empty day is low coverage."""
    fit = fitted(tmp_path, House(stove_days=(10, 30), gap_days=(20,)))
    loss = fit.heat_loss
    assert loss.exclusions.stove == 4
    assert loss.exclusions.low_coverage == 1
    dates = {d for p in loss.points for d in (p.first, p.last)}
    for day in (10, 11, 20, 30, 31):
        assert START + timedelta(days=day) not in dates
    assert loss.status == "credible"


def test_too_few_days_are_collecting(tmp_path: Path) -> None:
    """Fewer than ten days give no number."""
    loss = fitted(tmp_path, House(days=8)).heat_loss
    assert loss.status == "collecting"
    assert loss.reasons == ("too_few_days",)
    assert loss.fit is None


def test_a_few_weeks_are_provisional(tmp_path: Path) -> None:
    """Twelve to twenty-nine days give a provisional number with a wider band."""
    loss = fitted(tmp_path, House(days=16)).heat_loss
    assert loss.status == "provisional"
    assert "few_days" in loss.reasons
    assert loss.fit is not None


def test_a_narrow_span_is_provisional(tmp_path: Path) -> None:
    """Many days within a few kelvin are provisional (narrow span)."""
    loss = fitted(tmp_path, House(span_k=6.0)).heat_loss
    assert loss.status == "provisional"
    assert loss.reasons == ("narrow_span",)


def test_a_flat_span_is_collecting(tmp_path: Path) -> None:
    """Days within a kelvin cannot give a slope."""
    loss = fitted(tmp_path, House(span_k=1.0)).heat_loss
    assert loss.status == "collecting"
    assert loss.reasons == ("span_too_small",)


def points(slope: float, count: int = 20) -> list[LossPoint]:
    """Return windows on the line ``P = slope dT + 3000`` over 8 to 20 K."""
    day = START
    found = []
    for idx in range(count):
        delta = 8.0 + 12.0 * idx / (count - 1)
        found.append(
            LossPoint(
                day, day, delta, slope * delta + 3000.0 + (idx % 3) * 10.0, 21.0 - delta, 21.0
            )
        )
        day += timedelta(days=2)
    return found


def test_without_a_room_signal_nothing_is_fitted(tmp_path: Path) -> None:
    """No room signal: both fits are collecting with the reason."""
    path = tmp_path / "history.db"
    House(days=20).write(path)
    fit = compute_fit(path, now=end_of(House(days=20)), timezone=ZONE, room_signal=None)
    assert fit.heat_loss.reasons == ("no_room_signal",)
    assert fit.emitter.reasons == ("no_room_signal",)


def test_a_negative_slope_is_collecting() -> None:
    """Heat falling as it gets colder is not physical."""
    loss = fit_heat_loss(points(-50.0), Exclusions())
    assert loss.status == "collecting"
    assert loss.reasons == ("slope_not_positive",)


def test_an_absurd_slope_is_collecting() -> None:
    """A slope above the limit is not believed."""
    loss = fit_heat_loss(points(5000.0), Exclusions())
    assert loss.status == "collecting"
    assert loss.reasons == ("slope_implausible",)


def test_fit_line_recovers_a_line_and_its_band() -> None:
    """Ordinary least squares on exact points."""
    fit = fit_line([1.0, 2.0, 3.0, 4.0], [3.0, 5.0, 7.0, 9.0])
    assert fit is not None
    assert fit.slope == pytest.approx(2.0)
    assert fit.intercept == pytest.approx(1.0)
    assert fit.slope_se == pytest.approx(0.0)
    assert fit_line([1.0, 1.0, 1.0], [1.0, 2.0, 3.0]) is None
    assert fit_line([1.0, 2.0], [1.0, 2.0]) is None


def test_robust_line_drops_an_outlier() -> None:
    """A single wild point is left out."""
    xs = [float(x) for x in range(12)]
    ys = [10.0 * x + (1.0 if x % 2 else -1.0) for x in xs]
    ys[5] += 500.0
    fit, kept = robust_line(xs, ys)
    assert fit is not None
    assert kept.count(False) == 1
    assert not kept[5]
    assert fit.slope == pytest.approx(10.0, abs=0.5)


def test_fit_origin_clusters_its_error() -> None:
    """Through the origin; the error is clustered by group."""
    fit = fit_origin([1.0, 2.0, 3.0, 4.0], [2.1, 3.9, 6.1, 7.9], ["a", "a", "b", "b"])
    assert fit is not None
    assert fit.slope == pytest.approx(2.0, abs=0.05)
    assert fit.clusters == 2
    assert fit_origin([1.0, 2.0], [2.0, 4.0], ["a", "a"]) is None


def test_table_temperatures_span_the_setpoint_range() -> None:
    """The range ends and every 5 K between, not too close to an end."""
    assert table_temperatures(24.0, 45.0) == [24.0, 30.0, 35.0, 40.0, 45.0]
    assert table_temperatures(25.0, 35.0) == [25.0, 30.0, 35.0]
    assert table_temperatures(30.0, 30.0) == [30.0]


def test_steady_heat_follows_the_emitter_and_the_flow() -> None:
    """Without flow the mean water is the supply; with flow it sits half the spread lower."""
    assert steady_heat(400.0, 31.0, 21.0, None) == (4000.0, 31.0)
    heat, water = steady_heat(400.0, 31.0, 21.0, 1000.0)
    assert heat == pytest.approx(400.0 * (water - 21.0))
    assert 31.0 - water == pytest.approx(heat / 2000.0)
    assert steady_heat(400.0, 18.0, 21.0, None)[0] == 0.0


def test_night_span_runs_to_the_next_morning() -> None:
    """In the afternoon the night starts at 18:00; after midnight it starts now."""
    afternoon = datetime(2026, 1, 5, 15, 0, tzinfo=UTC).timestamp()
    begin, end = basics.night_span(afternoon, ZONE)
    assert begin == datetime(2026, 1, 5, 18, 0, tzinfo=UTC).timestamp()
    assert end == datetime(2026, 1, 6, 9, 0, tzinfo=UTC).timestamp()
    small_hours = datetime(2026, 1, 6, 3, 0, tzinfo=UTC).timestamp()
    assert basics.night_span(small_hours, ZONE) == (small_hours, end)


def test_production_by_weather_bins_the_days(default_db: Path) -> None:
    """Bins of 2 K with the pump's COP; thin bins are flagged in the body."""
    fit = fit_default(default_db)
    bins = fit.bins
    assert sum(b.days for b in bins) == 60
    assert all(b.to_c - b.from_c == 2.0 for b in bins)
    assert all(b.cop == pytest.approx(COP_TRUE) for b in bins if b.heat_w > 0)
    assert [b.from_c for b in bins] == sorted(b.from_c for b in bins)


def test_the_cache_recomputes_after_an_hour_or_a_new_day() -> None:
    """One computation per hour and local day."""
    calls: list[datetime] = []
    cache = BasicsCache()
    noon = datetime(2026, 1, 5, 12, 0, tzinfo=UTC)

    def compute_at(moment: datetime) -> Callable[[], BasicsFit]:
        """Return a computation stamped at ``moment``."""

        def compute() -> BasicsFit:
            """Record the call and return an empty fit."""
            calls.append(moment)
            return BasicsFit(
                moment.timestamp(),
                fit_heat_loss([], Exclusions()),
                basics.fit_emitter([], ZONE, room_known=True),
                (),
            )

        return compute

    key = ("db", ROOM, ZONE)
    for minutes in (0, 10, 59):
        moment = noon + timedelta(minutes=minutes)
        cache.get(key, moment, moment.date(), compute_at(moment))
    assert len(calls) == 1
    later = noon + timedelta(minutes=61)
    cache.get(key, later, later.date(), compute_at(later))
    assert len(calls) == 2
    midnight = datetime(2026, 1, 6, 0, 1, tzinfo=UTC)
    cache.get(key, midnight, midnight.date(), compute_at(midnight))
    assert len(calls) == 3
    cache.get(("other", ROOM, ZONE), midnight, midnight.date(), compute_at(midnight))
    assert len(calls) == 4


def test_the_payload_combines_the_fits_with_the_live_values(default_db: Path) -> None:
    """Loss now, design load, emitter table and balance are consistent with the fits."""
    body = basics.basics_payload(
        default_db,
        now=end_of(House()),
        timezone=ZONE,
        room_signal=ROOM,
        live=live(),
        cache=BasicsCache(),
    )
    assert body["enabled"] is True
    loss = body["heat_loss"]
    assert loss["status"] == "credible"
    assert loss["h_low_w_per_k"] <= H_TRUE <= loss["h_high_w_per_k"]
    now = body["loss_now"]["now"]
    expected = H_TRUE * (21.0 - 2.0) - G_TRUE
    assert now["low_w"] <= expected <= now["high_w"]
    assert body["loss_now"]["night"] is None
    assert body["loss_now"]["forecast_available"] is False
    design = body["loss_now"]["design"]
    assert design["outside_c"] == basics.DESIGN_OUTSIDE_C
    assert design["beyond_data"] is True
    emitter = body["heat_pump"]["emitter"]
    assert [row["supply_c"] for row in emitter["table"]] == [24.0, 30.0, 35.0, 40.0, 45.0]
    assert all(row["loss_now_w"] == now["loss_w"] for row in emitter["table"])
    heats = [row["heat_w"] for row in emitter["table"]]
    assert heats == sorted(heats)
    balance = emitter["balance_mean_water_c"]
    assert balance == pytest.approx(21.0 + now["loss_w"] / emitter["k_w_per_k"], abs=0.1)
    assert emitter["balance_in_range"] is True
    delivered = body["heat_pump"]["delivered"]
    assert delivered["now_w"] == 2500
    assert delivered["now_reason"] is None
    assert len(body["by_weather"]) >= 5


def test_hot_water_now_has_no_heat_value(tmp_path: Path) -> None:
    """During a hot-water run the loop heat now is unknown, with the reason."""
    body = basics.basics_payload(
        tmp_path / "missing.db",
        now=datetime(2026, 1, 5, tzinfo=UTC),
        timezone=ZONE,
        room_signal=ROOM,
        live=live(heat_now_w=None, hot_water=True),
        cache=BasicsCache(),
    )
    assert body["heat_pump"]["delivered"] == {
        "now_w": None,
        "now_reason": "hot_water",
        "mean_24h_w": None,
        "coverage_24h": 0.0,
    }
    assert body["heat_loss"]["status"] == "collecting"
    assert body["loss_now"]["now"] is None
    assert body["heat_pump"]["emitter"]["table"] == []


@pytest.fixture
def basics_settings(make_settings: Callable[..., Settings]) -> Callable[..., Settings]:
    """Return a factory of settings with the room signal and the time zone."""

    def factory(**overrides: Any) -> Settings:
        """Return the settings with ``overrides``."""
        return make_settings(
            control_timezone=ZONE,
            control_room_signal=ROOM,
            mqtt_inputs=[{"topic": "sim/room", "signal": ROOM, "unit": "°C"}],
            **overrides,
        )

    return factory


@pytest.fixture
def client(basics_settings: Callable[..., Settings], default_db: Path) -> Iterator[TestClient]:
    """Return a client of a service with a synthetic house in its history."""
    settings = basics_settings()
    settings.history_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(default_db, settings.history_path)
    clock = FakeClock(end_of(House()).timestamp())
    with TestClient(create_app(Runtime(clock=clock), settings)) as test_client:
        yield test_client


def test_the_endpoint_answers_the_basics(client: TestClient) -> None:
    """``GET insight/basics`` returns every part."""
    response = client.get("/api/v1/insight/basics")
    assert response.status_code == 200
    body = response.json()
    assert list(body) == [
        "enabled",
        "computed_at",
        "timezone",
        "room_signal",
        "design_outside_c",
        "heat_loss",
        "loss_now",
        "heat_pump",
        "by_weather",
    ]
    assert body["heat_loss"]["status"] == "credible"
    assert body["loss_now"]["room_source"] == "comfort"
    assert body["loss_now"]["outside_source"] is None
    assert body["loss_now"]["now"] is None
    assert body["loss_now"]["design"] is not None
    assert body["heat_pump"]["delivered"]["now_reason"] == "unknown"
    assert body["computed_at"] == client.get("/api/v1/insight/basics").json()["computed_at"]


def test_the_endpoint_answers_the_disabled_shape(
    basics_settings: Callable[..., Settings], tmp_path: Path
) -> None:
    """With the switch off every part is ``null``."""
    settings = basics_settings(house_basics_enabled=False)
    with TestClient(create_app(Runtime(clock=FakeClock()), settings)) as test_client:
        body = test_client.get("/api/v1/insight/basics").json()
    assert body == {
        "enabled": False,
        "computed_at": None,
        "timezone": ZONE,
        "room_signal": ROOM,
        "design_outside_c": basics.DESIGN_OUTSIDE_C,
        "heat_loss": None,
        "loss_now": None,
        "heat_pump": None,
        "by_weather": None,
    }
