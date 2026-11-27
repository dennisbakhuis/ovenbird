"""Load Home Assistant state history from the Datalake parquet layout.

Layout: ``datalake/states/entity_id=<id>/year=YYYY/month=MM/<file>.parquet`` with the
columns ``state`` (text), ``attributes`` (JSON text), ``last_changed``,
``last_updated`` and ``ingested_at`` (UTC timestamps). A sample is placed at
``last_updated``; non-numeric states (``unavailable``, ``unknown``) end the previous
value's validity and are kept as ``NaN``.

Entity ids are the generic ones of the example install (``sensor.living_room_temperature``);
an id the local settings map to this install's entity (:func:`ovenbird_sim.local.entity`)
is read from that entity's partitions when only those exist.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

import numpy as np

from ovenbird_sim import local
from ovenbird_sim.data.series import Series

if TYPE_CHECKING:
    import pyarrow as pa

STATES_DIR: Final = "states"


def entity_dir(root: Path, entity_id: str) -> Path:
    """Return the directory holding one entity's partitions, mapped to this install's id."""
    direct = root / STATES_DIR / f"entity_id={entity_id}"
    mapped = root / STATES_DIR / f"entity_id={local.entity(entity_id)}"
    return mapped if not direct.is_dir() and mapped.is_dir() else direct


def entities(root: Path) -> list[str]:
    """List the entity ids present in a Datalake root."""
    base = root / STATES_DIR
    if not base.is_dir():
        return []
    return sorted(
        p.name.split("=", 1)[1] for p in base.iterdir() if p.name.startswith("entity_id=")
    )


def _read_table(root: Path, entity_id: str) -> pa.Table | None:
    import pyarrow as pa
    import pyarrow.parquet as pq

    files = sorted(entity_dir(root, entity_id).rglob("*.parquet"))
    if not files:
        return None
    columns = ["state", "attributes", "last_updated"]
    return pa.concat_tables([pq.read_table(f, columns=columns) for f in files])


def _unix_seconds(column: pa.ChunkedArray[Any]) -> np.ndarray:
    import pyarrow as pa

    micros = column.cast(pa.timestamp("us", tz="UTC")).cast(pa.int64()).to_numpy()
    return np.asarray(micros, dtype=np.float64) / 1e6


def _float_or_nan(text: object) -> float:
    if not isinstance(text, str):
        return math.nan
    try:
        value = float(text)
    except ValueError:
        return math.nan
    return value if math.isfinite(value) else math.nan


def _dedupe(t: np.ndarray, v: np.ndarray) -> Series:
    order = np.argsort(t, kind="stable")
    t, v = t[order], v[order]
    if t.size == 0:
        return Series(t, v)
    keep = np.ones(t.size, dtype=bool)
    keep[:-1] = t[1:] != t[:-1]
    return Series(t[keep], v[keep])


def load_state(root: Path, entity_id: str) -> Series:
    """Load an entity's numeric state history.

    Parameters
    ----------
    root
        Datalake root (the directory containing ``states/``).
    entity_id
        Home Assistant entity id.

    Returns
    -------
    Series
        Numeric states at ``last_updated``; ``NaN`` where the state was not numeric.
        Empty when the entity is absent.
    """
    table = _read_table(root, entity_id)
    if table is None:
        return Series.empty()
    t = _unix_seconds(table.column("last_updated"))
    v = np.array([_float_or_nan(s) for s in table.column("state").to_pylist()])
    return _dedupe(t, v)


def load_attribute(root: Path, entity_id: str, attribute: str) -> Series:
    """Load one numeric attribute of an entity (e.g. ``weather.*`` ``cloud_coverage``).

    Parameters
    ----------
    root
        Datalake root.
    entity_id
        Home Assistant entity id.
    attribute
        Attribute key in the JSON ``attributes`` column.

    Returns
    -------
    Series
        Attribute values at ``last_updated``; ``NaN`` where absent or not numeric.
    """
    table = _read_table(root, entity_id)
    if table is None:
        return Series.empty()
    t = _unix_seconds(table.column("last_updated"))
    values: list[float] = []
    for text in table.column("attributes").to_pylist():
        try:
            attrs = json.loads(text) if isinstance(text, str) else {}
        except ValueError:
            attrs = {}
        raw = attrs.get(attribute) if isinstance(attrs, dict) else None
        if isinstance(raw, int | float) and not isinstance(raw, bool):
            values.append(float(raw))
        else:
            values.append(math.nan)
    return _dedupe(t, np.array(values))


def load_sun_elevation(root: Path) -> Series:
    """Load ``sun.sun`` elevation in degrees (from its attributes, when recorded)."""
    return load_attribute(root, "sun.sun", "elevation")
