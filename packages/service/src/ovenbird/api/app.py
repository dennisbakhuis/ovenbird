"""FastAPI application: API v1 (``docs/api-v1.md``) plus the static UI with SPA fallback.

The read-only endpoints live here; the configuration (:mod:`ovenbird.api.config_api`),
control (:mod:`ovenbird.api.control_api`), pump settings (:mod:`ovenbird.api.pump_api`),
data (:mod:`ovenbird.api.data_api`) and weather (:mod:`ovenbird.api.weather_api`)
routers add the rest, every
state-changing one checked by role and the request rules of :mod:`ovenbird.api.deps`. Every
response carries a Content-Security-Policy (no third-party sources) and
``X-Content-Type-Options: nosniff``; outside ingress the page may only be framed by
itself. No CORS headers are ever sent.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from collections.abc import AsyncIterator, Callable, Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Annotated, Any, Final

from fastapi import APIRouter, FastAPI, HTTPException, Query, Request, WebSocket
from fastapi.responses import FileResponse, JSONResponse, Response
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from ovenbird import __version__
from ovenbird.api.archive_api import build_archive_router
from ovenbird.api.auth import BasicAuthMiddleware, LiveTickets, OriginCheckMiddleware, Role
from ovenbird.api.config_api import HaCheck, build_config_router
from ovenbird.api.control_api import build_control_router
from ovenbird.api.data_api import DataDeps, build_data_router
from ovenbird.api.deps import RefusalAudit, SupervisionDeps, require_role
from ovenbird.api.export import (
    ALARM_COLUMNS,
    COMMAND_COLUMNS,
    DECISION_COLUMNS,
    HISTORY_COLUMNS,
    Format,
    csv_response,
)
from ovenbird.api.insight_api import build_insight_router
from ovenbird.api.models.app import (
    AlarmsPage,
    CommandsPage,
    DecisionsLatest,
    DecisionsPage,
    Health,
    History,
    LiveTicket,
    Snapshot,
)
from ovenbird.api.models.base import returns
from ovenbird.api.notify_api import build_notify_router
from ovenbird.api.pump_api import build_pump_router
from ovenbird.api.replay_api import ReplayDeps, build_replay_router
from ovenbird.api.shadow_api import build_shadow_router
from ovenbird.api.system_api import build_system_router
from ovenbird.api.trial_api import build_trial_router
from ovenbird.api.weather_api import build_weather_router
from ovenbird.api.ws import Broadcaster
from ovenbird.backoff import Backoff
from ovenbird.clock import iso_from_unix, iso_z
from ovenbird.config import Settings
from ovenbird.configstore import ConfigManager
from ovenbird.control.loop import ControlLoop
from ovenbird.hacheck import check_connection
from ovenbird.history import HistoryWriter
from ovenbird.history.journal import (
    latest_decision,
    query_alarms,
    query_commands,
    query_decisions,
)
from ovenbird.history.query import HistoryQueryError, default_step, query_series
from ovenbird.mqttsetup import MqttSetup
from ovenbird.payloads import Json
from ovenbird.pump.settings import PumpSettings
from ovenbird.replay.jobs import ReplayJobs
from ovenbird.runtime import Runtime
from ovenbird.system.facts import Facts
from ovenbird.trial.supervision import Supervision
from ovenbird.weather import WeatherService

LOGGER = logging.getLogger("ovenbird.api")
API_PREFIX: Final = "/api/v1"
HEALTH_PATH: Final = f"{API_PREFIX}/health"
PUBLIC_ICONS: Final = frozenset({"/favicon.svg", "/favicon.ico", "/apple-touch-icon.png"})
DEFAULT_WINDOW: Final = timedelta(hours=24)
MAX_SIGNALS: Final = 50
DEFAULT_LIMIT: Final = 500
MAX_LIMIT: Final = 5000
NO_CACHE: Final = {"Cache-Control": "no-cache"}
NO_STORE: Final = {"Cache-Control": "no-store"}
CSP: Final = (
    "default-src 'self'; connect-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'"
)
FRAME_ANCESTORS: Final = "; frame-ancestors 'self'"


class SecurityHeadersMiddleware:
    """ASGI middleware adding the Content-Security-Policy and ``nosniff`` to every response.

    Parameters
    ----------
    app
        Wrapped application.
    framed
        Served inside Home Assistant's ingress frame (no ``frame-ancestors``).
    """

    def __init__(self, app: ASGIApp, *, framed: bool) -> None:
        self.app = app
        policy = CSP if framed else CSP + FRAME_ANCESTORS
        self._headers = [
            (b"content-security-policy", policy.encode()),
            (b"x-content-type-options", b"nosniff"),
        ]

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Add the headers to the response start."""
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def with_headers(message: Message) -> None:
            """Replace the security headers of the response start before forwarding it."""
            if message["type"] == "http.response.start":
                headers = [
                    (key, value)
                    for key, value in message.get("headers", [])
                    if key.lower() not in {b"content-security-policy", b"x-content-type-options"}
                ]
                message = {**message, "headers": [*headers, *self._headers]}
            await send(message)

        await self.app(scope, receive, with_headers)


