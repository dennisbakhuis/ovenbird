# capture — record & replay HeishaMon MQTT traffic

Record the live heat pump (HeishaMon ↔ Mosquitto ↔ the existing controller) for
weeks, then replay those recordings into the local ovenbird dev stack
so ovenbird is developed against real behaviour without ever touching
the live system.

One container does the local shakedown, the discovery run and the weeks-long
recording on the NAS; only the env file differs.

```
capture/
├── src/climate_manager_capture/
│   ├── capture.py        capture format: JSONL per UTC day, gzip on rotation
│   ├── heishamon.py      pure model of the firmware's MQTT behaviour
│   ├── record.py         climate-manager-record        (read-only subscriber)
│   ├── replay.py         climate-manager-replay        (capture → dev broker)
│   ├── capture_info.py   climate-manager-capture-info  (stats + validation)
│   └── synthetic.py      climate-manager-capture-synthetic (test fixture)
├── Dockerfile, docker-compose.yml, .env.*.example
├── captures/             recordings (gitignored)
└── tests/
```

## What HeishaMon actually does on MQTT (why the tooling looks like this)

Observed on a live board and in recordings:

| Behaviour | Detail |
|---|---|
| Query cadence | pump polled every 5 s |
| `main/*` publishes | **only when a value changed**, plus a **full dump every 300 s** and once on first connect; retained, QoS 0 |
| `stats`, `LWT=Online` | every 5 s; `Online` is **not** retained |
| Will | `LWT=Offline`, **retained** → a fresh subscriber sees `Offline` first, then `Online` within 5 s |
| Commands | `commands/#`; payload read as its leading integer (no range check, `"21.5"`→21, text→0); 10-deep queue; **no echo**; the effect shows in `main/*` at the next 5 s query |
| `Outside_Temp` | integer °C — changes only a handful of times per hour |

The existing controller (here a Node-RED flow) publishes **only** `commands/*`. Its computed values and
state never reach the broker, and the room temperature/setpoint it uses come
from Home Assistant over websocket — hence the `climate_manager_capture/#`
mirror described below.

## Capture format

`captures/<name>/YYYY-MM-DD.jsonl` (active day, plain) and `.jsonl.gz` (closed
days). Every file starts with a header `{"v":1,...}`; each other line is

```json
{"t":1767225600.123,"k":"panasonic_heat_pump/main/Outside_Temp","p":"3","r":true}
```

`r` is set only when the broker delivered the message from its retained store
(initial flush / reconnect) — it does *not* mean the publisher used retain,
MQTT clears that flag on live deliveries. Replay decides retain by topic class.
`meta.json` records broker, filters and start time.

Size: ~220k messages/day ≈ 15–30 MB raw, 1–2 MB/day gzipped; two months ≈ 100–150 MB.

## Recording procedure

### 0. Read-only broker account (once, on the live Mosquitto)

```
mosquitto_passwd -b /etc/mosquitto/passwd recorder <password>
# acl file:
user recorder
topic read #
```

Verify: `mosquitto_sub -h the-main-broker -u recorder -P … -t 'panasonic_heat_pump/LWT' -C 2`
shows `Offline` then `Online`; a `mosquitto_pub` with that account must be refused.

### 1. Local shakedown (same container, dev broker)

```fish
make up; make sim-stateful          # in another shell
make recorder-build
make record ENV=.env.local          # copy from .env.local.example first
make record-logs
make capture-info CAPTURE=capture/captures/local
make record-stop
```

Expect the on-change + 300 s dump pattern, `LWT` `Offline`→`Online`, a healthy
container, and a clean exit with a flushed file.

### 2. Discovery (2 h, everything on the live broker)

```fish
cp capture/.env.nas.example capture/.env    # fill in host + password
make discover                                     # TOPICS='#', exits after 2 h
make capture-info CAPTURE=capture/captures/discovery ARGS=--catalogue
```

The catalogue lists every topic on the broker with counts and sample payloads.
Decide the filter; the default `panasonic_heat_pump/#,climate_manager_capture/#`
is right unless you want another device recorded too. `#` captures every
device on the broker, so keep the discovery capture short and local.

### 3. Mirror the HA-side inputs (live Home Assistant, publish-only)

The existing controller reads the room temperature from a Home Assistant sensor over
the HA websocket, not from MQTT; its room setpoint is a static value (nothing to
record). One automation on the live
HA publishes the sensor **retained** outside the HeishaMon base:

