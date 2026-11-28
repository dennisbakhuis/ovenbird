# Deploying ovenbird

How to run the service as a standalone container next to an MQTT broker, start it in
**shadow** and keep it there until the go-live checklist says otherwise. The settings are
described in [../packages/service/README.md](../packages/service/README.md#configuration);
the behaviour in [design.md](design.md). The Home Assistant app (`app/`) is for trying it
out; a controller should not depend on Home Assistant being up.

## What runs

One container, `ghcr.io/dennisbakhuis/ovenbird`:

| | |
| --- | --- |
| Process | `python -m ovenbird.launcher`: the service, its UI and API on one port |
| Port | `8099` (`OVENBIRD_HTTP_PORT`) |
| User | uid/gid `10001`; run it as `10001:10001` so it needs no capability at all |
| Data | `/data` (`OVENBIRD_DATA_DIR`), the only writable path besides `/tmp` |
| Health | `HEALTHCHECK` built in (`python -m ovenbird.launcher --check`) |
| Size | about 1 vCPU and 1 GB RAM is plenty; `history.db` grows with the raw retention (14 days by default) |

Outbound it talks to the broker, Home Assistant's WebSocket API (optional; a connection
test also makes one `GET /api/`), Open-Meteo
(optional, only with the weather forecast on) and ntfy plus a dead-man URL (optional).
Nothing calls in except the browser and your reverse proxy.

### Getting the image

| Way | When |
| --- | --- |
| Release image | `.github/workflows/release.yml` builds `linux/amd64` and `linux/arm64` and pushes `ghcr.io/dennisbakhuis/ovenbird:<version>` (plus `latest` for a non-prerelease) on a pushed tag `v*` whose version matches `packages/service/src/ovenbird/__init__.py` and `app/ovenbird/config.yaml`. A manual run (`workflow_dispatch`) pushes `sha-<sha7>` only. Pin the digest: `ghcr.io/dennisbakhuis/ovenbird:0.1.0@sha256:...` (`docker buildx imagetools inspect <tag>` prints it). |
| Local build | From a checkout: `docker build --platform linux/amd64 -t ovenbird:(git rev-parse --short HEAD) .` (the runtime stage is the default target). Move it with `docker save ovenbird:<sha> \| gzip > ovenbird.tar.gz` and `docker load` on the host. `make image-check` builds and smoke-tests it. |

Never use `latest` for a controller: an upgrade must be a deliberate step.

## Shadow first

