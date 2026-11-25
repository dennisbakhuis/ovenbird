# Architecture

How the code is organised, where a feature lives in each layer, and which safety nets
guard a refactor. The behaviour is described in [design.md](design.md); the HTTP contract
in [api-v1.md](api-v1.md).

## Packages and dependency direction

```
core  <-  service
core  <-  sim
harness  ->  core, service, sim
```

| Package | Import name | Role |
| --- | --- | --- |
| `packages/core` | `ovenbird_core` | Pure domain logic: the control algorithm (`control/`), HeishaMon parsing, inputs, readings, store. No I/O, no clock, no network. |
| `packages/service` | `ovenbird` | The asyncio service: MQTT, SQLite history, config store, REST and WebSocket API, notifications, weather, learner glue. |
| `packages/sim` | `ovenbird_sim` | Plant model and identification, open-loop run, learning, evaluation, the simulated HeishaMon. Depends on `core` only. |
| `packages/harness` | `ovenbird_harness` | Stepped closed-loop runs of the whole service on the simulated plant, invariants, fault scenarios, the golden decision log. Depends on all of the above. |
| `ui/` | | Svelte 5 UI. Talks to the service through `api/v1` only. |

Rules:

- `core` never imports from `service`, `sim` or `harness`.
- `service` and `sim` never import each other.
- Nothing imports `harness` except its own tests and `make` targets.

Old module paths that were moved keep working through re-exports for one round.
`packages/service/tests/test_old_paths.py` checks them.

## Feature map

A feature has one home per layer. Names follow the feature.

| Layer | Where |
| --- | --- |
| Core | `packages/core/src/ovenbird_core/control/<feature>.py` |
| Service | `packages/service/src/ovenbird/<feature>/` (settings in `<feature>/settings.py`, config validation in `config/validation/`) |
| API | `packages/service/src/ovenbird/api/<feature>_api.py` |
| Config fields | `packages/service/src/ovenbird/configstore/fields.py` |
| UI components | `ui/src/components/<feature>/` |
| UI lib | `ui/src/lib/<feature>/` (shared code in `lib/core/`) |
| i18n | `ui/src/lib/i18n/en/<page>.ts` and `nl/` (strings are per page, not per feature) |
| Tests | next to the code; see the worked example |

Feature packages in the service: `config`, `stove`, `trial`, `notify`, `pump`, `system`,
`weather`, `insight`, `control` (with `control/adapter/`), `history`, `configstore`.
UI component folders: `activity`, `charts`, `hold`, `home`, `house`, `insight`, `pump`,
`setpoint`, `settings`, `shadow`, `shell`, `stove`, `system`, `trial`, `weather`, plus the
shared `ui/`, `help/`, `brand/` and `art/`.

### Worked example: wood stove

| Piece | Path |
| --- | --- |
| Core: state machine, back-off, entry and exit rules | `packages/core/src/ovenbird_core/control/stove.py` |
| Core: how it enters the setpoint | `control/ovenbird.py`, `control/terms.py`, `control/notes.py` |
| Core settings: `StoveConfig` (defaults, ranges, units, descriptions) | `control/stove.py` (re-exported by `control/config.py`) |
| Service settings (`control_stove_*`, built from `StoveConfig`) and the mapping to it | `ovenbird/stove/settings.py` |
| Service: manual request, session, journal code | `packages/service/src/ovenbird/stove/request.py`, `session.py` |
| Service: config validation | `ovenbird/stove/validation.py`, `config/validation/` |
| Service: notification text | `ovenbird/notify/text.py` |
| API: `POST control/stove` | `ovenbird/api/control_api.py` |
| Config fields and schema | `configstore/fields.py`, group `stove` |
| UI components | `ui/src/components/stove/StoveBanner.svelte`, `StoveStart.svelte` |
| UI lib | `ui/src/lib/stove/stove.ts` |
| i18n | `ui/src/lib/i18n/en/home.ts`, `settings.ts`, `fields.ts` (and `nl/`) |
| Fault scenario | `packages/harness/src/ovenbird_harness/faults/stove.py` |
| Tests | `packages/core/tests/control/test_stove.py`, `packages/service/tests/test_control_stove.py`, `packages/sim/tests/evaluate/test_openloop_stove.py`, `ui/src/lib/stove/stove.test.ts`, `ui/src/lib/core/mockStove.test.ts`, `ui/e2e/stove.spec.ts` |
| Decision | [decisions/2026-11-18-stove-episode-cap.md](decisions/2026-11-18-stove-episode-cap.md) |