```yaml
alias: Climate Manager capture mirror
mode: queued
triggers:
  - trigger: state
    entity_id: sensor.living_room_temperature
    not_to: [unavailable, unknown]
    id: room_temp
actions:
  - action: mqtt.publish
    data:
      topic: "climate_manager_capture/{{ trigger.id }}"
      payload: "{{ trigger.to_state.state }}"
      retain: true
```

`sensor.living_room_temperature` stands for the room sensor the controller uses (use your
own entity id; see "Local settings" below for mapping it in the evaluations). Add a
trigger for **every** other HA entity the controller reads (outside-temperature override, humidity, production/consumption, …);
anything the controller gets from HA is invisible to the recorder otherwise. Verify
with `mosquitto_sub -t 'climate_manager_capture/#' -v` on the broker the
recorder uses — the live HA's MQTT integration is connected to a different
broker (the HA-side broker) that bridges to the main broker; check that the bridge
forwards this prefix.

### 4. Long run on the NAS

Copy this folder (or just `docker-compose.yml`, `.env`, and the image tarball
from `make recorder-save`) to the NAS, then:

```
PUID=$(id -u) PGID=$(id -g) docker compose up -d --build   # or: docker load < climate-manager-recorder.tar.gz
docker compose logs -f
```

Container Manager users: import `docker-compose.yml` as a project and set
`PUID`/`PGID` in the UI (or edit the `user:` line). The container is healthy
while `.heartbeat` is younger than two minutes; the recorder touches it every
30 s as long as the broker session is up, independent of `HEARTBEAT_SECONDS`
(which only paces the log line).

#### NAS via ssh

The image is built on the NAS (it may have another CPU architecture than the
laptop). Everything goes through `ssh $(NAS_HOST)` into `$(NAS_DIR)`; the Makefile
defaults are the placeholders `nas` and `/srv/ovenbird-recorder`, set your own on
the command line or in the local settings file (below):

```fish
make recorder-deploy      # tar capture/ (sources, compose, .env) over ssh, build + up -d, show status
make nas-status           # docker compose ps + last log lines
make nas-logs             # follow the logs
make capture-pull         # captures/live → capture/captures/live (NAME= for another capture)
make capture-info CAPTURE=capture/captures/live
```

`recorder-deploy` recreates the container, which shows up in the capture as a
retained burst and a few seconds gap. Notes for a NAS running DSM: `docker`
lives in `/usr/local/bin` and is not on the non-interactive PATH; DSM blocks
`rsync` and the SFTP subsystem for plain ssh accounts, so all copying is `tar`
over ssh (`scp -O` works too). The container runs as the ssh user's uid/gid and
the project is not visible as a Container Manager *project*, only as a container.

### 5. After 24 h

`make capture-info CAPTURE=capture/captures/live` should show

- yesterday's `.jsonl.gz` plus today's `.jsonl`
- ~144 distinct `main/*` topics, dump interval ≈ 300 s, `LWT=Online` cadence ≈ 5 s
- no unexplained gaps > 60 s (recorder restarts show as retained bursts)
- `commands/*` present with side-effect median latency ≤ 5 s
- `climate_manager_capture/*` present
- the `Δchg s` column for `main/Outside_Temp` — evidence for the smoothing follow-up

Repeat weekly with `make capture-pull`. Record until at least one
cold spell, some DHW cycles and several defrosts are covered; about two months
from early autumn spans the transition into the real heating season.

## Local settings (`captures/local.env`)

The tracked tree describes an example install only: Home Assistant entities such
as `sensor.living_room_temperature`, `sensor.living_room_humidity`,
`sensor.hall_temperature` and `sensor.bedroom_temperature`; example comfort,
minimum setpoint and pump duties; placeholder recorder host and directory; the
example house of the simulator. The values of the install a recording was made on
stay next to that recording, in `$(CAPTURES_DIR)/local.env` (default
`capture/captures/local.env`, git-ignored with the captures). Without the file
every default is the example one, as in CI or a fresh clone.

The file has `NAME = value` lines (`#` starts a comment line). The Makefile
includes it before its defaults, so a value there replaces a default (a value on
the command line still wins); the Python side reads it through
`ovenbird_sim.local`. Recognised names:

