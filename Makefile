# ovenbird: uv workspace dev tasks
# All Python work via uv. Targets are POSIX-compatible so make invokes /bin/sh.
# Recorded house data is local only: CAPTURES_DIR (default capture/captures, git-ignored)
# holds the captures, the recorded test slice and the real-data golden streams.
# $(CAPTURES_DIR)/local.env, when present, sets this install's values (comfort, pump
# duties, recorder host, recording days; see capture/README.md) before the example
# defaults below; a value given on the command line still wins.

SHELL := /bin/sh
CAPTURES_DIR ?= capture/captures
-include $(CAPTURES_DIR)/local.env
MQTT_PORT ?= 1884

.PHONY: help sync test test-fast typecheck lint format install-hooks \
        recorder-build recorder-save record record-logs record-stop discover \
        recorder-deploy nas-status nas-logs capture-pull capture-overview \
        capture-info capture-synthetic replay replay-ignore replay-fixture \
        dev-up dev-down dev-logs image image-check ui-dev ui-build ui-check \
        ui-e2e ui-fixtures dev-check shadow-check dev-sim-logs sim evaluate-identify evaluate-open-loop evaluate-counterfactual \
        evaluate-sensorcheck convert-capture api-schema api-check

.DEFAULT_GOAL := help

CAPTURE_DIR := capture
COMPOSE_RECORDER := docker compose -f $(CAPTURE_DIR)/docker-compose.yml --project-directory $(CAPTURE_DIR)
ENV ?= .env
NAS_HOST ?= nas
NAS_DIR ?= /srv/ovenbird-recorder
NAS_SHELL := export PATH=/usr/local/bin:$$PATH; cd $(NAS_DIR) &&
DEPLOY_TAR := COPYFILE_DISABLE=1 tar -C $(CAPTURE_DIR) --exclude captures --exclude tests \
        --exclude '.env.*' --exclude __pycache__ --exclude '*.pyc' \
        --exclude .pytest_cache --exclude .mypy_cache --exclude .ruff_cache -cf - .
SPEED ?= 1
START ?= $(or $(SIM_START),2026-01-06)
REFERENCE_PLANT ?=
BOOTSTRAP ?= 50
COMFORT_C ?= 21.0
MIN_SETPOINT_C ?= 24
RECORDED_ROOM_SOURCE ?= auto
PUMP_DUTY_HEAT ?= 159
PUMP_DUTY_IDLE ?= 102
ROOM_MAX_AGE ?= 1800
CONVERT_ROOM_MAX_AGE ?=
CONVERT_CONFIG ?= dev/config-seed.json
CONVERT_OUT ?= capture/captures/replay-db
ROOM_CONFIRM ?= inf
ROOM_PROFILE ?= on_change
CROSSCHECK ?= main/Room_Thermostat_Temp
CF_FROM ?=
CF_TO ?=
CF_ARGS ?=
FOLDS ?= 2
MODELS ?= capture/captures/models
SIM_ROOM_PROFILE ?= on_change
SENSOR_ENTITY ?= sensor.living_room_temperature
SENSOR_LIVENESS ?= sensor.living_room_humidity
OUT ?= capture/captures/evaluations/ovenbird
COMPOSE_DEV := docker compose -f dev/docker-compose.yml
REPLAY_ARGS := --host localhost --port $(MQTT_PORT) --speed $(SPEED) \
        $(if $(FROM),--from $(FROM),) $(if $(TO),--to $(TO),) $(ARGS)

