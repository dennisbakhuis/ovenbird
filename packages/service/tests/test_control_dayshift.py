"""The sun day shift rule: boost, set-back, recovery, cancels, steps and the schedule."""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, date, datetime, time, timedelta
from typing import Any

import pytest

from ovenbird.control.dayshift import (
    DEFAULT_MIN_BOOST_S,
    DEFAULT_SETBACK_WARM_K,
    STEP_K,
    DayShiftInputs,
    DayShiftMemory,
    DayShiftParams,
    DayShiftResult,
    Phase,
    Reason,
    Schedule,
    decide,
    window_problem,
)
from ovenbird.control.forecastread import Guard
from ovenbird_core.control.forecast import HOUR_S, ForecastHour

DAY = date(2026, 3, 10)
RULE = DayShiftParams()
PARAMS = replace(RULE, setback_warm_k=None)
COMFORT = 21.0
QUARTER = timedelta(minutes=15)


def at(hour: int, minute: int = 0, day: date = DAY) -> datetime:
    """Return a UTC instant on ``day``."""
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=UTC)


def sun_curve(peak: float) -> Callable[[float], float]:
    """Return an irradiance profile over the hour of the day (0 outside 07-17 h)."""

    def sun(hour: float) -> float:
        """Return the irradiance at an hour of the day: a half sine between 07 and 17 h."""
        if not 7.0 < hour < 17.0:
            return 0.0
        return peak * math.sin(math.pi * (hour - 7.0) / 10.0)

    return sun


def forecast(
    *, day_c: float = 8.0, night_c: float = 6.0, peak: float = 500.0, start: date = DAY
) -> tuple[ForecastHour, ...]:
    """Return 72 forecast hours from the day before ``start``: mild days, cool nights."""
    sun = sun_curve(peak)
    first = at(0, day=start - timedelta(days=1)).timestamp()
    hours = []
    for index in range(72):
        ts = first + index * HOUR_S
        hour = (ts % 86_400.0) / HOUR_S
        temp = day_c if 7.0 <= hour < 20.0 else night_c
        hours.append(ForecastHour(ts, temp, max(0.0, sun(hour - 0.5))))
    return tuple(hours)


def inputs(
    now: datetime,
    hours: tuple[ForecastHour, ...],
    *,
    outside: float | None = 8.0,
    room: float | None = COMFORT,
    guards: tuple[str, ...] = (),
) -> DayShiftInputs:
    """Return the rule's inputs at ``now``."""
    return DayShiftInputs(now, outside, hours, room, COMFORT, guards)


def run(
    start: datetime,
    end: datetime,
    hours: tuple[ForecastHour, ...],
    *,
    params: DayShiftParams = PARAMS,
    memory: DayShiftMemory | None = None,
    **kwargs: Any,
) -> list[DayShiftResult]:
    """Evaluate every quarter hour in ``[start, end)``, carrying the memory along."""
    state = memory or DayShiftMemory()
    results = []
    moment = start
    while moment < end:
        result = decide(params, inputs(moment, hours, **kwargs), state)
        results.append(result)
        state = result.memory
        moment += QUARTER
    return results


def boosted_memory(day: date = DAY, sunny_s: float = DEFAULT_MIN_BOOST_S) -> DayShiftMemory:
    """Return the memory a day boosted for ``sunny_s`` at the full boost leaves at its evening."""
    return DayShiftMemory(boost_day=day, sunny_day=day, sunny_s=sunny_s)


def offsets(results: list[DayShiftResult]) -> list[float]:
    """Return the offsets of a run."""
    return [result.offset_k for result in results]


