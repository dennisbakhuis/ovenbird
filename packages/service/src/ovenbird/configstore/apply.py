"""The configuration manager: start-up from the store, validate, apply, roll back, modes.

Start-up (:meth:`ConfigManager.open`): the store is opened; the newest version is
merged with the installation's settings. When the store was lost (missing after
having existed, or corrupt) or its newest version no longer validates, the service
starts with the environment/options/preset values in **shadow** with
the warning alarm ``config_reset`` until an admin acknowledges it: it never
silently controls with different settings. An invalid newest version is followed by
an empty ``reset`` version, so the store and the running configuration agree. An
empty store with ``OVENBIRD_CONFIG_SEED`` gets the seed file's values as version 1.

Apply (:meth:`ConfigManager.apply`): optimistic concurrency on ``base_version``, at
most one apply per 60 s and 30 per day, full validation, every warning acknowledged,
then the version and its audit row are written, the new settings are handed to the
control loop (swapped in at its next tick, state carried over) and the store is
snapshotted. A rollback is a new version with an old document through the same path.

Home Assistant connection (:meth:`ConfigManager.set_connection`): ``ha_url`` and the
secret ``ha_token`` are kept in the store's ``connection`` table, not in a version; a
change is validated like an apply (pairing, the ``ha/`` signals still known), audited
without the token, and handed to the connection listeners at once (the HA input
reconnects) and to the control loop at its next tick.

Modes: the environment's ``control_mode`` is the ceiling. Pause turns an ``auto``
installation into shadow (the publish guard's :class:`~ovenbird.control.guard.ModeHold`);
resume returns to ``auto``. The pause survives restarts (``runtime`` table).
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

from pydantic import ValidationError

from ovenbird import __version__
from ovenbird.clock import Clock, iso_from_unix
from ovenbird.config import SECRET_FIELDS, ConfigError, Issue, Settings
from ovenbird.configstore.effective import (
    Source,
    Validation,
    field_views,
    merge,
    provided_sources,
    storable,
    store_rules,
    typed_mqtt,
    validate_connection,
    validate_doc,
    validate_mqtt,
    validation_issues,
)
from ovenbird.configstore.fields import CONNECTION_FIELDS, MQTT_FIELDS, effective_value
from ovenbird.configstore.store import ConfigStore, ConfigVersion, Origin, StoreLoss
from ovenbird.control.alarms import AlarmBoard, AlarmCode
from ovenbird.control.guard import ModeHold
from ovenbird.hotwater import hot_water_payload
from ovenbird_core import Instant
from ovenbird_core.control import Mode, OvenbirdConfig

if TYPE_CHECKING:
    from ovenbird.control.loop import ControlLoop

LOGGER = logging.getLogger("ovenbird.configstore")
EXPORT_FORMAT: Final = 1
MAX_ARCHIVED_VERSIONS: Final = 100_000
PAUSED_KEY: Final = "paused"
RESET_KEY: Final = "reset_pending"
APPLY_SPACING_S: Final = 60.0
APPLY_DAY_LIMIT: Final = 30
DAY_S: Final = 86_400.0
MAX_COMMENT: Final = 200
SYSTEM_ACTOR: Final = "ovenbird"
APPLY_ORIGINS: Final = (Origin.UI, Origin.ROLLBACK)


class ConfigRefusedError(Exception):
    """A configuration or mode request is refused.

    Parameters
    ----------
    status
        HTTP status (``409``, ``422``, ``429``).
    body
        JSON response body.
    """

    def __init__(self, status: int, body: dict[str, Any]) -> None:
        super().__init__(body.get("detail", status))
        self.status = status
        self.body = body


@dataclass(frozen=True, slots=True)
class Actor:
    """Who makes a request.

    Parameters
    ----------
    name
        Audit name (``admin from 192.168.1.20``, the ingress user, ...).
    source_ip
        Client address.
    """

    name: str
    source_ip: str | None = None


def diff(old: Mapping[str, Any], new: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Return ``[{"field", "from", "to"}]`` between two stored documents (absent = ``None``)."""
    return [
        {"field": name, "from": old.get(name), "to": new.get(name)}
        for name in sorted(set(old) | set(new))
        if old.get(name) != new.get(name)
    ]