help:
	@echo "Targets:"
	@echo "  sync           Install all workspace packages and the dev group (uv sync --all-packages)."
	@echo "  test           Run the full test suite."
	@echo "  test-fast      Run the test suite without the tests marked slow."
	@echo "  typecheck      Run mypy (strict) on packages and capture/src."
	@echo "  lint           Run ruff check."
	@echo "  format         Run ruff format."
	@echo "  install-hooks  Install pre-commit + pre-push hooks."
	@echo "  recorder-build Build the recorder container image."
	@echo "  recorder-save  Save the image to capture/dist/ for docker load on the NAS."
	@echo "  record         Start the recorder container (ENV=.env.local for the dev broker)."
	@echo "  record-logs    Tail recorder container logs."
	@echo "  record-stop    Stop the recorder container."
	@echo "  discover       2 h '#' discovery run against the broker in capture/.env."
	@echo "  recorder-deploy  Copy capture/ + .env to the NAS over ssh, build there, (re)start."
	@echo "  nas-status     Container health + last log lines on the NAS."
	@echo "  nas-logs       Follow the recorder logs on the NAS."
	@echo "  capture-pull   Copy captures/<NAME=live> from the NAS into capture/captures/."
	@echo "  capture-info   Summarise a capture: CAPTURE=capture/captures/<name> [ARGS=--catalogue]."
	@echo "  capture-synthetic  Write the deterministic synthetic capture."
	@echo "  replay         Replay CAPTURE=... into the dev broker [SPEED= FROM= TO= ARGS=]."
	@echo "  replay-ignore  Replay without answering commands (delivery-failure path)."
	@echo "  replay-fixture Replay the committed fixture into the dev broker, keeping stats [SPEED=60]."
	@echo "  capture-overview  Build capture/captures/overview.html from NAME=live."
	@echo "  dev-up         Start the simulated dev stack (mosquitto :1884, heishamon-sim, ovenbird :8099; HA with COMPOSE_PROFILES=ha)."
	@echo "  dev-check      Check the running simulated stack end to end through the API."
	@echo "  shadow-check   Read-only check of a deployed ovenbird in shadow URL=https://... (password in OVENBIRD_ADMIN_PASSWORD)."
	@echo "  dev-sim-logs   Follow the simulated HeishaMon logs."
	@echo "  sim            Run the simulated HeishaMon locally [SPEED= START=YYYY-MM-DD SIM_ROOM_PROFILE=on_change|periodic]."
	@echo "  evaluate-identify        Fit the plant (all days and one train-only file per rolling-origin fold) into $(MODELS) [FOLDS=2 CF_TO=last day]."
	@echo "  evaluate-open-loop       Open-loop run with the install profile [RECORDED_ROOM_SOURCE=auto|datalake|mirror ROOM_MAX_AGE=1800 OUT=dir]."
	@echo "  evaluate-counterfactual  Closed loop on the fitted plant: ovenbird vs the recorded setpoints [BOOTSTRAP=50 ROOM_PROFILE=on_change CROSSCHECK=main/Room_Thermostat_Temp CF_FROM=first day CF_TO=last day MODELS=dir OUT=dir CF_ARGS=--no-known-events]."
	@echo "  convert-capture          Convert a recorded period into an ovenbird history.db for System -> Replay: CF_FROM= CF_TO= [CONVERT_CONFIG=dev/config-seed.json CONVERT_OUT=capture/captures/replay-db RECORDED_ROOM_SOURCE=auto CONVERT_ROOM_MAX_AGE=s, default the room profile's silence limit CONVERT_ARGS=--force]."
	@echo "  evaluate-sensorcheck     Propose a room sensor profile from the Datalake HA states [SENSOR_ENTITY= SENSOR_LIVENESS=]."
	@echo "  fullrun        B1: stepped closed-loop run of the whole service over the recorded span [ARGS=--from/--to/--out]."
	@echo "  fullrun-faults B1 with every fault scenario injected [ARGS=]."
	@echo "  fullrun-replay B2: exact replays (MQTT and HA paths) and a 48 h KPI comparison against the real asyncio service [ARGS=--out dir --hours 96]."
	@echo "  golden         Regenerate the golden decision log: the synthetic streams (full-run, fault sweep, drills) in"
	@echo "                 packages/harness/tests/golden and, with the recorded capture present, the real-data streams"
	@echo "                 (open-loop run) in \$$CAPTURES_DIR/golden-real (local only, never committed)."
	@echo "  golden-check   Regenerate into a temp dir and diff (non-zero on a difference); the real-data streams are"
	@echo "                 checked only when \$$CAPTURES_DIR/live exists, otherwise skipped with a note (CI, fresh clone)."
	@echo "  test-fixture   Regenerate the synthetic two-hour capture slice the replay tests use."
	@echo "  ui-sim-fixtures  Regenerate the simulated service responses in ui/mock/fixtures (decisions, weather)."
	@echo "  learn          Refit the house model on a history.db [LEARN_HISTORY=$(LEARN_HISTORY) LEARN_CONFIG=$(LEARN_CONFIG) LEARN_MODELS=$(LEARN_MODELS) WEATHER=dir FLOOR_AREA=m2 LEARN_ARGS=]."
	@echo "  dev-down       Stop the dev stack."
	@echo "  dev-logs       Tail dev stack logs."
	@echo "  ui-dev         Run the UI dev server against mock data."
	@echo "  ui-build       Install UI dependencies and build ui/dist."
	@echo "  ui-check       Type-check, lint and test the UI."
	@echo "  ui-e2e         Run the UI Playwright suite against the mock service."
	@echo "  ui-fixtures    Regenerate the service UI fixtures and copy them to ui/mock/fixtures."
	@echo "  api-schema     Regenerate docs/openapi.json and the UI's api-types.gen.ts from the response models."
	@echo "  api-check      Fail when docs/openapi.json or ui/src/lib/core/api-types.gen.ts is stale."
	@echo "  image          Build the ovenbird image (ovenbird:dev)."
	@echo "  image-check    Build the image and run it with --check."

