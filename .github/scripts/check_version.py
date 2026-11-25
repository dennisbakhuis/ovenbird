"""Fail when the service package version and the add-on manifest version differ."""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PACKAGE_INIT = ROOT / "packages/service/src/ovenbird/__init__.py"
ADDON_CONFIG = ROOT / "app/ovenbird/config.yaml"


def read_version(path: Path, pattern: str) -> str:
    """Return the first capture group of ``pattern`` found in ``path``."""
    match = re.search(pattern, path.read_text(encoding="utf-8"), re.MULTILINE)
    if match is None:
        sys.exit(f"no version found in {path.relative_to(ROOT)}")
    return match.group(1)


def main() -> None:
    """Compare both versions and exit non-zero on a mismatch."""
    package = read_version(PACKAGE_INIT, r'^__version__\s*=\s*"([^"]+)"')
    addon = read_version(ADDON_CONFIG, r'^version:\s*"?([^"\s]+)"?\s*$')
    if package != addon:
        sys.exit(f"version mismatch: {PACKAGE_INIT.name}={package} config.yaml={addon}")
    print(f"versions match: {package}")


if __name__ == "__main__":
    main()
