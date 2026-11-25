"""Read-only Home Assistant input over the WebSocket API.

The client sends only read commands: ``auth``, ``get_config``, the registry lists
(``config/entity_registry/list_for_display``, ``config/device_registry/list``,
``config/area_registry/list``), ``subscribe_entities`` and ``get_states``, so it
cannot change anything in Home Assistant. Every state HA reports becomes a reading
built by the core's :func:`~ovenbird_core.ha_reading`, with HA's ``last_reported``
(or ``last_updated``) as the source timestamp.

What it reads
-------------
The input follows the configuration: :meth:`HaInput.configure` takes the URL, the
token, the entities whose state is read (the ``ha/`` signals of the configuration
plus the optional ``ha_entities``) and the thermostat attributes
(``ha/climate.x#current_temperature``). A changed URL, token or entity set closes
the session and reconnects at once; without a URL and token the input waits.

Units
-----
Temperatures in °F or K become °C in the core. A temperature input (the room,
cross-check, stove reference and outside signals) without a temperature unit, or with
one ovenbird does not know, is used only when Home Assistant's unit system is metric
(``get_config``: ``unit_system.temperature`` is ``°C``); otherwise it is refused: its
view carries the reason ``unit: ...`` naming the signal and is not fresh, so the
controller treats it as a missing value. A thermostat's ``current_temperature`` has HA's
temperature unit.

Freshness
---------
``subscribe_entities`` forwards state *changes* only, and its compressed states
carry no ``last_reported``; a sensor that keeps reporting the same value (a stable
room temperature) therefore produces no event at all. To confirm such values the
client re-reads the full states with ``get_states`` right after subscribing and
then every ``refresh_interval`` seconds (5 min by default). A full state carries
``last_reported``, the last time the device reported a value, even an unchanged
one; the store moves the value's confirmation back to that moment. So:

* a value is confirmed when it changes, and at every re-read for as long as the
  device keeps reporting it;
* a device that stops reporting is not confirmed by the re-read (its
  ``last_reported`` stays old), so the value ages out after the signal's maximum
  age (30 min for HA entities);
* ``unavailable``/``unknown`` states invalidate the value at once (see
  :class:`~ovenbird_core.StateStore`).

Every reading also carries HA's ``last_changed``, so the store knows how long a
value has been held, also right after a restart.

Entity index
------------
Every ``get_states`` result also refreshes :attr:`HaInput.index`, the ``sensor.*`` and
``climate.*`` entities with their name, unit, device class and state (the
configuration's signal pickers), and :attr:`HaInput.home`, the latitude and longitude
of ``zone.home`` (the default weather location). The registry lists give each
entity's device and area (:meth:`HaInput.device_of`, :meth:`HaInput.area_of`); when
they fail the pickers just lack them. Everything is only read, never written.

Link state
----------
The client reports its link to the store (:meth:`~ovenbird_core.StateStore.set_link`):
connected after subscribing, *confirmed* at every successful ``get_states``
re-read, down when the connection ends. A held room value (``on_change`` sensor
profile) counts as held only while the link is up and confirmed within the store's
window; otherwise the normal 1800 s limit applies.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Final
from urllib.parse import urlsplit, urlunsplit

from pydantic import SecretStr
from websockets.asyncio.client import ClientConnection, connect
from websockets.exceptions import WebSocketException

from ovenbird.backoff import Backoff
from ovenbird.runtime import Runtime
from ovenbird_core import ParseError, ParseErrorKind, Reading, SourceKind, ha_reading
from ovenbird_core.inputs import CELSIUS, parse_timestamp
from ovenbird_core.readings import echo

LOGGER = logging.getLogger("ovenbird.ha")
WS_LOGGER = logging.getLogger("ovenbird.ha.websockets")
WS_LOGGER.setLevel(logging.WARNING)
SUBSCRIBE_ID: Final = 1
CONFIG_ID: Final = 2
ENTITY_REGISTRY_ID: Final = 3
DEVICE_REGISTRY_ID: Final = 4
AREA_REGISTRY_ID: Final = 5
FIRST_READ_ID: Final = 6
SESSION_REQUESTS: Final = (
    (CONFIG_ID, "get_config"),
    (ENTITY_REGISTRY_ID, "config/entity_registry/list_for_display"),
    (DEVICE_REGISTRY_ID, "config/device_registry/list"),
    (AREA_REGISTRY_ID, "config/area_registry/list"),
)
OPEN_TIMEOUT_S: Final = 20.0
AUTH_TIMEOUT_S: Final = 20.0
MAX_MESSAGE_BYTES: Final = 32 * 1024 * 1024
LARGE_MESSAGE_BYTES: Final = 256 * 1024
REFRESH_INTERVAL_S: Final = 300.0
INDEX_DOMAINS: Final = ("sensor.", "climate.")
HOME_ZONE: Final = "zone.home"
SUPERVISOR_HOST: Final = "supervisor"
SUPERVISOR_CORE_PATH: Final = "/core"
WEBSOCKET_SUFFIX: Final = "/websocket"

type Connector = Callable[[str], Any]


class HaAuthError(RuntimeError):
    """Home Assistant rejected the access token."""


class HaProtocolError(RuntimeError):
    """Home Assistant answered with something the client does not expect."""


def websocket_url(base_url: str) -> str:
    """Turn an HA base URL into its WebSocket API URL, keeping any base path.

    Parameters
    ----------
    base_url
        ``http``, ``https``, ``ws`` or ``wss`` URL: an HA base URL
        (``http://host:8123``, ``https://proxy.example/ha``), the Supervisor proxy
        (``http://supervisor/core``) or a WebSocket URL already ending in
        ``/websocket``.

    Returns
    -------
    str
        ``<base path>/api/websocket`` for Home Assistant itself,
        ``/core/websocket`` for the Supervisor proxy, or the given WebSocket path,
        with ``http`` mapped to ``ws`` and ``https`` to ``wss``.
    """
    parts = urlsplit(base_url.strip())
    scheme = {"http": "ws", "https": "wss", "ws": "ws", "wss": "wss"}.get(parts.scheme.lower())
    if scheme is None or not parts.netloc:
        raise ValueError("HA URL must be an http(s) or ws(s) URL")
    path = parts.path.rstrip("/")
    if path.endswith(WEBSOCKET_SUFFIX):
        target = path
    elif parts.hostname == SUPERVISOR_HOST and path == SUPERVISOR_CORE_PATH:
        target = path + WEBSOCKET_SUFFIX
    else:
        target = path + "/api" + WEBSOCKET_SUFFIX
    return urlunsplit((scheme, parts.netloc, target, "", ""))


def _timestamp(raw: Any) -> float | None:
    if isinstance(raw, bool) or not isinstance(raw, int | float):
        return None
    return float(raw)


def _iso_timestamp(raw: Any) -> float | None:
    parsed = parse_timestamp(raw)
    return None if parsed is None else parsed.timestamp()


@dataclass
class EntityState:
    """Last known state of one entity, rebuilt from compressed ``subscribe_entities`` data.

    Parameters
    ----------
    state
        State string.
    attributes
        Attributes.
    last_updated, last_reported, last_changed
        HA timestamps in unix seconds.
    """

    state: str
    attributes: dict[str, Any] = field(default_factory=dict)
    last_updated: float | None = None
    last_reported: float | None = None
    last_changed: float | None = None

    @classmethod
    def from_full(cls, data: dict[str, Any]) -> EntityState:
        """Build from a full state object (``get_states``) with ISO 8601 timestamps."""
        attributes = data.get("attributes")
        last_updated = _iso_timestamp(data.get("last_updated")) or _iso_timestamp(
            data.get("last_changed")
        )
        return cls(
            state=str(data.get("state", "")),
            attributes=dict(attributes) if isinstance(attributes, dict) else {},
            last_updated=last_updated,
            last_reported=_iso_timestamp(data.get("last_reported")) or last_updated,
            last_changed=_iso_timestamp(data.get("last_changed")),
        )

    @classmethod
    def from_compressed(cls, data: dict[str, Any]) -> EntityState:
        """Build from a full compressed state (``s``, ``a``, ``lc`` and optional ``lu``/``lr``)."""
        last_changed = _timestamp(data.get("lc"))
        last_updated = _timestamp(data.get("lu")) or last_changed
        attributes = data.get("a")
        return cls(
            state=str(data.get("s", "")),
            attributes=dict(attributes) if isinstance(attributes, dict) else {},
            last_updated=last_updated,
            last_reported=_timestamp(data.get("lr")) or last_updated,
            last_changed=last_changed,
        )

    def apply_diff(self, diff: dict[str, Any]) -> None:
        """Apply a change diff (``+`` additions, ``-`` removals)."""
        additions = diff.get("+")
        if isinstance(additions, dict):
            if "s" in additions:
                self.state = str(additions["s"])
            changed = _timestamp(additions.get("lc"))
            updated = _timestamp(additions.get("lu"))
            if changed is not None:
                self.last_updated = self.last_reported = self.last_changed = changed
            elif updated is not None:
                self.last_updated = self.last_reported = updated
            reported = _timestamp(additions.get("lr"))
            if reported is not None:
                self.last_reported = reported
            if isinstance(additions.get("a"), dict):
                self.attributes.update(additions["a"])
        removals = diff.get("-")
        if isinstance(removals, dict):
            for key in removals.get("a") or ():
                self.attributes.pop(key, None)

    @property
    def unit(self) -> str | None:
        """``unit_of_measurement`` attribute, if any."""
        unit = self.attributes.get("unit_of_measurement")
        return unit if isinstance(unit, str) else None


def _location(attributes: Any) -> tuple[float, float] | None:
    if not isinstance(attributes, dict):
        return None
    values: list[float] = []
    for key in ("latitude", "longitude"):
        value = attributes.get(key)
        if isinstance(value, bool) or not isinstance(value, int | float):
            return None
        values.append(float(value))
    return values[0], values[1]


def _utc(timestamp: float | None) -> datetime | None:
    return None if timestamp is None else datetime.fromtimestamp(timestamp, UTC)


def _text(raw: Any) -> str | None:
    return raw if isinstance(raw, str) and raw else None


def _attribute_text(state: EntityState, attribute: str) -> str:
    if state.state.strip().lower() in {"unavailable", "unknown"}:
        return state.state
    raw = state.attributes.get(attribute)
    if raw is None:
        return "unknown"
    return str(raw)


class HaInput:
    """Subscribe to HA entities and apply their states to the runtime.

    Parameters
    ----------
    url
        HA base URL or WebSocket URL; ``None`` until the connection is configured.
    token
        Long-lived access token; never logged.
    entities
        Entity ids whose state is read (signal ``ha/<entity_id>``).
    runtime
        Receives readings and the connection state.
    attributes
        ``(entity_id, attribute)`` pairs read as ``ha/<entity_id>#<attribute>``.
    temperature
        Signals used as a temperature (the unit rule of the module docstring).
    connector
        Opens a WebSocket connection (async context manager) for a URL.
    backoff
        Reconnect delays.
    refresh_interval
        Seconds between ``get_states`` re-reads that confirm unchanged values
        (see the module docstring).
    """

    def __init__(
        self,
        url: str | None,
        token: SecretStr | None,
        entities: tuple[str, ...],
        runtime: Runtime,
        *,
        attributes: tuple[tuple[str, str], ...] = (),
        temperature: frozenset[str] = frozenset(),
        connector: Connector | None = None,
        backoff: Backoff | None = None,
        refresh_interval: float = REFRESH_INTERVAL_S,
    ) -> None:
        self.url = None if url is None or token is None else websocket_url(url)
        self._token = token
        self.entities = entities
        self.attributes = attributes
        self.temperature = temperature
        self.runtime = runtime
        self._connector = connector or _default_connector
        self.backoff = backoff or Backoff(cap=300.0)
        self.refresh_interval = refresh_interval
        self._states: dict[str, EntityState] = {}
        self._next_id = FIRST_READ_ID
        self._pending_reads: set[int] = set()
        self._ws: ClientConnection | None = None
        self._closing: asyncio.Task[None] | None = None
        self._wake: asyncio.Event | None = None
        self._reconnect = False
        self.readings = 0
        self.refreshes = 0
        self.index: dict[str, EntityState] = {}
        self.home: tuple[float, float] | None = None
        self.temperature_unit: str | None = None
        self.ha_version: str | None = None
        self._entity_registry: dict[str, tuple[str | None, str | None]] = {}
        self._device_areas: dict[str, str] = {}
        self._area_names: dict[str, str] = {}

    @property
    def configured(self) -> bool:
        """Whether a URL and a token are set."""
        return self.url is not None and self._token is not None

    @property
    def metric(self) -> bool:
        """Whether Home Assistant's unit system is metric (known from ``get_config``)."""
        return self.temperature_unit == CELSIUS

    @property
    def subscription(self) -> tuple[str, ...]:
        """Every entity the session subscribes to (state and attribute signals)."""
        return tuple(dict.fromkeys((*self.entities, *(item[0] for item in self.attributes))))

    def configure(
        self,
        url: str | None,
        token: SecretStr | None,
        entities: tuple[str, ...],
        *,
        attributes: tuple[tuple[str, str], ...] = (),
        temperature: frozenset[str] = frozenset(),
    ) -> bool:
        """Follow a new configuration: connection, entities, attributes, temperature inputs.

        A new URL, token or subscription closes the current session; :meth:`run`
        reconnects at once (or waits while nothing is configured). A changed set of
        temperature inputs only re-applies the known states.

        Returns
        -------
        bool
            Whether the session has to reconnect.
        """
        target = None if url is None or token is None else websocket_url(url)
        secret = None if token is None else token.get_secret_value()
        current = None if self._token is None else self._token.get_secret_value()
        subscription = tuple(dict.fromkeys((*entities, *(item[0] for item in attributes))))
        reconnect = target != self.url or secret != current or subscription != self.subscription
        if target != self.url:
            self.temperature_unit = None
            self.ha_version = None
            self.index = {}
            self.home = None
        temperature_changed = temperature != self.temperature
        self.url = target
        self._token = token
        self.entities = entities
        self.attributes = attributes
        self.temperature = temperature
        if reconnect:
            LOGGER.info(
                "HA input follows the configuration: %s, %d entities; reconnecting",
                "configured" if self.configured else "not configured",
                len(subscription),
            )
            self._restart()
        elif temperature_changed:
            self._replay_states()
        return reconnect

    def resubscribe(self, entities: tuple[str, ...]) -> bool:
        """Subscribe to a new entity set (a new configuration's room signals).

        ``subscribe_entities`` cannot be changed on an open session, so the current
        session is closed and :meth:`run` reconnects with the new set.

        Parameters
        ----------
        entities
            Entity ids to subscribe to.

        Returns
        -------
        bool
            Whether the set changed.
        """
        if entities == self.entities:
            return False
        return self.configure(
            None if self.url is None else self.url,
            self._token,
            entities,
            attributes=self.attributes,
            temperature=self.temperature,
        )

    def _restart(self) -> None:
        self._reconnect = True
        if self._wake is not None:
            self._wake.set()
        ws = self._ws
        if ws is not None:
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                return
            self._closing = loop.create_task(ws.close())

    def __repr__(self) -> str:
        """Representation without the token."""
        return f"HaInput(url={self.url!r}, entities={self.subscription!r})"

    async def _pause(self, delay: float | None) -> None:
        if self._wake is None:
            self._wake = asyncio.Event()
        if self._reconnect:
            self._reconnect = False
            self._wake.clear()
            return
        try:
            if delay is None:
                await self._wake.wait()
            else:
                await asyncio.wait_for(self._wake.wait(), delay)
        except TimeoutError:
            pass
        self._wake.clear()
        if self._reconnect:
            self._reconnect = False
            self.backoff.reset()

    async def run(self) -> None:
        """Connect, subscribe and ingest forever, reconnecting with backoff.

        Idle while no URL and token are configured; a new configuration ends the
        wait or the backoff delay at once.
        """
        while True:
            if not self.configured:
                await self._pause(None)
                continue
            started = time.monotonic()
            reason = await self.session()
            if self._reconnect:
                await self._pause(0.0)
                continue
            delay = self.backoff.next_delay(time.monotonic() - started)
            LOGGER.warning("HA %s; reconnecting in %.0f s", reason, delay)
            await self._pause(delay)

    async def session(self) -> str:
        """Run one connection until it ends.

        Returns
        -------
        str
            Why the session ended.
        """
        url = self.url
        if url is None or self._token is None:
            return "not configured"
        refresher: asyncio.Task[None] | None = None
        try:
            async with self._connector(url) as ws:
                self._ws = ws
                await self._authenticate(ws)
                for message_id, kind in SESSION_REQUESTS:
                    await ws.send(json.dumps({"id": message_id, "type": kind}))
                subscription = self.subscription
                if subscription:
                    await ws.send(
                        json.dumps(
                            {
                                "id": SUBSCRIBE_ID,
                                "type": "subscribe_entities",
                                "entity_ids": list(subscription),
                            }
                        )
                    )
                self.open_session()
                LOGGER.info("HA connected to %s; subscribed %d entities", url, len(subscription))
                refresher = asyncio.create_task(self._refresh_loop(ws))
                first_event = True
                async for raw in ws:
                    for message in await _decode(raw):
                        if self.handle(message) and first_event:
                            first_event = False
                            self._report_missing()
            return "closed by server"
        except HaAuthError as exc:
            return f"authentication rejected ({exc})"
        except (HaProtocolError, WebSocketException, OSError, TimeoutError, ValueError) as exc:
            return f"connection lost ({type(exc).__name__}: {exc})"
        finally:
            self._ws = None
            if refresher is not None:
                refresher.cancel()
            self.close_session()

    def open_session(self) -> None:
        """Start a session: forget the previous states and reads; the link is up.

        The link counts as confirmed only after a successful ``get_states`` re-read.
        """
        self._states = {}
        self._pending_reads = set()
        self.runtime.ha_connected = True
        self.runtime.set_link(SourceKind.HA, up=True)

    def close_session(self) -> None:
        """End the session: the link is down."""
        self.runtime.ha_connected = False
        self.runtime.set_link(SourceKind.HA, up=False)

    def expect_states(self) -> int:
        """Reserve the id of a ``get_states`` request whose result :meth:`handle` applies."""
        message_id = self._next_id
        self._next_id += 1
        self._pending_reads.add(message_id)
        return message_id

    async def _refresh_loop(self, ws: ClientConnection) -> None:
        backoff = Backoff(initial=1.0, cap=self.refresh_interval)
        while True:
            message_id = self.expect_states()
            try:
                await ws.send(json.dumps({"id": message_id, "type": "get_states"}))
            except WebSocketException:
                self._pending_reads.discard(message_id)
                return
            except Exception:
                self._pending_reads.discard(message_id)
                delay = backoff.next_delay()
                LOGGER.exception("HA state refresh failed; retrying in %.1f s", delay)
                await asyncio.sleep(delay)
                continue
            backoff.reset()
            await asyncio.sleep(self.refresh_interval)

    async def _authenticate(self, ws: ClientConnection) -> None:
        if self._token is None:
            raise HaAuthError("no token")
        hello = await _receive(ws)
        if hello.get("type") != "auth_required":
            raise HaProtocolError(f"expected auth_required, got {hello.get('type')!r}")
        await ws.send(json.dumps({"type": "auth", "access_token": self._token.get_secret_value()}))
        reply = await _receive(ws)
        if reply.get("type") == "auth_invalid":
            raise HaAuthError(str(reply.get("message", "auth_invalid")))
        if reply.get("type") != "auth_ok":
            raise HaProtocolError(f"expected auth_ok, got {reply.get('type')!r}")
        self.ha_version = _text(reply.get("ha_version")) or self.ha_version

    def handle(self, message: dict[str, Any]) -> bool:
        """Process one message.

        Parameters
        ----------
        message
            Decoded HA message.

        Returns
        -------
        bool
            Whether it was a subscription event.

        Raises
        ------
        HaProtocolError
            When the subscription was refused.
        """
        message_id = message.get("id")
        if message_id in self._pending_reads:
            self._pending_reads.discard(message_id)
            self._apply_full_states(message)
            return False
        if message_id == CONFIG_ID:
            self._apply_config(message)
            return False
        if message_id in (ENTITY_REGISTRY_ID, DEVICE_REGISTRY_ID, AREA_REGISTRY_ID):
            self._apply_registry(message_id, message)
            return False
        if message_id != SUBSCRIBE_ID:
            return False
        if message.get("type") == "result":
            if not message.get("success", False):
                raise HaProtocolError(f"subscribe_entities failed: {message.get('error')}")
            return False
        event = message.get("event")
        if message.get("type") != "event" or not isinstance(event, dict):
            return False
        added = event.get("a")
        if isinstance(added, dict):
            for entity_id, data in added.items():
                if isinstance(data, dict):
                    self._states[entity_id] = EntityState.from_compressed(data)
                    self._emit(entity_id)
        changed = event.get("c")
        if isinstance(changed, dict):
            for entity_id, diff in changed.items():
                current = self._states.get(entity_id)
                if current is None or not isinstance(diff, dict):
                    continue
                current.apply_diff(diff)
                self._emit(entity_id)
        for entity_id in event.get("r") or ():
            if self._states.pop(entity_id, None) is not None:
                LOGGER.warning("HA entity %s was removed", entity_id)
        return True

    def _apply_config(self, message: dict[str, Any]) -> None:
        result = message.get("result")
        if message.get("type") != "result" or not message.get("success", False):
            LOGGER.warning("HA get_config failed: %s", message.get("error"))
            return
        if not isinstance(result, dict):
            return
        units = result.get("unit_system")
        unit = _text(units.get("temperature")) if isinstance(units, dict) else None
        self.ha_version = _text(result.get("version")) or self.ha_version
        if unit != self.temperature_unit:
            self.temperature_unit = unit
            LOGGER.info("HA temperature unit: %s", unit or "unknown")
            self._replay_states()

    def _apply_registry(self, message_id: int, message: dict[str, Any]) -> None:
        result = message.get("result")
        if message.get("type") != "result" or not message.get("success", False):
            LOGGER.info("HA registry list %d not available: %s", message_id, message.get("error"))
            return
        if message_id == ENTITY_REGISTRY_ID and isinstance(result, dict):
            entries = result.get("entities")
            self._entity_registry = {
                str(item["ei"]): (_text(item.get("di")), _text(item.get("ai")))
                for item in entries or ()
                if isinstance(item, dict) and isinstance(item.get("ei"), str)
            }
        elif message_id == DEVICE_REGISTRY_ID and isinstance(result, list):
            self._device_areas = {
                str(item["id"]): str(item["area_id"])
                for item in result
                if isinstance(item, dict)
                and isinstance(item.get("id"), str)
                and _text(item.get("area_id")) is not None
            }
        elif message_id == AREA_REGISTRY_ID and isinstance(result, list):
            self._area_names = {
                str(item["area_id"]): str(item["name"])
                for item in result
                if isinstance(item, dict)
                and isinstance(item.get("area_id"), str)
                and isinstance(item.get("name"), str)
            }

    def device_of(self, entity_id: str) -> str | None:
        """Return the HA device id of an entity, when the entity registry was read."""
        entry = self._entity_registry.get(entity_id)
        return None if entry is None else entry[0]

    def area_of(self, entity_id: str) -> str | None:
        """Return the area name of an entity (its own area, else its device's)."""
        entry = self._entity_registry.get(entity_id)
        if entry is None:
            return None
        device, area = entry
        if area is None and device is not None:
            area = self._device_areas.get(device)
        return None if area is None else self._area_names.get(area, area)

    def _apply_full_states(self, message: dict[str, Any]) -> None:
        result = message.get("result")
        if message.get("type") != "result" or not message.get("success", False):
            LOGGER.warning("HA get_states failed: %s", message.get("error"))
            return
        if not isinstance(result, list):
            LOGGER.warning("HA get_states returned no list; ignored")
            return
        wanted = set(self.subscription)
        matched = 0
        index: dict[str, EntityState] = {}
        for item in result:
            if not isinstance(item, dict):
                continue
            entity_id = item.get("entity_id")
            if not isinstance(entity_id, str):
                continue
            if entity_id.startswith(INDEX_DOMAINS):
                index[entity_id] = EntityState.from_full(item)
            elif entity_id == HOME_ZONE:
                self.home = _location(item.get("attributes"))
            if entity_id not in wanted:
                continue
            matched += 1
            self._states[entity_id] = EntityState.from_full(item)
            self._emit(entity_id)
        self.index = index
        LOGGER.debug("HA get_states: %d states, %d configured", len(result), matched)
        self.refreshes += 1
        self.runtime.set_link(SourceKind.HA, up=True, confirmed=True)

    def _report_missing(self) -> None:
        missing = sorted(set(self.subscription) - set(self._states))
        if missing:
            LOGGER.warning("HA entities not found: %s", ", ".join(missing))

    def _replay_states(self) -> None:
        for entity_id in list(self._states):
            self._emit(entity_id)

    def _emit(self, entity_id: str) -> None:
        state = self._states.get(entity_id)
        if state is None:
            return
        reported = _utc(state.last_reported)
        updated = _utc(state.last_updated)
        if entity_id in self.entities:
            self._apply(
                ha_reading(
                    entity_id,
                    state.state,
                    instant=self.runtime.clock(),
                    unit=state.unit,
                    last_reported=reported,
                    last_updated=updated,
                    last_changed=_utc(state.last_changed),
                )
            )
        for owner, attribute in self.attributes:
            if owner != entity_id:
                continue
            self._apply(
                ha_reading(
                    entity_id,
                    _attribute_text(state, attribute),
                    instant=self.runtime.clock(),
                    unit=self.temperature_unit,
                    last_reported=reported,
                    last_updated=updated,
                    last_changed=updated,
                    attribute=attribute,
                )
            )

    def refusal(self, reading: Reading) -> str | None:
        """Return why a temperature input's reading is refused for its unit, or ``None``.

        A numeric reading of a temperature input without °C (after the core's
        conversion of °F and K) is used only when Home Assistant's unit system is
        metric. The reason names the reading's signal.
        """
        if reading.signal not in self.temperature or reading.unit == CELSIUS:
            return None
        if isinstance(reading.value, bool) or not isinstance(reading.value, int | float):
            return None
        if self.metric:
            return None
        what = (
            "no temperature unit"
            if reading.unit is None
            else f"the unit {reading.unit!r} is not a temperature unit"
        )
        system = (
            "Home Assistant's unit system is unknown"
            if self.temperature_unit is None
            else f"Home Assistant's unit system is not metric ({self.temperature_unit})"
        )
        return f"{what} and {system}; {reading.signal} is not used as a temperature"

    def _apply(self, item: Reading | ParseError) -> None:
        if isinstance(item, Reading):
            reason = self.refusal(item)
            if reason is not None:
                error = ParseError(
                    item.signal, ParseErrorKind.UNIT, echo(item.unit or ""), reason, item.observed
                )
                self.runtime.refuse(item, error)
                self.readings += 1
                return
        self.runtime.apply(item)
        self.readings += 1


class NoRedirectConnect(connect):
    """``websockets`` ``connect`` that follows no redirect.

    The access token goes out in the ``auth`` message after the handshake, so a
    followed redirect would hand it to whatever host the redirect names; a 3xx answer
    fails the connection instead.
    """

    def process_redirect(self, exc: Exception) -> Exception | str:
        """Refuse every redirect: return the handshake error unchanged."""
        return exc


def _default_connector(url: str) -> Any:
    return NoRedirectConnect(
        url,
        open_timeout=OPEN_TIMEOUT_S,
        ping_interval=30,
        ping_timeout=30,
        close_timeout=5,
        max_size=MAX_MESSAGE_BYTES,
        proxy=None,
        logger=WS_LOGGER,
    )


async def _receive(ws: ClientConnection) -> dict[str, Any]:
    raw = await asyncio.wait_for(ws.recv(), AUTH_TIMEOUT_S)
    message = json.loads(raw)
    if not isinstance(message, dict):
        raise HaProtocolError("expected a JSON object")
    return message


async def _decode(raw: str | bytes) -> list[dict[str, Any]]:
    if len(raw) > LARGE_MESSAGE_BYTES:
        return await asyncio.to_thread(_messages, raw)
    return _messages(raw)


def _messages(raw: str | bytes) -> list[dict[str, Any]]:
    try:
        decoded = json.loads(raw)
    except ValueError:
        LOGGER.warning("HA sent a non-JSON message; ignored")
        return []
    items = decoded if isinstance(decoded, list) else [decoded]
    return [item for item in items if isinstance(item, dict)]
