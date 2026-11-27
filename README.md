# ovenbird

An open-source, standalone smart controller for air-to-water heat pumps. The first target is
Panasonic units behind a HeishaMon board, over MQTT. It runs next to Home Assistant rather than
inside it, and keeps running when Home Assistant restarts.

It sets the water target of the heat pump from a heating curve and a room-temperature
feedback term, inside safety limits that follow the outside temperature. It shows the
weather forecast. A house model learned from its history, refitted weekly inside the
service, proposes curve changes for you to review, shows what the house needs at a given
outside temperature and how the heat flows now, and can compute a bounded room-target shift
ahead of sun or cold in shadow, where it changes nothing. Every decision carries a plain-language explanation, and every decision
can be replayed on recorded data.

## Status

Pre-alpha. The whole system runs fully simulated, on a plant model fitted to recorded heat
pump traffic, and a new installation starts in shadow: it reads and decides but sends
nothing. It has not controlled a real pump yet; trials against a real pump come next.

## Repository layout

| Path | Purpose |
| --- | --- |
| `packages/core` | `ovenbird-core`: pure domain logic and the control algorithm, no I/O |
| `packages/service` | `ovenbird`: asyncio service (MQTT, storage, REST and WebSocket API), one package per feature |
| `packages/sim` | `ovenbird-sim`: model identification, open-loop run, learning, the simulated HeishaMon |
| `packages/harness` | `ovenbird-harness`: stepped closed-loop runs of the whole service on the simulated plant, invariants, fault scenarios, the golden decision log |
| `ui/` | Web UI (Svelte 5, TypeScript, Vite) |
| `capture/` | Live MQTT recorder, replayer and overview tooling |
| `app/` | Optional Home Assistant app wrapper |
| `custom_components/ovenbird/` | Planned: thin Home Assistant integration (placeholder) |
| `integration/` | Planned: HA-pinned integration tests (placeholder) |
| `dev/` | Docker compose dev stack |
| `docs/` | Documentation |

Dependency direction: `core` is imported by `service` and `sim`; `harness` uses all of them.
See [docs/architecture.md](docs/architecture.md).

## Quickstart

Requires [uv](https://docs.astral.sh/uv/) and Docker.

```fish
make sync       # uv sync --all-packages
make test       # full test suite
make dev-up     # simulated stack: mosquitto :1884, heishamon-sim, ovenbird :8099
make dev-check  # check the running stack through the API
make dev-down
```

The preview UI is served on `http://127.0.0.1:8099` with Basic auth `admin` / `ovenbird-dev`.
Home Assistant (:8123) is optional and only starts with `COMPOSE_PROFILES=ha make dev-up`.
UI development without a backend: `make ui-dev` (mock data).

## Main make targets

Run `make help` for all of them.

| Target | What it does |
| --- | --- |
| `test`, `test-fast` | Python tests; `test-fast` skips the slow ones |
| `lint`, `typecheck`, `format` | ruff and mypy strict |
| `ui-check`, `ui-e2e`, `ui-fixtures` | UI type check, lint and unit tests; Playwright; fixture sync |
| `fullrun`, `fullrun-faults`, `fullrun-replay` | Closed-loop harness runs over the recorded span |
| `golden`, `golden-check` | Write or verify the golden decision log |
| `test-fixture`, `ui-sim-fixtures` | Regenerate the synthetic capture slice and the simulated UI responses |
| `evaluate-identify`, `evaluate-open-loop`, `evaluate-counterfactual` | Fit the plant, run ovenbird open loop over the recording, compare ovenbird with the recorded setpoints on the fitted plant |
| `learn` | Refit the house model on a history database |
| `image-check` | Build the container image and smoke-test it |
| `shadow-check` | Read-only check of a deployed instance in shadow (`URL=`, password in `OVENBIRD_ADMIN_PASSWORD`) |

## Recorded data stays local

Tests, fixtures and the committed golden streams are synthetic: the simulated board on the
built-in example house and a synthetic cold week. Recordings of a real house (the MQTT
capture, Home Assistant states, weather, fitted models, and what is derived from them per
timestamp) live only in `capture/captures` (git-ignored; `CAPTURES_DIR` points elsewhere).
Where they are present, the extra real-data checks run as well: the replay tests' `recorded`
variants on `fixtures/live/`, and the real-data golden streams in `golden-real/`. Without
them (CI, a fresh clone) those checks are skipped and say so.

## Documentation

- [docs/README.md](docs/README.md): index of all documentation
- [docs/architecture.md](docs/architecture.md): packages, features, safety nets
- [docs/design.md](docs/design.md): the approved design
- [docs/api-v1.md](docs/api-v1.md): the HTTP and WebSocket contract
- [docs/deploy.md](docs/deploy.md): deploying the container, shadow first
- [docs/decisions/](docs/decisions/): owner decisions
- [ui/README.md](ui/README.md): UI primitives, tokens, tests
- [CONTRIBUTING.md](CONTRIBUTING.md), [SECURITY.md](SECURITY.md), [CHANGELOG.md](CHANGELOG.md)

## Credits

ovenbird builds on the work of others:

- [HeishaMon](https://github.com/heishamon/HeishaMon): the open-source board and firmware
  that connects Panasonic Aquarea heat pumps to MQTT. ovenbird talks to the pump through it.
- [HeishaMoNR](https://github.com/edterbak/HeishaMoNR) by Ed ter Bak: a Node-RED flow for
  HeishaMon that showed how far a heat pump can be tuned from outside the unit.

## License

Apache License 2.0, see [LICENSE](LICENSE).
