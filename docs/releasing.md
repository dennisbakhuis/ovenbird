# Releasing

The version has one source per ecosystem. Python code never spells it out: `ovenbird.__version__`
and `ovenbird_core.__version__` read the installed package metadata, and tests and snapshots
compare against that value.

## Where the literal remains

`.github/scripts/check_version.py` lists every place: the four `pyproject.toml` files, the
sim package's own `__init__.py` and smoke test, `app/ovenbird/config.yaml`,
`dev/config-seed.json`, `ui/package.json`, both lockfiles (`uv.lock`,
`ui/package-lock.json`) and three example bodies in `docs/api-v1.md`. The UI mock and the
Playwright suite import `ui/package.json`.

## Procedure

1. `make bump VERSION=x.y.z` rewrites all places, then refreshes `uv.lock` and
   `ui/package-lock.json` offline.
2. `make lint typecheck api-check golden-check test` and `python3 .github/scripts/check_version.py`.
3. Add the changelog entries (`CHANGELOG.md`, `app/ovenbird/CHANGELOG.md`), commit, tag.

CI runs `check_version.py` first and fails when any place disagrees with
`packages/service/pyproject.toml`.
