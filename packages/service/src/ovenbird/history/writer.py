"""Single history writer thread fed by a bounded, drop-oldest queue.

The event loop only ever calls :meth:`HistoryWriter.offer`, which never blocks
beyond a short lock. The thread drains the queue in batches, commits each batch in
one transaction (decision and command log rows in a second one), applies retention
periodically, writes a consistent snapshot for
backups periodically and pauses writing while the data directory is low on space.
When ``history.db`` is missing but a snapshot exists (a restored backup), the
database is recreated from the snapshot before it is opened.

Retention can change while the writer runs (:meth:`HistoryWriter.set_retention`);
the new limits are applied at the next batch. Space freed by retention is handed
back to the file system with an incremental vacuum. A database not yet in
incremental auto-vacuum mode is converted by a full ``VACUUM`` (compaction), which
the writer runs itself between batches, so writes and snapshots never overlap it:
on request (:meth:`HistoryWriter.request_compaction`) and once at start when a
quarter or more of the file is free pages (after the decision journal was packed).

With a :class:`~ovenbird.history.archive.MonthArchiver` the writer also builds the
monthly archive between batches (every quarter of an hour, and right before retention),
and holds retention back while the archive is catching up, freezing a month or failing
(:meth:`~ovenbird.history.archive.MonthArchiver.holds_retention`), so retention never
removes data the archive has not copied yet; a failing archive holds it back for at most
:data:`~ovenbird.history.archive.MAX_WAIT_S`.
"""

from __future__ import annotations

import logging
import shutil
import threading
import time
from collections import deque
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from ovenbird.history.archive import INTERVAL_S as ARCHIVE_INTERVAL_S
from ovenbird.history.archive import MonthArchiver
from ovenbird.history.database import (
    INCREMENTAL_VACUUM,
    SECONDS_PER_DAY,
    HistoryDatabase,
    Retention,
    Sample,
)
from ovenbird.history.forecast import ForecastRow, delete_forecast_before, write_forecast
from ovenbird.history.journal import (
    AlarmRow,
    CommandRow,
    DecisionRow,
    StateRow,
    delete_journal_before,
    write_journal,
)
from ovenbird.history.packing import DecisionPacker
from ovenbird.history.schema import open_history
from ovenbird.history.snapshot import discard_temp, restore_snapshot

LOGGER = logging.getLogger("ovenbird.history")
FLUSH_INTERVAL_S: Final = 1.0
BATCH_MAX: Final = 5000
RETENTION_INTERVAL_S: Final = 3600.0
DISK_CHECK_INTERVAL_S: Final = 30.0
REOPEN_INTERVAL_S: Final = 60.0
SNAPSHOT_INTERVAL_S: Final = 6 * 3600.0
RESUME_FACTOR: Final = 1.1

COMPACT_FREE_SHARE: Final = 0.25
COMPACT_MIN_FREE_BYTES: Final = 1024 * 1024

type Item = Sample | DecisionRow | CommandRow | AlarmRow | StateRow | ForecastRow


class DropOldestQueue[T]:
    """Thread-safe bounded queue that discards the oldest item when full.

    Parameters
    ----------
    maxsize
        Capacity.
    """

    def __init__(self, maxsize: int) -> None:
        self._items: deque[T] = deque()
        self._maxsize = maxsize
        self._cond = threading.Condition()
        self._closed = False
        self.dropped = 0

    def put(self, item: T) -> None:
        """Append ``item``; drops (and counts) the oldest item when full."""
        with self._cond:
            if len(self._items) >= self._maxsize:
                self._items.popleft()
                self.dropped += 1
            self._items.append(item)
            self._cond.notify()

    def drain(self, timeout: float, limit: int) -> list[T]:
        """Wait up to ``timeout`` seconds for items and return at most ``limit`` of them."""
        with self._cond:
            if not self._items and not self._closed:
                self._cond.wait(timeout)
            count = min(limit, len(self._items))
            return [self._items.popleft() for _ in range(count)]

    def close(self) -> None:
        """Wake a waiting :meth:`drain` and stop waiting from now on."""
        with self._cond:
            self._closed = True
            self._cond.notify_all()

    @property
    def closed(self) -> bool:
        """Whether :meth:`close` was called."""
        with self._cond:
            return self._closed

    def __len__(self) -> int:
        """Return the number of queued items."""
        with self._cond:
            return len(self._items)