sync:
	uv sync --all-packages

install-hooks: sync
	uv run pre-commit install --hook-type pre-commit --hook-type pre-push

recorder-build:
	docker build -t climate-manager-recorder:latest $(CAPTURE_DIR)

recorder-save: recorder-build
	mkdir -p $(CAPTURE_DIR)/dist
	docker save climate-manager-recorder:latest | gzip > $(CAPTURE_DIR)/dist/climate-manager-recorder.tar.gz
	@echo "copy $(CAPTURE_DIR)/dist/climate-manager-recorder.tar.gz to the NAS and: docker load < climate-manager-recorder.tar.gz"

record:
	@test -f $(CAPTURE_DIR)/$(ENV) || { echo "$(CAPTURE_DIR)/$(ENV) missing; copy one of the .env.*.example files"; exit 1; }
	ENV_FILE=$(ENV) PUID=$$(id -u) PGID=$$(id -g) $(COMPOSE_RECORDER) up -d --build

record-logs:
	$(COMPOSE_RECORDER) logs -f

record-stop:
	$(COMPOSE_RECORDER) down

discover:
	@test -f $(CAPTURE_DIR)/$(ENV) || { echo "$(CAPTURE_DIR)/$(ENV) missing; copy .env.nas.example"; exit 1; }
	ENV_FILE=$(ENV) PUID=$$(id -u) PGID=$$(id -g) $(COMPOSE_RECORDER) run --rm --build \
	    -e TOPICS='#' -e CAPTURE_NAME=discovery -e MAX_HOURS=$(or $(DISCOVER_HOURS),2) recorder

recorder-deploy:
	@test -f $(CAPTURE_DIR)/.env || { echo "$(CAPTURE_DIR)/.env missing; copy .env.nas.example"; exit 1; }
	ssh $(NAS_HOST) 'mkdir -p $(NAS_DIR)/captures'
	$(DEPLOY_TAR) | ssh $(NAS_HOST) 'cd $(NAS_DIR) && tar -xf - && chmod 600 .env'
	ssh $(NAS_HOST) '$(NAS_SHELL) PUID=$$(id -u) PGID=$$(id -g) docker compose up -d --build'
	$(MAKE) nas-status

nas-status:
	ssh $(NAS_HOST) '$(NAS_SHELL) docker compose ps && docker compose logs --no-log-prefix --tail 5'

nas-logs:
	ssh $(NAS_HOST) '$(NAS_SHELL) docker compose logs --no-log-prefix --tail 50 -f'