def parse_time(raw: str, name: str) -> datetime:
    """Parse an ISO 8601 query parameter; naive times are taken as UTC.

    Raises
    ------
    HTTPException
        400 when the value is not ISO 8601.
    """
    text = raw.strip()
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        raise HTTPException(400, f"{name} is not an ISO 8601 time") from None
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)


def static_file(root: Path, path: str) -> Path | None:
    """Resolve ``path`` inside ``root`` to an existing file, refusing escapes."""
    base = root.resolve()
    candidate = (base / path).resolve()
    if not candidate.is_relative_to(base) or not candidate.is_file():
        return None
    return candidate


def window(runtime: Runtime, start: str | None, end: str | None) -> tuple[datetime, datetime]:
    """Resolve a ``from``/``to`` query window; the last 24 h of the service clock by default.

    Raises
    ------
    HTTPException
        400 for unparsable or reversed bounds.
    """
    until = parse_time(end, "to") if end is not None else runtime.clock().wall
    since = parse_time(start, "from") if start is not None else until - DEFAULT_WINDOW
    if since >= until:
        raise HTTPException(400, "from must be before to")
    return since, until


def build_router(
    runtime: Runtime,
    settings: Settings,
    broadcaster: Broadcaster,
    control: ControlLoop | None = None,
    tickets: LiveTickets | None = None,
) -> APIRouter:
    """Return the API v1 routes.

    Parameters
    ----------
    runtime
        Live signal store and clock the routes read.
    settings
        Service settings (history path, tokens and roles).
    broadcaster
        Fan-out the WebSocket route serves its clients from.
    control
        Control loop whose latest decision and status are served; ``None`` without one.
    tickets
        Issuer of the one-time WebSocket tickets; a fresh one when omitted.
    """
    router = APIRouter(prefix=API_PREFIX)
    passes = tickets or LiveTickets()

    @router.get("/health", **returns(Health))
    async def health() -> Json:
        """Return the service health."""
        return runtime.health()

    @router.get("/snapshot", **returns(Snapshot))
    async def snapshot() -> Json:
        """Return the latest value of every signal."""
        return runtime.snapshot()

    @router.get("/history", **returns(History, encoder=True))
    def history(
        signals: Annotated[str, Query()],
        start: Annotated[str | None, Query(alias="from")] = None,
        end: Annotated[str | None, Query(alias="to")] = None,
        step: Annotated[int | None, Query()] = None,
        output: Annotated[Format, Query(alias="format")] = "json",
    ) -> Json | Response:
        """Return the history of the requested signals as JSON or CSV.

        Parameters
        ----------
        signals
            Comma-separated signal ids.
        start
            Start of the window as ISO time; 24 h before ``end`` by default.
        end
            End of the window as ISO time; now by default.
        step
            Resolution in seconds; chosen from the window length when omitted.
        output
            Response format: ``json`` or ``csv``.
        """
        ids = list(dict.fromkeys(part.strip() for part in signals.split(",") if part.strip()))
        if not ids:
            raise HTTPException(400, "signals must name at least one signal id")
        if len(ids) > MAX_SIGNALS:
            raise HTTPException(400, f"at most {MAX_SIGNALS} signals per request")
        since, until = window(runtime, start, end)
        t0, t1 = since.timestamp(), until.timestamp()
        resolved = default_step(t0, t1) if step is None else step
        try:
            series = query_series(
                settings.history_path, ids, t0, t1, resolved, staleness=runtime.store.policy
            )
        except HistoryQueryError as exc:
            raise HTTPException(400, str(exc)) from None
        if output == "csv":
            rows = (
                {"signal": signal, "unit": data.unit, "at": iso_from_unix(ts), "value": value}
                for signal, data in series.items()
                for ts, value in data.points
            )
            return csv_response("history", HISTORY_COLUMNS, rows, iso_z(since))
        return {
            "from": iso_z(since),
            "to": iso_z(until),
            "step": resolved,
            "series": {
                signal: {
                    "unit": data.unit,
                    "points": [[iso_from_unix(ts), value] for ts, value in data.points],
                }
                for signal, data in series.items()
            },
        }

    @router.get("/decisions", **returns(DecisionsPage, encoder=True))
    def decisions(
        start: Annotated[str | None, Query(alias="from")] = None,
        end: Annotated[str | None, Query(alias="to")] = None,
        limit: Annotated[int, Query(ge=1, le=MAX_LIMIT)] = DEFAULT_LIMIT,
        output: Annotated[Format, Query(alias="format")] = "json",
    ) -> Json | Response:
        """Return the journalled control decisions of a window as JSON or CSV.

        Parameters
        ----------
        start
            Start of the window as ISO time; 24 h before ``end`` by default.
        end
            End of the window as ISO time; now by default.
        limit
            Maximum number of rows (the newest ones).
        output
            Response format: ``json`` or ``csv``.
        """
        since, until = window(runtime, start, end)
        rows = query_decisions(settings.history_path, since.timestamp(), until.timestamp(), limit)
        if output == "csv":
            payloads = (row.payload() for row in rows)
            return csv_response("decisions", DECISION_COLUMNS, payloads, iso_z(since))
        return {
            "from": iso_z(since),
            "to": iso_z(until),
            "limit": limit,
            "decisions": [row.payload() for row in rows],
        }

    @router.get("/decisions/latest", **returns(DecisionsLatest))
    def decisions_latest() -> Json:
        """Return the latest control decision and the control status."""
        decision = control.latest if control is not None else None
        if decision is None:
            row = latest_decision(settings.history_path)
            decision = row.payload() if row is not None else None
        return {
            "decision": decision,
            "control": control.status() if control is not None else None,
        }

    @router.get("/alarms", **returns(AlarmsPage, encoder=True))
    def alarms(
        start: Annotated[str | None, Query(alias="from")] = None,
        end: Annotated[str | None, Query(alias="to")] = None,
        limit: Annotated[int, Query(ge=1, le=MAX_LIMIT)] = DEFAULT_LIMIT,
        output: Annotated[Format, Query(alias="format")] = "json",
    ) -> Json | Response:
        """Return the journalled alarm transitions of a window as JSON or CSV.

        Parameters
        ----------
        start
            Start of the window as ISO time; 24 h before ``end`` by default.
        end
            End of the window as ISO time; now by default.
        limit
            Maximum number of rows (the newest ones).
        output
            Response format: ``json`` or ``csv``.
        """
        since, until = window(runtime, start, end)
        rows = query_alarms(settings.history_path, since.timestamp(), until.timestamp(), limit)
        if output == "csv":
            events = (row.to_json() for row in rows)
            return csv_response("alarms", ALARM_COLUMNS, events, iso_z(since))
        active = control.alarms.active() if control is not None else ()
        return {
            "from": iso_z(since),
            "to": iso_z(until),
            "limit": limit,
            "active": [alarm.to_json() for alarm in active],
            "events": [row.to_json() for row in rows],
        }

    @router.get("/commands", **returns(CommandsPage, encoder=True))
    def commands(
        start: Annotated[str | None, Query(alias="from")] = None,
        end: Annotated[str | None, Query(alias="to")] = None,
        limit: Annotated[int, Query(ge=1, le=MAX_LIMIT)] = DEFAULT_LIMIT,
        output: Annotated[Format, Query(alias="format")] = "json",
    ) -> Json | Response:
        """Return the journalled command events of a window as JSON or CSV.

        Parameters
        ----------
        start
            Start of the window as ISO time; 24 h before ``end`` by default.
        end
            End of the window as ISO time; now by default.
        limit
            Maximum number of rows (the newest ones).
        output
            Response format: ``json`` or ``csv``.
        """
        since, until = window(runtime, start, end)
        rows = query_commands(settings.history_path, since.timestamp(), until.timestamp(), limit)
        if output == "csv":
            events = (row.to_json() for row in rows)
            return csv_response("commands", COMMAND_COLUMNS, events, iso_z(since))
        return {
            "from": iso_z(since),
            "to": iso_z(until),
            "limit": limit,
            "commands": [row.to_json() for row in rows],
        }

    @router.post("/live/ticket", **returns(LiveTicket))
    async def live_ticket(request: Request) -> JSONResponse:
        """Issue a short-lived ticket for opening the WebSocket."""
        who = require_role(request, settings, Role.READ)
        body = {"ticket": passes.issue(who.role), "expires_in": passes.ttl}
        return JSONResponse(body, headers=NO_STORE)

    @router.websocket("/ws")
    async def ws(websocket: WebSocket) -> None:
        """Serve one live WebSocket client."""
        await broadcaster.serve(websocket)

    return router


