from __future__ import annotations

import asyncio
import functools
from pathlib import Path

import pytest

from ovenbird.backoff import Backoff
from ovenbird.history import HistoryWriter, Retention, Sample, SampleKind
from ovenbird.runtime import CRASH_LIMIT, Runtime
from ovenbird.service import Component, HistoryWriterStoppedError, supervise, watch_history


async def test_supervisor_restarts_with_backoff_and_reports_not_live() -> None:
    runtime = Runtime()
    calls: list[int] = []
    done = asyncio.Event()

    async def flaky() -> None:
        calls.append(len(calls))
        if len(calls) > CRASH_LIMIT:
            done.set()
            await asyncio.Event().wait()
        raise RuntimeError("boom")

    task = asyncio.create_task(
        supervise(Component("flaky", flaky), runtime, Backoff(initial=0.001, cap=0.002))
    )
    await asyncio.wait_for(done.wait(), 2)
    assert len(calls) == CRASH_LIMIT + 1
    assert runtime.crashes["flaky"] == CRASH_LIMIT
    assert runtime.live is False
    assert runtime.health()["live"] is False
    assert runtime.health()["ready"] is False
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


async def test_supervisor_restarts_a_component_that_returns() -> None:
    runtime = Runtime()
    runs = 0
    again = asyncio.Event()

    async def returns() -> None:
        nonlocal runs
        runs += 1
        if runs == 2:
            again.set()

    task = asyncio.create_task(
        supervise(Component("returns", returns), runtime, Backoff(initial=0.001, cap=0.002))
    )
    await asyncio.wait_for(again.wait(), 2)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert runtime.live is True


def test_stable_run_resets_crash_count() -> None:
    runtime = Runtime()
    for _ in range(CRASH_LIMIT):
        runtime.record_crash("x")
    assert not runtime.live
    runtime.record_recovery("x")
    assert runtime.live


async def test_watch_history_starts_writer_and_fails_when_it_dies(tmp_path: Path) -> None:
    writer = HistoryWriter(tmp_path / "history.db", Retention(), flush_interval=0.01)
    watcher = asyncio.create_task(watch_history(writer, interval=0.01))
    for _ in range(200):
        if writer.healthy():
            break
        await asyncio.sleep(0.01)
    assert writer.healthy()
    await asyncio.to_thread(writer.stop)
    with pytest.raises(HistoryWriterStoppedError):
        await asyncio.wait_for(watcher, 2)


async def test_supervisor_restarts_a_dead_history_writer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    writer = HistoryWriter(tmp_path / "history.db", Retention(), flush_interval=0.01)
    runtime = Runtime(history=writer)
    original = writer.run_once
    crashes = {"left": 1}

    def crash_once(batch: list[Sample]) -> None:
        if crashes["left"] and batch:
            crashes["left"] -= 1
            raise RuntimeError("disk on fire")
        original(batch)

    monkeypatch.setattr(writer, "run_once", crash_once)
    component = Component("history", functools.partial(watch_history, writer, 0.01))
    task = asyncio.create_task(supervise(component, runtime, Backoff(initial=0.01, cap=0.02)))
    for _ in range(200):
        if writer.healthy():
            break
        await asyncio.sleep(0.01)
    first_thread = writer._thread
    writer.offer(Sample("main/Outside_Temp", "°C", SampleKind.NUMBER, 1.8e9, 3.0, 330.0))
    for _ in range(300):
        if (
            runtime.crashes.get("history")
            and writer.healthy()
            and writer._thread is not first_thread
        ):
            break
        await asyncio.sleep(0.01)
    assert runtime.crashes["history"] == 1
    assert writer.healthy()
    assert writer._thread is not first_thread
    assert runtime.health()["checks"]["history"] == "ok"
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    await asyncio.to_thread(writer.stop)
