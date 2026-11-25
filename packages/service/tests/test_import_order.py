"""Every service module imports on its own, whatever was imported before it."""

from __future__ import annotations

import pkgutil
import subprocess
import sys

import ovenbird

SCRIPT = """
import importlib
import sys

failed = []
for name in sys.argv[1:]:
    for loaded in [key for key in sys.modules if key == "ovenbird" or key.startswith("ovenbird.")]:
        del sys.modules[loaded]
    try:
        importlib.import_module(name)
    except Exception as exc:
        failed.append(f"{name}: {exc!r}")
print("\\n".join(failed))
"""


def test_every_module_imports_first() -> None:
    names = sorted(
        info.name for info in pkgutil.walk_packages(ovenbird.__path__, prefix="ovenbird.")
    )
    result = subprocess.run(  # noqa: S603
        [sys.executable, "-c", SCRIPT, *names],
        capture_output=True,
        text=True,
        check=True,
        timeout=300,
    )
    assert result.stdout.strip() == ""
