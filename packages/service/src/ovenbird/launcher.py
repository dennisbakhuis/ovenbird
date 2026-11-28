"""Container entrypoint: repair data directory ownership as root, then drop privileges.

The image starts as root because a Home Assistant app gets ``/data`` (and the
Supervisor's ``options.json`` in it) owned by root. ``python -m ovenbird.launcher``
never runs the service as root:

* started as a non-root user (``docker run --user 10001:10001``, Kubernetes
  ``runAsUser``) it execs the service unchanged, with no root phase at all;
* started as root it first makes every entry of the data directory that is not
  owned by the service user (``OVENBIRD_UID``/``OVENBIRD_GID``, default 10001)
  owned by it (only when starting the service, never for ``--check`` or
  ``--version``; nothing is touched when the ownership is already right), then
  drops to that user without supplementary groups, verifies root cannot be
  regained and execs the service.

The ownership walk uses directory file descriptors and never follows symbolic
links, so a link planted in the data directory cannot redirect it.
"""

from __future__ import annotations

import logging
import os
import stat
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final

from ovenbird.config import DATA_DIR_ENV, DEFAULT_DATA_DIR

LOGGER = logging.getLogger("ovenbird.launcher")
UID_ENV: Final = "OVENBIRD_UID"
GID_ENV: Final = "OVENBIRD_GID"
DEFAULT_ID: Final = 10001
ROOT: Final = 0
NO_REPAIR_FLAGS: Final = frozenset({"--check", "--version", "-h", "--help"})
SERVICE_MODULE: Final = "ovenbird"


class LauncherError(RuntimeError):
    """The launcher cannot start the service safely."""


def _chown(path: str, uid: int, gid: int, *, dir_fd: int | None) -> None:
    """Change the owner of ``path`` (relative to ``dir_fd``) without following a symlink.

    Parameters
    ----------
    path
        Path to change.
    uid, gid
        New owner and group.
    dir_fd
        Directory descriptor ``path`` is relative to, ``None`` for the working directory.
    """
    os.chown(path, uid, gid, dir_fd=dir_fd, follow_symlinks=False)


def _lstat(path: str, *, dir_fd: int | None) -> os.stat_result:
    """Return the status of ``path`` (relative to ``dir_fd``) without following a symlink."""
    return os.stat(path, dir_fd=dir_fd, follow_symlinks=False)


def _cannot_regain_root() -> bool:
    """Return whether the process, after dropping privileges, can no longer become root."""
    try:
        os.setuid(ROOT)
    except PermissionError:
        return True
    return False


@dataclass(frozen=True, slots=True)
class System:
    """Operating-system calls the launcher uses (injectable for tests).

    Parameters
    ----------
    geteuid, getuid, getegid
        Identity queries.
    setgroups, setgid, setuid
        Privilege changes.
    chown, lstat
        Ownership change and lookup relative to a directory descriptor, without
        following symbolic links.
    cannot_regain_root
        Whether switching back to root fails (it must after dropping).
    execv
        Replaces the process.
    """

    geteuid: Callable[[], int] = os.geteuid
    getuid: Callable[[], int] = os.getuid
    getegid: Callable[[], int] = os.getegid
    setgroups: Callable[[list[int]], None] = os.setgroups
    setgid: Callable[[int], None] = os.setgid
    setuid: Callable[[int], None] = os.setuid
    chown: Callable[..., None] = field(default=_chown)
    lstat: Callable[..., os.stat_result] = field(default=_lstat)
    cannot_regain_root: Callable[[], bool] = _cannot_regain_root
    execv: Callable[[str, list[str]], None] = os.execv


@dataclass(frozen=True, slots=True)
class Plan:
    """What the launcher does before exec'ing the service.

    Parameters
    ----------
    repair
        Fix the ownership of the data directory.
    drop
        Switch to the service user.
    """

    repair: bool
    drop: bool


def plan(euid: int, args: Sequence[str]) -> Plan:
    """Decide the root phase for a process with effective uid ``euid``.

    Parameters
    ----------
    euid
        Effective uid of the launcher.
    args
        Arguments passed through to the service.

    Returns
    -------
    Plan
        Non-root: nothing to do. Root: always drop; repair ownership only when the
        service itself starts (not for ``--check``, ``--version`` or ``--help``).
    """
    if euid != ROOT:
        return Plan(repair=False, drop=False)
    return Plan(repair=not NO_REPAIR_FLAGS.intersection(args), drop=True)


