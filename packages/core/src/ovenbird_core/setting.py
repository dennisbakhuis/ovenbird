"""Controller settings: a configuration field's default with its bounds, unit and text.

A configuration dataclass declares each setting with :func:`setting` (or a required
one with ``field(metadata=setting_metadata(...))``) and calls :func:`check_settings`
from its ``__post_init__``. The service builds its settings fields from the same
metadata (see ``ovenbird.config.fromcore``), so the controller and the configuration
API cannot disagree on a default, a range, a unit or a description.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import Field, dataclass, field, fields, is_dataclass
from typing import Any, Final

SETTING: Final = "ovenbird_setting"


@dataclass(frozen=True, slots=True)
class SettingSpec:
    """Bounds, unit and description of one setting.

    Parameters
    ----------
    doc
        What the setting means (the single text of the controller and the service).
    unit
        Unit of the value (``K``, ``s``, ``°C``); ``None`` for a plain number, a flag
        or a name.
    gt, ge, lt, le
        Exclusive and inclusive lower and upper bounds; ``None`` leaves that side open.
    """

    doc: str
    unit: str | None = None
    gt: float | None = None
    ge: float | None = None
    lt: float | None = None
    le: float | None = None

    @property
    def bounded(self) -> bool:
        """Whether the setting has a range."""
        return any(bound is not None for bound in (self.gt, self.ge, self.lt, self.le))

    def admits(self, value: float) -> bool:
        """Whether ``value`` lies in the range."""
        return (
            (self.gt is None or value > self.gt)
            and (self.ge is None or value >= self.ge)
            and (self.lt is None or value < self.lt)
            and (self.le is None or value <= self.le)
        )

    def interval(self) -> str:
        """Return the range as text, e.g. ``(0, 15] K``."""
        if self.gt is not None:
            low = f"({self.gt:g}"
        elif self.ge is not None:
            low = f"[{self.ge:g}"
        else:
            low = "(-inf"
        if self.lt is not None:
            high = f"{self.lt:g})"
        elif self.le is not None:
            high = f"{self.le:g}]"
        else:
            high = "inf)"
        return f"{low}, {high}" + ("" if self.unit is None else f" {self.unit}")


def setting_metadata(
    *,
    doc: str,
    unit: str | None = None,
    gt: float | None = None,
    ge: float | None = None,
    lt: float | None = None,
    le: float | None = None,
) -> Mapping[str, SettingSpec]:
    """Return the dataclass field metadata of a setting (for a required field)."""
    return {SETTING: SettingSpec(doc=doc, unit=unit, gt=gt, ge=ge, lt=lt, le=le)}


def setting(
    default: Any,
    *,
    doc: str,
    unit: str | None = None,
    gt: float | None = None,
    ge: float | None = None,
    lt: float | None = None,
    le: float | None = None,
) -> Any:
    """Return a dataclass field with ``default`` and the setting's metadata.

    Parameters
    ----------
    default
        Default value (immutable).
    doc
        What the setting means.
    unit
        Unit of the value.
    gt, ge, lt, le
        Bounds, enforced by :func:`check_settings` and offered by the service.

    Returns
    -------
    dataclasses.Field
        The field, typed ``Any`` so it can stand for the annotated value.
    """
    return field(
        default=default, metadata=setting_metadata(doc=doc, unit=unit, gt=gt, ge=ge, lt=lt, le=le)
    )


def _spec_of(item: Field[Any]) -> SettingSpec | None:
    found = item.metadata.get(SETTING)
    return found if isinstance(found, SettingSpec) else None


def specs(owner: type) -> dict[str, SettingSpec]:
    """Return the settings of the dataclass ``owner`` by field name, in field order."""
    if not is_dataclass(owner):
        raise TypeError(f"{owner!r} is not a dataclass")
    return {item.name: spec for item in fields(owner) if (spec := _spec_of(item)) is not None}


def spec(owner: type, name: str) -> SettingSpec:
    """Return the setting ``name`` of the dataclass ``owner``.

    Raises
    ------
    KeyError
        When ``owner`` has no setting of that name.
    """
    found = specs(owner).get(name)
    if found is None:
        raise KeyError(f"{owner.__name__} has no setting {name!r}")
    return found


def default_of(owner: type, name: str) -> Any:
    """Return the default of setting ``name`` of ``owner`` (``MISSING`` when required)."""
    spec(owner, name)
    return next(item.default for item in fields(owner) if item.name == name)


def check_settings(instance: Any) -> None:
    """Validate every bounded setting of a dataclass instance against its range.

    ``None`` (an optional setting left out) and flags are not checked; a number must be
    finite and inside the range.

    Raises
    ------
    ValueError
        Naming the first setting outside its range.
    """
    owner = type(instance).__name__
    for item in fields(instance):
        found = _spec_of(item)
        if found is None or not found.bounded:
            continue
        value = getattr(instance, item.name)
        if value is None or isinstance(value, bool):
            continue
        if not math.isfinite(value):
            raise ValueError(f"{owner}.{item.name} must be finite")
        if not found.admits(value):
            raise ValueError(f"{owner}.{item.name} must be in {found.interval()}")