def disk_free_bytes(path: Path) -> int:
    """Free bytes on the file system holding ``path``."""
    return shutil.disk_usage(path).free


@dataclass
class HistoryStats:
    """Counters and state of the writer.

    Parameters
    ----------
    written
        Raw samples written.
    journal_written
        Decision and command log rows written.
    batches
        Batches committed.
    dropped_paused
        Samples discarded while writing was paused for disk space.
    dropped_failed
        Samples lost in batches that failed to commit.
    retention_deleted
        Rows deleted by retention.
    snapshots
        Backup snapshots written.
    snapshots_skipped
        Snapshots skipped for lack of free space.
    paused
        Writing is paused for disk space.
    error
        Last error, cleared by the next successful batch.
    open
        The database is open.
    """

    written: int = 0
    journal_written: int = 0
    batches: int = 0
    dropped_paused: int = 0
    dropped_failed: int = 0
    retention_deleted: int = 0
    snapshots: int = 0
    snapshots_skipped: int = 0
    paused: bool = False
    error: str | None = None
    open: bool = False


@dataclass
class CompactionState:
    """The last compaction of the database file (``VACUUM``).

    Parameters
    ----------
    pending
        A compaction is requested and not yet run.
    running
        The writer is compacting now.
    last_at
        Wall-clock unix seconds of the last finished compaction.
    freed_bytes
        File size it gave back (database and WAL).
    error
        Why the last request failed or was skipped, if it did.
    """

    pending: bool = False
    running: bool = False
    last_at: float | None = None
    freed_bytes: int | None = None
    error: str | None = None


