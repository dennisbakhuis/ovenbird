"""Small JSON facts that survive restarts, kept in ``config.db``'s ``runtime`` table.

The go-live pump-state snapshot, the envelope rule's evidence, the last notification
test and the service start count live here. Without a configuration store (tests,
the harness) they are kept in memory only.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any, Final

if TYPE_CHECKING:
    from ovenbird.configstore import ConfigStore

LOGGER = logging.getLogger("ovenbird.facts")
PREFIX: Final = "fact:"
COMPACT: Final = (",", ":")


class Facts:
    """Read and write JSON facts by key.

    Parameters
    ----------
    store
        The configuration store; ``None`` keeps the facts in memory.
    """

    def __init__(self, store: ConfigStore | None = None) -> None:
        self.store = store
        self._memory: dict[str, Any] = {}

    def get(self, key: str) -> Any:
        """Return the fact ``key`` (``None`` when unset or unreadable)."""
        if self.store is None:
            return self._memory.get(key)
        raw = self.store.runtime_get(PREFIX + key)
        if raw is None:
            return None
        try:
            return json.loads(raw)
        except ValueError:
            LOGGER.warning("fact %s is not JSON; ignored", key)
            return None

    def set(self, key: str, value: Any) -> None:
        """Store the fact ``key`` (``None`` removes it)."""
        if self.store is None:
            if value is None:
                self._memory.pop(key, None)
            else:
                self._memory[key] = json.loads(json.dumps(value))
            return
        text = None if value is None else json.dumps(value, separators=COMPACT, sort_keys=True)
        self.store.runtime_set(PREFIX + key, text)