class TestBoost:
    """Boost rules: sun, outside temperature, steps and the end of the day window."""

    def test_a_sunny_mild_day_boosts_in_quarter_steps(self) -> None:
        """A sunny, mild day boosts in quarter-kelvin steps up to the full boost."""
        results = run(at(9), at(10), forecast())
        assert offsets(results) == [0.25, 0.5, 0.5, 0.5]
        assert {result.phase for result in results} == {Phase.BOOST}
        assert results[0].reasons == (Reason.SUN_FORECAST, Reason.OUTSIDE_MILD)
        assert results[0].desired_k == 0.5
        assert results[-1].memory.boost_day == DAY

    def test_a_cloudy_day_does_not_boost(self) -> None:
        """A cloudy day stays idle because the forecast sun is too low."""
        results = run(at(9), at(17), forecast(peak=80.0))
        assert set(offsets(results)) == {0.0}
        assert {result.phase for result in results} == {Phase.IDLE}
        assert Reason.SUN_LOW in results[0].reasons
        assert results[-1].memory.boost_day is None

    @pytest.mark.parametrize(("outside", "day_c"), [(3.0, 8.0), (8.0, 3.0), (3.0, 3.0)])
    def test_a_cold_day_does_not_boost(self, outside: float, day_c: float) -> None:
        """A cold outside temperature, now or forecast, prevents the boost."""
        results = run(at(9), at(12), forecast(day_c=day_c), outside=outside)
        assert set(offsets(results)) == {0.0}
        assert Reason.OUTSIDE_COLD in results[0].reasons

    def test_without_an_outside_temperature_there_is_no_boost(self) -> None:
        """An unknown outside temperature prevents the boost."""
        result = decide(PARAMS, inputs(at(10), forecast(), outside=None), DayShiftMemory())
        assert result.offset_k == 0.0
        assert result.reasons == (Reason.OUTSIDE_UNKNOWN,)

    def test_without_forecast_hours_there_is_no_boost(self) -> None:
        """A missing forecast prevents the boost."""
        result = decide(PARAMS, inputs(at(10), ()), DayShiftMemory())
        assert result.offset_k == 0.0
        assert Reason.FORECAST_MISSING in result.reasons

    def test_one_kelvin_hysteresis_on_the_outside_limit(self) -> None:
        """The outside limit has a one kelvin hysteresis once a boost runs."""
        hours = forecast(day_c=8.0)
        start = run(at(9), at(10), hours, outside=5.5)
        assert start[-1].offset_k == 0.5
        kept = run(at(10), at(11), hours, outside=4.2, memory=start[-1].memory)
        assert set(offsets(kept)) == {0.5}
        assert kept[0].forecast.outside_limit_c == 4.0
        ended = decide(PARAMS, inputs(at(11), hours, outside=3.9), kept[-1].memory)
        assert ended.desired_k == 0.0
        assert Reason.OUTSIDE_COLD in ended.reasons
        fresh = run(at(9), at(10), hours, outside=4.5)
        assert set(offsets(fresh)) == {0.0}

    def test_a_running_boost_keeps_the_fading_afternoon_sun(self) -> None:
        """A running boost tolerates the fading afternoon sun, which would not start one."""
        hours = forecast(peak=320.0)
        afternoon = decide(PARAMS, inputs(at(14), hours), DayShiftMemory())
        assert afternoon.reasons == (Reason.SUN_LOW,)
        day = run(at(9), at(17), hours)
        assert day[0].offset_k == 0.25
        assert all(result.phase is Phase.BOOST for result in day[:21])
        assert day[20].forecast.sun_limit_wm2 == PARAMS.min_sun_wm2 / 2

    def test_the_boost_ramps_back_after_the_day_window(self) -> None:
        """The boost ramps back to zero in quarter steps after the day window."""
        day = run(at(9), at(17), forecast())
        evening = run(at(17), at(18), forecast(), memory=day[-1].memory)
        assert offsets(evening) == [0.25, 0.0, 0.0, 0.0]
        assert [result.phase for result in evening[:2]] == [Phase.BOOST, Phase.IDLE]

    def test_steps_are_at_most_a_quarter_kelvin_and_within_the_bound(self) -> None:
        """Steps are at most a quarter kelvin and stay within the configured maximum."""
        big = replace(PARAMS, boost_k=1.0)
        assert offsets(run(at(9), at(10), forecast(), params=big)) == [0.25, 0.5, 0.75, 1.0]
        bounded = replace(big, max_k=0.6)
        results = run(at(9), at(10), forecast(), params=bounded)
        assert offsets(results) == [0.25, 0.5, 0.6, 0.6]
        assert results[-1].desired_k == 0.6
        steps = [b - a for a, b in zip(offsets(results), offsets(results)[1:], strict=False)]
        assert all(abs(step) <= STEP_K for step in steps)