def read_seed(path: Path) -> dict[str, Any]:
    """Return the ``values`` of a seed (export) file.

    Raises
    ------
    ConfigError
        When the file cannot be read or is not an ovenbird configuration export.
    """
    try:
        body = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ConfigError(f"cannot read the configuration seed: {type(exc).__name__}") from None
    if (
        not isinstance(body, dict)
        or body.get("ovenbird_config") != EXPORT_FORMAT
        or not isinstance(body.get("values"), dict)
    ):
        raise ConfigError(
            f"the configuration seed is not an ovenbird configuration export "
            f'(needs "ovenbird_config": {EXPORT_FORMAT} and "values")'
        )
    return dict(body["values"])


class ConfigManager:
    """Owns the configuration store and the effective settings of one service instance.

    Build with :meth:`open`; connect the control loop with :meth:`attach`.

    Parameters
    ----------
    store
        The configuration store.
    base
        Installation settings (environment, options file, keyword arguments).
    locked
        Fields provided by the environment or the options file.
    clock
        Service clock.
    settings
        Effective settings.
    version
        Newest stored version (``None`` for an empty store).
    hold
        Shadow reasons shared with the publish guard.
    loss
        Why the stored configuration was not used at start, if it was not.
    connection
        The stored Home Assistant connection (``ha_url``, ``ha_token``).
    """

    def __init__(
        self,
        store: ConfigStore,
        base: Settings,
        locked: Mapping[str, Source],
        clock: Clock,
        settings: Settings,
        version: int | None,
        hold: ModeHold,
        loss: StoreLoss | None = None,
        connection: Mapping[str, str] | None = None,
    ) -> None:
        self.store = store
        self.base = base
        self.locked = dict(locked)
        self.clock = clock
        self.settings = settings
        self.version = version
        self.applied_version = version
        self.hold = hold
        self.loss = loss
        self.connection: dict[str, str] = dict(connection or {})
        self.connection_listeners: list[Callable[[Settings], None]] = []
        self.mqtt_listeners: list[Callable[[Settings], None]] = []
        self.loop: ControlLoop | None = None
        self.alarms: AlarmBoard | None = None
        self.on_applied: list[Callable[[int | None, Instant], None]] = []
        self.audit_listeners: list[Callable[[Actor, str, Mapping[str, Any]], None]] = []
        self.dhw_installed: Callable[[], bool | None] = lambda: None
        self._configs: dict[int | None, OvenbirdConfig | None] = {}
        self._settings: dict[int | None, Settings | None] = {}

    @classmethod
    def open(
        cls,
        base: Settings,
        clock: Clock,
        *,
        locked: Mapping[str, Source] | None = None,
    ) -> ConfigManager:
        """Open the store in ``base.data_dir`` and work out the effective settings.

        Parameters
        ----------
        base
            Installation settings.
        clock
            Service clock (version and audit times).
        locked
            Locked fields; read from the environment and the options file when
            omitted.

        Returns
        -------
        ConfigManager
            The manager.

        Raises
        ------
        ConfigError
            When the seed file is unreadable or invalid.
        """
        locks = provided_sources() if locked is None else dict(locked)
        store, loss = ConfigStore.open(base.data_dir)
        connection = store.connection()
        now = clock().wall.timestamp()
        reset = store.runtime_get(RESET_KEY) is not None
        settings = base
        if connection:
            try:
                settings = _checked(base, locks, {}, connection)
            except ValueError as exc:
                LOGGER.critical(
                    "the stored connection (Home Assistant, broker) is invalid (%s); it is ignored",
                    exc,
                )
                connection = {}
        latest = store.latest()
        version = None if latest is None else latest.version
        if latest is not None:
            try:
                settings = _checked(base, locks, latest.values, connection)
            except ValueError as exc:
                LOGGER.critical(
                    "CONFIGURATION VERSION %d NO LONGER VALIDATES (%s); starting in shadow "
                    "with the installation's values",
                    latest.version,
                    exc,
                )
                loss = StoreLoss.INVALID
                reset_version = store.append(
                    {},
                    actor=SYSTEM_ACTOR,
                    origin=Origin.RESET,
                    now_ts=now,
                    comment=f"version {latest.version} no longer validates",
                )
                version = reset_version.version
        elif loss is None and base.config_seed is not None:
            values = read_seed(base.config_seed)
            try:
                settings = _checked(base, locks, values, connection)
            except ValueError as exc:
                raise ConfigError(f"the configuration seed is invalid: {exc}") from None
            seeded = store.append(
                storable(values),
                actor=SYSTEM_ACTOR,
                origin=Origin.SEED,
                now_ts=now,
                comment=f"seed {base.config_seed.name}",
            )
            version = seeded.version
            LOGGER.info("configuration seeded from %s as version %d", base.config_seed, version)
        if loss is not None and not reset:
            reset = True
            store.runtime_set(RESET_KEY, loss.value)
            store.audit(now, SYSTEM_ACTOR, "config_reset", {"loss": loss.value})
        if version is not None:
            store.snapshot()
        hold = ModeHold(paused=store.runtime_get(PAUSED_KEY) is not None, reset_pending=reset)
        if hold.reset_pending:
            LOGGER.warning("configuration reset pending: shadow until an admin acknowledges it")
        return cls(store, base, locks, clock, settings, version, hold, loss, connection)

    def attach(self, loop: ControlLoop, alarms: AlarmBoard) -> None:
        """Connect the control loop and the alarm board; raise ``config_reset`` when pending."""
        self.loop = loop
        self.alarms = alarms
        loop.on_config = self._applied
        now = self.clock()
        if self.version is not None:
            self.store.mark_applied(self.version, now.wall.timestamp())
        if self.hold.reset_pending:
            alarms.raise_alarm(AlarmCode.CONFIG_RESET, self._reset_message(), now)

    def close(self) -> None:
        """Close the store."""
        self.store.close()

    def _reset_message(self) -> str:
        why = self.store.runtime_get(RESET_KEY) or "lost"
        return (
            f"the stored configuration was {why}; running in shadow with the installation's "
            "values until an admin acknowledges it (POST api/v1/config/reset-ack)"
        )

    def _applied(self, version: int | None, at: Instant) -> None:
        self.applied_version = version
        if version is not None:
            self.store.mark_applied(version, at.wall.timestamp())
        for listener in self.on_applied:
            listener(version, at)

    def _doc(self) -> dict[str, Any]:
        latest = self.store.latest()
        return {} if latest is None else dict(latest.values)

    @property
    def configured_mode(self) -> Mode:
        """The environment's mode (the ceiling)."""
        return Mode(self.base.control_mode)

    @property
    def effective_mode(self) -> Mode:
        """The mode the loop runs in (``shadow`` while an ``auto`` installation is held)."""
        if self.configured_mode is Mode.AUTO and self.hold.active:
            return Mode.SHADOW
        return self.configured_mode

    def mode_payload(self) -> dict[str, Any]:
        """Return the ``mode`` object of the API."""
        return {
            "configured": self.configured_mode.value,
            "effective": self.effective_mode.value,
            "paused": self.hold.paused,
            "reset_pending": self.hold.reset_pending,
        }

    def payload(self) -> dict[str, Any]:
        """Return the body of ``GET api/v1/config``."""
        latest = self.store.latest()
        doc = {} if latest is None else latest.values
        return {
            "version": 0 if latest is None else latest.version,
            "applied_version": self.applied_version or 0,
            "updated_at": None if latest is None else iso_from_unix(latest.created_ts),
            "updated_by": None if latest is None else latest.actor,
            "mode": self.mode_payload(),
            "reset_pending": self.hold.reset_pending,
            "fields": field_views(self.settings, self.locked, doc, self.connection),
            "hot_water": hot_water_payload(self.settings.hot_water, self.dhw_installed()),
        }

    def config_of(self, version: int | None) -> OvenbirdConfig | None:
        """Return the controller configuration a stored version ran with (cached).

        ``None`` (ticks before the store existed, or an empty store) is the
        installation's configuration; an unknown or no longer valid version gives
        ``None``.
        """
        if version in self._configs:
            return self._configs[version]
        settings = self.settings_of(version)
        found: OvenbirdConfig | None = None
        if settings is not None:
            try:
                found = settings.controller_config()
            except ValueError:
                found = None
        self._configs[version] = found
        return found

    def settings_of(self, version: int | None) -> Settings | None:
        """Return the settings a stored version ran with (cached).

        ``None`` (ticks before the store existed, or an empty store) is the
        installation's settings; an unknown or no longer valid version gives ``None``.
        """
        if version in self._settings:
            return self._settings[version]
        found: Settings | None = None
        try:
            if version is None:
                found = self.base
            else:
                item = self.store.get(version)
                if item is not None:
                    found = _checked(self.base, self.locked, item.values, self.connection)
        except ValueError:
            found = None
        self._settings[version] = found
        return found

    def validate(self, changes: Mapping[str, Any]) -> Validation:
        """Validate ``changes`` against the stored document and the installation."""
        return validate_doc(
            self.base, self.locked, self._doc(), changes, self.settings, self.connection
        )

    def _check_rate(self, now: float) -> None:
        last = self.store.last_created(APPLY_ORIGINS)
        if last is not None and now - last < APPLY_SPACING_S:
            raise ConfigRefusedError(
                429,
                {
                    "detail": f"at most one apply per {APPLY_SPACING_S:.0f} s",
                    "retry_after": round(APPLY_SPACING_S - (now - last), 1),
                },
            )
        if self.store.count_since(now - DAY_S, APPLY_ORIGINS) >= APPLY_DAY_LIMIT:
            raise ConfigRefusedError(429, {"detail": f"at most {APPLY_DAY_LIMIT} applies per day"})

    def apply(
        self,
        base_version: int,
        changes: Mapping[str, Any],
        actor: Actor,
        *,
        comment: str | None = None,
        acknowledge: Sequence[str] = (),
        origin: Origin = Origin.UI,
        action: str = "config_apply",
        detail: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Validate and store ``changes`` as a new version and hand it to the control loop.

        Parameters
        ----------
        base_version
            The version the client edited (``0`` for an empty store).
        changes
            Field to value; ``None`` removes the stored value.
        actor
            Who applies.
        comment
            Optional comment (at most 200 characters).
        acknowledge
            Warning codes the client acknowledged.
        origin
            ``ui`` or ``rollback``.
        action
            Audit action.
        detail
            Extra audit detail.

        Returns
        -------
        dict
            ``{"version", "applies", "config"}``.

        Raises
        ------
        ConfigRefusedError
            ``409`` for a stale ``base_version``, ``422`` for invalid, locked,
            unchanged or unacknowledged changes, ``429`` for a valid apply over the
            apply rate.
        """
        now = self.clock()
        stamp = now.wall.timestamp()
        latest = self.store.latest()
        current = 0 if latest is None else latest.version
        if base_version != current:
            raise ConfigRefusedError(
                409, {"detail": "the configuration changed meanwhile", "version": current}
            )
        if comment is not None and len(comment) > MAX_COMMENT:
            raise ConfigRefusedError(
                422,
                {
                    "errors": [
                        Issue(
                            None, "comment_too_long", f"at most {MAX_COMMENT} characters"
                        ).to_json()
                    ],
                    "warnings": [],
                },
            )
        validation = self.validate(changes)
        errors = list(validation.errors)
        acked = set(acknowledge)
        errors.extend(
            Issue(
                warning.field,
                "warning_not_acknowledged",
                f"acknowledge {warning.code} to apply",
                {"warning": warning.code},
            )
            for warning in validation.warnings
            if warning.code not in acked
        )
        old_doc = {} if latest is None else latest.values
        if not errors and validation.doc == old_doc:
            errors.append(Issue(None, "no_change", "the changes leave the configuration as it is"))
        if errors or validation.settings is None:
            raise ConfigRefusedError(
                422,
                {
                    "errors": [issue.to_json() for issue in errors],
                    "warnings": [issue.to_json() for issue in validation.warnings],
                },
            )
        self._check_rate(stamp)
        candidate = validation.settings
        stored = self.store.append(
            validation.doc,
            actor=actor.name,
            origin=origin,
            now_ts=stamp,
            source_ip=actor.source_ip,
            comment=comment,
        )
        if self.loop is not None:
            self.loop.reconfigure(candidate, stored.version)
        changed = diff(old_doc, stored.values)
        self.store.audit(
            stamp,
            actor.name,
            action,
            {"version": stored.version, "changed": changed, "comment": comment, **(detail or {})},
            source_ip=actor.source_ip,
        )
        self.settings = candidate
        self.version = stored.version
        self.store.snapshot()
        LOGGER.warning(
            "configuration version %d stored by %s (%s)",
            stored.version,
            actor.name,
            ", ".join(item["field"] for item in changed),
        )
        return {"version": stored.version, "applies": "next_tick", "config": self.payload()}

    def rollback(
        self,
        version: int,
        base_version: int,
        actor: Actor,
        *,
        comment: str | None = None,
        acknowledge: Sequence[str] = (),
    ) -> dict[str, Any]:
        """Apply the document of an older version as a new version.

        Raises
        ------
        ConfigRefusedError
            ``404`` for an unknown version, otherwise as :meth:`apply`.
        """
        target = self.store.get(version)
        if target is None:
            raise ConfigRefusedError(404, {"detail": f"no configuration version {version}"})
        current = self._doc()
        changes: dict[str, Any] = {name: None for name in current if name not in target.values}
        changes |= {
            name: value
            for name, value in storable(target.values).items()
            if name not in self.locked
        }
        return self.apply(
            base_version,
            changes,
            actor,
            comment=comment,
            acknowledge=acknowledge,
            origin=Origin.ROLLBACK,
            action="config_rollback",
            detail={"rollback_to": version},
        )

    def check_mqtt(
        self, changes: Mapping[str, Any]
    ) -> tuple[list[Issue], dict[str, str], Settings | None]:
        """Validate a broker change without storing it.

        Parameters
        ----------
        changes
            ``mqtt_*`` / ``heishamon_base`` fields to new values (see
            :func:`~ovenbird.configstore.effective.validate_mqtt`).

        Returns
        -------
        tuple
            The errors, the candidate connection and its settings (``None`` when invalid).
        """
        errors, candidate, settings = validate_mqtt(
            self.base, self.locked, self._doc(), self.connection, changes
        )
        if not errors and candidate == self.connection:
            errors = [Issue(None, "no_change", "the broker connection stays as it is")]
        return errors, candidate, None if errors else settings

    def restore_mqtt(self, previous: Mapping[str, str]) -> tuple[dict[str, str], Settings]:
        """Return the connection and settings that put the broker of ``previous`` back.

        Only the unlocked broker fields come from ``previous``; the Home Assistant
        connection and the configuration are the current ones, so a configuration
        version or HA change made since stays. The stored text values are converted
        (:func:`~ovenbird.configstore.effective.typed_mqtt`) and validated like a change;
        when that refuses, the connection is merged as it is.

        Parameters
        ----------
        previous
            A stored connection from before a broker change.

        Returns
        -------
        tuple
            The whole connection to store and its merged settings.

        Raises
        ------
        pydantic.ValidationError
            When the previous broker no longer fits the current configuration.
        """
        fields = [name for name in MQTT_FIELDS if name not in self.locked]
        back = typed_mqtt({name: previous.get(name) for name in fields})
        errors, candidate, settings = validate_mqtt(
            self.base, self.locked, self._doc(), self.connection, back, restoring=True
        )
        if not errors and settings is not None:
            return candidate, settings
        candidate = dict(self.connection)
        for name in fields:
            if name in previous:
                candidate[name] = previous[name]
            else:
                candidate.pop(name, None)
        return candidate, merge(self.base, self.locked, self._doc(), candidate)

    def set_mqtt(
        self,
        candidate: Mapping[str, str],
        settings: Settings,
        actor: Actor,
        action: str = "mqtt_connection",
    ) -> None:
        """Store a validated broker connection and hand it to the MQTT listeners.

        Audited without the password (``set``/``unset`` only). No configuration
        version is written; the control loop gets the settings at its next tick.

        Parameters
        ----------
        candidate
            The whole stored connection after the change (from :meth:`check_mqtt`).
        settings
            Its merged settings.
        actor
            Who changes it (the service itself for a revert).
        action
            Audit action: ``mqtt_connection`` or ``mqtt_connection_reverted``.
        """
        if self.loop is not None:
            self.loop.reconfigure(settings, self.version)
        now = self.clock().wall.timestamp()
        self.store.set_connection({name: candidate.get(name) for name in MQTT_FIELDS}, now)
        changed = sorted(
            name for name in MQTT_FIELDS if candidate.get(name) != self.connection.get(name)
        )
        self.audit(
            actor,
            action,
            {
                "changed": changed,
                "host": settings.mqtt_host,
                "port": settings.mqtt_port,
                "username": settings.mqtt_username,
                "password": "set" if settings.mqtt_password else "unset",
                "tls": settings.mqtt_tls,
                "base": settings.heishamon_base,
            },
        )
        self.connection = dict(candidate)
        self.settings = settings
        self.store.snapshot()
        for listener in self.mqtt_listeners:
            try:
                listener(settings)
            except Exception:
                LOGGER.exception("MQTT listener failed")
        LOGGER.warning(
            "MQTT broker %s:%d set by %s (%s)",
            settings.mqtt_host,
            settings.mqtt_port,
            actor.name,
            changed,
        )

    def set_connection(self, changes: Mapping[str, Any], actor: Actor) -> dict[str, Any]:
        """Change the Home Assistant connection (``ha_url``, ``ha_token``).

        The new connection is stored, audited (the URL, never the token) and handed
        to the connection listeners at once; the control loop gets the settings at
        its next tick. No configuration version is written.

        Parameters
        ----------
        changes
            ``ha_url`` and/or ``ha_token``; ``None`` or a blank string removes the
            stored value, an absent field keeps it.
        actor
            Who changes it.

        Returns
        -------
        dict
            ``{"config"}``: the configuration after the change.

        Raises
        ------
        ConfigRefusedError
            ``422`` for an unknown, locked, invalid or unpaired value, for removing
            the connection while ``ha/`` signals are configured, and for no change.
        """
        errors, candidate, settings = validate_connection(
            self.base, self.locked, self._doc(), self.connection, changes
        )
        if not errors and candidate == self.connection:
            errors = [Issue(None, "no_change", "the connection stays as it is")]
        if errors or settings is None:
            raise ConfigRefusedError(
                422, {"errors": [issue.to_json() for issue in errors], "warnings": []}
            )
        if self.loop is not None:
            self.loop.reconfigure(settings, self.version)
        now = self.clock().wall.timestamp()
        self.store.set_connection({name: candidate.get(name) for name in CONNECTION_FIELDS}, now)
        changed = sorted(
            name for name in CONNECTION_FIELDS if candidate.get(name) != self.connection.get(name)
        )
        self.audit(
            actor,
            "ha_connection",
            {
                "changed": changed,
                "url": candidate.get("ha_url"),
                "token": "set" if candidate.get("ha_token") else "unset",
            },
        )
        self.connection = candidate
        self.settings = settings
        self.store.snapshot()
        for listener in self.connection_listeners:
            try:
                listener(settings)
            except Exception:
                LOGGER.exception("connection listener failed")
        LOGGER.warning("Home Assistant connection changed by %s (%s)", actor.name, changed)
        return {"config": self.payload()}

    def version_payload(self, item: ConfigVersion, *, values: bool = False) -> dict[str, Any]:
        """Return one entry of ``GET api/v1/config/versions``."""
        parent = self.store.get(item.parent) if item.parent is not None else None
        body: dict[str, Any] = {
            "version": item.version,
            "created_at": iso_from_unix(item.created_ts),
            "actor": item.actor,
            "origin": item.origin.value,
            "comment": item.comment,
            "applied_at": None if item.applied_ts is None else iso_from_unix(item.applied_ts),
            "changed": diff({} if parent is None else parent.values, item.values),
        }
        if values:
            body["values"] = item.values
        return body

    def versions_payload(self, limit: int) -> dict[str, Any]:
        """Return the body of ``GET api/v1/config/versions``."""
        return {"versions": [self.version_payload(item) for item in self.store.versions(limit)]}

    def export(self) -> dict[str, Any]:
        """Return the export file: stored values and every non-secret effective value."""
        latest = self.store.latest()
        return {
            "ovenbird_config": EXPORT_FORMAT,
            "app_version": __version__,
            "exported_at": iso_from_unix(self.clock().wall.timestamp()),
            "version": 0 if latest is None else latest.version,
            "values": {} if latest is None else latest.values,
            "effective": {
                name: effective_value(self.settings, name)
                for name in Settings.model_fields
                if name not in SECRET_FIELDS
            },
        }

    def archive_config(
        self, start: float, end: float, used: Sequence[int | None]
    ) -> dict[str, Any]:
        """Return ``config.json`` of an archived month: the versions active in ``[start, end)``.

        A version counts when the month's decisions ran with it, when it was applied in
        the month, or when it was the applied one at the month's start. ``version`` and
        ``values`` are the last of them (the form of :meth:`export`); secret fields are
        never part of it.

        Parameters
        ----------
        start, end
            The month in unix seconds.
        used
            Configuration versions of the month's decisions (``None``: before the store).
        """
        stored = sorted(self.store.versions(MAX_ARCHIVED_VERSIONS), key=lambda v: v.version)
        applied = [(v.applied_ts, v) for v in stored if v.applied_ts is not None]
        wanted = {number for number in used if number is not None}
        wanted |= {v.version for ts, v in applied if start <= ts < end}
        before = [(ts, v) for ts, v in applied if ts <= start]
        if before:
            wanted.add(max(before, key=lambda pair: pair[0])[1].version)
        chosen = [v for v in stored if v.version in wanted]
        last = chosen[-1] if chosen else None

        def public(values: Mapping[str, Any]) -> dict[str, Any]:
            return {key: value for key, value in values.items() if key not in SECRET_FIELDS}

        return {
            "ovenbird_config": EXPORT_FORMAT,
            "app_version": __version__,
            "exported_at": iso_from_unix(self.clock().wall.timestamp()),
            "from": iso_from_unix(start),
            "to": iso_from_unix(end),
            "version": 0 if last is None else last.version,
            "values": {} if last is None else public(last.values),
            "versions": [
                {
                    "version": item.version,
                    "created_at": iso_from_unix(item.created_ts),
                    "applied_at": None
                    if item.applied_ts is None
                    else iso_from_unix(item.applied_ts),
                    "origin": item.origin.value,
                    "comment": item.comment,
                    "values": public(item.values),
                }
                for item in chosen
            ],
            "unversioned_decisions": None in used,
        }

    def audit(self, actor: Actor, action: str, detail: Mapping[str, Any] | None = None) -> None:
        """Append an audit row at the service clock's now and tell the audit listeners."""
        self.store.audit(
            self.clock().wall.timestamp(), actor.name, action, detail, source_ip=actor.source_ip
        )
        for listener in self.audit_listeners:
            try:
                listener(actor, action, dict(detail or {}))
            except Exception:
                LOGGER.exception("audit listener failed")

    def reset_ack(self, actor: Actor) -> dict[str, Any]:
        """Acknowledge a configuration reset: control returns to the configured mode.

        Raises
        ------
        ConfigRefusedError
            ``409`` when no reset is pending.
        """
        if not self.hold.reset_pending:
            raise ConfigRefusedError(409, {"detail": "no configuration reset is pending"})
        why = self.store.runtime_get(RESET_KEY)
        self.hold.reset_pending = False
        self.store.runtime_set(RESET_KEY, None)
        self.audit(actor, "config_reset_ack", {"loss": why})
        if self.alarms is not None:
            self.alarms.clear(AlarmCode.CONFIG_RESET, self.clock(), f"acknowledged by {actor.name}")
        LOGGER.warning("configuration reset acknowledged by %s", actor.name)
        return {"mode": self.mode_payload(), "config": self.payload()}

    def _require_auto(self) -> None:
        if self.configured_mode is not Mode.AUTO:
            raise ConfigRefusedError(
                409,
                {
                    "detail": f"the installation runs in {self.configured_mode.value} "
                    "(OVENBIRD_CONTROL_MODE); pause and resume need auto",
                    "mode": self.mode_payload(),
                },
            )

    def pause(self, actor: Actor, reason: str | None = None) -> dict[str, Any]:
        """Pause control: nothing is sent until resumed (kept across restarts).

        Raises
        ------
        ConfigRefusedError
            ``409`` when the installation's mode is not ``auto``.
        """
        self._require_auto()
        if not self.hold.paused:
            self.hold.paused = True
            self.store.runtime_set(PAUSED_KEY, reason or "paused")
            self.audit(actor, "mode_pause", {} if reason is None else {"reason": reason})
            LOGGER.warning("control paused by %s", actor.name)
        return {"mode": self.mode_payload()}

    def store_pause(self, actor: Actor, reason: str) -> None:
        """Store a pause (kept across restarts) without changing the running hold.

        Release control stores its pause first, so a restart during the restore
        comes back paused, and lets it take effect once the snapshot is restored.
        """
        if self.store.runtime_get(PAUSED_KEY) is None:
            self.store.runtime_set(PAUSED_KEY, reason)
            self.audit(actor, "mode_pause", {"reason": reason})
            LOGGER.warning("control paused by %s: %s", actor.name, reason)

    def resume(self, actor: Actor) -> dict[str, Any]:
        """End a pause (the configuration reset, if pending, still holds).

        Raises
        ------
        ConfigRefusedError
            ``409`` when the installation's mode is not ``auto`` or a release of
            control is still restoring the go-live snapshot.
        """
        self._require_auto()
        if self.hold.releasing:
            raise ConfigRefusedError(
                409,
                {
                    "detail": "release control is restoring the go-live snapshot; resume "
                    "once it is done",
                    "mode": self.mode_payload(),
                },
            )
        if self.hold.paused:
            self.hold.paused = False
            self.store.runtime_set(PAUSED_KEY, None)
            self.audit(actor, "mode_resume", {})
            LOGGER.warning("control resumed by %s", actor.name)
        return {"mode": self.mode_payload()}


def _checked(
    base: Settings,
    locked: Mapping[str, Source],
    values: Mapping[str, Any],
    connection: Mapping[str, str] | None = None,
) -> Settings:
    try:
        merged = merge(base, locked, values, connection)
    except ValidationError as exc:
        issues = validation_issues(exc)
        raise ValueError("; ".join(f"{i.field}: {i.code}" for i in issues)) from None
    problems = store_rules(merged, storable(values), locked)
    if problems:
        raise ValueError("; ".join(f"{i.field}: {i.code}" for i in problems))
    return merged
