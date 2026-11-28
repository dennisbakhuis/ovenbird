"""Check that every place that spells out the release version agrees, or rewrite them all.

``check_version.py`` exits non-zero when a place differs from the service package
version in ``packages/service/pyproject.toml``. ``check_version.py --set X.Y.Z``
rewrites every place (``make bump VERSION=X.Y.Z`` wraps it). Python packages read
their version from installed metadata, so only the manifests, lockfiles and a few
fixed documentation examples spell it out.
"""

import re
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REFERENCE = "packages/service/pyproject.toml"
SEMVER = re.compile(r"\d+\.\d+\.\d+")


@dataclass(frozen=True)
class Place:
    """A file and the pattern whose first group is a version string.

    Parameters
    ----------
    path
        File path relative to the repository root.
    pattern
        Multiline regular expression; group 1 is the version.
    optional
        When true, a file without any match is accepted.
    """

    path: str
    pattern: str
    optional: bool = False


PLACES = (
    Place("packages/core/pyproject.toml", r'^version\s*=\s*"([^"]+)"'),
    Place("packages/harness/pyproject.toml", r'^version\s*=\s*"([^"]+)"'),
    Place("packages/service/pyproject.toml", r'^version\s*=\s*"([^"]+)"'),
    Place("packages/sim/pyproject.toml", r'^version\s*=\s*"([^"]+)"'),
    Place("app/ovenbird/config.yaml", r'^version:\s*"?([^"\s]+)"?\s*$'),
    Place("dev/config-seed.json", r'"app_version":\s*"([^"]+)"'),
    Place("ui/package.json", r'^  "version":\s*"([^"]+)"'),
    Place("ui/package-lock.json", r'"name": "ovenbird-ui",\s*"version": "([^"]+)"'),
    Place("uv.lock", r'^name = "ovenbird(?:-core|-harness|-sim)?"\nversion = "([^"]+)"'),
    Place("docs/api-v1.md", r'"live": true, "ready": true, "version": "([^"]+)"'),
    Place("docs/api-v1.md", r'"ovenbird_config": 1, "app_version": "([^"]+)"'),
    Place("docs/api-v1.md", r'\{"version": "([^"]+)", "api_version": 1'),
)


def matches(place: Place) -> list[re.Match[str]]:
    """Return the matches of ``place`` in its file; exit when a required one is missing."""
    text = (ROOT / place.path).read_text(encoding="utf-8")
    found = list(re.finditer(place.pattern, text, re.MULTILINE))
    if not found and not place.optional:
        sys.exit(f"no version found in {place.path}")
    return found


def reference_version() -> str:
    """Return the version declared by the service package."""
    first = matches(PLACES[2])[0]
    return first.group(1)


def check() -> None:
    """Exit non-zero when any place differs from the reference version."""
    expected = reference_version()
    wrong = [
        f"{place.path}={found.group(1)}"
        for place in PLACES
        for found in matches(place)
        if found.group(1) != expected
    ]
    if wrong:
        sys.exit(f"version mismatch (expected {expected}): " + ", ".join(wrong))
    print(f"versions match: {expected}")


def rewrite(version: str) -> None:
    """Write ``version`` into every place."""
    if not SEMVER.fullmatch(version):
        sys.exit(f"not a version of the form X.Y.Z: {version}")
    for path in dict.fromkeys(place.path for place in PLACES):
        file = ROOT / path
        text = file.read_text(encoding="utf-8")
        for place in (p for p in PLACES if p.path == path):
            text = re.sub(
                place.pattern,
                lambda m: m.group(0).replace(m.group(1), version),
                text,
                flags=re.MULTILINE,
            )
        file.write_text(text, encoding="utf-8")
    print(f"version set to {version}")


def main(argv: list[str]) -> None:
    """Run the check, or the rewrite when ``--set VERSION`` is given."""
    if len(argv) == 3 and argv[1] == "--set":
        rewrite(argv[2])
        check()
    elif len(argv) == 1:
        check()
    else:
        sys.exit("usage: check_version.py [--set X.Y.Z]")


if __name__ == "__main__":
    main(sys.argv)
