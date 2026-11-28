"""Compressed storage of the decision journal's JSON texts.

A decision row keeps its summary columns as plain values and its three JSON texts
(record, arbiter decisions, command events) in one ``body`` BLOB: the texts joined
by an ASCII record separator (``0x1e``, which JSON text never contains unescaped)
and deflated with zlib. Consecutive records share almost all of their keys and
most of their values, so the deflate stream is primed with a preset dictionary: an
earlier decision of the same database, kept in ``decision_dictionary`` and named
by the row's ``dictionary_id`` (``NULL`` for a body packed without one). The
writer starts a new dictionary once a day of decisions, so it follows changes of
the record's shape; retention drops the dictionaries no row uses any more.

Unpacking returns the stored texts byte for byte.
"""

from __future__ import annotations

import sqlite3
import zlib
from collections.abc import Callable
from dataclasses import dataclass
from typing import Final

SEPARATOR: Final = "\x1e"
LEVEL: Final = 9
MAX_DICTIONARY: Final = 32 * 1024
ROTATE_S: Final = 86_400.0
PACK_FUNCTION: Final = "ovenbird_pack"
DICTIONARY_FUNCTION: Final = "ovenbird_dictionary"


def dictionary_from(record: str, arbiter: str) -> bytes:
    """Return a preset dictionary built from one decision's record and arbiter texts.

    Parameters
    ----------
    record, arbiter
        JSON texts of a decision row.

    Returns
    -------
    bytes
        The joined texts, cut to the last 32 kB (zlib's window).
    """
    data = (record + SEPARATOR + arbiter + SEPARATOR).encode()
    return data[-MAX_DICTIONARY:]


def pack(record: str, arbiter: str, commands: str, dictionary: bytes | None) -> bytes:
    """Return the ``body`` BLOB of a decision row.

    Parameters
    ----------
    record, arbiter, commands
        JSON texts of the row.
    dictionary
        Preset dictionary, or ``None``.

    Returns
    -------
    bytes
        The deflated texts.
    """
    text = SEPARATOR.join((record, arbiter, commands)).encode()
    packer = (
        zlib.compressobj(LEVEL, zdict=dictionary)
        if dictionary is not None
        else zlib.compressobj(LEVEL)
    )
    return packer.compress(text) + packer.flush()


def unpack(body: bytes, dictionary: bytes | None) -> tuple[str, str, str]:
    """Return the record, arbiter and commands texts of a ``body`` BLOB.

    Parameters
    ----------
    body
        Bytes written by :func:`pack`.
    dictionary
        The preset dictionary the body was packed with, or ``None``.

    Returns
    -------
    tuple of str
        ``(record, arbiter, commands)``.

    Raises
    ------
    ValueError
        When the body is not a packed decision.
    """
    unpacker = (
        zlib.decompressobj(zdict=dictionary) if dictionary is not None else zlib.decompressobj()
    )
    try:
        text = (unpacker.decompress(body) + unpacker.flush()).decode()
    except (zlib.error, UnicodeDecodeError) as exc:
        raise ValueError(f"not a packed decision: {exc}") from None
    parts = text.split(SEPARATOR)
    if len(parts) != 3:
        raise ValueError("not a packed decision: expected three texts")
    return parts[0], parts[1], parts[2]


def _sql_pack(record: str, arbiter: str, commands: str, dictionary: bytes | None) -> bytes:
    """Pack a decision for the SQL function used by migrations.

    Parameters
    ----------
    record
        Decision record JSON.
    arbiter
        Arbiter JSON.
    commands
        Commands JSON.
    dictionary
        Compression dictionary, if any.
    """
    return pack(record, arbiter, commands, dictionary)


def register_functions(conn: sqlite3.Connection) -> None:
    """Make :func:`pack` and :func:`dictionary_from` callable from SQL (for migrations)."""
    conn.create_function(PACK_FUNCTION, 4, _sql_pack, deterministic=True)
    conn.create_function(DICTIONARY_FUNCTION, 2, dictionary_from, deterministic=True)


@dataclass(frozen=True, slots=True)
class Dictionary:
    """One stored preset dictionary.

    Parameters
    ----------
    id
        Row id in ``decision_dictionary``.
    created_ts
        Time of the decision it was built from (unix seconds).
    data
        The dictionary.
    """

    id: int
    created_ts: float
    data: bytes


class DecisionPacker:
    """Picks the dictionary of each new decision row; used by the writer thread only.

    Parameters
    ----------
    rotate_s
        Decision time after which a new dictionary is started.
    """

    def __init__(self, rotate_s: float = ROTATE_S) -> None:
        self.rotate_s = rotate_s
        self._current: Dictionary | None = None
        self._loaded = False

    def forget(self) -> None:
        """Drop the cached dictionary (after a rolled back transaction)."""
        self._current = None
        self._loaded = False

    def _load(self, conn: sqlite3.Connection) -> None:
        """Load the newest stored dictionary."""
        row = conn.execute(
            "SELECT id, created_ts, data FROM decision_dictionary ORDER BY id DESC LIMIT 1"
        ).fetchone()
        self._current = None if row is None else Dictionary(int(row[0]), float(row[1]), row[2])
        self._loaded = True

    def pack(
        self, conn: sqlite3.Connection, ts: float, record: str, arbiter: str, commands: str
    ) -> tuple[int, bytes]:
        """Return ``(dictionary_id, body)`` of a row, storing a new dictionary when due.

        Parameters
        ----------
        conn
            Writer connection inside the journal transaction.
        ts
            Time of the decision.
        record, arbiter, commands
            JSON texts of the row.

        Returns
        -------
        tuple
            Dictionary id and packed body.
        """
        if not self._loaded:
            self._load(conn)
        current = self._current
        if current is None or abs(ts - current.created_ts) >= self.rotate_s:
            data = dictionary_from(record, arbiter)
            cursor = conn.execute(
                "INSERT INTO decision_dictionary (created_ts, data) VALUES (?, ?)", (ts, data)
            )
            current = Dictionary(int(cursor.lastrowid or 0), ts, data)
            self._current = current
        return current.id, pack(record, arbiter, commands, current.data)


class DictionaryCache:
    """Reads stored dictionaries on demand, each once.

    Parameters
    ----------
    conn
        Connection to read ``decision_dictionary`` from.
    """

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn
        self._found: dict[int, bytes | None] = {}

    def get(self, dictionary_id: int | None) -> bytes | None:
        """Return the dictionary ``dictionary_id`` (``None`` for ``None``).

        Raises
        ------
        ValueError
            When a row names a dictionary that does not exist.
        """
        if dictionary_id is None:
            return None
        if dictionary_id not in self._found:
            row = self._conn.execute(
                "SELECT data FROM decision_dictionary WHERE id = ?", (dictionary_id,)
            ).fetchone()
            self._found[dictionary_id] = None if row is None else bytes(row[0])
        found = self._found[dictionary_id]
        if found is None:
            raise ValueError(f"decision dictionary {dictionary_id} is missing")
        return found


type Unpacker = Callable[[bytes, int | None], tuple[str, str, str]]


def unpacker(conn: sqlite3.Connection) -> Unpacker:
    """Return a function that unpacks bodies read through ``conn``."""
    cache = DictionaryCache(conn)

    def run(body: bytes, dictionary_id: int | None) -> tuple[str, str, str]:
        """Unpack a stored body with the dictionary it was packed with."""
        return unpack(bytes(body), cache.get(dictionary_id))

    return run
