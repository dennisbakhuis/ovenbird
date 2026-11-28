"""CSV export of journals and series (``?format=csv``) and the streamed bulk exports.

Rows are written with the standard library's ``csv`` module; nested values become
compact JSON text. A text cell starting with ``=``, ``+``, ``-``, ``@``, a tab or a
carriage return is prefixed with ``'`` so a spreadsheet never runs it as a formula
(numbers are written as numbers). The bulk exports (``export/...``) stream CSV or
newline-delimited JSON in pieces of about 64 kB, gzip-encoded when the client
accepts it.
"""

from __future__ import annotations

import csv
import io
import json
import zlib
from collections.abc import Iterable, Iterator, Mapping, Sequence
from typing import Any, Final, Literal

from fastapi.responses import Response, StreamingResponse

type Format = Literal["json", "csv"]

FORMULA_START: Final = ("=", "+", "-", "@", "\t", "\r")
MEDIA_TYPE: Final = "text/csv; charset=utf-8"


def cell(value: Any) -> Any:
    """Return the CSV form of one value."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int | float):
        return value
    if isinstance(value, Mapping | list | tuple):
        value = json.dumps(value, separators=(",", ":"), ensure_ascii=False, sort_keys=True)
    text = str(value)
    return "'" + text if text.startswith(FORMULA_START) else text


def csv_text(columns: Sequence[str], rows: Iterable[Mapping[str, Any]]) -> str:
    """Return CSV text with a header row and one line per row."""
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(columns)
    for row in rows:
        writer.writerow([cell(row.get(name)) for name in columns])
    return buffer.getvalue()


def csv_response(
    name: str, columns: Sequence[str], rows: Iterable[Mapping[str, Any]], stamp: str
) -> Response:
    """Return a CSV download named ``ovenbird-<name>-<stamp>.csv``.

    Parameters
    ----------
    name
        Export name in the filename.
    columns
        Column names, in output order.
    rows
        Rows keyed by column name.
    stamp
        Timestamp text in the filename; other characters than letters, digits, ``-`` and ``_``
        become ``-``.
    """
    safe = "".join(ch if ch.isalnum() or ch in "-_" else "-" for ch in stamp)
    return Response(
        csv_text(columns, rows),
        media_type=MEDIA_TYPE,
        headers={"Content-Disposition": f'attachment; filename="ovenbird-{name}-{safe}.csv"'},
    )


DECISION_COLUMNS: Final = (
    "at",
    "controller",
    "mode",
    "ladder",
    "reason",
    "setpoint",
    "config_version",
    "note",
    "arbiter",
    "commands",
)
COMMAND_COLUMNS: Final = ("at", "kind", "value", "status", "attempt", "topic", "payload", "detail")
ALARM_COLUMNS: Final = ("at", "code", "severity", "event", "message", "detail")
AUDIT_COLUMNS: Final = ("at", "actor", "source_ip", "action", "detail")
HISTORY_COLUMNS: Final = ("signal", "unit", "at", "value")
JOURNAL_COLUMNS: Final = {
    "decisions": DECISION_COLUMNS,
    "commands": COMMAND_COLUMNS,
    "alarms": ALARM_COLUMNS,
    "forecast": ("issued_at", "target_at", "temp_c", "radiation_wm2", "cloud_pct", "wind_ms"),
}
NDJSON_MEDIA_TYPE: Final = "application/x-ndjson"
GZIP_LEVEL: Final = 6
GZIP_WBITS: Final = 31
FLUSH_BYTES: Final = 64 * 1024

type StreamFormat = Literal["csv", "ndjson"]


def csv_line(values: Sequence[Any]) -> str:
    """Return one CSV line (cells as :func:`cell` writes them)."""
    buffer = io.StringIO()
    csv.writer(buffer, lineterminator="\n").writerow([cell(value) for value in values])
    return buffer.getvalue()


def ndjson_line(value: Any) -> str:
    """Return one line of newline-delimited JSON."""
    return json.dumps(value, separators=(",", ":"), ensure_ascii=False, allow_nan=False) + "\n"


def accepts_gzip(header: str | None) -> bool:
    """Whether an ``Accept-Encoding`` header admits gzip (not refused with ``q=0``)."""
    for part in (header or "").split(","):
        name, _, params = part.strip().partition(";")
        if name.strip().lower() not in {"gzip", "*"}:
            continue
        weight = params.strip().lower().removeprefix("q=")
        if not weight:
            return True
        try:
            return float(weight) > 0
        except ValueError:
            return True
    return False


def gzipped(chunks: Iterable[str]) -> Iterator[bytes]:
    """Compress a text stream into gzip pieces of about 64 kB."""
    packer = zlib.compressobj(GZIP_LEVEL, zlib.DEFLATED, GZIP_WBITS)
    pending = 0
    for text in chunks:
        data = text.encode()
        pending += len(data)
        piece = packer.compress(data)
        if pending >= FLUSH_BYTES:
            piece += packer.flush(zlib.Z_SYNC_FLUSH)
            pending = 0
        if piece:
            yield piece
    yield packer.flush()


def batched(chunks: Iterable[str]) -> Iterator[bytes]:
    """Join a text stream into pieces of about 64 kB."""
    parts: list[str] = []
    size = 0
    for text in chunks:
        parts.append(text)
        size += len(text)
        if size >= FLUSH_BYTES:
            yield "".join(parts).encode()
            parts, size = [], 0
    if parts:
        yield "".join(parts).encode()


def download_name(name: str, stamp: str, extension: str) -> str:
    """Return ``ovenbird-<name>-<stamp>.<extension>`` with a safe stamp."""
    safe = "".join(ch if ch.isalnum() or ch in "-_" else "-" for ch in stamp)
    return f"ovenbird-{name}-{safe}.{extension}"


def stream_response(
    chunks: Iterable[str], output: StreamFormat, filename: str, *, gzip: bool
) -> StreamingResponse:
    """Return a streamed CSV or NDJSON download, gzip-encoded when the client accepts it.

    Parameters
    ----------
    chunks
        Pre-rendered text chunks to stream.
    output
        Stream format; ``csv`` or NDJSON, which sets the media type.
    filename
        File name offered to the client.
    gzip
        Whether to gzip-encode the stream.
    """
    headers = {
        "Content-Disposition": f'attachment; filename="{filename}"',
        "Cache-Control": "no-store",
        "Vary": "Accept-Encoding",
    }
    if gzip:
        headers["Content-Encoding"] = "gzip"
    media_type = MEDIA_TYPE if output == "csv" else NDJSON_MEDIA_TYPE
    body = gzipped(chunks) if gzip else batched(chunks)
    return StreamingResponse(body, media_type=media_type, headers=headers)
