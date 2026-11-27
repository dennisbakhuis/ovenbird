# dev

Docker compose dev stack, fully simulated: Mosquitto (anonymous, host port 1884), the
**simulated HeishaMon** (`ovenbird_sim.heishamon`: the fitted plant model behind
HeishaMon's MQTT behaviour) and ovenbird in `auto` mode driving it. Home Assistant
(port 8123, config in `dev/ha-config/`, gitignored except `configuration.yaml`) is
optional: `COMPOSE_PROFILES=ha make dev-up`.

```fish
make dev-up
make dev-logs
make dev-down
```

ovenbird listens on `127.0.0.1:8099` (user `admin`, password `ovenbird-dev` unless
`OVENBIRD_ADMIN_PASSWORD` is set). Useful endpoints: `api/v1/decisions/latest` (control
status, alarms, adapter counters), `api/v1/decisions`, `api/v1/commands`,
`api/v1/history?signals=room_temperature,main/Z1_Water_Target_Temp`.

## Simulation

`heishamon-sim` is built from the root `Dockerfile` (target `heishamon-sim`; the
production image does not contain it). It publishes `panasonic_heat_pump/main/*` on
change every simulated 5 s with a full retained dump every 300 s, `stats` and LWT like
the firmware, applies `SetCurves`, `SetZ1HeatRequestTemperature`, `SetMaxPumpDuty` and
`SetQuietMode` with HeishaMon's parsing (integer parsing, no range check, effect on the next
query cycle, no echo) in Direct mode, and publishes the room temperature on
`climate_manager_capture/room_temp`. It refuses any broker other than local ones.