| Name | Used for |
|---|---|
| `ENTITY.<example id> = <entity id>` | read `<entity id>` from the Datalake wherever the code names the example entity; the open-loop run records the mapped room entity |
| `COMFORT_C`, `MIN_SETPOINT_C`, `PUMP_DUTY_HEAT`, `PUMP_DUTY_IDLE` | the install's profile in `make evaluate-*`, the real-data golden open-loop run and the full-run command line |
| `ROOM_SENSOR_*` | the calibrated room sensor (`STEP_K`, `GRID_OFFSET_K`, `NOISE_K`, `HYSTERESIS_K`, `CHANGES_PER_DAY`, `REVERSAL_SHARE`) for runs over recorded spans |
| `RECORDING_FROM`, `RECORDING_TO`, `SIM_START`, `CF_FROM`, `OPENLOOP_DAY`, `VALIDATE_START`, `STOVE_DAYS` | the recorded span of the full run, the simulator's start day, the counterfactual's first day, the day of the real-data golden open-loop run, the validation start and the known stove days |
| `REFERENCE_PLANT` | a fitted plant (`plant_params.json`) for `make sim`; `OVENBIRD_REFERENCE_PLANT` does the same for the command lines |
| `NAS_HOST`, `NAS_DIR` | the recorder host and directory of the `recorder-*`, `nas-*` and `capture-pull` targets |

## Replaying

```fish
make mqtt-reset                                        # wipe retained state in the dev broker
make replay CAPTURE=capture/captures/live              # 1x, overlay mode
make replay CAPTURE=capture/captures/live SPEED=10 FROM=+6h TO=+8h
make replay-ignore CAPTURE=capture/captures/live       # exercise command_delivery_failure
```

On start the replayer **primes** the broker with every retained topic as it
stood at the window start, then publishes `LWT=Offline` (retained) and lets the
stream's first `Online` flip it — exactly what a reconnecting HeishaMon looks like.

### Command modes

| `--commands` | What happens on `commands/*` |
|---|---|
| `overlay` (default) | The integration under test may send commands. They are applied with HeishaMon semantics (integer parsing, 10-deep queue, side-effect on the next query tick, no echo) and the replayer then **owns** the affected `main/*` topics: recorded values for them — including the 300 s dump repeats and the recorded controller's later decisions — are suppressed. `--overlay-release N` hands a topic back to the capture N s after its last command. |
| `ignore` | No overlay, recorded commands dropped. Commands from the integration go unanswered → `binary_sensor.*_command_delivery_failure`. |
| `passthrough` | Recorded commands are replayed too, nothing is overlaid. For watching the recorded controller's decisions in the dev stack. |

### Fidelity caveats — read before drawing conclusions

- **Replay is not a plant model.** Outlet temperatures, power and compressor
  behaviour stay exactly as recorded no matter what the integration commands.
  Only the side-effect topics react.
- **`--speed > 1` distorts every wall-clock metric** in the coordinator: the
  60 s CCC publish throttle, the 60 s hysteresis tick, the 24 h cycling window,
  rolling COP. At 60x a capture-hour passes per minute, so the throttle allows
  one setpoint publish per capture-hour. Use speed to *reach* a window and
  eyeball dashboards; quantitative work is 1x — or the in-process harness in
  `tests/integration/test_capture_harness.py`, which replays through the real
  coordinator with frozen time.
- **Message-count-based smoothing.** The integration's outside-temperature EMA
  advances once per *changed* message. Real `Outside_Temp` is an integer that
  changes a few times per hour, so the smoothed value lags far more than with
  the jittering synthetic simulator. `capture-info` quantifies it (`Δchg s`);
  a time-based EMA is a tracked follow-up.
- The overlay caps its query grid at 4.5 s wall time so a side-effect always
  beats the integration's 5 s confirmation timeout; real HeishaMon can take up
  to 5 s and occasionally trigger a retry.

### Safety

The replayer refuses any broker host other than `localhost`, `127.0.0.1`,
`::1` or `mosquitto` unless `--allow-remote-broker` is given: HeishaMon executes
`commands/#` from *any* publisher, and the real pump would obey.

The recorder has no code path that sends anything (a test asserts the module
source contains no publish call) and should run under a read-only broker account.

## Synthetic capture

`uv run climate-manager-capture-synthetic --out capture/captures --name synthetic`
writes a deterministic 30-minute capture built on the same protocol model:
retained flush, on-change traffic, a 300 s dump, the LWT quirk, a 90 s gap,
one setpoint command with its side-effect, and two HA-side records.
The test suites use the same generator.