class TestSetback:
    """Night set-back rules and the recovery before the comfort time."""

    def test_the_night_after_a_boost_sets_back_and_recovers_before_comfort(self) -> None:
        """The night after a boost sets back and recovers before the comfort time."""
        hours = forecast()
        evening = run(at(22, 45), at(23, 30), hours, memory=boosted_memory())
        assert offsets(evening) == [0.0, -0.25, -0.5]
        assert evening[1].phase is Phase.SETBACK
        assert evening[1].reasons == (Reason.NIGHT_AFTER_BOOST,)
        night = run(
            at(2, 0, DAY + timedelta(days=1)),
            at(7, 15, DAY + timedelta(days=1)),
            hours,
            memory=evening[-1].memory,
        )
        by_time = {result.at.time(): result for result in night}
        assert by_time[time(2, 15)].offset_k == -0.5
        assert by_time[time(2, 30)].offset_k == -0.25
        assert by_time[time(2, 30)].phase is Phase.RECOVERY
        assert by_time[time(2, 45)].offset_k == 0.0
        assert by_time[time(5, 0)].phase is Phase.RECOVERY
        assert by_time[time(5, 0)].reasons == (Reason.RECOVERY_LEAD,)
        assert by_time[time(7, 0)].phase is Phase.IDLE

    def test_a_single_boosted_quarter_hour_does_not_allow_a_setback(self) -> None:
        """A short morning boost followed by clouds leaves the night alone."""
        hours = forecast()
        cloudy = forecast(peak=60.0)
        morning = run(at(9), at(9, 45), hours)
        assert offsets(morning) == [0.25, 0.5, 0.5]
        assert morning[-1].memory.sunny_s == 900.0
        rest = run(at(9, 45), at(23, 30), cloudy, memory=morning[-1].memory)
        night = [result for result in rest if result.at.time() >= time(23)]
        assert set(offsets(night)) == {0.0}
        assert night[0].reasons == (Reason.NO_BOOST_TODAY,)
        assert rest[-1].memory.boost_day == DAY

    def test_two_hours_at_the_full_boost_allow_the_setback(self) -> None:
        """The night sets back once the day held the full boost for two hours."""
        hours = forecast()
        cloudy = forecast(peak=60.0)
        short = run(at(9), at(11), hours)
        assert short[-1].memory.sunny_s == 5400.0
        evening = run(at(11), at(23, 30), cloudy, memory=short[-1].memory)
        assert evening[-1].memory.sunny_s == 6300.0
        assert set(offsets(evening[-2:])) == {0.0}
        full = run(at(9), at(11, 15), hours)
        assert full[-1].memory.sunny_s == 6300.0
        later = run(at(11, 15), at(23, 30), cloudy, memory=full[-1].memory)
        assert later[-1].memory.sunny_s == DEFAULT_MIN_BOOST_S
        assert offsets(later[-2:]) == [-0.25, -0.5]

    def test_the_ramp_and_a_missed_evaluation_do_not_count(self) -> None:
        """The first quarter on the ramp and a gap beyond one slot add nothing."""
        hours = forecast()
        first = run(at(9), at(9, 30), hours)
        assert [result.memory.sunny_s for result in first] == [0.0, 0.0]
        assert first[-1].memory.sunny_at is not None
        late = decide(PARAMS, inputs(at(11), hours), first[-1].memory)
        assert late.memory.sunny_s == 900.0

    def test_a_setback_only_setting_needs_the_sunny_conditions(self) -> None:
        """With the boost at 0 the sunny conditions alone qualify the night."""
        params = replace(PARAMS, boost_k=0.0)
        hours = forecast()
        day = run(at(9), at(17), hours, params=params)
        assert set(offsets(day)) == {0.0}
        assert day[-1].memory.sunny_s == 8 * 3600.0 - 900.0
        night = run(at(17), at(23, 30), hours, params=params, memory=day[-1].memory)
        assert offsets(night[-2:]) == [-0.25, -0.5]
        dull = run(at(9), at(23, 30), forecast(peak=60.0), params=params)
        assert set(offsets(dull)) == {0.0}

    def test_the_sunny_time_of_yesterday_holds_until_the_next_day_window(self) -> None:
        """After midnight the night still reads yesterday; the next window starts at 0."""
        hours = forecast()
        tomorrow = DAY + timedelta(days=1)
        night = run(at(23), at(9, 0, tomorrow), hours, memory=boosted_memory())
        assert offsets(night)[:2] == [-0.25, -0.5]
        assert night[-1].memory.sunny_day == DAY
        start = decide(PARAMS, inputs(at(9, day=tomorrow), forecast(peak=60.0)), night[-1].memory)
        assert start.memory.sunny_day == tomorrow
        assert start.memory.sunny_s == 0.0

    def test_the_night_after_a_day_without_boost_has_no_setback(self) -> None:
        """The night after a day without a boost has no set-back."""
        results = run(at(23), at(23, 45), forecast())
        assert set(offsets(results)) == {0.0}
        assert results[0].reasons == (Reason.NO_BOOST_TODAY,)
        assert results[0].phase is Phase.IDLE

    def test_a_boost_yesterday_does_not_set_back_tonight(self) -> None:
        """A boost from yesterday does not allow a set-back tonight."""
        tomorrow = DAY + timedelta(days=1)
        results = run(
            at(23, day=tomorrow), at(23, 30, day=tomorrow), forecast(), memory=boosted_memory()
        )
        assert set(offsets(results)) == {0.0}
        assert results[0].reasons == (Reason.NO_BOOST_TODAY,)

    def test_a_cold_night_has_no_setback(self) -> None:
        """A cold forecast night has no set-back."""
        results = run(at(23), at(23, 45), forecast(night_c=2.0), memory=boosted_memory())
        assert set(offsets(results)) == {0.0}
        assert results[0].reasons == (Reason.NIGHT_COLD,)
        assert results[0].forecast.night_min_c == 2.0

    def test_the_night_limit_relaxes_once_set_back(self) -> None:
        """The night temperature limit is relaxed once the set-back has started."""
        mild = run(at(23), at(23, 30), forecast(night_c=6.0), memory=boosted_memory())
        cooler = decide(PARAMS, inputs(at(23, 30), forecast(night_c=4.5)), mild[-1].memory)
        assert cooler.desired_k == -0.5
        assert cooler.forecast.night_limit_c == 4.0
        fresh = decide(PARAMS, inputs(at(23), forecast(night_c=4.5)), boosted_memory())
        assert fresh.reasons == (Reason.NIGHT_COLD,)

    @pytest.mark.parametrize(
        ("recovery_h", "night_end", "setback_end", "release"),
        [
            (4.0, time(5), time(3), time(2, 30)),
            (5.0, time(5), time(2), time(1, 30)),
            (3.0, time(1), time(1), time(0, 30)),
        ],
    )
    def test_the_recovery_lead_ends_the_setback(
        self, recovery_h: float, night_end: time, setback_end: time, release: time
    ) -> None:
        """The recovery lead moves the set-back end and the release ahead of the night end."""
        params = replace(PARAMS, recovery_s=recovery_h * HOUR_S, night_end=night_end)
        night = Schedule(params).night(DAY)
        assert night.setback_end.time() == setback_end
        assert night.release.time() == release
        results = run(
            at(23),
            at(7, 0, DAY + timedelta(days=1)),
            forecast(),
            params=params,
            memory=boosted_memory(),
        )
        lowered = [result.at.time() for result in results if result.offset_k < 0.0]
        assert lowered[0] == time(23)
        last = (datetime.combine(DAY, setback_end) - QUARTER - QUARTER).time()
        assert lowered[-1] == last
        assert all(result.offset_k == 0.0 for result in results if result.at.time() == setback_end)

    def test_a_lead_longer_than_the_night_leaves_no_setback(self) -> None:
        """A recovery lead longer than the night leaves no set-back possible."""
        params = replace(PARAMS, recovery_s=8 * HOUR_S)
        assert not Schedule(params).night(DAY).possible
        results = run(at(23), at(23, 45), forecast(), params=params, memory=boosted_memory())
        assert set(offsets(results)) == {0.0}
        assert results[0].reasons == (Reason.RECOVERY_LEAD,)
        assert results[0].setback_end is None


