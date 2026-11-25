# ovenbird

ovenbird is a standalone heat pump controller. This app runs the same container image that is
used in production, packaged for Home Assistant OS and Supervised installs.

## Status

Pre-alpha. ovenbird starts in **shadow**: it reads the HeishaMon MQTT topics (and optionally
Home Assistant entities), decides every minute and shows what it would send, but publishes
nothing to the heat pump or the broker. Sending stays off unless the deployment enables
commands.

## Production recommendation

Run ovenbird as a standalone container next to the MQTT broker for production use. A controller
should keep running when Home Assistant restarts, updates or is restored from a backup, and
should not depend on the Supervisor being healthy. The app is a convenience for trying it out
and for read-only monitoring.

## Access

Open ovenbird from the Home Assistant sidebar (ingress). Requests coming through ingress are
trusted and need no login. Nothing else is trusted: the optional direct port (8099, disabled by
default under Network) always requires the admin password. If no admin password is set, the
direct port rejects every request.

## Configuration

| Option | Description |
| --- | --- |
| `mqtt_host`, `mqtt_port` | MQTT broker; default is the Mosquitto app (`core-mosquitto`). |
| `mqtt_username`, `mqtt_password` | Broker credentials; leave empty for an anonymous broker. |
| `mqtt_tls` | Connect with TLS. |
| `heishamon_base` | The HeishaMon `mqtt_topic_base`, default `panasonic_heat_pump`. |
| `ha_entities` | Optional extra Home Assistant entity ids to read. The sensors chosen in ovenbird's settings are read without listing them here. Uses the Supervisor proxy; no token needed. |
| `admin_password` | HTTP Basic password (user `admin`) for the optional direct port. |
| `log_level` | `debug`, `info`, `warning`, `error` or `critical`. |

## Data and backups

History is stored in the app's `/data` volume. Backups are hot and never copy the live database
(a copy of a database that is being written can be torn). Instead the app writes a consistent
snapshot, `history.snapshot.db`, every 6 hours (and at start when the last one is older), and
backups contain only that snapshot. After a restore the app rebuilds its history from the
snapshot, so a restored history misses at most the last 6 hours. The snapshot needs about as
much disk space as the history itself.

Every finished month is also frozen into `/data/archive/YYYY-MM.zip` (System → Data, on by
default; some 30 MB a month). Backups include these files; the month still being built is
left out and rebuilt from the history after a restore.

The app starts as root only to give `/data` to its own unprivileged user (uid 10001); the
service itself always runs as that user.
