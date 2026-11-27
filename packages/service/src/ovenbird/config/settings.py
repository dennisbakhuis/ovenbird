"""Bootstrap settings from the environment and an optional options file.

Precedence, highest first: ``OVENBIRD_*`` environment variables, the options file
(``/data/options.json`` as written by the Home Assistant app supervisor, or
``OVENBIRD_OPTIONS_FILE``), the configuration store (``config.db``, see
:mod:`ovenbird.configstore`) and the defaults below (an emitter preset where a field
defaults to ``None``). Options-file keys are the field names without the prefix
(``mqtt_host``). Explicit keyword arguments (tests, the harness) take precedence over
the environment when the settings are loaded, and act as the installation's base below
the configuration store when it merges.

Cross-field rules are :class:`Issue` objects (:func:`control_issues`), so the
configuration API reports them per field with a stable code; at load time they are
raised as one validation error.

Secrets are :class:`~pydantic.SecretStr`, so they are masked in ``repr`` and never
appear in :meth:`Settings.summary`; validation errors are reported without the
offending input values (see :func:`load_settings`).

:class:`Settings` combines one model per feature
(:class:`~ovenbird.config.fromcore.FeatureSettings`). Pydantic orders inherited
fields from the last base to the first, so the bases are listed in reverse field
order; names, order, environment variables, validators and the JSON schema are those
of the single model this replaced.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any, Self

from pydantic import SecretStr, ValidationError, model_validator
from pydantic_settings import BaseSettings, PydanticBaseSettingsSource, SettingsConfigDict

from ovenbird.config.installation import AccessSettings, InstallationSettings, SimulationSettings
from ovenbird.config.sources import (
    ENV_PREFIX,
    INGRESS_SOURCE,
    SECRET_FIELDS,
    OptionsFileSource,
    apply_ingress_mode,
    options_file,
)
from ovenbird.config.validation.access import check_bind, check_simulation
from ovenbird.config.validation.duty import check_duty_range
from ovenbird.config.validation.ha import check_ha, valid_ha_signal
from ovenbird.config.validation.issues import raise_issues
from ovenbird.config.validation.notify import check_notify
from ovenbird.config.values import SNAPSHOT_NAME, ConfigError
from ovenbird.control.settings import (
    CommandSettings,
    ControlSettings,
    SafetySettings,
    TuningSettings,
    controller_config,
    room_profile,
    safety_limits,
)
from ovenbird.history.settings import HistorySettings
from ovenbird.insight.settings import HouseSettings
from ovenbird.notify.settings import NotifySettings
from ovenbird.stove.settings import StoveSettings
from ovenbird.weather.settings import WeatherSettings
from ovenbird_core import CATALOGUE, MqttSignal, StalenessPolicy
from ovenbird_core.control import (
    EmitterType,
    OvenbirdConfig,
    RoomSensorProfile,
    SafetyLimits,
)
from ovenbird_core.inputs import HA_SIGNAL_PREFIX, split_ha_signal


class Settings(
    BaseSettings,
    SimulationSettings,
    SafetySettings,
    CommandSettings,
    NotifySettings,
    AccessSettings,
    HouseSettings,
    WeatherSettings,
    TuningSettings,
    StoveSettings,
    ControlSettings,
    HistorySettings,
    InstallationSettings,
):
    """Bootstrap settings of the service.

    Parameters
    ----------
    mqtt_host, mqtt_port
        Broker address.
    mqtt_username, mqtt_password
        Broker credentials (optional).
    mqtt_tls
        Connect with TLS.
    mqtt_ca_file
        CA bundle for TLS; the system store when unset.
    mqtt_client_id
        MQTT client identifier; a random one when unset.
    heishamon_base
        HeishaMon ``mqtt_topic_base``.
    mqtt_inputs
        Plain MQTT topics to read as signals (JSON list in the environment).
    ha_url, ha_token
        Home Assistant base URL and long-lived token; HA input is off unless both are
        set. Set in the environment (locked) or in the app (``PUT api/v1/config/ha``,
        kept in ``config.db`` outside the configuration versions).
    ha_entities
        Optional extra entity ids to read (comma-separated or a JSON list in the
        environment); the input already follows every ``ha/`` signal of the
        configuration.
    data_dir
        Directory for ``history.db`` and the instance lock.
    ui_dir
        Directory with the built UI served at ``/``.
    http_host, http_port
        HTTP bind address and port.
    admin_username, admin_password
        HTTP Basic credentials; required to bind a non-loopback address.
    http_allowed_origins
        Browser origins allowed to open the WebSocket besides the service's own
        origin (comma-separated or a JSON list in the environment).
    log_level
        Root log level.
    ingress
        Home Assistant app mode: bind all interfaces for the ingress proxy, serve the
        Supervisor ingress address (``172.30.32.2``) without credentials, require the
        admin password from every other source, and reach Home Assistant through the
        Supervisor proxy with ``SUPERVISOR_TOKEN`` when ``ha_url`` is unset. ``None``
        enables it when ``SUPERVISOR_TOKEN`` is present in the environment.
    history_raw_days, history_1m_days, history_15m_days, history_1h_days
        Retention per resolution in days; ``0`` or ``None`` keeps data forever,
        any other value is at least one day.
    history_min_free_mb
        History writes pause while the data directory has less free space.
    history_queue_size
        Bound of the history write queue (oldest samples are dropped on overflow).
    history_snapshot_hours
        Interval of the consistent ``history.snapshot.db`` copy that backups pick up
        (the live database is excluded from Home Assistant backups); ``None``
        disables it.
    history_decision_days
        Retention of the decision, command and alarm journals in days; ``0`` or
        ``None`` keeps them.
    history_archive_enabled
        Freeze each calendar month into ``archive/YYYY-MM.zip`` in the data directory
        (1 min, 15 min and 1 h rollups, journals, forecasts, configuration versions),
        independent of the retention.
    control_mode
        ``shadow`` (default) computes and logs decisions and publishes nothing;
        ``auto`` may publish commands when the publish guard allows it; ``off``
        records refusals only.
    control_interval_s
        Seconds between controller ticks.
    control_emitter
        Emitter preset of the controller (curve, safety limits, tuning).
    control_room_signal
        Signal id of the room temperature (``ha/sensor...`` or an MQTT input's signal).
    control_room_profile
        How the room sensor reports: ``periodic`` (default; on a schedule or with a
        heartbeat, stale after ``max(1800 s, 3 x report interval)``) or
        ``on_change`` (only when the value moves by one step; held while the device
        is alive and the source link is up, up to the silence limit).
    control_room_step_k
        The sensor's step; unset takes 0.1 K (``periodic``) or 0.2 K (``on_change``).
    control_room_report_interval_s
        Report or heartbeat interval of a ``periodic`` sensor.
    control_room_silence_limit_s
        An ``on_change`` value without any proof of life for this long is stale.
    control_room_liveness_signals
        Sibling signals of the room sensor's device whose reports prove it alive
        (``ha/<entity_id>`` or an MQTT input's signal; comma-separated or a JSON
        list). Their HA entities are subscribed automatically.
    control_room_crosscheck_signal
        Optional plausibility cross-check of the room value (e.g.
        ``main/Room_Thermostat_Temp``): a disagreement of more than 1.5 K after a
        slowly learned offset for 2 h switches the room feedback off.
    control_comfort_c
        Room target in °C.
    control_min_setpoint_c
        Lowest water setpoint in °C; unset keeps the emitter preset's safety minimum.
    control_pump_duty
        Let the controller set the maximum pump duty (heating vs idle); on by default.
    control_pump_duty_heat, control_pump_duty_idle
        Maximum pump duty while the compressor runs or defrosts, and while it is idle.
    control_pump_duty_idle_delay_s
        Wait after a compressor stop before lowering the duty to the idle value.
    control_stove_enabled
        Wood-stove mode: while a stove overheats the room the sensor is in, the room
        feedback is paused (its integrator held), the cross-check suspended and the
        curve lowered by a back-off (the pump is never switched off). Off by default;
        also needed for a manual start (``POST api/v1/control/stove``).
    control_stove_auto
        Detect a stove automatically (otherwise only manual starts).
    control_stove_enter_above_k, control_stove_exit_hysteresis_k
        Detection threshold above the comfort temperature, and how far below it the
        room must cool before an episode ends.
    control_stove_rise_enabled, control_stove_rise_k, control_stove_rise_window_s
        Fast-rise trigger: a rise of ``rise_k`` within the window above the comfort
        temperature also starts an episode.
    control_stove_backoff_k, control_stove_to_minimum
        How far the water setpoint goes below the curve, or (to minimum) down to the
        safety minimum.
    control_stove_min_active_s, control_stove_max_active_s
        Shortest automatic episode and the hard cap of an episode (an automatic one
        otherwise lasts while the room stays above the exit threshold; after the cap
        only a new fast rise starts another until the room has cooled).
    control_stove_reentry_hold_s
        After an episode ended on an untrusted room value: how long the value must be
        trusted again before the detection re-enters.
    control_stove_reference_signal, control_stove_reference_floor_c,
    control_stove_reference_band_k
        Optional room that must stay warm (``ha/<entity_id>`` or an MQTT input's
        signal, e.g. the hall; its HA entity is subscribed automatically): below
        its floor the back-off shrinks linearly to zero at floor minus band.
    control_curve
        Heating curve as 2-6 ``[outside_c, water_c]`` points; unset takes the
        emitter preset's curve. It must lie inside the safety envelope.
    control_outside_filter_s
        Time constant of the outside-temperature filter; unset takes the preset's.
    control_feedback_enabled
        Room feedback (PI) on; off leaves the curve only.
    control_feedback_kp, control_feedback_ti_s
        PI gain (K water per K room) and integral time (0 disables the integral
        part); unset takes the preset's.
    control_feedback_output_limit_k, control_feedback_integral_limit_k
        Clamps of the feedback and of its integrator; unset takes the preset's.
    control_max_supply_c
        Hard maximum water setpoint; unset takes the emitter's (40 °C screed and
        mixed, 55 °C radiators). The configuration API only lowers it.
    control_deadband_k, control_dwell_s
        Smallest worthwhile setpoint change and minimum time between changes.
    control_ramp_enabled, control_ramp_hold_s, control_ramp_max_below_curve_k,
    control_ramp_release_k_per_h
        Start ramp after a compressor start; unset takes the preset's.
    control_cycling_enabled, control_cycling_min_run_s
        Protection against the pump's stop rule early in a run.
    control_quiet_windows
        Up to four daily quiet-mode windows ``{start, end, level}`` (JSON list).
    control_timezone
        IANA zone of the quiet windows.
    control_envelope_curve, control_envelope_below_k, control_envelope_above_k
        Safety envelope (expert, environment or options file only); unset takes the
        emitter preset's curve with 6 K below and 5 K above.
    control_rounding_hysteresis_k, control_ramp_dwell_s, control_ramp_below_outlet_k,
    control_cycling_stop_delta_k, control_cycling_margin_k, control_cycling_max_raise_k,
    control_cycling_decrease_headroom_k, control_feedback_max_integration_step_s,
    control_room_decay_start_s, control_room_alive_decay_start_s,
    control_room_alive_decay_end_s, control_room_crosscheck_threshold_k,
    control_room_crosscheck_sustain_s, control_room_crosscheck_tau_s
        Expert constants of the controller (a model of the pump firmware and the
        room-value guards); unset takes the preset's.
    weather_enabled
        Fetch a weather forecast (the coordinates leave the house; opt-in).
    weather_latitude, weather_longitude
        Manual location, rounded to 0.01°.
    weather_location_source
        ``ha_zone_home`` (Home Assistant's home zone), ``manual`` or ``browser``
        (the coordinates came from the browser's location).
    weather_sim_file
        Simulation mode only: the simulator's Open-Meteo cache the simulated
        forecast is derived from (a synthetic winter when unset); never stored.
    house_floor_area_m2
        Heated floor area for the house model's indicative insulation score (W/m²
        at design conditions); unset leaves the score without W/m² and band.
    house_learn_enabled
        Whether the service refits the house model itself on a schedule (a
        low-priority child process in the night window); off leaves only "run now".
    house_learn_interval_h
        Hours between scheduled refits (24 to 720; a weekly refit by default).
    hot_water
        Whether the app shows hot water (DHW): ``auto`` (default) follows the pump's
        ``main/DHW_Installed`` and shows it while that is unknown, ``on`` or ``off``.
        Display only: a DHW run still freezes the corrections.
    operate_token
        Bearer token of the operate role (at least 32 characters); environment only.
    notify_ntfy_url
        ntfy server (``https://ntfy.sh`` or a local one) for alarm notifications;
        unset disables them. Environment or options file only, like the topic.
    notify_ntfy_topic, notify_ntfy_token
        ntfy topic and optional access token (secrets).
    notify_min_severity
        Lowest alarm severity sent (``info``, ``warning``, ``critical``).
    notify_events
        Also send hold, wood-stove, pause/resume and release events.
    notify_deadman_url
        External dead-man check (e.g. healthchecks.io) pinged with a ``GET`` while
        the control loop is healthy (a secret: the URL identifies the check).
    notify_deadman_interval_s
        Seconds between dead-man pings.
    notify_deadman_allow_http
        Accept a plain ``http://`` dead-man URL (it is a secret; ``https`` is
        required otherwise).
    notify_language
        Language of the ntfy messages (``en`` or ``nl``).
    envelope_rule_installed
        The owner installed the HeishaMon envelope fallback rule (the service
        cannot see the rule; it reports its recognised corrections as evidence).
    config_seed
        Export file whose values become the first configuration version when the
        store is empty.
    allow_commands
        Explicit permission to publish commands; environment only.
    command_brokers
        Broker hosts (``host`` or ``host:port``) commands may be published to;
        environment only, empty by default.
    command_setpoint_register
        HeishaMon command that carries the water setpoint.
    command_min_spacing_s
        Minimum time between two published commands.
    command_verify_timeout_s
        Time a command has to show up in ``main/*`` before it is retried.
    command_max_retries
        Retries before a command counts as failed (alarm and hold).
    command_daily_budget
        Commands per UTC day; exhausting it raises an alarm and stops publishing.
    command_hold_s
        Hold after a failed verification or a foreign writer.
    command_pump_duty_min, command_pump_duty_max
        Clamp of the maximum pump duty.
    command_escalation_hours
        Window in which repeated holds escalate.
    command_escalation_factor
        The second hold within the window lasts this many times ``command_hold_s``.
    command_latch_after
        The hold that many incidents within the window is latched until an
        operator releases it (``POST api/v1/control/release-hold``).
    control_state_max_age_s
        Saved controller state (integrator, timers) older than this is not restored.
    safety_interval_s
        Seconds between safety monitor evaluations.
    safety_outlet_margin_k, safety_outlet_sustain_s
        ``Main_Outlet_Temp`` above the maximum supply plus the margin for the sustain
        time is a critical alarm.
    safety_min_flow_lpm, safety_flow_sustain_s
        ``Pump_Flow`` below the minimum while the compressor runs for the sustain
        time is a critical alarm (the minimum is model dependent).
    safety_defrost_low_flow
        What low flow during a defrost (the warning ``low_flow_defrost``) does:
        ``auto`` (default) only journals it when the model profile says the pump
        stops its water pump by design (deice mode 2) and raises it otherwise;
        ``log`` also only journals it for an unknown model; ``alarm`` always raises
        it. Journalled means recorded in the alarm history, never active and never
        notified. In a profile's deice mode 1 it is always raised.
    safety_defrost_max_s
        A defrost longer than this is a warning.
    safety_room_floor_k, safety_room_floor_sustain_s
        The room this many K below ``control_comfort_c`` for the sustain time is a
        warning; ``None`` disables the monitor.
    simulation
        The broker is a simulator: a scaled clock may then publish, and the broker
        must be loopback or the dev stack's ``mosquitto``; environment only.
    clock_speed
        Simulated seconds per real second (simulation only; 1 in production).
    clock_start
        Wall time the clock starts at (simulation only); now when unset.
    """

    model_config = SettingsConfigDict(
        env_prefix=ENV_PREFIX,
        case_sensitive=False,
        extra="ignore",
        frozen=True,
    )

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        """Read keyword arguments, then the environment, then the options file."""
        return (
            init_settings,
            env_settings,
            OptionsFileSource(settings_cls, json_file=options_file()),
        )

    @model_validator(mode="before")
    @classmethod
    def _apply_ingress_mode(cls, data: Any) -> Any:
        return apply_ingress_mode(data)

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        check_ha(self)
        check_notify(self)
        check_duty_range(self)
        if self.simulation:
            check_simulation(self)
        check_bind(self)
        raise_issues(self)
        return self

    def _signal_known(self, signal: str, *, heishamon: bool) -> bool:
        if signal.startswith(HA_SIGNAL_PREFIX):
            return self.ha_enabled and valid_ha_signal(signal)
        if heishamon and signal in CATALOGUE:
            return True
        return signal in {item.signal_id for item in self.mqtt_inputs}

    def signal_known(self, signal: str, *, heishamon: bool) -> bool:
        """Whether ``signal`` is an HA entity (with HA configured), an MQTT input or ``main/*``.

        Parameters
        ----------
        signal
            Signal id.
        heishamon
            Whether HeishaMon ``main/*`` signals count.

        Returns
        -------
        bool
            ``True`` when the service can receive the signal.
        """
        return self._signal_known(signal, heishamon=heishamon)

    @property
    def realtime_clock(self) -> bool:
        """Whether the service clock is the real clock (speed 1, no start time)."""
        return self.clock_speed == 1.0 and self.clock_start is None

    @property
    def ha_enabled(self) -> bool:
        """Whether the Home Assistant input is configured."""
        return self.ha_url is not None and self.ha_token is not None

    @property
    def ha_signals(self) -> tuple[str, ...]:
        """Every ``ha/`` signal read: room, liveness, cross-check, stove room, outside."""
        signals = (
            *(() if self.control_room_signal is None else (self.control_room_signal,)),
            *self.control_room_liveness_signals,
            *(
                ()
                if self.control_room_crosscheck_signal is None
                else (self.control_room_crosscheck_signal,)
            ),
            *(
                ()
                if self.control_stove_reference_signal is None
                else (self.control_stove_reference_signal,)
            ),
            *(() if self.control_outside_signal is None else (self.control_outside_signal,)),
        )
        return tuple(dict.fromkeys(s for s in signals if s.startswith(HA_SIGNAL_PREFIX)))

    @property
    def ha_subscriptions(self) -> tuple[str, ...]:
        """Entities whose state is read: ``ha_entities`` plus the configured state signals."""
        extra = [
            parts[0]
            for parts in map(split_ha_signal, self.ha_signals)
            if parts is not None and parts[1] is None
        ]
        return tuple(dict.fromkeys((*self.ha_entities, *extra)))

    @property
    def ha_attributes(self) -> tuple[tuple[str, str], ...]:
        """``(entity_id, attribute)`` of every configured attribute signal (a thermostat's)."""
        return tuple(
            (parts[0], parts[1])
            for parts in map(split_ha_signal, self.ha_signals)
            if parts is not None and parts[1] is not None
        )

    @property
    def ha_temperature_signals(self) -> frozenset[str]:
        """The ``ha/`` signals read as a temperature: room, cross-check, stove room, outside."""
        candidates = (
            self.control_room_signal,
            self.control_room_crosscheck_signal,
            self.control_stove_reference_signal,
            self.control_outside_signal,
        )
        return frozenset(
            signal
            for signal in candidates
            if signal is not None and signal.startswith(HA_SIGNAL_PREFIX)
        )

    def room_profile(self) -> RoomSensorProfile:
        """Return the room sensor profile the settings describe."""
        return room_profile(self)

    @property
    def emitter(self) -> EmitterType:
        """The emitter type."""
        return EmitterType(self.control_emitter)

    def safety_limits(self) -> SafetyLimits:
        """Return the safety limits: the emitter's, with the configured overrides."""
        return safety_limits(self)

    def controller_config(self) -> OvenbirdConfig:
        """Return the controller configuration: the emitter preset with every set field applied.

        Raises
        ------
        ValueError
            When the controller's own checks reject the combination.
        """
        return controller_config(self)

    def staleness_policy(self) -> StalenessPolicy:
        """Return the store's staleness rules.

        The chosen outside thermometer is judged by ``control_outside_max_age_s``, so
        a limit above the source default works; the room signal keeps its room profile.
        """
        policy = StalenessPolicy()
        if self.control_outside_signal is not None:
            policy = policy.with_override(
                self.control_outside_signal, self.control_outside_max_age_s
            )
        if self.control_room_signal is None:
            return policy
        return self.room_profile().policy(policy, self.control_room_signal)

    @property
    def ingress_mode(self) -> bool:
        """Whether the service runs as a Home Assistant app behind ingress."""
        return self.ingress is True

    @property
    def auth_required(self) -> bool:
        """Whether HTTP Basic authentication is enforced for untrusted sources."""
        return self.admin_password is not None or self.ingress_mode

    @property
    def trusted_sources(self) -> frozenset[str]:
        """Client addresses served without credentials (the ingress proxy in app mode)."""
        return frozenset({INGRESS_SOURCE}) if self.ingress_mode else frozenset()

    @property
    def history_path(self) -> Path:
        """Path of the history database."""
        return self.data_dir / "history.db"

    @property
    def snapshot_path(self) -> Path:
        """Path of the consistent history snapshot that backups include."""
        return self.data_dir / SNAPSHOT_NAME

    @property
    def archive_dir(self) -> Path:
        """Folder of the monthly archive files."""
        return self.data_dir / "archive"

    def mqtt_signals(self) -> Mapping[str, MqttSignal]:
        """Return the core parser specifications of the plain MQTT inputs by topic."""
        return {item.topic: item.to_core() for item in self.mqtt_inputs}

    def summary(self) -> dict[str, object]:
        """Return the settings for logging, with every secret replaced by set/unset.

        Returns
        -------
        dict
            Field name to value; secrets become ``"set"`` or ``"unset"``.
        """
        result: dict[str, object] = {}
        for name in type(self).model_fields:
            value = getattr(self, name)
            if isinstance(value, SecretStr) or name in SECRET_FIELDS:
                result[name] = "set" if value is not None else "unset"
            elif isinstance(value, Path):
                result[name] = str(value)
            elif name == "mqtt_inputs":
                result[name] = [item.topic for item in value]
            else:
                result[name] = value
        return result


def describe_errors(exc: ValidationError) -> str:
    """Format validation errors without echoing input values (which may be secrets).

    Parameters
    ----------
    exc
        The validation error.

    Returns
    -------
    str
        One ``field: message`` line per error.
    """
    lines = []
    for error in exc.errors(include_input=False, include_url=False, include_context=False):
        location = ".".join(str(part) for part in error["loc"]) or "settings"
        lines.append(f"{location}: {error['msg']}")
    return "; ".join(lines)


def load_settings(**overrides: Any) -> Settings:
    """Load and validate the settings.

    Parameters
    ----------
    **overrides
        Field values taking precedence over every other source.

    Returns
    -------
    Settings
        Validated settings.

    Raises
    ------
    ConfigError
        When the settings are invalid or the options file cannot be read.
    """
    try:
        return Settings(**overrides)
    except ValidationError as exc:
        raise ConfigError(describe_errors(exc)) from None
    except (OSError, ValueError, TypeError) as exc:
        raise ConfigError(f"cannot read settings: {type(exc).__name__}") from None
