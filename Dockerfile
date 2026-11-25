FROM --platform=$BUILDPLATFORM node:22-slim@sha256:e9f565d32859f0cbfb52125eafe8be39390f24dac302dc3cdf566e8ba3ab21ee AS ui
WORKDIR /ui
COPY ui/ ./
RUN mkdir -p dist \
    && if [ -f package.json ]; then npm ci --ignore-scripts && npm run build; fi

FROM python:3.14-slim@sha256:9aaa474097d094040649f2162a627c0049b408f52138d980916788d80f04802f AS build
COPY --from=ghcr.io/astral-sh/uv:0.13.7@sha256:96f40d3904aad8d0bd010539001d36c8e2188b981e1334471a90c4a1d93bb490 /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
WORKDIR /src
COPY pyproject.toml uv.lock .python-version ./
COPY capture/pyproject.toml capture/README.md ./capture/
COPY packages/ ./packages/
RUN uv sync --frozen --no-dev --no-editable --package ovenbird --python /usr/local/bin/python3

# Simulated HeishaMon for the dev stack (target heishamon-sim). These stages are not
# ancestors of the runtime stage, so the production image holds no simulator code or data.
FROM python:3.14-slim@sha256:9aaa474097d094040649f2162a627c0049b408f52138d980916788d80f04802f AS sim-build
COPY --from=ghcr.io/astral-sh/uv:0.13.7@sha256:96f40d3904aad8d0bd010539001d36c8e2188b981e1334471a90c4a1d93bb490 /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
WORKDIR /src
COPY pyproject.toml uv.lock .python-version ./
COPY capture/pyproject.toml capture/README.md ./capture/
COPY capture/src/ ./capture/src/
COPY packages/ ./packages/
RUN uv sync --frozen --no-dev --no-editable --package ovenbird-sim --python /usr/local/bin/python3

FROM python:3.14-slim@sha256:9aaa474097d094040649f2162a627c0049b408f52138d980916788d80f04802f AS heishamon-sim
ENV PATH=/opt/venv/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1
RUN useradd --system --uid 10002 --no-create-home --shell /usr/sbin/nologin heishamon-sim
COPY --from=sim-build /src/.venv /opt/venv
USER 10002:10002
ENTRYPOINT ["python", "-m", "ovenbird_sim.heishamon"]
CMD ["--host", "mosquitto", "--port", "1883", "--scenario", "cold-week", "--speed", "60"]

# House-model learner (target learner): refits the house model on the service's history
# snapshot and writes JSON into the models directory the service reads. It carries the
# scientific stack (numpy, scipy), so it is its own image; the runtime stage below stays
# without it. It runs as its own user (uid 10003) in the service's group (gid 10001) and
# needs two sub-directories of the data volume only: learner/ read-only (the service
# writes learner-config.json and history.snapshot.db there, mode 0750/0640) at /learner,
# and models/ (mode 2770, its output) at /models. Never mount the whole data volume: it
# holds options.json, config.db and the live history. See packages/service/README.md.
FROM python:3.14-slim@sha256:9aaa474097d094040649f2162a627c0049b408f52138d980916788d80f04802f AS learner
ENV PATH=/opt/venv/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1
RUN groupadd --system --gid 10001 ovenbird \
    && useradd --system --uid 10003 --gid ovenbird --no-create-home --shell /usr/sbin/nologin learner
COPY --from=sim-build /src/.venv /opt/venv
USER 10003:10001
ENTRYPOINT ["python", "-m", "ovenbird_sim.learn"]
CMD ["--history", "/learner/history.snapshot.db", "--config", "/learner/learner-config.json", \
     "--models", "/models", "--every-h", "168"]

FROM python:3.14-slim@sha256:9aaa474097d094040649f2162a627c0049b408f52138d980916788d80f04802f AS runtime
ENV PATH=/opt/venv/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    OVENBIRD_DATA_DIR=/data \
    OVENBIRD_UI_DIR=/opt/ovenbird/ui \
    OVENBIRD_HTTP_PORT=8099 \
    OVENBIRD_UID=10001 \
    OVENBIRD_GID=10001
RUN groupadd --system --gid 10001 ovenbird \
    && useradd --system --uid 10001 --gid ovenbird --no-create-home --shell /usr/sbin/nologin ovenbird \
    && mkdir /data \
    && chown ovenbird:ovenbird /data \
    && chmod 0750 /data
COPY --from=build /src/.venv /opt/venv
COPY --from=ui /ui/dist /opt/ovenbird/ui
# No USER: the launcher starts as root only to give /data to uid 10001, then drops to it
# before the service starts. `docker run --user 10001:10001` skips the root phase entirely.
WORKDIR /data
VOLUME ["/data"]
EXPOSE 8099
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD ["python", "-m", "ovenbird.launcher", "--check"]
ENTRYPOINT ["python", "-m", "ovenbird.launcher"]