A new installation computes and journals every decision but **publishes nothing**.
Publishing needs all four conditions of the publish guard
([../packages/service/README.md](../packages/service/README.md#publish-guard)):

1. `OVENBIRD_CONTROL_MODE=auto`;
2. `OVENBIRD_ALLOW_COMMANDS=true`;
3. the broker listed exactly in `OVENBIRD_COMMAND_BROKERS`;
4. the real clock (or `OVENBIRD_SIMULATION=true`, which only accepts a loopback or dev broker).

For shadow, set the safe values explicitly rather than relying on defaults:

```
OVENBIRD_CONTROL_MODE=shadow
OVENBIRD_ALLOW_COMMANDS=false
OVENBIRD_COMMAND_BROKERS=
OVENBIRD_SIMULATION=false
```

`OVENBIRD_CONTROL_MODE` is the ceiling: the UI and the API can pause an `auto`
installation but never raise `shadow`. The mode, `allow_commands`, `command_brokers` and
`simulation` are never stored in `config.db` and an options file cannot set the last three,
so neither a configuration seed, an import nor the UI can switch publishing on. Without the
four conditions the publishing connection is never created; the ingest connection has no
publish method and connects without a last will.

Make the broker enforce it too: give ovenbird its own MQTT user that may only read the
HeishaMon topics. For Mosquitto:

```
# acl_file
user ovenbird
topic read panasonic_heat_pump/#
```

With an `acl_file` Mosquitto denies everything not listed, so every other user needs its
own entry (`topic readwrite #` keeps today's behaviour). A denied publish is dropped
silently (MQTT 3.1.1), so a misconfigured ovenbird can never reach the pump. Add the topics
of plain MQTT inputs (`OVENBIRD_MQTT_INPUTS`) to the `read` lines if you use any. At go-live
the user needs `topic write panasonic_heat_pump/commands/#` as well.

## Configuration

Two kinds of settings:

- **Installation** (environment): connections, credentials, bind address, publish gates,
  the mode ceiling. They are locked in the UI.
- **Control** (the configuration store `config.db`): room sensor, comfort, emitter,
  minimum setpoint, pump duty, stove, weather, floor area. Editable in the UI with
  validation, preview, audit and rollback. Do not set them in the environment: an
  environment value locks the field.

### Environment

| Variable | Shadow deployment |
| --- | --- |
| `OVENBIRD_MQTT_HOST` / `_PORT` | the broker; can also be set in the app (below), these win |
| `OVENBIRD_MQTT_USERNAME` / `_PASSWORD` | the read-only user (secret) |
| `OVENBIRD_HEISHAMON_BASE` | HeishaMon's `mqtt_topic_base` (default `panasonic_heat_pump`) |
| `OVENBIRD_HA_URL` / `_TOKEN` | optional: Home Assistant base URL and a long-lived token (secret) of a non-admin user. Usually set in the app instead (below); when set here they are locked in the UI and win |
| `OVENBIRD_HA_ENTITIES` | optional: extra HA entities to read besides the ones the control settings use (the subscription follows the settings by itself) |
| `OVENBIRD_HTTP_HOST` | `0.0.0.0` inside the container |
| `OVENBIRD_ADMIN_PASSWORD` | required for a non-loopback bind (secret) |
| `OVENBIRD_HTTP_ALLOWED_ORIGINS` | the public origin behind a reverse proxy, e.g. `https://ovenbird.example` (the service does not trust `X-Forwarded-*`, so the browser's WebSocket and state-changing requests are checked against this list) |
| `OVENBIRD_CONFIG_SEED` | path of the seed file (below) |
| `OVENBIRD_CONTROL_MODE`, `_ALLOW_COMMANDS`, `_COMMAND_BROKERS`, `_SIMULATION` | the shadow values above |
| `OVENBIRD_NOTIFY_NTFY_URL` / `_NTFY_TOPIC` / `_NTFY_TOKEN`, `_DEADMAN_URL` | optional alarms and dead-man ping (topic, token and URL are secrets) |
| `OVENBIRD_LOG_LEVEL` | `INFO` |

Secrets (`mqtt_password`, `ha_token`, `admin_password`, `operate_token`,
`notify_ntfy_topic`, `notify_ntfy_token`, `notify_deadman_url`) are never logged and
appear as `set`/`unset` in the API. Only the Home Assistant token and the broker password
can be stored, and only when they are entered in the app (below); the others are never
stored. Keep them in an env file of mode `0600`
outside the data directory. Leave `OVENBIRD_OPERATE_TOKEN` unset until the HA
integration needs it.

### Home Assistant

Home Assistant is optional and read-only. Set it up in the app: **Settings → Home
Assistant** takes the address and a long-lived access token, **Test connection** checks
them without saving (reachable, token accepted, HA version, response time, unit system,
and whether the sensors in use exist), and **Save connection** applies them at once: the
HA input reconnects without a restart.

- **Address**: HA's base URL, direct (`http://192.0.2.10:8123`) or behind a reverse
  proxy (`https://ha.example.org`, a path prefix is fine). `http`, `https`, `ws` or
  `wss` with a host; no user name, password, query or fragment; redirects are not
  followed (use the final address). Plain `http` is fine on the LAN. Certificates are
  always verified for `https`; there is no option to switch that off (a token would go
  to whoever answers). For a private CA, point OpenSSL's `SSL_CERT_FILE` at a bundle that
  contains it, or use `http` on the LAN.
- **Token**: a long-lived access token of a non-admin user. It is kept in `config.db`
  (table `connection`, outside the configuration versions, so a rollback or a seed never
  touches it) and therefore also in `config.snapshot.db` and in backups of the data
  directory; protect that directory like the env file. The API never returns it: `GET
  api/v1/config`, exports, diagnostics and the audit show `set`/`unset`.
- **Environment wins**: `OVENBIRD_HA_URL`/`OVENBIRD_HA_TOKEN` (or the options file) lock
  the fields in the UI; a stored value stays but is inactive. An empty variable counts
  as unset.
- **Sensors**: chosen in the settings (room sensor, liveness, cross-check, wood-stove
  reference, the outside thermometer of the curve); a thermostat's measured temperature can be picked as
  `ha/climate.<name>#current_temperature`. The service subscribes to exactly the
  entities those settings use, plus `OVENBIRD_HA_ENTITIES`, and follows every change.
  With none in use it stays connected for the picker lists but subscribes to nothing.
  The heat pump itself is read over MQTT, never through Home Assistant: entities of a
  Home Assistant device that copies the heat pump's HeishaMon values (such as HA's own
  HeishaMon integration) are listed last in the pickers, grouped as "Heat pump, via
  Home Assistant" (`pump_mirror` in `GET api/v1/config/signals`).
- **Units**: °F and K are converted to °C when they arrive. A temperature input (room,
  cross-check, wood-stove reference, outside thermometer) without a temperature unit is
  accepted only when HA's unit system is metric; otherwise it is refused (the controller
  treats the value as missing; for the room signal the `room_unit_refused` alarm).
- **What it sends**: `auth`, `get_config`, the read-only registry lists
  (`config/entity_registry/list_for_display`, `config/device_registry/list`,
  `config/area_registry/list`, for area and device names in the pickers),
  `subscribe_entities` and `get_states`; the test adds a `GET /api/`. Nothing is
  written to Home Assistant.

Existing installations need nothing: a `config.db` without the connection table is
migrated at start, and `OVENBIRD_HA_URL`/`_TOKEN`/`_ENTITIES` keep working as before.

### Broker (MQTT)

The broker can be set in the environment (above) or in the app: **Settings → MQTT** takes
the host, port, user name, password, TLS, a CA file, the client id and HeishaMon's base
topic. **Test connection** opens a separate subscribe-only session and reports whether
HeishaMon values arrive on `<base>/main/#`; **Save connection** is offered only for
exactly the settings that just passed the test. The service then reconnects at once and
watches for 60 s: without a connection and live (not retained) HeishaMon data in that
time it puts the previous broker back (keeping any configuration or HA change made
meanwhile), writes `mqtt_connection_reverted` to the audit and raises the warning of the
same name; if that fails, the critical alarm `mqtt_revert_failed` asks for a working
broker. A restart during the 60 s runs the watch again after the start; when the
service restarts with commands enabled, the new broker is kept instead, because the
command link starts on it. A successful test of the current broker ends a trial left
unfinished.

- **Environment wins**: a field set by `OVENBIRD_MQTT_*`, `OVENBIRD_HEISHAMON_BASE` or
  the options file shows read-only ("set by the deployment"); a stored value stays but
  is inactive.
- **Password**: stored like the HA token (table `connection`, write-only, `set`/`unset`
  in the API). It never goes to another broker: a change of the effective host or port,
  switching TLS off or another CA file drops the stored password unless the same change
  (test and save) brings it again. A password from `OVENBIRD_MQTT_PASSWORD` or the
  options file cannot be dropped, so such a change is refused (`password_locked`):
  change the broker in the deployment and restart. The rule applies to changes made in
  the app: when the deployment itself moves the host, a password stored in the app goes
  along, so set the password in the deployment too, or clear it in the app first.
- **Commands enabled**: the command link and the publish guard keep the broker they
  started with, so the broker cannot be changed in the app then; change it in the
  deployment and restart.
- **Extra topics**: **Settings → MQTT** also edits `mqtt_inputs` (a plain topic read as a
  numeric signal, e.g. a garden thermometer); they are part of the configuration
  versions and appear in the sensor pickers next to the HA entities.

### Configuration seed

`OVENBIRD_CONFIG_SEED` names an export file (the format of `GET api/v1/config/export`,
see [../dev/config-seed.json](../dev/config-seed.json)) whose `values` become version 1
of an **empty** store; it is ignored once `config.db` has a version. Keep the seed with
the deployment, not in the image. Signals are `ha/<entity_id>` for Home Assistant
entities, `main/<name>` for HeishaMon values and the `signal` of an MQTT input.
`"weather_location_source": "ha_zone_home"` takes the location from Home Assistant's
`zone.home` (rounded to 0.01°, sent to Open-Meteo once weather is on), so no coordinates
have to be written anywhere. A seed that does not validate stops the service at start
with the field and the rule.

## Container

```yaml
services:
  ovenbird:
    image: ghcr.io/dennisbakhuis/ovenbird:<version>@sha256:<digest>
    user: "10001:10001"
    restart: unless-stopped
    read_only: true
    cap_drop: [ALL]
    security_opt: ["no-new-privileges:true"]
    tmpfs: [/tmp]
    env_file: ./ovenbird.env
    environment:
      OVENBIRD_HTTP_HOST: 0.0.0.0
      OVENBIRD_CONFIG_SEED: /seed/config-seed.json
      OVENBIRD_CONTROL_MODE: shadow
      OVENBIRD_ALLOW_COMMANDS: "false"
      OVENBIRD_COMMAND_BROKERS: ""
      OVENBIRD_SIMULATION: "false"
    ports: ["8099:8099"]
    volumes:
      - /srv/ovenbird/data:/data
      - /srv/ovenbird/config-seed.json:/seed/config-seed.json:ro
```

The data directory must be owned by uid 10001 (mode `0750`). Without `user:` the launcher
starts as root only to give `/data` to 10001 and then drops to it.

## Deploy-day check

Read-only, in this order:

1. The broker answers with ovenbird's user and HeishaMon publishes:
   `mosquitto_sub -h <broker> -u ovenbird -P <password> -t 'panasonic_heat_pump/main/#' -v -C 5 -W 30`.
2. The token reads the room entity:
   `curl -fsS -H "Authorization: Bearer <token>" <ha_url>/api/states/<room entity>`.
3. After start: `curl -fsS <url>/api/v1/health` shows `live` and `ready` true with
   `mqtt` connected, `heishamon` alive and `ha` connected.
4. `make shadow-check URL=<url>` (password in `OVENBIRD_ADMIN_PASSWORD`;
   [../dev/check_shadow.py](../dev/check_shadow.py)): only `GET`s to ovenbird; it fails
   unless the mode is `shadow` configured and effective, `allow_commands` is off,
   `command_brokers` is empty, nothing is publishing, the room input is fresh and the
   shadow divergence has compared minutes. Run it again after an hour.
5. The Shadow page fills: ovenbird's would-be setpoint next to the pump's
   `Z1_Water_Target_Temp`, minute by minute.

## Go-live

Not before the checklist on the Trial page (`GET api/v1/trial/status`, see
[design.md](design.md#shadow-mode-and-the-supervised-trial-service)): 14 shadow days with
the divergence reviewed, the HeishaMon envelope rule declared and seen acting,
notifications and the dead-man ping live, a rehearsed release, no open critical alarm and a
trusted room value. Going live is a local change of all three gates
(`OVENBIRD_CONTROL_MODE=auto`, `OVENBIRD_ALLOW_COMMANDS=true`,
`OVENBIRD_COMMAND_BROKERS=<broker>`) plus the broker ACL's write line, and a restart. A
`COMMANDS ENABLED` warning is logged at start. "Release control" hands the pump back.

## Upgrade

1. Read `CHANGELOG.md` between the two versions.
2. Take an app-consistent copy: the service keeps `config.snapshot.db` (after every
   change) and `history.snapshot.db` (every 6 h) in the data directory; copy the whole
   directory while the container is stopped, or rely on file-system snapshots that
   include those two files.
3. Pin the new tag and digest, pull, recreate the container. Database migrations run on
   start and are forward-only: an older image refuses a newer `history.db` or `config.db`.

Rollback: pin the previous image. If the newer one migrated a database, restore the copy
from step 2 (decisions recorded meanwhile are lost; the pump is unaffected in shadow).

### Upgrading from 0.5.0

The house model of 0.5.0 is removed: the learner, the model plan, the what-if and the
House page tabs built on them. Nothing to migrate: the databases are unchanged.

- The image is smaller again, about 146 MB instead of 356 MB: it no longer carries numpy
  and scipy.
- Stored settings of the removed features (`house_learn_*`, the `house_*` bounds,
  `control_model_*`) are ignored on load; the facts about the house (floor area, volume,
  build period, windows, occupants) are kept.
- The `models/` and `learner/` directories in the data directory are no longer read or
  written and are left as they are; delete them by hand when you no longer want them.
- The recorded `derived/model_plan_*` signals are no longer written; rows already in the
  history stay readable.
- Every new feature is off by default: the sun day shift, the summer switch and quiet mode
  after a compressor start. House basics (`house_basics_enabled`) is on, and boost and
  away act only when you ask for them. The `compressor_starts` alarm is on as well. The
  Features section in Settings lists all of them; `GET api/v1/control/features` shows
  their state.
- The sun day shift is experimental: its simulator evaluation did not pass (a house with
  large sun-facing windows got too warm). `shadow` records what it would do; `on` needs
  `control_dayshift_experimental_ok` as well (the checkbox under the switch in Settings →
  Features). In the environment or the options file, set both together, or the service
  refuses the configuration (`dayshift_on_needs_ack`). A client of
  `GET api/v1/control/dayshift` that read `locked` reads `on_available` and
  `experimental` instead.
- The heat-loss estimate of House basics shows no number until about 10 heating days
  (days that qualify, see `GET api/v1/insight/basics`) are in the history; until then the
  page says how many are missing.
- Set the time zone (`control_timezone`, for example `Europe/Amsterdam`) before you use
  the day shift or the quiet windows: both follow the local clock, as do the local days of
  the house basics.
- Details of what changed: [../CHANGELOG.md](../CHANGELOG.md#060---2026-11-28) and
  [notes/house-model-attempt.md](notes/house-model-attempt.md).

After upgrading, check that `GET api/v1/health` shows `live` and `ready` true and that
decisions keep their one-minute cadence on the Setpoint page.

## Backup and restore

Back up the data directory. The two `*.snapshot.db` files are consistent copies made by
the service, so a crash-consistent file-system snapshot or a plain file copy of a running
service is enough. To restore: stop the container, put the directory back (or only the two
snapshots), delete `config.db` and `history.db` with their `-wal`/`-shm` files, start. The
service rebuilds both from the snapshots and logs that it did; the history misses at most
the last 6 hours.

The yearly archive lives in `archive/` in the data directory: one finished
`YYYY-MM.zip` per month (written atomically, safe to copy at any time) and the working
copy `YYYY-MM.db` of the current month, which can be left out of a backup (it is rebuilt
from `history.db`). Plan some 30 MB a month for it, or switch it off in System → Data.
While the archive cannot copy (an error, the disk too full) history retention waits for
it, at most 3 days, and the warning `archive_failing` shows; after those 3 days old
history is removed again even if it never reached the archive. A damaged working copy is
moved aside as `YYYY-MM.db.corrupt-<time>` (keep it for a recovery or delete it) and
rebuilt from `history.db` (warning `archive_rebuilt`).

Removal: stop and delete the container, then the data directory if the history is not
needed. In shadow nothing has to be handed back to the pump.