capture-pull:
	mkdir -p $(CAPTURE_DIR)/captures
	ssh $(NAS_HOST) 'tar -C $(NAS_DIR)/captures -cf - $(or $(NAME),live)' | tar -C $(CAPTURE_DIR)/captures -xf -
	@for gz in $(CAPTURE_DIR)/captures/$(or $(NAME),live)/*.jsonl.gz; do \
	    [ -e "$$gz" ] && [ -e "$${gz%.gz}" ] && { echo "dropping rotated $${gz%.gz}"; rm -f "$${gz%.gz}"; }; \
	done; true
	@echo "pulled $(CAPTURE_DIR)/captures/$(or $(NAME),live); next: make capture-info CAPTURE=$(CAPTURE_DIR)/captures/$(or $(NAME),live)"

capture-overview:
	uv run python $(CAPTURE_DIR)/tools/overview_data.py $(CAPTURE_DIR)/captures/$(or $(NAME),live) $(CAPTURE_DIR)/captures/overview.json >/dev/null
	python3 -c 'import pathlib,sys; t,d,o=map(pathlib.Path,sys.argv[1:]); o.write_text(t.read_text().replace("__DATA__", d.read_text().replace("</", "<\\/")))' \
	    $(CAPTURE_DIR)/tools/overview.html $(CAPTURE_DIR)/captures/overview.json $(CAPTURE_DIR)/captures/overview.html
	@echo "wrote $(CAPTURE_DIR)/captures/overview.html"

capture-info:
	@test -n "$(CAPTURE)" || { echo "usage: make capture-info CAPTURE=capture/captures/<name> [ARGS=--catalogue]"; exit 1; }
	uv run climate-manager-capture-info $(CAPTURE) $(ARGS)

capture-synthetic:
	uv run climate-manager-capture-synthetic --out $(CAPTURE_DIR)/captures --name synthetic

replay:
	@test -n "$(CAPTURE)" || { echo "usage: make replay CAPTURE=capture/captures/<name> [SPEED=10 FROM=+6h TO=+8h]"; exit 1; }
	uv run climate-manager-replay --capture $(CAPTURE) $(REPLAY_ARGS)

replay-ignore:
	@test -n "$(CAPTURE)" || { echo "usage: make replay-ignore CAPTURE=capture/captures/<name>"; exit 1; }
	uv run climate-manager-replay --capture $(CAPTURE) --commands ignore $(REPLAY_ARGS)

FIXTURE_CAPTURE := packages/core/tests/fixtures/synthetic

replay-fixture:
	uv run climate-manager-replay --capture $(FIXTURE_CAPTURE) --host localhost --port $(MQTT_PORT) \
	    --speed $(if $(filter command line environment,$(origin SPEED)),$(SPEED),60) --drop log $(ARGS)

dev-up:
	$(COMPOSE_DEV) up -d --build

dev-down:
	$(COMPOSE_DEV) down

dev-logs:
	$(COMPOSE_DEV) logs -f

image:
	docker build -t ovenbird:dev .

image-check: image
	docker run --rm ovenbird:dev --check

test:
	uv run pytest

test-fast:
	uv run pytest -m "not slow"

typecheck:
	uv run mypy packages capture/src

lint:
	uv run ruff check .

format:
	uv run ruff format .

ui-dev:
	npm --prefix ui run dev:mock

ui-build:
	npm --prefix ui ci --ignore-scripts
	npm --prefix ui run build

ui-check:
	npm --prefix ui run check
	npm --prefix ui run lint
	npm --prefix ui test

ui-e2e:
	npm --prefix ui run e2e

UI_FIXTURE_FILES := config.json schema.json codes.json

ui-fixtures:
	UPDATE_UI_FIXTURES=1 uv run pytest packages/service/tests/test_ui_fixtures.py -q -k are_current
	for f in $(UI_FIXTURE_FILES); do cp packages/service/tests/fixtures/ui/$$f ui/mock/fixtures/$$f; done

api-schema:
	uv run python -m ovenbird.api.openapi docs/openapi.json
	npm --prefix ui run api-types

api-check:
	uv run python -m ovenbird.api.openapi --check docs/openapi.json
	npm --prefix ui run api-types:check

dev-check:
	uv run python dev/check_sim.py

shadow-check:
	@test -n "$(URL)" || { echo "usage: make shadow-check URL=https://ovenbird.example"; exit 2; }
	uv run python dev/check_shadow.py --url $(URL) $(ARGS)

dev-sim-logs:
	$(COMPOSE_DEV) logs -f heishamon-sim

sim:
	uv run python -m ovenbird_sim.heishamon --host localhost --port $(MQTT_PORT) --speed $(SPEED) --start $(START) $(if $(REFERENCE_PLANT),--params $(REFERENCE_PLANT),) --room-profile $(SIM_ROOM_PROFILE) --humidity-topic climate_manager_capture/room_humidity

evaluate-identify:
	uv run python -m ovenbird_sim.identify capture/captures --folds $(FOLDS) --out $(MODELS)/plant_params.json $(if $(CF_TO),--to $(CF_TO),)

evaluate-open-loop:
	uv run python -m ovenbird_sim.evaluate open-loop --capture capture/captures/live --datalake capture/captures/datalake --room $(RECORDED_ROOM_SOURCE) --room-max-age $(ROOM_MAX_AGE) --comfort $(COMFORT_C) --min-setpoint $(MIN_SETPOINT_C) --pump-duty --pump-duty-heat $(PUMP_DUTY_HEAT) --pump-duty-idle $(PUMP_DUTY_IDLE) --emitter mixed --out $(OUT)

evaluate-counterfactual:
	uv run python -m ovenbird_sim.evaluate counterfactual --capture capture/captures/live --params $(MODELS)/plant_params.json --bootstrap $(BOOTSTRAP) --comfort $(COMFORT_C) --ovenbird-target $(COMFORT_C) --ovenbird-min-setpoint $(MIN_SETPOINT_C) --pump-duty --pump-duty-heat $(PUMP_DUTY_HEAT) --pump-duty-idle $(PUMP_DUTY_IDLE) --room-confirm-s $(ROOM_CONFIRM) --room-profile $(ROOM_PROFILE) --room-crosscheck "$(CROSSCHECK)" $(if $(CF_FROM),--from $(CF_FROM),) $(if $(CF_TO),--to $(CF_TO),) --out $(OUT) $(CF_ARGS)

convert-capture:
	uv run python -m ovenbird_harness.convert --capture capture/captures/live --datalake capture/captures/datalake --from $(CF_FROM) --to $(CF_TO) --config $(CONVERT_CONFIG) --room $(RECORDED_ROOM_SOURCE) $(if $(CONVERT_ROOM_MAX_AGE),--room-max-age $(CONVERT_ROOM_MAX_AGE),) --out $(CONVERT_OUT) $(CONVERT_ARGS)

evaluate-sensorcheck:
	uv run python -m ovenbird_sim.sensorcheck --datalake capture/captures/datalake --entity $(SENSOR_ENTITY) $(if $(SENSOR_LIVENESS),--liveness $(SENSOR_LIVENESS),)

.PHONY: fullrun fullrun-faults fullrun-replay

fullrun:
	uv run python -m ovenbird_harness.fullrun $(ARGS)

fullrun-faults:
	uv run python -m ovenbird_harness.fullrun --faults $(ARGS)

fullrun-replay:
	uv run python -m ovenbird_harness.validate $(ARGS)

.PHONY: learn golden golden-check test-fixture ui-sim-fixtures

LEARN_HISTORY ?= capture/captures/fullrun/plain/history.db
LEARN_CONFIG ?= dev/learner-config.json
LEARN_MODELS ?= capture/captures/models/house
LEARN_ARGS ?=

learn:
	uv run python -m ovenbird_sim.learn --history $(LEARN_HISTORY) --config $(LEARN_CONFIG) \
	    --models $(LEARN_MODELS) $(if $(WEATHER),--weather-dir $(WEATHER),) \
	    $(if $(FLOOR_AREA),--floor-area $(FLOOR_AREA),) $(LEARN_ARGS)

golden:
	uv run python -m ovenbird_harness.golden write

golden-check:
	uv run python -m ovenbird_harness.golden check

test-fixture:
	uv run python -m ovenbird_sim.heishamon.fixture

ui-sim-fixtures:
	uv run python -m ovenbird_harness.uifixtures
	npm --prefix ui run format
