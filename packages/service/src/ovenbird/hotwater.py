"""Whether the UI shows hot water (DHW): the ``hot_water`` setting and the pump's own report.

``hot_water`` is ``on``, ``off`` or ``auto``. With ``auto`` the pump's
``main/DHW_Installed`` (``1`` enabled / ``0`` disabled) decides; while the pump has not
reported it, hot water is shown. Only the display follows this: a DHW run (three-way
valve on the tank) still freezes the controller's corrections exactly as before.
"""

from __future__ import annotations

from typing import Any, Final

from ovenbird_core import HeishaSignal, Instant, StateStore

INSTALLED: Final = 1
NOT_INSTALLED: Final = 0


def dhw_installed(store: StateStore, now: Instant) -> bool | None:
    """Return whether the pump reports a DHW tank; ``None`` while it has not said.

    Parameters
    ----------
    store
        The state store.
    now
        Current instant.

    Returns
    -------
    bool or None
        ``True`` for ``1`` (enabled), ``False`` for ``0`` (disabled), ``None`` otherwise.
    """
    view = store.view(HeishaSignal.DHW_INSTALLED, now)
    if view is None or view.reason is not None or isinstance(view.value, bool):
        return None
    if view.value == INSTALLED:
        return True
    if view.value == NOT_INSTALLED:
        return False
    return None


def hot_water_payload(setting: str, installed: bool | None) -> dict[str, Any]:
    """Return the ``hot_water`` object of ``GET api/v1/config``.

    Parameters
    ----------
    setting
        ``auto``, ``on`` or ``off``.
    installed
        What the pump reports (``None`` when unknown).

    Returns
    -------
    dict
        ``setting``, ``installed`` and ``shown`` (whether the UI shows hot water).
    """
    shown = setting == "on" or (setting == "auto" and installed is not False)
    return {"setting": setting, "installed": installed, "shown": shown}