def add_ui(app: FastAPI, ui_dir: Path) -> None:
    """Serve the built UI at ``/``; unknown extension-less non-API paths get ``index.html``."""

    @app.get("/{path:path}", include_in_schema=False)
    async def ui(path: str) -> Response:
        """Serve a UI file, falling back to ``index.html`` for client-side routes."""
        if path == "api" or path.startswith("api/"):
            return JSONResponse({"detail": "Not Found"}, status_code=404)
        found = static_file(ui_dir, path) if path else None
        if found is not None:
            headers = NO_CACHE if found.name == "index.html" else None
            return FileResponse(found, headers=headers)
        last = path.rsplit("/", 1)[-1]
        index = static_file(ui_dir, "index.html")
        if "." in last or index is None:
            return Response("Not Found", status_code=404, media_type="text/plain")
        return FileResponse(index, headers=NO_CACHE)


async def _keep_running(name: str, factory: Callable[[], Any]) -> None:
    """Run ``factory()`` forever, restarting it with a backoff after a crash."""
    backoff = Backoff()
    while True:
        started = time.monotonic()
        try:
            await factory()
        except asyncio.CancelledError:
            raise
        except Exception:
            LOGGER.exception("%s crashed", name)
        delay = backoff.next_delay(time.monotonic() - started)
        await asyncio.sleep(delay)