class TestEvaluationFixes:
    """Rule refinements: confirmed sun, warm stop and the warm-room set-back."""

    def test_the_defaults_carry_the_fixes(self) -> None:
        """The confirmed sun, the warm stop and the warm-room set-back are on by default."""
        assert RULE.confirm_sun
        assert RULE.warm_stop_k == 0.0
        assert RULE.setback_warm_k == DEFAULT_SETBACK_WARM_K == 0.5

    def test_a_set_back_starts_only_in_a_room_the_sun_left_warm(self) -> None:
        """At comfort the night stays; 0.5 K above it the set-back starts and holds."""
        hours = forecast()
        cool = run(at(23), at(23, 30), hours, params=RULE, memory=boosted_memory())
        assert set(offsets(cool)) == {0.0}
        assert cool[0].reasons == (Reason.ROOM_BELOW_TARGET,)
        assert cool[0].phase is Phase.IDLE
        warm = run(at(23), at(23, 30), hours, params=RULE, memory=boosted_memory(), room=21.5)
        assert offsets(warm) == [-0.25, -0.5]
        cooling = run(
            at(23, 30),
            at(1, 0, DAY + timedelta(days=1)),
            hours,
            params=RULE,
            memory=warm[-1].memory,
            room=20.9,
        )
        assert set(offsets(cooling)) == {-0.5}

    def test_the_boost_ends_for_the_day_once_the_room_reaches_its_target(self) -> None:
        """A room at the boosted target ends the boost from the next quarter hour, for the day."""
        hours = forecast()
        morning = run(at(9), at(10), hours, params=RULE)
        assert offsets(morning) == [0.25, 0.5, 0.5, 0.5]
        warm = run(at(10), at(11), hours, params=RULE, memory=morning[-1].memory, room=21.5)
        assert offsets(warm) == [0.5, 0.25, 0.0, 0.0]
        assert warm[1].reasons == (Reason.ROOM_WARM,)
        later = run(at(11), at(17), hours, params=RULE, memory=warm[-1].memory)
        assert set(offsets(later)) == {0.0}
        assert later[-1].memory.sunny_s >= DEFAULT_MIN_BOOST_S
        tomorrow = run(
            at(9, day=DAY + timedelta(days=1)),
            at(9, 30, day=DAY + timedelta(days=1)),
            hours,
            params=RULE,
            memory=later[-1].memory,
        )
        assert offsets(tomorrow) == [0.25, 0.5]

    def test_a_forecast_of_later_sun_does_not_boost_a_dark_morning(self) -> None:
        """The sun must be there now: a bright afternoon forecast leaves the morning alone."""
        dark_morning = tuple(
            ForecastHour(
                h.target_ts, h.outside_c, h.ghi_w_m2 if at(13).timestamp() <= h.target_ts else 0.0
            )
            for h in forecast(peak=900.0)
        )
        found = decide(RULE, inputs(at(9), dark_morning), DayShiftMemory())
        assert found.offset_k == 0.0
        assert found.reasons == (Reason.SUN_LOW,)
        unconfirmed = replace(RULE, confirm_sun=False)
        assert decide(unconfirmed, inputs(at(9), dark_morning), DayShiftMemory()).offset_k == 0.25


