"""Single-instance lock on the data directory and the liveness probe used by ``--check``.

The running service holds an exclusive ``flock`` on ``<data_dir>/ovenbird.lock``
(so two instances never write the same ``history.db``) and, once HTTP is up, writes
the address of its health endpoint into the file. ``--check`` uses the lock to tell
whether a service runs: if none does it is a fast self-check, otherwise it probes
the liveness endpoint.
"""

from __future__ import annotations

import contextlib
import fcntl
import http.client
import ipaddress
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Final

LOCK_NAME: Final = "ovenbird.lock"
HEALTH_PATH: Final = "/api/v1/health"
PROBE_TIMEOUT_S: Final = 3.0


class AlreadyRunningError(RuntimeError):
    """Another service instance holds the data directory."""


@dataclass(frozen=True, slots=True)
class Endpoint:
    """Where the running service answers HTTP.

    Parameters
    ----------
    host, port
        Address to connect to.
    """

    host: str
    port: int


def probe_host(bind_host: str) -> str:
    """Return the address to probe for a bind address (wildcards map to loopback)."""
    host = bind_host.strip().strip("[]")
    if not host:
        return "127.0.0.1"
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return host
    if address.is_unspecified:
        return "::1" if address.version == 6 else "127.0.0.1"
    return host


class InstanceLock:
    """Exclusive lock on a data directory.

    Parameters
    ----------
    data_dir
        Directory to lock; created when missing.
    """

    def __init__(self, data_dir: Path) -> None:
        self.path = data_dir / LOCK_NAME
        self._fd: int | None = None

    def acquire(self) -> None:
        """Take the lock.

        Raises
        ------
        AlreadyRunningError
            When another process holds it.
        """
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(self.path, os.O_RDWR | os.O_CREAT, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            os.close(fd)
            raise AlreadyRunningError(
                f"another ovenbird instance uses {self.path.parent}"
            ) from None
        os.ftruncate(fd, 0)
        self._fd = fd

    def record_endpoint(self, endpoint: Endpoint) -> None:
        """Record the health endpoint for ``--check``."""
        if self._fd is None:
            return
        data = json.dumps({"pid": os.getpid(), "host": endpoint.host, "port": endpoint.port})
        os.ftruncate(self._fd, 0)
        os.pwrite(self._fd, data.encode("utf-8"), 0)

    def release(self) -> None:
        """Clear and release the lock."""
        fd, self._fd = self._fd, None
        if fd is None:
            return
        with contextlib.suppress(OSError):
            os.ftruncate(fd, 0)
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def running_endpoint(data_dir: Path) -> tuple[bool, Endpoint | None]:
    """Find out whether a service holds ``data_dir`` and where it answers.

    Parameters
    ----------
    data_dir
        Data directory of the service.

    Returns
    -------
    tuple
        ``(running, endpoint)``; ``endpoint`` is ``None`` while the service has not
        published one yet (still starting) or when none runs.
    """
    path = data_dir / LOCK_NAME
    try:
        fd = os.open(path, os.O_RDONLY)
    except OSError:
        return False, None
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_SH | fcntl.LOCK_NB)
        except BlockingIOError:
            pass
        else:
            fcntl.flock(fd, fcntl.LOCK_UN)
            return False, None
        raw = os.pread(fd, 4096, 0)
    finally:
        os.close(fd)
    try:
        data = json.loads(raw.decode("utf-8"))
        return True, Endpoint(str(data["host"]), int(data["port"]))
    except ValueError, KeyError, TypeError:
        return True, None


def probe_live(endpoint: Endpoint, timeout: float = PROBE_TIMEOUT_S) -> bool:
    """Whether the health endpoint answers with ``"live": true``."""
    conn = http.client.HTTPConnection(endpoint.host, endpoint.port, timeout=timeout)
    try:
        conn.request("GET", HEALTH_PATH, headers={"Accept": "application/json"})
        response = conn.getresponse()
        if response.status != http.client.OK:
            return False
        body = json.loads(response.read(65536))
    except OSError, ValueError, http.client.HTTPException:
        return False
    finally:
        conn.close()
    return isinstance(body, dict) and body.get("live") is True