def create_app(
    runtime: Runtime,
    settings: Settings,
    *,
    broadcaster: Broadcaster | None = None,
    control: ControlLoop | None = None,
    config: ConfigManager | None = None,
    pumps: PumpSettings | None = None,
    weather: WeatherService | None = None,
    signals: Callable[[], Mapping[str, Any]] | None = None,
    supervision: Supervision | None = None,
    ha_check: HaCheck = check_connection,
    writer: HistoryWriter | None = None,
    mqtt: MqttSetup | None = None,
) -> FastAPI:
    """Build the FastAPI application.

    Parameters
    ----------
    runtime
        Shared service state.
    settings
        Settings (UI directory, history path, credentials).
    broadcaster
        WebSocket fan-out; one with default intervals when omitted.
    control
        Control loop whose latest decision and status the API reports.
    config
        Configuration manager; without it there are no configuration endpoints,
        no pause/resume and no audit trail.
    pumps
        Pump settings service; without it there are no ``pump/settings`` endpoints.
    weather
        Weather component; without it there is no ``weather`` endpoint.
    signals
        Signal picker candidates (``config/signals``).
    supervision
        Shadow, trial, notification and system facts; one with in-memory facts
        and no notifier when omitted.
    ha_check
        Tests a Home Assistant connection (``config/ha/test``; tests pass a fake).
    writer
        History writer (retention in effect, compaction); without it
        ``history/compact`` is refused.
    mqtt
        Broker test and change (``config/mqtt``); without it those endpoints
        answer 404.

    Returns
    -------
    FastAPI
        The application; its lifespan runs the broadcaster.
    """
    fanout = broadcaster or Broadcaster(runtime)
    replays = ReplayJobs(lambda: (config.settings if config is not None else settings).history_path)

    @contextlib.asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        """Run the broadcaster for the life of the app and close the replay jobs on exit."""
        task = asyncio.create_task(_keep_running("websocket broadcaster", fanout.run))
        try:
            yield
        finally:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
            await replays.close()

    app = FastAPI(
        title="ovenbird",
        version=__version__,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
    )
    app.state.broadcaster = fanout
    audit = RefusalAudit(config.audit if config is not None else None)
    tickets = LiveTickets()
    app.include_router(build_router(runtime, settings, fanout, control, tickets))
    app.include_router(
        build_control_router(
            settings,
            control,
            config,
            audit,
            lambda start, end: window(runtime, start, end),
        ),
        prefix=API_PREFIX,
    )
    if config is not None:
        app.include_router(
            build_config_router(
                settings,
                config,
                audit,
                control=control,
                signals=(lambda: dict(signals())) if signals is not None else None,
                ha_check=ha_check,
                mqtt=mqtt,
            ),
            prefix=API_PREFIX,
        )
    app.include_router(
        build_insight_router(
            runtime, lambda: config.settings if config is not None else settings, control
        ),
        prefix=API_PREFIX,
    )
    facts_view = supervision or Supervision(
        runtime,
        lambda: config.settings if config is not None else settings,
        control,
        config,
        None,
        Facts(config.store if config is not None else None),
        runtime.clock(),
    )
    supervised = SupervisionDeps(
        settings, facts_view, audit, lambda start, end: window(runtime, start, end)
    )
    app.include_router(build_shadow_router(supervised), prefix=API_PREFIX)
    app.include_router(build_trial_router(supervised), prefix=API_PREFIX)
    app.include_router(build_notify_router(supervised), prefix=API_PREFIX)
    app.include_router(build_system_router(supervised), prefix=API_PREFIX)
    data = DataDeps(runtime, settings, config, writer, audit, parse_time)
    app.include_router(build_data_router(data), prefix=API_PREFIX)
    app.include_router(build_archive_router(data), prefix=API_PREFIX)
    app.include_router(
        build_replay_router(ReplayDeps(runtime, settings, config, audit, parse_time, replays)),
        prefix=API_PREFIX,
    )
    if pumps is not None:
        app.include_router(build_pump_router(settings, pumps, audit), prefix=API_PREFIX)
    if weather is not None:
        app.include_router(
            build_weather_router(settings, runtime, weather, control), prefix=API_PREFIX
        )
    add_ui(app, settings.ui_dir)
    password = settings.admin_password
    token = settings.operate_token
    app.add_middleware(
        BasicAuthMiddleware,
        username=settings.admin_username,
        password=password.get_secret_value() if password is not None else None,
        exempt={HEALTH_PATH, *PUBLIC_ICONS},
        trusted_sources=settings.trusted_sources,
        operate_token=token.get_secret_value() if token is not None else None,
        required=settings.auth_required,
        tickets=tickets,
    )
    app.add_middleware(
        OriginCheckMiddleware,
        allowed_origins=settings.http_allowed_origins,
        trusted_sources=settings.trusted_sources,
    )
    app.add_middleware(SecurityHeadersMiddleware, framed=settings.ingress_mode)
    return app
