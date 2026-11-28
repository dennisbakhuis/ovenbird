import re

from ovenbird_core import __version__


def test_import() -> None:
    """The package imports and reports a release version from its metadata."""
    assert re.fullmatch(r"\d+\.\d+\.\d+", __version__)