class HistoryWriter:
    """Own ``history.db`` from one background thread.

    Parameters
    ----------
    path
        Database file.
    retention
        Retention limits.
    queue_size
        Queue capacity.
    min_free_bytes
        Writing pauses below this much free space and resumes 10 % above it.
    flush_interval, retention_interval, disk_check_interval, reopen_interval
        Timing in seconds.
    snapshot_path
        Where the backup snapshot is written; ``None`` disables snapshots.
    snapshot_interval
        Seconds between snapshots; the first one is due when the existing snapshot
        is older than this and the first batch of this run was committed. A snapshot
        is skipped unless free space exceeds ``min_free_bytes`` plus the database size.
    disk_free
        Free-space probe (injectable for tests).
    wall
        Wall-clock unix time source for retention.
    journal_days
        Retention of the decision and command logs; ``None`` keeps them.
    archiver
        Builds the monthly archive between batches; ``None`` keeps no archive.
    archive_interval
        Seconds between archive steps once it has caught up.
    """

    def __init__(
        self,
        path: Path,
        retention: Retention,
        *,
        queue_size: int = 20_000,
        min_free_bytes: int = 256 * 1024 * 1024,
        flush_interval: float = FLUSH_INTERVAL_S,
        retention_interval: float = RETENTION_INTERVAL_S,
        disk_check_interval: float = DISK_CHECK_INTERVAL_S,
        reopen_interval: float = REOPEN_INTERVAL_S,
        snapshot_path: Path | None = None,
        snapshot_interval: float = SNAPSHOT_INTERVAL_S,
        disk_free: Callable[[Path], int] = disk_free_bytes,
        wall: Callable[[], float] = time.time,
        journal_days: float | None = None,
        archiver: MonthArchiver | None = None,
        archive_interval: float = ARCHIVE_INTERVAL_S,
    ) -> None:
        self.path = path
        self.retention = retention
        self.min_free_bytes = min_free_bytes
        self.flush_interval = flush_interval
        self.retention_interval = retention_interval
        self.disk_check_interval = disk_check_interval
        self.reopen_interval = reopen_interval
        self.snapshot_path = snapshot_path
        self.snapshot_interval = snapshot_interval
        self._next_snapshot: float | None = None
        self._disk_free = disk_free
        self._wall = wall
        self.journal_days = journal_days
        self.archiver = archiver
        self.archive_interval = archive_interval
        self._next_archive = 0.0
        self._queue: DropOldestQueue[Item] = DropOldestQueue(queue_size)
        self._thread: threading.Thread | None = None
        self._db: HistoryDatabase | None = None
        self._next_retention = 0.0
        self._next_disk_check = 0.0
        self._next_open = 0.0
        self._retention_due = False
        self._packer = DecisionPacker()
        self.stats = HistoryStats()
        self.compaction = CompactionState()

    def set_retention(self, retention: Retention, journal_days: float | None) -> None:
        """Change the retention limits; the writer applies them before its next batch.

        Parameters
        ----------
        retention
            Limits per resolution.
        journal_days
            Retention of the decision, command and alarm journals; ``None`` keeps them.
        """
        changed = retention != self.retention or journal_days != self.journal_days
        self.retention = retention
        self.journal_days = journal_days
        if changed:
            self._retention_due = True
            LOGGER.info("history retention changed: %s, journal %s days", retention, journal_days)

    def request_compaction(self) -> bool:
        """Ask the writer to compact the database file at its next batch.

        Returns
        -------
        bool
            ``False`` when a compaction is already pending or running.
        """
        if self.compaction.pending or self.compaction.running:
            return False
        self.compaction.error = None
        self.compaction.pending = True
        return True

    @property
    def dropped_overflow(self) -> int:
        """Samples discarded because the queue was full."""
        return self._queue.dropped

    def backlog(self) -> int:
        """Items waiting to be written."""
        return len(self._queue)

    def offer(self, sample: Sample) -> None:
        """Queue a sample; never blocks the caller for long."""
        self._queue.put(sample)

    def offer_decision(self, row: DecisionRow) -> None:
        """Queue a decision log row."""
        self._queue.put(row)

    def offer_command(self, row: CommandRow) -> None:
        """Queue a command log row."""
        self._queue.put(row)

    def offer_alarm(self, row: AlarmRow) -> None:
        """Queue an alarm transition row."""
        self._queue.put(row)

    def offer_state(self, row: StateRow) -> None:
        """Queue a controller state row (replaces the stored one with the same key)."""
        self._queue.put(row)

    def offer_forecast(self, rows: Sequence[ForecastRow]) -> None:
        """Queue the rows of one forecast issue."""
        for row in rows:
            self._queue.put(row)

    def start(self) -> None:
        """Start the writer thread (again, if it died)."""
        if self._thread is not None and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._main, name="history-writer", daemon=True)
        self._thread.start()

    def is_alive(self) -> bool:
        """Whether the writer thread runs."""
        return self._thread is not None and self._thread.is_alive()

    def healthy(self) -> bool:
        """Whether history is being written (open, not paused, last batch succeeded)."""
        stats = self.stats
        return self.is_alive() and stats.open and not stats.paused and stats.error is None

    def starting(self) -> bool:
        """Whether the writer is still coming up: not yet open and no error so far."""
        stats = self.stats
        thread_ok = self._thread is None or self._thread.is_alive()
        return thread_ok and not stats.open and stats.error is None

    def stop(self, timeout: float = 10.0) -> None:
        """Flush the queue, close the database and join the thread."""
        self._queue.close()
        if self._thread is not None:
            self._thread.join(timeout)
            if self._thread.is_alive():
                LOGGER.error("history writer did not stop within %.0f s", timeout)

    def _main(self) -> None:
        try:
            while True:
                closing = self._queue.closed
                batch = self._queue.drain(self.flush_interval, BATCH_MAX)
                self.run_once(batch)
                if closing and not batch and not len(self._queue):
                    break
        except Exception:
            LOGGER.exception("history writer crashed")
            self.stats.error = "writer crashed"
        finally:
            self._close()

    def run_once(self, batch: Sequence[Item]) -> None:
        """Process one drained batch: open, guard disk space, write, apply retention.

        Parameters
        ----------
        batch
            Samples and log rows drained from the queue.
        """
        now = time.monotonic()
        if self._db is None and now >= self._next_open:
            self._open(now)
        if now >= self._next_disk_check:
            self._check_disk()
            self._next_disk_check = now + self.disk_check_interval
        if self._db is None or self.stats.paused:
            if self.stats.paused:
                self.stats.dropped_paused += len(batch)
            else:
                self.stats.dropped_failed += len(batch)
            return
        if batch:
            self._write(batch)
        behind = self._archive(now)
        if (now >= self._next_retention or self._retention_due) and not behind:
            self._retention_due = False
            self._apply_retention()
            self._next_retention = now + self.retention_interval
        if self.compaction.pending:
            self._compact()
        if (
            self._next_snapshot is not None
            and self.stats.batches > 0
            and now >= self._next_snapshot
        ):
            self._write_snapshot()
            self._next_snapshot = now + self.snapshot_interval

    def _archive(self, now: float) -> bool:
        archiver = self.archiver
        if archiver is None:
            return False
        if now >= self._next_archive:
            again = archiver.step(self._wall())
            self._next_archive = now if again else now + self.archive_interval
        return archiver.holds_retention()

    def _open(self, now: float) -> None:
        try:
            if self.snapshot_path is not None:
                discard_temp(self.snapshot_path)
                restore_snapshot(self.path, self.snapshot_path)
            self._db = HistoryDatabase(open_history(self.path))
            self._packer.forget()
        except Exception as exc:
            self._next_open = now + self.reopen_interval
            self.stats.error = f"cannot open history: {type(exc).__name__}: {exc}"
            LOGGER.exception("cannot open %s; retrying in %.0f s", self.path, self.reopen_interval)
            return
        self.stats.open = True
        self.stats.error = None
        LOGGER.info("history open at %s", self.path)
        if self.snapshot_path is not None and self._next_snapshot is None:
            self._next_snapshot = now + self._snapshot_delay()
        if self._worth_compacting():
            LOGGER.info("history has many free pages; compacting it once")
            self.request_compaction()

    def _worth_compacting(self) -> bool:
        if self._db is None:
            return False
        conn = self._db.conn
        mode = int(conn.execute("PRAGMA auto_vacuum").fetchone()[0])
        if mode == INCREMENTAL_VACUUM:
            return False
        page = int(conn.execute("PRAGMA page_size").fetchone()[0])
        free = int(conn.execute("PRAGMA freelist_count").fetchone()[0]) * page
        total = int(conn.execute("PRAGMA page_count").fetchone()[0]) * page
        return free >= COMPACT_MIN_FREE_BYTES and free >= COMPACT_FREE_SHARE * total

    def _file_bytes(self) -> int:
        size = 0
        for suffix in ("", "-wal"):
            try:
                size += self.path.with_name(self.path.name + suffix).stat().st_size
            except OSError:
                continue
        return size

    def _compact(self) -> None:
        state = self.compaction
        state.pending = False
        if self._db is None:
            state.error = "history is not open"
            return
        try:
            free = self._disk_free(self.path.parent)
        except OSError as exc:
            state.error = f"cannot read free space: {exc}"
            return
        before = self._file_bytes()
        needed = self.min_free_bytes + 2 * before
        if free < needed:
            state.error = (
                f"not enough free space: {free // 2**20} MB free, {needed // 2**20} MB needed"
            )
            LOGGER.warning("history compaction skipped: %s", state.error)
            return
        state.running = True
        conn = self._db.conn
        try:
            conn.execute(f"PRAGMA auto_vacuum = {INCREMENTAL_VACUUM:d}")
            conn.execute("VACUUM")
            conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        except Exception as exc:
            state.error = f"{type(exc).__name__}: {exc}"
            LOGGER.exception("history compaction failed")
            return
        finally:
            state.running = False
        state.freed_bytes = max(0, before - self._file_bytes())
        state.last_at = self._wall()
        LOGGER.warning("history compacted: %d MB freed", state.freed_bytes // 2**20)
        if self._next_snapshot is not None:
            self._write_snapshot()

    def _snapshot_delay(self) -> float:
        if self.snapshot_path is None:
            return 0.0
        try:
            written = self.snapshot_path.stat().st_mtime
        except OSError:
            return 0.0
        age = self._wall() - written
        return min(self.snapshot_interval, max(0.0, self.snapshot_interval - age))

    def _write_snapshot(self) -> None:
        if self._db is None or self.snapshot_path is None:
            return
        discard_temp(self.snapshot_path)
        if not self._snapshot_fits():
            self.stats.snapshots_skipped += 1
            return
        try:
            self._db.write_snapshot(self.snapshot_path)
        except Exception:
            LOGGER.exception("writing the history snapshot %s failed", self.snapshot_path)
            return
        self.stats.snapshots += 1
        LOGGER.info("history snapshot written to %s", self.snapshot_path)

    def _snapshot_fits(self) -> bool:
        try:
            free = self._disk_free(self.path.parent)
            size = self.path.stat().st_size
        except OSError:
            LOGGER.exception("cannot size the history snapshot; skipping it")
            return False
        needed = self.min_free_bytes + size
        if free < needed:
            LOGGER.warning(
                "history snapshot skipped: %d MB free, %d MB needed",
                free // 2**20,
                needed // 2**20,
            )
            return False
        return True

    def _check_disk(self) -> None:
        try:
            free = self._disk_free(self.path.parent)
        except OSError:
            LOGGER.exception("cannot read free space of %s", self.path.parent)
            return
        if not self.stats.paused and free < self.min_free_bytes:
            self.stats.paused = True
            LOGGER.error(
                "history writes PAUSED: %d MB free in %s, below the %d MB minimum",
                free // 2**20,
                self.path.parent,
                self.min_free_bytes // 2**20,
            )
        elif self.stats.paused and free >= self.min_free_bytes * RESUME_FACTOR:
            self.stats.paused = False
            if self._db is not None:
                self._db.forget_held()
            LOGGER.warning("history writes resumed: %d MB free", free // 2**20)

    def _write(self, batch: Sequence[Item]) -> None:
        if self._db is None:
            return
        samples = [item for item in batch if isinstance(item, Sample)]
        decisions = [item for item in batch if isinstance(item, DecisionRow)]
        commands = [item for item in batch if isinstance(item, CommandRow)]
        alarms = [item for item in batch if isinstance(item, AlarmRow)]
        states = [item for item in batch if isinstance(item, StateRow)]
        forecasts = [item for item in batch if isinstance(item, ForecastRow)]
        try:
            result = self._db.write_batch(samples)
            self.stats.journal_written += write_journal(
                self._db.conn, decisions, commands, alarms, states, self._packer
            )
            self.stats.journal_written += write_forecast(self._db.conn, forecasts)
        except Exception as exc:
            self.stats.dropped_failed += len(batch)
            self.stats.error = f"{type(exc).__name__}: {exc}"
            LOGGER.exception("history batch of %d items failed", len(batch))
            return
        self.stats.written += result.samples
        self.stats.batches += 1
        self.stats.error = None

    def _apply_retention(self) -> None:
        if self._db is None:
            return
        try:
            now = self._wall()
            deleted = self._db.apply_retention(self.retention, now)
            if self.journal_days is not None:
                cutoff = now - self.journal_days * SECONDS_PER_DAY
                deleted += delete_journal_before(self._db.conn, cutoff)
            hour_days = self.retention.hour_days
            if hour_days is not None:
                cutoff = now - hour_days * SECONDS_PER_DAY
                deleted += delete_forecast_before(self._db.conn, cutoff)
            if deleted:
                self._db.release_free_pages()
        except Exception:
            LOGGER.exception("history retention failed")
            return
        self.stats.retention_deleted += deleted
        if deleted:
            LOGGER.info("history retention deleted %d rows", deleted)

    def _close(self) -> None:
        db, self._db = self._db, None
        self.stats.open = False
        if db is not None:
            try:
                db.close()
            except Exception:
                LOGGER.exception("closing history failed")
