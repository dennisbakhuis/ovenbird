"""Settings fields derived from the controller's own setting declarations.

The controller declares every setting once in ``ovenbird_core``
(:func:`ovenbird_core.setting.setting`): default, range, unit and description.
:func:`core_field` turns one into the pydantic field of a service setting, so the
service never repeats a default or a bound. The field keeps an explicit annotation in
its feature model (mypy sees the real type); ``tests/test_settings_fromcore.py`` checks
that it matches the core field and that every core setting has exactly one service
field.

Feature settings models derive from :class:`FeatureSettings`, which records which
service field each :func:`core_field` became (:data:`CORE_FIELDS`).
"""

from __future__ import annotations

from dataclasses import MISSING, dataclass, replace
from enum import Enum
from typing import Any, Final

from pydantic import BaseModel, Field

from ovenbird_core.setting import SettingSpec, default_of, spec


@dataclass(frozen=True, slots=True)
class CoreSource:
    """The core setting a service field is built from.

    Parameters
    ----------
    owner
        Core configuration dataclass.
    name
        Field name in ``owner``.
    unset
        The service field defaults to ``None``: unset takes the core (or emitter
        preset) value.
    narrowed
        The narrower range the service offers, ``None`` for the core range.
    """

    owner: type
    name: str
    unset: bool
    narrowed: SettingSpec | None = None

    @property
    def core_spec(self) -> SettingSpec:
        """Bounds, unit and description of the core setting."""
        return spec(self.owner, self.name)

    @property
    def spec(self) -> SettingSpec:
        """Bounds, unit and description the service field offers."""
        return self.core_spec if self.narrowed is None else self.narrowed

    @property
    def default(self) -> Any:
        """The core default in its service form (an enum as its value)."""
        return _plain(default_of(self.owner, self.name))


CORE_FIELDS: Final[dict[str, CoreSource]] = {}
_PENDING: Final[dict[int, tuple[object, CoreSource]]] = {}


def _plain(value: Any) -> Any:
    return value.value if isinstance(value, Enum) else value


def core_field(
    owner: type,
    name: str,
    *,
    unset: bool = False,
    gt: float | None = None,
    ge: float | None = None,
    lt: float | None = None,
    le: float | None = None,
) -> Any:
    """Return the pydantic field of the core setting ``owner.name``.

    Parameters
    ----------
    owner
        Core configuration dataclass (``StoveConfig``).
    name
        Setting in ``owner`` (``backoff_k``).
    unset
        Default to ``None`` (unset takes the core or emitter preset value) instead of
        the core default.
    gt, ge, lt, le
        A narrower range the service offers than the controller accepts (each bound
        must lie inside the core range); it replaces the core bound on that side.

    Returns
    -------
    pydantic.fields.FieldInfo
        Default and bounds of the core setting, typed ``Any`` like ``Field``.

    Raises
    ------
    TypeError
        When the core setting has no default and ``unset`` is false.
    ValueError
        When a narrowed bound lies outside the core range.
    """
    source = CoreSource(owner, name, unset, _narrowed(spec(owner, name), gt, ge, lt, le))
    found = source.spec
    default = None if unset else source.default
    if default is MISSING:
        raise TypeError(f"{owner.__name__}.{name} has no default; declare it unset")
    info = Field(default=default, gt=found.gt, ge=found.ge, lt=found.lt, le=found.le)
    _PENDING[id(info)] = (info, source)
    return info


def _narrowed(
    core: SettingSpec,
    gt: float | None,
    ge: float | None,
    lt: float | None,
    le: float | None,
) -> SettingSpec | None:
    if gt is None and ge is None and lt is None and le is None:
        return None
    edges = {core.gt, core.ge, core.lt, core.le}
    for value in (gt, ge, lt, le):
        if value is not None and not (core.admits(value) or value in edges):
            raise ValueError(f"bound {value:g} lies outside the core range {core.interval()}")
    lower = (gt, ge) if gt is not None or ge is not None else (core.gt, core.ge)
    upper = (lt, le) if lt is not None or le is not None else (core.lt, core.le)
    return replace(core, gt=lower[0], ge=lower[1], lt=upper[0], le=upper[1])


def core_source(name: str) -> CoreSource | None:
    """Return the core setting service field ``name`` is built from (``None`` if none)."""
    return CORE_FIELDS.get(name)


class FeatureSettings(BaseModel):
    """Base of the per-feature settings models that :class:`~ovenbird.config.Settings` combines.

    Records the service name of every :func:`core_field` in :data:`CORE_FIELDS` when a
    feature model is defined.
    """

    def __init_subclass__(cls, **kwargs: Any) -> None:
        """Bind the pending core fields of the new model to their attribute names."""
        super().__init_subclass__(**kwargs)
        for attribute, value in vars(cls).items():
            pending = _PENDING.pop(id(value), None)
            if pending is not None:
                CORE_FIELDS[attribute] = pending[1]
