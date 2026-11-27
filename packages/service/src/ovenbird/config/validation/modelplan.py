"""Rules of the model plan settings, and the lock on switching it on.

``control_model_use`` accepts ``off`` and ``shadow``. ``on`` is refused until the
offline evaluation and a shadow period have been reviewed (the decision record
``docs/decisions/2026-11-27-learned-model-in-controller.md``, point 2).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from ovenbird.config.values import Issue

if TYPE_CHECKING:
    from ovenbird.config.settings import Settings

ON_LOCKED: Final = True
"""THE LOCK on ``control_model_use`` = ``on``.

While true, validation refuses ``on`` and the plan runner never hands a slice to the
controller. Lifting the lock is this one line: set it to ``False`` (or delete the
constant and :func:`model_use_issues`).
"""

LOCKED_MESSAGE: Final = (
    "the model may only be switched on after the evaluation and a shadow period; "
    "see docs/decisions/2026-11-27-learned-model-in-controller.md"
)


def model_use_issues(settings: Settings) -> list[Issue]:
    """Return the refusal of ``control_model_use`` = ``on`` while :data:`ON_LOCKED` holds."""
    if ON_LOCKED and settings.control_model_use == "on":
        return [Issue("control_model_use", "model_use_on_locked", LOCKED_MESSAGE)]
    return []
