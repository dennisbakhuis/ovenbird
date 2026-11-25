"""Command line entrypoint for the ovenbird service.

``python -m ovenbird`` runs the service until SIGTERM/SIGINT.
``--check`` is the container health check: when a service holds the data
directory it probes the liveness endpoint (exit 0 only when ``live`` is true);
when none runs (image smoke test) it validates the settings and the installation
and exits 0. ``--version`` prints the version.
"""

import argparse
import asyncio
import logging
import os
import signal
import sys
from collections.abc import Sequence

from ovenbird import __version__
from ovenbird.config import ConfigError, Settings, load_settings
from ovenbird.configstore.store import MIGRATIONS_PACKAGE as CONFIG_MIGRATIONS
from ovenbird.history.schema import bundled_migrations
from ovenbird.instance import AlreadyRunningError, probe_live, running_endpoint
from ovenbird.service import build_service

LOGGER = logging.getLogger("ovenbird")
LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s %(message)s"


def build_parser() -> argparse.ArgumentParser:
    """Build the command line parser.

    Returns
    -------
    argparse.ArgumentParser
        Parser with ``--version`` and ``--check``.
    """
    parser = argparse.ArgumentParser(prog="ovenbird", description="ovenbird heat pump controller")
    parser.add_argument("--version", action="version", version=f"ovenbird {__version__}")
    parser.add_argument(
        "--check",
        action="store_true",
        help=(
            "health check: probe the running service's liveness endpoint, or validate the "
            "settings and installation when no service runs; exit 0 when healthy"
        ),
    )
    return parser


def run_check(settings: Settings) -> int:
    """Run the health check.

    Parameters
    ----------
    settings
        Validated settings.

    Returns
    -------
    int
        0 when healthy, 1 otherwise.
    """
    running, endpoint = running_endpoint(settings.data_dir)
    if not running:
        bundled_migrations()
        bundled_migrations(CONFIG_MIGRATIONS)
        LOGGER.info("ovenbird %s self-check ok (no service running)", __version__)
        return 0
    if endpoint is None:
        LOGGER.error("ovenbird is starting; its health endpoint is not recorded yet")
        return 1
    if probe_live(endpoint):
        LOGGER.info("ovenbird %s live at %s:%d", __version__, endpoint.host, endpoint.port)
        return 0
    LOGGER.error("ovenbird at %s:%d is not live", endpoint.host, endpoint.port)
    return 1


async def run_until_terminated(settings: Settings) -> None:
    """Run the service until SIGTERM or SIGINT is received."""
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for signum in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(signum, stop.set)
    try:
        await build_service(settings).run(stop)
    finally:
        for signum in (signal.SIGTERM, signal.SIGINT):
            loop.remove_signal_handler(signum)


def main(argv: Sequence[str] | None = None) -> int:
    """Run the service entrypoint.

    Parameters
    ----------
    argv : Sequence[str] or None
        Arguments to parse; defaults to ``sys.argv[1:]``.

    Returns
    -------
    int
        Process exit code: 0 on a clean stop or healthy check, 1 when unhealthy or
        failed, 2 for invalid settings.
    """
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=logging.INFO, format=LOG_FORMAT)
    try:
        settings = load_settings()
    except ConfigError as exc:
        LOGGER.error("invalid settings: %s", exc)
        return 2
    logging.getLogger().setLevel(settings.log_level)
    if args.check:
        return run_check(settings)
    LOGGER.info("ovenbird %s starting (control mode %s)", __version__, settings.control_mode)
    LOGGER.info("settings: %s", settings.summary())
    try:
        asyncio.run(run_until_terminated(settings))
    except AlreadyRunningError as exc:
        LOGGER.error("%s", exc)
        return 1
    except ConfigError as exc:
        LOGGER.error("invalid configuration: %s", exc)
        return 2
    except PermissionError as exc:
        LOGGER.error(
            "data directory %s is not writable by uid %d (%s); start the container as root "
            "so the launcher can fix its ownership, or give it to this uid",
            settings.data_dir,
            os.getuid(),
            exc.strerror or type(exc).__name__,
        )
        return 1
    except Exception as exc:
        LOGGER.critical("ovenbird failed: %s", exc, exc_info=exc)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
