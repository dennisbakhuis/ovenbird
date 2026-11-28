from importlib.metadata import version

from ovenbird_sim import __version__


def test_import() -> None:
    """The package exposes the installed distribution version."""
    assert __version__ == version("ovenbird-sim")