def target_ids(environ: dict[str, str] | os._Environ[str]) -> tuple[int, int]:
    """Return the service user's ``(uid, gid)`` from the environment.

    Raises
    ------
    LauncherError
        When an id is not a positive integer (the service never runs as root).
    """
    ids = []
    for name in (UID_ENV, GID_ENV):
        raw = environ.get(name, str(DEFAULT_ID)).strip()
        if not raw.isdigit() or int(raw) == ROOT:
            raise LauncherError(f"{name} must be a positive integer, not {raw!r}")
        ids.append(int(raw))
    return ids[0], ids[1]


def data_dir(environ: dict[str, str] | os._Environ[str]) -> Path:
    """Return the data directory (``OVENBIRD_DATA_DIR`` or ``/data``)."""
    raw = environ.get(DATA_DIR_ENV)
    return Path(raw) if raw else DEFAULT_DATA_DIR


def repair_ownership(root: Path, uid: int, gid: int, system: System | None = None) -> int:
    """Give ``root`` and everything below it to ``uid:gid``, without following links.

    Parameters
    ----------
    root
        Data directory; created (mode 0750) when missing.
    uid, gid
        Owner to set.
    system
        OS calls.

    Returns
    -------
    int
        Number of entries whose ownership was changed.
    """
    ops = system or System()
    root.mkdir(mode=0o750, parents=True, exist_ok=True)
    changed = 0
    for directory, dirnames, filenames, dir_fd in os.fwalk(root, follow_symlinks=False):
        if directory == str(root):
            info = os.stat(root, follow_symlinks=False)
            if not stat.S_ISDIR(info.st_mode):
                raise LauncherError(f"data directory {root} is not a directory")
            if (info.st_uid, info.st_gid) != (uid, gid):
                ops.chown(str(root), uid, gid, dir_fd=None)
                changed += 1
        for name in (*dirnames, *filenames):
            info = ops.lstat(name, dir_fd=dir_fd)
            if (info.st_uid, info.st_gid) != (uid, gid):
                ops.chown(name, uid, gid, dir_fd=dir_fd)
                changed += 1
    return changed


def drop_privileges(uid: int, gid: int, system: System | None = None) -> None:
    """Switch to ``uid:gid`` with no supplementary groups and verify it sticks.

    Raises
    ------
    LauncherError
        When the switch did not take effect or root could be regained.
    """
    ops = system or System()
    ops.setgroups([])
    ops.setgid(gid)
    ops.setuid(uid)
    if ops.getuid() != uid or ops.geteuid() != uid or ops.getegid() != gid:
        raise LauncherError("dropping privileges did not take effect")
    if not ops.cannot_regain_root():
        raise LauncherError("root could be regained after dropping privileges")


def launch(
    args: Sequence[str],
    environ: dict[str, str] | os._Environ[str],
    system: System | None = None,
) -> None:
    """Run the root phase if any, then exec ``python -m ovenbird <args>``.

    Parameters
    ----------
    args
        Arguments for the service.
    environ
        Process environment.
    system
        OS calls.

    Raises
    ------
    LauncherError
        When privileges cannot be dropped safely.
    """
    ops = system or System()
    steps = plan(ops.geteuid(), args)
    if steps.drop:
        uid, gid = target_ids(environ)
        if steps.repair:
            directory = data_dir(environ)
            try:
                changed = repair_ownership(directory, uid, gid, ops)
            except OSError as exc:
                LOGGER.error("cannot repair ownership of %s: %s", directory, exc)
            else:
                if changed:
                    LOGGER.warning(
                        "gave %d entries in %s to uid %d gid %d", changed, directory, uid, gid
                    )
        drop_privileges(uid, gid, ops)
    ops.execv(sys.executable, [sys.executable, "-m", SERVICE_MODULE, *args])


def main(argv: Sequence[str] | None = None) -> int:
    """Run the launcher; returns only when it fails.

    Parameters
    ----------
    argv
        Arguments for the service; defaults to ``sys.argv[1:]``.

    Returns
    -------
    int
        1 when the service could not be started safely.
    """
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    try:
        launch(list(sys.argv[1:] if argv is None else argv), os.environ)
    except (LauncherError, OSError) as exc:
        LOGGER.critical("ovenbird launcher: %s", exc)
        return 1
    return 1


if __name__ == "__main__":
    sys.exit(main())
