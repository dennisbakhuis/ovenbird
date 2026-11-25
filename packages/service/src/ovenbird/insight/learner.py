"""Keep the house-model learner's configuration file in step with the configuration."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ovenbird.insight import house
from ovenbird_core import Instant

if TYPE_CHECKING:
    from ovenbird.configstore import ConfigManager


def keep_learner_config(manager: ConfigManager) -> None:
    """Write ``learner/learner-config.json`` now and again after every applied configuration.

    Parameters
    ----------
    manager
        The configuration manager whose settings and version the file follows.
    """
    house.write_learner_config(manager.settings, manager.version)

    def refresh(version: int | None, _at: Instant) -> None:
        house.write_learner_config(manager.settings, version)

    manager.on_applied.append(refresh)