class TestCancel:
    """Conditions that cancel a boost or a night set-back."""

    def test_a_room_too_far_below_the_lowered_target_ends_the_night(self) -> None:
        """A room too far below the lowered target ends the night set-back until recovery."""
        hours = forecast()
        evening = run(at(23), at(23, 30), hours, memory=boosted_memory(), room=20.8)
        assert evening[-1].offset_k == -0.5
        cold = decide(PARAMS, inputs(at(23, 30), hours, room=20.15), evening[-1].memory)
        assert cold.offset_k == 0.0
        assert cold.phase is Phase.BLOCKED
        assert cold.reasons == (Reason.ROOM_BELOW_TARGET,)
        later = run(at(23, 45), at(2, 0, DAY + timedelta(days=1)), hours, memory=cold.memory)
        assert set(offsets(later)) == {0.0}
        assert {result.phase for result in later} == {Phase.BLOCKED}
        morning = decide(
            PARAMS, inputs(at(4, day=DAY + timedelta(days=1)), hours), later[-1].memory
        )
        assert morning.phase is Phase.RECOVERY

    def test_a_room_within_the_margin_keeps_the_setback(self) -> None:
        """A room within the margin of the lowered target keeps the set-back."""
        results = run(at(23), at(23, 45), forecast(), memory=boosted_memory(), room=20.5)
        assert offsets(results)[-1] == -0.5
        assert results[-1].phase is Phase.SETBACK

    @pytest.mark.parametrize("guard", [guard.value for guard in Guard])
    def test_every_guard_cancels_a_boost_at_once(self, guard: str) -> None:
        """Every guard cancels a running boost at once and allows it again afterwards."""
        hours = forecast()
        day = run(at(9), at(10), hours)
        assert day[-1].offset_k == 0.5
        blocked = decide(PARAMS, inputs(at(10), hours, guards=(guard,)), day[-1].memory)
        assert blocked.offset_k == 0.0
        assert blocked.phase is Phase.BLOCKED
        assert blocked.reasons == (guard,)
        assert blocked.guards == (guard,)
        assert blocked.next_change is None
        again = decide(PARAMS, inputs(at(10, 15), hours), blocked.memory)
        assert again.offset_k == 0.25

    @pytest.mark.parametrize("guard", [guard.value for guard in Guard])
    def test_every_guard_cancels_a_setback_at_once(self, guard: str) -> None:
        """Every guard cancels a running set-back at once."""
        hours = forecast()
        evening = run(at(23), at(23, 30), hours, memory=boosted_memory())
        blocked = decide(PARAMS, inputs(at(23, 30), hours, guards=(guard,)), evening[-1].memory)
        assert blocked.offset_k == 0.0
        assert blocked.phase is Phase.BLOCKED