| Variable | Default | |
|---|---|---|
| `SIM_SPEED` | `60` | simulated seconds per second (also ovenbird's clock speed) |
| `SIM_START` | `2026-01-06` | simulated start date (UTC midnight; also ovenbird's clock start); a day of your recorded weather when `capture/captures/weather` holds one |
| `SIM_SCENARIO` | `recorded` | `recorded` (Open-Meteo cache in `capture/captures/weather/`) or `cold-week` (synthetic, no local data) |
| `SIM_PARAMS` | empty | empty for the built-in example house; `/sim/models/plant_params.json` for a plant fitted on a local recording (`capture/captures/models/`) |

Without local data: `SIM_SCENARIO=cold-week make dev-up`.

The recorded weather ends where the Open-Meteo cache ends. By default
(`--at-end stop`) the simulator then logs one line (`recorded weather ends at ...: the
simulated HeishaMon stops`), publishes `LWT` `Offline` (retained), disconnects and
idles: ovenbird sees HeishaMon go away and refuses (`heishamon_dead`), and the
container's restart policy does not start the simulation over from `SIM_START`. With
`--at-end loop` the recording repeats from its first hour (a jump in outside
temperature at each wrap); for the compose stack add it to the `heishamon-sim` command
in `docker-compose.yml`, or refresh the weather cache and restart with a later
`SIM_START`.

ovenbird runs with `OVENBIRD_CONTROL_MODE=auto`, `OVENBIRD_ALLOW_COMMANDS=true`,
`OVENBIRD_COMMAND_BROKERS=mosquitto:1883`, `OVENBIRD_SIMULATION=true` (required for a
scaled clock to publish; it only accepts a loopback or `mosquitto` broker and publishes
only while HeishaMon reports simulated firmware) and a clock running at `SIM_SPEED` from
`SIM_START` (`OVENBIRD_CLOCK_START` overrides it, e.g. to resume after an ovenbird
restart), so its 60 s tick, dwell times and command spacing follow simulated time. The
two containers start their clocks independently; expect them to differ by a few
simulated minutes. Set `OVENBIRD_CONTROL_MODE=shadow` to watch decisions without
commands, or pause a running stack (nothing is sent until you resume) and resume it:

```fish
set api curl -u admin:ovenbird-dev -H 'Content-Type: application/json' -H 'X-Ovenbird-Request: 1'
$api -d '{"reason": "watching"}' http://127.0.0.1:8099/api/v1/control/pause
$api -d '{}' http://127.0.0.1:8099/api/v1/control/resume
```

The stack runs the **example profile** (`docs/design.md`): comfort 21.5 °C (stored, half a
kelvin above the 21.0 °C default so the UI shows a stored value) on the simulated room topic, emitter `mixed`, minimum water setpoint 24 °C, `on_change` room profile with
the humidity as liveness signal, pump duty 159 heating / 102 idle, a heated floor area of
130 m² (for the insulation score); the simulator starts the room at `SIM_ROOM_C` (21.5).
These control values are not environment variables: they come from the configuration seed `dev/config-seed.json`, which becomes version 1 of
the configuration store (`config.db` in the `ovenbird-data` volume) on a fresh volume, so
they are editable in the UI and through `api/v1/config`. The environment keeps only the
publish gates, connections, credentials, the clock and `OVENBIRD_CONTROL_MODE` (the mode
ceiling). Another seed: `OVENBIRD_SEED_FILE=path/to/export.json make dev-up` on a fresh
volume (`make dev-down` plus `docker volume rm ovenbird-dev_ovenbird-data`); an operate
token for API tests: `OVENBIRD_OPERATE_TOKEN` (at least 32 characters).
`make dev-check` (`dev/check_sim.py`) asserts decisions under room feedback, verified
commands, no failed commands, no alarm raised or active (`--allow-alarm CODE` to accept
one, `--from ISO` to check a window), health ready with `alarms` ok, every safety monitor
`ok` and the room within 21.5 ± 0.7 °C with a mean within ±0.3 K.

The simulator keeps the pump registers in the `heishamon-sim-state` volume
(`/state/registers.json`, owned by a one-shot `heishamon-sim-state` container), so a
restarted simulator comes back with the setpoint and pump duty it had, like a real pump.

## Fault injection

The simulator listens on `heishamon_sim/inject/#` (simulator only, never a HeishaMon
topic):

| Topic | Payload | Effect |
|---|---|---|
| `heishamon_sim/inject/main/<Name>` | value, or empty to clear | override what `main/<Name>` reports (plant unaffected) |
| `heishamon_sim/inject/register/<field>` | integer | set a pump register (`heating_mode`, `direct_setpoint`, `max_pump_duty`, ...) |
| `heishamon_sim/inject/house/extra_heat_w` | watts (0–30000), `0` or empty to stop | heat from a wood stove: into the house air, and the sensor's room warms 0.6 K/kW faster than the house (the pump's thermostat follows the house) |
| `heishamon_sim/inject/clear` | anything | remove every override and the extra heat |

```fish
set pub docker compose -f dev/docker-compose.yml exec -T mosquitto mosquitto_pub
$pub -t heishamon_sim/inject/main/Pump_Flow -m 3.0          # low flow
$pub -t heishamon_sim/inject/main/Pump_Flow -n              # clear it
$pub -t heishamon_sim/inject/main/Error -m H62              # pump error
$pub -t heishamon_sim/inject/register/heating_mode -m 0     # compensation mode
$pub -t heishamon_sim/inject/house/extra_heat_w -m 6000     # light the wood stove
$pub -t heishamon_sim/inject/house/extra_heat_w -m 0        # put it out
$pub -t panasonic_heat_pump/commands/SetCurves -m '{"zone1":{"heat":{"target":{"high":300}}}}'  # wraps to 44 °C
curl -u admin:ovenbird-dev -H 'Content-Type: application/json' -H 'X-Ovenbird-Request: 1' \
    -d '{}' http://127.0.0.1:8099/api/v1/control/release-hold     # end a (latched) hold
```

## Replays

Stop the simulator before replaying a capture into the same broker (both publish
`panasonic_heat_pump/main/*`):

```fish
docker compose -f dev/docker-compose.yml stop heishamon-sim
make replay-fixture SPEED=60
```

`make replay-fixture` replays the committed two-hour synthetic HeishaMon slice
(`packages/core/tests/fixtures/synthetic/`, written by `make test-fixture` from the
simulated board in closed loop with ovenbird's own controller) with `stats` kept, so ovenbird sees the
heat pump as alive. In `auto` mode ovenbird's commands are applied by the replayer's
overlay; the replayed plant does not react to them. Point `make replay` at a capture of
your own (`CAPTURE=capture/captures/<name>`) for recorded data.

## Convert a recording into a history.db

`ovenbird_harness.convert` (harness package, one-off) turns a recorded capture period into
an ovenbird `history.db` that a local ovenbird opens like its own, so **System → Replay**
works on your recording. It writes the samples and rollups the service would have written
from the same inputs (also the 60 s rollups of `main/Z1_Water_Target_Temp`), one decision
per 60 s tick from ovenbird's controller driven over the recording like the open-loop
run (`ovenbird_sim.evaluate.openloop`, `make evaluate-open-loop`), and the recorded `SetCurves` / `SetMaxPumpDuty`
messages as `command` rows with the status `recorded` (not `sent` or `verified`: they were
sent by the controller that ran then, never by ovenbird). The room (Datalake or mirror) is
stored under the configured `control_room_signal`.

```fish
make convert-capture CF_FROM=2026-10-01 CF_TO=2026-10-08
make convert-capture CF_FROM=2026-10-01 CF_TO=2026-10-08 CONVERT_CONFIG=my-seed.json CONVERT_OUT=/tmp/replay-db
uv run python -m ovenbird_harness.convert --capture capture/captures/live \
    --datalake capture/captures/datalake --from 2026-10-01 --to 2026-10-08 \
    --config dev/config-seed.json --out /tmp/replay-db --config-version 1
```

`--config` is a configuration export in the format of `OVENBIRD_CONFIG_SEED` (default: the
service's default settings) and sets the controller; its `control_room_signal` must be the
signal of the recorded room sensor (`ha/<entity_id>`; a bare name such as the dev seed's
`room_temperature` is stored as an MQTT input signal). `--out` receives `history.db` and the
effective `config-seed.json`; it refuses a non-empty `history.db` unless `--force` and the
service's data directory. The run prints each day and the time per recorded day (about 2 s
and 3 MB per day on a laptop).

Start a local ovenbird on the result with the seed, as version 1 of its configuration, and
keep every row. The Replay identity check only compares decisions of the active
configuration version, hence `--config-version 1` above (without it the decisions carry no
version). The service deletes rows older than its retention at start, so set all
`history_*_days` to 0 (keep forever):

```fish
OVENBIRD_DATA_DIR=/tmp/replay-db OVENBIRD_CONFIG_SEED=/tmp/replay-db/config-seed.json \
OVENBIRD_HISTORY_RAW_DAYS=0 OVENBIRD_HISTORY_1M_DAYS=0 OVENBIRD_HISTORY_15M_DAYS=0 \
OVENBIRD_HISTORY_1H_DAYS=0 OVENBIRD_HISTORY_DECISION_DAYS=0 \
    uv run python -m ovenbird
```

Without Home Assistant or MQTT the instance stays in shadow on stale inputs; it only
serves the stored history. Open **System → Replay**, pick a window inside the converted
period and compare the replayed setpoint with the pump's recorded one. The replay is open
loop: the house followed the recorded control, so it shows what ovenbird would have decided,
not what it would have caused. The room freshness is decided by the open-loop run's policy
(`--room-max-age`, default 1800 s, pessimistic for a sensor that reports on change).
Home Assistant sensors other than the room (liveness signals) are not in the recording
stream, so they are not stored.

## House-model learner

The learner refits the house model on ovenbird's history and writes JSON that ovenbird
serves under `api/v1/insight/house` (see `docs/design.md`, House insight). The ovenbird
service runs it itself by default (the image carries numpy and scipy through the `learner`
extra; weekly at night and on request, see `packages/service/README.md`), so the simulated
stack needs nothing extra. The optional compose service `learner` (root `Dockerfile`
target `learner`) is only for running it in isolation: use it instead of the built-in
learner, with `house_learn_enabled` set to false, never next to it, because both write
`models/`:

```fish
COMPOSE_PROFILES=learner docker compose -f dev/docker-compose.yml up -d learner
docker compose -f dev/docker-compose.yml logs -f learner
```

It waits `LEARNER_DELAY_S` (300) after ovenbird is healthy, then runs every
`LEARNER_EVERY_H` hours (168, weekly) on the **wall clock**. It mounts two
sub-directories of the data volume and nothing else: `learner/` read-only at `/learner`
(ovenbird writes `learner-config.json` there and exports the history snapshot, written
every 6 real hours, as `history.snapshot.db`) and `models/` at `/models` (its output). It
runs as uid 10003 in ovenbird's group 10001, read-only, without capabilities or network;
it never sees `options.json`, `config.db` or the live history. It needs at least 22 days
of 1 min history before it promotes a first model; until then `insight/house` answers
`200` with `state` `learning` and what is missing. The production recipe (and a cron
alternative) is in `packages/service/README.md` (House-model learner).

Offline on a history database (the harness full run writes one to
`capture/captures/fullrun/plain/history.db`), with the harness example profile
`dev/learner-config.json` and the recorded weather instead of stored forecasts:

```fish
make learn WEATHER=capture/captures/weather FLOOR_AREA=150
make learn LEARN_HISTORY=path/to/history.snapshot.db LEARN_CONFIG=path/to/learner-config.json LEARN_MODELS=out/models
```

About 5 minutes for 40 days of history; `--building-only` (in `LEARN_ARGS`) skips the
heat-pump layer and is faster.
