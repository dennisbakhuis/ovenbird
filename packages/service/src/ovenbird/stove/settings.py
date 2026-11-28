"""Wood-stove mode settings (``control_stove_*``) and the controller configuration they give.

Every field but the two switches is a :class:`~ovenbird_core.control.StoveConfig`
setting: its default, range, unit and description come from core
(:func:`~ovenbird.config.fromcore.core_field`). The cross-field rules are in
:mod:`ovenbird.stove.validation`.
"""

from __future__ import annotations

from typing import Any

from pydantic import field_validator

from ovenbird.config.fromcore import FeatureSettings, core_field
from ovenbird_core.control import StoveConfig


class StoveSettings(FeatureSettings):
    """Wood-stove mode (``control_stove_*``).

    Parameters
    ----------
    control_stove_enabled
        Wood-stove mode on (off by default; also needed for a manual start).
    control_stove_rise_enabled
        Fast-rise trigger on; off leaves ``StoveConfig.rise_k`` unset.
    control_stove_reference_signal
        :attr:`StoveConfig.reference <ovenbird_core.control.StoveConfig.reference>`;
        its HA entity is subscribed automatically.
    """

    control_stove_enabled: bool = False
    control_stove_auto: bool = core_field(StoveConfig, "auto")
    control_stove_enter_above_k: float = core_field(StoveConfig, "enter_above_k")
    control_stove_exit_hysteresis_k: float = core_field(StoveConfig, "exit_hysteresis_k")
    control_stove_rise_enabled: bool = True
    control_stove_rise_k: float = core_field(StoveConfig, "rise_k")
    control_stove_rise_window_s: float = core_field(StoveConfig, "rise_window_s")
    control_stove_backoff_k: float = core_field(StoveConfig, "backoff_k")
    control_stove_to_minimum: bool = core_field(StoveConfig, "to_minimum")
    control_stove_min_active_s: float = core_field(StoveConfig, "min_active_s")
    control_stove_max_active_s: float = core_field(StoveConfig, "max_active_s")
    control_stove_reentry_hold_s: float = core_field(StoveConfig, "reentry_hold_s")
    control_stove_reference_signal: str | None = core_field(StoveConfig, "reference")
    control_stove_reference_floor_c: float = core_field(StoveConfig, "reference_floor_c")
    control_stove_reference_band_k: float = core_field(StoveConfig, "reference_band_k")

    @field_validator("control_stove_reference_signal", mode="before")
    @classmethod
    def _empty_reference_is_unset(cls, value: Any) -> Any:
        """Treat an empty reference signal as unset."""
        if isinstance(value, str) and not value.strip():
            return None
        return value

    def stove_config(self) -> StoveConfig | None:
        """Return the wood-stove mode configuration (``None`` when it is off)."""
        if not self.control_stove_enabled:
            return None
        return StoveConfig(
            auto=self.control_stove_auto,
            enter_above_k=self.control_stove_enter_above_k,
            exit_hysteresis_k=self.control_stove_exit_hysteresis_k,
            rise_k=self.control_stove_rise_k if self.control_stove_rise_enabled else None,
            rise_window_s=self.control_stove_rise_window_s,
            backoff_k=self.control_stove_backoff_k,
            to_minimum=self.control_stove_to_minimum,
            min_active_s=self.control_stove_min_active_s,
            max_active_s=self.control_stove_max_active_s,
            reentry_hold_s=self.control_stove_reentry_hold_s,
            reference=self.control_stove_reference_signal,
            reference_floor_c=self.control_stove_reference_floor_c,
            reference_band_k=self.control_stove_reference_band_k,
        )
