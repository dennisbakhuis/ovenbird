"""The dead-man ping: an HTTP ``GET`` every interval while the service is healthy.

``OVENBIRD_NOTIFY_DEADMAN_URL`` (``https`` unless ``_DEADMAN_ALLOW_HTTP``) and
``_INTERVAL_S``. Healthy is what :meth:`ovenbird.trial.supervision.Supervision.healthy_reason`
says; when the service stops, hangs, loses the pump or stops writing history, the
pings stop and the external service alerts. The URL never appears in the status or
the logs (only its host).
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from typing import Any

from ovenbird.notify.transport import HttpRequest, NotifyError, Transport, host_of

LOGGER = logging.getLogger("ovenbird.notify")


class DeadmanPing:
    """The dead-man ping's URL, interval and outcome.

    Parameters
    ----------
    url
        The dead-man URL (a secret); ``None`` when it is not configured.
    interval_s
        Seconds between pings.
    """

    def __init__(self, url: str | None, interval_s: float) -> None:
        self.url = url
        self.interval_s = interval_s
        self.last_ok: str | None = None
        self.last_error: dict[str, Any] | None = None
        self.last_skip: str | None = None
        self.pings = 0

    @property
    def configured(self) -> bool:
        """Whether a dead-man URL is configured."""
        return self.url is not None

    def state(self) -> str:
        """Return ``not_configured``, ``skipped``, ``failing``, ``waiting`` or ``ok``."""
        if self.url is None:
            return "not_configured"
        if self.last_skip is not None:
            return "skipped"
        failed = (self.last_error or {}).get("at")
        last_ok = self.last_ok
        if failed is not None and (last_ok is None or failed > last_ok):
            return "failing"
        return "waiting" if self.last_ok is None else "ok"

    async def ping(
        self,
        transport: Transport,
        healthy: Callable[[], str | None] | None,
        now_iso: Callable[[], str],
        error_text: Callable[[BaseException], str],
    ) -> bool:
        """Ping the URL if the service is healthy; ``True`` when a ping succeeded.

        Parameters
        ----------
        transport
            HTTP transport.
        healthy
            Returns ``None`` while the service is healthy, else why not.
        now_iso
            Returns the service time as ISO 8601.
        error_text
            Returns a redacted, shortened error text.
        """
        if self.url is None:
            return False
        reason = healthy() if healthy is not None else None
        if reason is not None:
            self.last_skip = reason
            LOGGER.warning("dead-man ping skipped: %s", reason)
            return False
        self.last_skip = None
        try:
            status = await asyncio.to_thread(transport, HttpRequest("GET", self.url))
            if not 200 <= status < 300:
                raise NotifyError(f"HTTP {status}")
        except Exception as exc:
            error = error_text(exc)
            self.last_error = {"at": now_iso(), "error": error}
            LOGGER.warning("dead-man ping failed: %s", error)
            return False
        self.pings += 1
        self.last_ok = now_iso()
        return True

    def status(self, reason: str | None) -> dict[str, Any]:
        """Return the ``deadman`` part of the notification status (``reason``: unhealthy)."""
        return {
            "configured": self.configured,
            "server": host_of(self.url),
            "interval_s": self.interval_s,
            "pings": self.pings,
            "last_ok": self.last_ok,
            "last_error": self.last_error,
            "last_skip": self.last_skip,
            "healthy": reason is None,
            "unhealthy_reason": reason,
        }