## Adding a feature

1. Pure rules go in a core module under `control/`. Take plain values in, return plain
   values out. Declare each setting once on the feature's configuration dataclass with
   `ovenbird_core.setting.setting(default, ge=, le=, unit=, doc=)` (in the feature's
   module, or `control/config.py`) and call `check_settings(self)` in `__post_init__`;
   write out only the cross-field rules.
2. Service glue goes in a new package `ovenbird/<feature>/`. Its settings go in
   `<feature>/settings.py` as a `FeatureSettings` model whose fields mirror the core
   settings with `core_field(Config, "name")` (explicit annotation, no repeated default
   or bound), combined into `Settings` in `config/settings.py` (bases in reverse field
   order). `test_settings_fromcore.py` checks types and coverage. Config validation goes
   in `config/validation/`, one module per feature.
3. Add config fields to `configstore/fields.py` with a group, tier and help key (the unit
   of a core-backed field comes from core).
4. Add an API router `api/<feature>_api.py` with module-level handlers and a small
   dependency object. Register it in `api/app.py`. Document it in `api-v1.md`.
5. Run `make ui-fixtures` so the UI mock sees the new fields.
6. UI: components in `components/<feature>/`, logic in `lib/<feature>/`, strings in
   `lib/i18n/en/` and `nl/`. Add the new folder names to the lists in
   `ui/src/lib/core/structure.test.ts`. Use the primitives in `components/ui/`.
7. Add a core test, a service test, a UI unit test and, for a user flow, a Playwright spec.
8. If the feature changes decisions, run `make golden-check`; regenerate with
   `make golden` only for an intended change.
9. Add a `CHANGELOG.md` entry. Record an owner decision in `docs/decisions/`.

## Safety nets

| Net | What it catches | How to run |
| --- | --- | --- |
| Golden decision log | Any change in the decisions (whole records with the controller state), command events, alarm transitions or persisted state of the full-run, the fault sweep, the golden drills (defrost and DHW holds, manual setpoint and boost, latched hold across a restart, go-live restore) or the open-loop run. The synthetic streams are committed in `packages/harness/tests/golden/`; the real-data streams (the open-loop run on the recorded capture) live next to the local captures in `$CAPTURES_DIR/golden-real/` (default `capture/captures`, git-ignored) and are written and checked only where that capture exists. CI and a fresh clone check the synthetic streams and say that the real ones were skipped. | `make golden-check`; `make golden` to accept a deliberate change |
| Harness full-run and fault sweep | Invariant violations in the closed loop and under injected faults. | `make fullrun`, `make fullrun-faults`, `make fullrun-replay` |
| Old-path shim test | A moved module that no longer re-exports. | `make test` |
| Fixture sync | UI mock fixtures drifting from the service. `test_ui_fixtures.py` fails when `packages/service/tests/fixtures/ui/` and `ui/mock/fixtures/` differ. | `make ui-fixtures` |
| Theme test | A `var(--x)` without a definition, a missing dark-mode token, a colour literal in a `<style>` block. `ui/src/lib/core/theme.test.ts`. | `make ui-check` |
| Primitives guard | A raw `<button>`, `<input>`, `<select>`, `<textarea>` or `class="card"` outside `components/ui/`. `ui/src/lib/core/primitives.test.ts`. | `make ui-check` |
| Structure guard | A file loose in `components/` or `lib/`, or an unknown folder. `ui/src/lib/core/structure.test.ts`. | `make ui-check` |
| Mock drift tests | The mock server diverging from the API shapes. `mockDrift.test.ts`, `mockShapes.test.ts`, `mockFidelity.test.ts`. | `make ui-check` |
| Playwright | Routes and user flows in the browser. | `make ui-e2e` |

Slow tests carry the `slow` marker. `make test-fast` skips them; `make test` runs all.
CI runs the full set.
