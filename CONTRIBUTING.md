# Contributing

Thanks for helping with ovenbird. The design and phase plan live in [docs/design.md](docs/design.md).

## Development setup

Requires [uv](https://docs.astral.sh/uv/) and, for the dev stack, Docker.

```fish
make sync
make install-hooks
make test
```

`make sync` runs `uv sync --all-packages`; the workspace members (`packages/*`, `capture`)
are only installed with `--all-packages`, so use that when you call uv directly.

Other useful targets: `make lint`, `make format`, `make typecheck`, `make dev-up`,
`make image-check`. Run `make help` for the full list.

## Conventions

- Python 3.14, managed with uv; run everything through `uv run`.
- ruff (lint and format), mypy strict and pytest must pass; CI enforces them.
- numpy-style docstrings on all functions, classes and methods.
- No inline comments in Python; use clear names and structure. Comment only genuinely
  non-obvious algorithmic reasoning.
- Pin third-party GitHub Actions to full commit SHAs.
- Keep `packages/core` free of I/O.
- Add a `CHANGELOG.md` entry under Unreleased for user-visible changes.

## Commits and pull requests

- Small, focused commits with imperative messages.
- No AI-attribution trailers (such as `Co-Authored-By`) are required or expected.
- Fill in the pull request template.

## Safety

This software controls physical equipment. Changes to anything that writes to the heat pump
must come with tests covering clamps, allowlists and failure paths.
