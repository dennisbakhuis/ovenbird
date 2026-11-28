"""HTTP for notifications: one request type and the stdlib transport.

All HTTP goes through a :data:`Transport` (stdlib ``urllib`` by default, only
``http``/``https``, redirects are not followed); tests pass a fake.
"""

from __future__ import annotations

import urllib.request
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Final
from urllib.parse import urlsplit

from ovenbird import __version__

TIMEOUT_S: Final = 10.0


@dataclass(frozen=True, slots=True)
class HttpRequest:
    """One outgoing HTTP request.

    Parameters
    ----------
    method
        ``GET`` or ``POST``.
    url
        Full URL (``http`` or ``https``).
    body
        Request body.
    headers
        Request headers.
    """

    method: str
    url: str
    body: bytes | None = None
    headers: Mapping[str, str] | None = None


type Transport = Callable[[HttpRequest], int]


class NotifyError(Exception):
    """Sending failed (transport error or a non-2xx status)."""


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Redirect handler that never follows a redirect."""

    def redirect_request(
        self, req: Any, fp: Any, code: int, msg: str, headers: Any, newurl: str
    ) -> None:
        """Refuse every redirect.

        Parameters
        ----------
        req
            Original request.
        fp
            Response file.
        code
            Redirect status code.
        msg
            Status message.
        headers
            Response headers.
        newurl
            Redirect target.
        """
        return None  # noqa: RET501


OPENER: Final = urllib.request.build_opener(_NoRedirect)


def urllib_transport(request: HttpRequest) -> int:
    """Send ``request`` with the standard library (redirects not followed); returns the status.

    Raises
    ------
    NotifyError
        For a URL that is not ``http``/``https``.
    OSError
        For network errors and HTTP error statuses (a redirect included).
    """
    if urlsplit(request.url).scheme not in {"http", "https"}:
        raise NotifyError("only http and https URLs are used")
    headers = {"User-Agent": f"ovenbird/{__version__}", **dict(request.headers or {})}
    req = urllib.request.Request(  # noqa: S310
        request.url, data=request.body, headers=headers, method=request.method
    )
    with OPENER.open(req, timeout=TIMEOUT_S) as response:
        response.read(4096)
        return int(response.status)


def host_of(url: str | None) -> str | None:
    """Return the host of ``url`` (for the status: never the path, topic or token)."""
    if url is None:
        return None
    return urlsplit(url).hostname