class TestSchedule:
    """The schedule: next change, local time zones, window ordering."""

    def test_next_change_follows_the_schedule(self) -> None:
        """The next change reported follows the boost, idle, set-back and recovery schedule."""
        hours = forecast()
        day = run(at(9), at(17), hours)
        boost = day[1]
        assert boost.next_change is not None
        assert (boost.next_change.at, boost.next_change.phase) == (at(17), Phase.IDLE)
        idle = decide(PARAMS, inputs(at(18), hours), day[-1].memory)
        assert idle.next_change is not None
        assert (idle.next_change.at, idle.next_change.phase) == (at(23), Phase.SETBACK)
        setback = run(at(23), at(23, 30), hours, memory=idle.memory)[-1]
        assert setback.next_change is not None
        assert setback.next_change.at == at(2, 30, DAY + timedelta(days=1))
        assert setback.next_change.phase is Phase.RECOVERY
        plain = decide(PARAMS, inputs(at(18), hours), DayShiftMemory())
        assert plain.next_change is not None
        assert plain.next_change.at == at(9, day=DAY + timedelta(days=1))

    def test_local_time_follows_the_zone(self) -> None:
        """The windows are evaluated in the configured local time zone."""
        params = replace(PARAMS, timezone="Europe/Amsterdam")
        hours = forecast()
        before = decide(params, inputs(at(7, 45), hours), DayShiftMemory())
        assert before.phase is Phase.IDLE
        assert before.reasons == (Reason.OUTSIDE_WINDOWS,)
        start = decide(params, inputs(at(8), hours), DayShiftMemory())
        assert start.offset_k == 0.25
        assert start.at.utcoffset() == timedelta(hours=1)

    @pytest.mark.parametrize(
        ("zone", "night_utc", "release_utc"),
        [
            ("Europe/Amsterdam", time(22), time(1, 30)),
            ("America/New_York", time(3), time(6, 30)),
            ("UTC", time(23), time(2, 30)),
        ],
    )
    def test_the_night_windows_are_local(
        self, zone: str, night_utc: time, release_utc: time
    ) -> None:
        """The night window is 23:00 on the local clock of the configured zone."""
        params = replace(PARAMS, timezone=zone)
        night = Schedule(params).night(DAY)
        assert night.start.astimezone(UTC).time() == night_utc
        assert night.release.astimezone(UTC).time() == release_utc
        local = night.start.astimezone(params.zone)
        assert (local.hour, local.minute) == (23, 0)

    def test_the_summer_time_night_keeps_its_local_hours(self) -> None:
        """On the night the clocks go back the windows stay on the local clock."""
        params = replace(PARAMS, timezone="Europe/Amsterdam")
        change = date(2026, 10, 24)
        night = Schedule(params).night(change)
        assert night.start.astimezone(UTC) == datetime(2026, 10, 24, 21, 0, tzinfo=UTC)
        assert night.comfort.astimezone(UTC) == datetime(2026, 10, 25, 6, 0, tzinfo=UTC)
        assert night.setback_end.astimezone(UTC) == datetime(2026, 10, 25, 2, 0, tzinfo=UTC)

    def test_outside_the_windows_nothing_happens(self) -> None:
        """Outside the day and night windows nothing happens."""
        result = decide(PARAMS, inputs(at(19), forecast()), DayShiftMemory())
        assert result.reasons == (Reason.OUTSIDE_WINDOWS,)
        assert result.phase is Phase.IDLE

    @pytest.mark.parametrize(
        ("changes", "part"),
        [
            ({}, None),
            ({"day_start": time(17), "day_end": time(9)}, "day"),
            ({"day_start": time(9), "day_end": time(9)}, "day"),
            ({"night_start": time(12)}, "night"),
            ({"night_start": time(23), "night_end": time(23)}, "night"),
            ({"night_end": time(10)}, "night"),
            ({"comfort_at": time(22)}, "comfort"),
            ({"comfort_at": time(12)}, "comfort"),
            ({"night_start": time(17), "night_end": time(9), "comfort_at": time(9)}, None),
            ({"night_start": time(0, 30), "night_end": time(5)}, None),
        ],
    )
    def test_window_order(self, changes: dict[str, Any], part: str | None) -> None:
        """Window settings that are out of order are reported with the part they concern."""
        problem = window_problem(replace(PARAMS, **changes))
        assert (None if problem is None else problem[0]) == part


class TestMemory:
    """The stored form of the rule's memory."""

    def test_the_memory_survives_its_stored_form(self) -> None:
        """The memory survives a round trip through its stored form."""
        memory = DayShiftMemory(-0.25, Phase.SETBACK, False, True, DAY, DAY, None)
        assert DayShiftMemory.from_json(memory.to_json()) == memory
        sunny = DayShiftMemory(0.5, Phase.BOOST, True, False, DAY, None, None, DAY, 2700.0, 1e9)
        assert DayShiftMemory.from_json(sunny.to_json()) == sunny

    def test_a_version_one_form_reads_without_sunny_time(self) -> None:
        """A memory saved before the sunny time reads back without a qualified day."""
        body = DayShiftMemory(0.5, Phase.BOOST, True, False, DAY, None, None).to_json()
        body = {key: value for key, value in body.items() if not key.startswith("sunny")}
        memory = DayShiftMemory.from_json({**body, "v": 1})
        assert memory.boost_day == DAY
        assert memory.sunny_s == 0.0
        assert not memory.sunny(DAY, PARAMS)

    @pytest.mark.parametrize(
        "body",
        [
            {"v": 99},
            {"v": 1, "offset_k": "nan", "phase": "idle", "boosting": False, "setting_back": False},
        ],
    )
    def test_a_foreign_stored_form_is_refused(self, body: dict[str, Any]) -> None:
        """A stored form with an unknown version or invalid values is refused."""
        with pytest.raises(ValueError, match="day shift"):
            DayShiftMemory.from_json(body)
