export const fields = {
  'cfg.control_curve.label': 'Heating curve',
  'cfg.control_curve.help':
    'The water setpoint for each outside temperature. Between 2 and 6 points; the water temperature never rises when it gets warmer outside.',
  'cfg.control_outside_filter_s.label': 'Outside temperature smoothing',
  'cfg.control_outside_filter_s.help':
    'Time constant of the filter on the outside temperature. The pump reports whole degrees, so this smooths the jumps. Below 30 minutes is not recommended.',
  'cfg.control_room_signal.label': 'Room sensor',
  'cfg.control_room_signal.help':
    'The temperature sensor that tells the controller how warm the room is. Leave empty to run on the heating curve alone.',
  'cfg.control_room_profile.label': 'Sensor type',
  'cfg.control_room_profile.help':
    'Periodic sensors report on a fixed interval. On-change sensors only report when the value moves, so silence is normal.',
  'cfg.control_room_profile.opt.periodic': 'Periodic',
  'cfg.control_room_profile.opt.on_change': 'On change',
  'cfg.control_room_step_k.label': 'Sensor step size',
  'cfg.control_room_step_k.help':
    'The smallest change the sensor reports. Used to judge whether a held value is still believable.',
  'cfg.control_room_report_interval_s.label': 'Report interval',
  'cfg.control_room_report_interval_s.help':
    'How often a periodic sensor reports. A value older than a few intervals is treated as stale.',
  'cfg.control_room_silence_limit_s.label': 'Silence limit',
  'cfg.control_room_silence_limit_s.help':
    'How long an on-change sensor may stay silent before its value is no longer trusted.',
  'cfg.control_room_liveness_signals.label': 'Liveness signals',
  'cfg.control_room_liveness_signals.help':
    'Other signals from the same device (humidity, battery). While they keep arriving, a silent temperature is still trusted.',
  'cfg.control_room_crosscheck_signal.label': 'Cross-check sensor',
  'cfg.control_room_crosscheck_signal.help':
    'A second temperature that must roughly agree with the room sensor. If it does not, room correction is paused.',
  'cfg.control_comfort_c.label': 'Comfort target',
  'cfg.control_comfort_c.help': 'The room temperature the controller aims for.',
  'cfg.control_weather_compensation.label': 'Weather-dependent control (WAR)',
  'cfg.control_weather_compensation.help':
    'On: the water temperature follows the heating curve, warmer when it is colder outside. Off: one fixed water temperature at any outside temperature. Room correction is a separate switch and works either way.',
  'cfg.control_fixed_water_c.label': 'Fixed water temperature',
  'cfg.control_fixed_water_c.help':
    'Water temperature while weather-dependent control is off. Room correction can still raise or lower it a little, and the safety band still lifts it when it is very cold outside.',
  'cfg.control_feedback_enabled.label': 'Room correction',
  'cfg.control_feedback_enabled.help':
    'When off, only the heating curve (or the fixed water temperature) is used: no proportional or integral correction from the room. Independent of weather-dependent control.',
  'cfg.control_feedback_kp.label': 'Proportional gain',
  'cfg.control_feedback_kp.help':
    'How many K the water setpoint changes per K of room error. Higher reacts faster but can overshoot.',
  'cfg.control_feedback_ti_s.label': 'Integral time',
  'cfg.control_feedback_ti_s.help':
    'How slowly the correction builds up to remove a lasting room error. 0 switches the integral part off.',
  'cfg.control_feedback_output_limit_k.label': 'Correction limit',
  'cfg.control_feedback_output_limit_k.help':
    'The most the room correction may add to or take off the heating curve, in K.',
  'cfg.control_feedback_integral_limit_k.label': 'Integral limit',
  'cfg.control_feedback_integral_limit_k.help':
    'The most the integral part may contribute, in K. It cannot exceed the correction limit.',
  'cfg.safety_room_floor_k.label': 'Room too cold margin',
  'cfg.safety_room_floor_k.help':
    'Raise a warning when the room stays this many K below the comfort target. Empty switches the monitor off.',
  'cfg.safety_room_floor_sustain_s.label': 'Room too cold duration',
  'cfg.safety_room_floor_sustain_s.help':
    'How long the room must stay too cold before the warning is raised.',
  'cfg.safety_defrost_low_flow.label': 'No flow during defrost',
  'cfg.safety_defrost_low_flow.help':
    'Some heat pumps stop their water pump while defrosting. For a pump model ovenbird knows from its service manual, it can tell when that is by design: the WH-MXC12J9E8 defrosts with hot gas below 27 °C return water and stops its water pump (deice mode 2). Automatic only logs that case and raises an alarm otherwise; Log only also only logs it for a pump model ovenbird does not know; Alarm always raises the warning. Logged means under Activity → Alarms, without an active alarm or a notification. When the model says the pump should run, low flow is always an alarm.',
  'cfg.safety_defrost_low_flow.opt.auto':
    'Automatic (log only when the pump model does this by design)',
  'cfg.safety_defrost_low_flow.opt.alarm': 'Alarm',
  'cfg.safety_defrost_low_flow.opt.log': 'Log only (Activity → Alarms)',
  'cfg.control_min_setpoint_c.label': 'Minimum water setpoint',
  'cfg.control_min_setpoint_c.help':
    'The controller never asks for water colder than this. Empty follows the emitter preset.',
  'cfg.control_max_supply_c.label': 'Maximum supply temperature',
  'cfg.control_max_supply_c.help':
    'The controller never asks for water hotter than this. It can only be lowered here; raising it needs the environment or options file.',
  'cfg.control_deadband_k.label': 'Dead band',
  'cfg.control_deadband_k.help':
    'The setpoint only changes when the calculated value differs by at least this much. Larger means fewer changes.',
  'cfg.control_dwell_s.label': 'Wait time between changes',
  'cfg.control_dwell_s.help':
    'Minimum time between two setpoint changes. It protects the daily write budget; below 10 minutes is not recommended.',
  'cfg.control_ramp_enabled.label': 'Start ramp',
  'cfg.control_ramp_enabled.help':
    'After the compressor starts, hold the water setpoint below the curve and release it slowly (soft start).',
  'cfg.control_ramp_hold_s.label': 'Start ramp hold time',
  'cfg.control_ramp_hold_s.help': 'How long the setpoint stays low after a compressor start.',
  'cfg.control_ramp_max_below_curve_k.label': 'Start ramp depth',
  'cfg.control_ramp_max_below_curve_k.help':
    'How far below the curve the setpoint may start, in K.',
  'cfg.control_ramp_release_k_per_h.label': 'Start ramp release speed',
  'cfg.control_ramp_release_k_per_h.help':
    'How fast the setpoint climbs back to the curve, in K per hour.',
  'cfg.control_cycling_enabled.label': 'Cycling protection',
  'cfg.control_cycling_enabled.help':
    'Keeps the setpoint high enough early in a run so the pump does not stop and restart. Switching it off raises a warning.',
  'cfg.control_cycling_min_run_s.label': 'Cycling protection window',
  'cfg.control_cycling_min_run_s.help': 'The minimum run time the protection tries to secure.',
  'cfg.control_pump_duty.label': 'Control pump duty',
  'cfg.control_pump_duty.help':
    "Let the controller set the maximum pump duty: higher while heating, lower when idle. Off by default: it replaces the pump's own setting, so enter values that suit your installation (ask your installer) before switching it on.",
  'cfg.control_pump_duty_heat.label': 'Duty while heating',
  'cfg.control_pump_duty_heat.help': 'Maximum pump duty while the compressor runs (64–254).',
  'cfg.control_pump_duty_idle.label': 'Duty when idle',
  'cfg.control_pump_duty_idle.help': 'Maximum pump duty while the compressor is off (64–254).',
  'cfg.control_pump_duty_idle_delay_s.label': 'Delay before idle duty',
  'cfg.control_pump_duty_idle_delay_s.help':
    'How long after the compressor stops before the idle duty is set.',
  'cfg.control_quiet_windows.label': 'Quiet mode windows',
  'cfg.control_quiet_windows.help':
    'Daily time windows in which the pump is switched to quiet mode at the chosen level. A window that ends before it starts runs past midnight.',
  'cfg.control_timezone.label': 'Time zone',
  'cfg.control_timezone.help': 'The time zone of the quiet windows, for example Europe/Amsterdam.',
  'cfg.control_emitter.label': 'Emitter',
  'cfg.control_emitter.help':
    'The kind of heat emitter. It sets the preset curve, safety envelope and tuning that every other setting starts from.',
  'cfg.control_emitter.opt.screed_floor': 'Floor heating in screed',
  'cfg.control_emitter.opt.mixed': 'Mixed (floor and low-temperature radiators)',
  'cfg.control_emitter.opt.radiators': 'Radiators',
  'cfg.weather_enabled.label': 'Weather forecast',
  'cfg.weather_enabled.help':
    'Fetch an outside temperature forecast for the weather page. The controller uses it only when the model plan is switched on (House → Control); otherwise it is for display.',
  'cfg.weather_latitude.label': 'Latitude',
  'cfg.weather_latitude.help': 'Degrees north, rounded to 0.01°.',
  'cfg.weather_longitude.label': 'Longitude',
  'cfg.weather_longitude.help': 'Degrees east, rounded to 0.01°.',
  'cfg.weather_location_source.label': 'Location source',
  'cfg.weather_location_source.help': 'Where the forecast location comes from.',
  'cfg.weather_location_source.opt.ha_zone_home': 'Home Assistant home zone',
  'cfg.weather_location_source.opt.manual': 'Entered manually',
  'cfg.weather_location_source.opt.browser': 'This browser',
  'cfg.control_cycling_stop_delta_k.label': 'Cycling model: stop delta',
  'cfg.control_cycling_stop_delta_k.help': 'Part of the model of the pump’s own stop rule.',
  'cfg.control_cycling_margin_k.label': 'Cycling model: margin',
  'cfg.control_cycling_margin_k.help': 'Safety margin added to the model of the pump’s stop rule.',
  'cfg.control_rounding_hysteresis_k.label': 'Rounding hysteresis',
  'cfg.control_rounding_hysteresis_k.help':
    'Hysteresis when rounding the setpoint to whole degrees.',
  'cfg.control_ramp_dwell_s.label': 'Start ramp step time',
  'cfg.control_ramp_dwell_s.help': 'Time per step while the start ramp is released.',
  'cfg.control_interval_s.label': 'Decision interval',
  'cfg.control_interval_s.help': 'How often the controller makes a decision.',
  'cfg.control_envelope_curve.label': 'Safety envelope curve',
  'cfg.control_envelope_curve.help':
    'The preset curve the safety envelope is anchored to. A curve you edit must stay within the envelope around it.',
  'cfg.command_pump_duty_min.label': 'Lowest pump duty allowed',
  'cfg.command_pump_duty_min.help': 'Hard lower limit for commanded pump duty.',
  'cfg.command_pump_duty_max.label': 'Highest pump duty allowed',
  'cfg.command_pump_duty_max.help': 'Hard upper limit for commanded pump duty.',
  'cfg.hot_water.label': 'Hot water',
  'cfg.hot_water.help':
    'Whether the app shows hot water, the pump heating a tank. Automatic follows what the pump reports. Hidden, a hot-water run still shows, as “Pump busy elsewhere”. It changes nothing in how ovenbird controls the pump.',
  'cfg.hot_water.opt.auto': 'Automatic (as the pump reports)',
  'cfg.hot_water.opt.on': 'Show',
  'cfg.hot_water.opt.off': 'Hide',
  'cfg.history_retention_days.label': 'History retention',
  'cfg.history_retention_days.help': 'How many days of history are kept.',
  'cfg.admin_password.label': 'Admin password',
  'cfg.admin_username.label': 'Admin user name',
  'cfg.allow_commands.label': 'Send commands to the pump',
  'cfg.clock_speed.label': 'Simulation clock speed',
  'cfg.clock_start.label': 'Simulation clock start',
  'cfg.command_brokers.label': 'Command brokers',
  'cfg.command_daily_budget.label': 'Daily write budget',
  'cfg.command_escalation_factor.label': 'Retry escalation factor',
  'cfg.command_escalation_hours.label': 'Retry escalation window',
  'cfg.command_hold_s.label': 'Hold after a foreign write',
  'cfg.command_latch_after.label': 'Latch after failures',
  'cfg.command_max_retries.label': 'Maximum retries',
  'cfg.command_min_spacing_s.label': 'Minimum time between commands',
  'cfg.command_setpoint_register.label': 'Setpoint register',
  'cfg.command_verify_timeout_s.label': 'Verification timeout',
  'cfg.config_seed.label': 'Configuration seed file',
  'cfg.control_cycling_decrease_headroom_k.label': 'Cycling model: decrease headroom',
  'cfg.control_cycling_max_raise_k.label': 'Cycling model: largest raise',
  'cfg.control_envelope_above_k.label': 'Safety envelope above the curve',
  'cfg.control_envelope_below_k.label': 'Safety envelope below the curve',
  'cfg.control_feedback_max_integration_step_s.label': 'Longest integration step',
  'cfg.control_mode.label': 'Control mode ceiling',
  'cfg.control_ramp_below_outlet_k.label': 'Start ramp: below outlet',
  'cfg.control_room_alive_decay_end_s.label': 'Room trust ends (alive)',
  'cfg.control_room_alive_decay_start_s.label': 'Room trust fades from (alive)',
  'cfg.control_room_crosscheck_sustain_s.label': 'Cross-check duration',
  'cfg.control_room_crosscheck_tau_s.label': 'Cross-check smoothing',
  'cfg.control_room_crosscheck_threshold_k.label': 'Cross-check threshold',
  'cfg.control_room_decay_start_s.label': 'Room trust fades from',
  'cfg.control_state_max_age_s.label': 'Oldest controller state to restore',
  'cfg.data_dir.label': 'Data folder',
  'cfg.ha_entities.label': 'Home Assistant entities',
  'cfg.ha_token.label': 'Home Assistant token',
  'cfg.ha_url.label': 'Home Assistant address',
  'cfg.ha_url.help':
    'Where ovenbird reads Home Assistant: http://<host>:8123 on your network or your https address. Set it in the Home Assistant section.',
  'cfg.ha_token.help':
    'Long-lived access token for reading Home Assistant. It is stored but never shown again.',
  'cfg.heishamon_base.label': 'HeishaMon topic base',
  'cfg.history_15m_days.label': 'Keep 15-minute history',
  'cfg.history_15m_days.help':
    'How long the 15-minute averages stay. They feed the long-range charts. 0 keeps them forever.',
  'cfg.history_1h_days.label': 'Keep hourly history',
  'cfg.history_1h_days.help':
    'How long the hourly averages stay. They are small; 0 keeps them forever.',
  'cfg.history_1m_days.label': 'Keep 1-minute history',
  'cfg.history_1m_days.help':
    'How long the 1-minute averages stay. They are the largest part of the database.',
  'cfg.history_archive_enabled.label': 'Yearly archive',
  'cfg.history_archive_enabled.help':
    'Freeze every finished month into a zip in the data directory, kept however short the history is kept. Download or delete months on System → Data.',
  'cfg.history_decision_days.label': 'Keep decisions',
  'cfg.history_decision_days.help': 'How long decisions, commands, alarms and forecasts stay.',
  'cfg.history_min_free_mb.label': 'Minimum free disk space',
  'cfg.history_queue_size.label': 'History write queue',
  'cfg.history_raw_days.label': 'Keep raw history',
  'cfg.history_raw_days.help':
    'How long every raw sample stays, as it arrived. Older data stays as averages.',
  'cfg.history_snapshot_hours.label': 'History snapshot interval',
  'cfg.http_allowed_origins.label': 'Allowed web origins',
  'cfg.http_host.label': 'Web server address',
  'cfg.http_port.label': 'Web server port',
  'cfg.ingress.label': 'Home Assistant ingress',
  'cfg.log_level.label': 'Log level',
  'cfg.mqtt_ca_file.label': 'MQTT CA certificate',
  'cfg.mqtt_client_id.label': 'MQTT client id',
  'cfg.mqtt_host.label': 'MQTT broker',
  'cfg.mqtt_inputs.label': 'Extra MQTT inputs',
  'cfg.mqtt_password.label': 'MQTT password',
  'cfg.mqtt_port.label': 'MQTT port',
  'cfg.mqtt_tls.label': 'MQTT over TLS',
  'cfg.mqtt_username.label': 'MQTT user name',
  'cfg.operate_token.label': 'Operate token',
  'cfg.safety_defrost_max_s.label': 'Longest defrost',
  'cfg.safety_flow_sustain_s.label': 'Low flow duration',
  'cfg.safety_interval_s.label': 'Safety check interval',
  'cfg.safety_min_flow_lpm.label': 'Minimum flow',
  'cfg.safety_outlet_margin_k.label': 'Outlet margin',
  'cfg.safety_outlet_sustain_s.label': 'Outlet too hot duration',
  'cfg.simulation.label': 'Simulation',
  'cfg.ui_dir.label': 'Web UI folder',
  'cfg.weather_sim_file.label': 'Simulated weather file',
  'cfg.control_stove_enabled.label': 'Wood-stove mode',
  'cfg.control_stove_enabled.help':
    'When a wood stove heats the room with the sensor, ovenbird backs the heating off instead of letting the room correction cool the whole house.',
  'cfg.control_stove_auto.label': 'Detect the stove automatically',
  'cfg.control_stove_auto.help':
    'Start wood-stove mode by itself when the room gets clearly warmer than the comfort temperature. Off: only by hand (Stove on… on Home).',
  'cfg.control_stove_enter_above_k.label': 'Start above comfort',
  'cfg.control_stove_enter_above_k.help':
    'Wood-stove mode starts when the room is this much above the comfort temperature, in K.',
  'cfg.control_stove_exit_hysteresis_k.label': 'Stop this much lower',
  'cfg.control_stove_exit_hysteresis_k.help':
    'It ends once the room is this much below the start threshold, in K, so it does not switch on and off.',
  'cfg.control_stove_rise_enabled.label': 'Also start on a fast rise',
  'cfg.control_stove_rise_enabled.help':
    'Start early when the room warms quickly while it is already above the comfort temperature.',
  'cfg.control_stove_rise_k.label': 'Fast rise',
  'cfg.control_stove_rise_k.help':
    'How much the room must rise within the window to count as a fast rise, in K.',
  'cfg.control_stove_rise_window_s.label': 'Fast-rise window',
  'cfg.control_stove_rise_window_s.help': 'The time in which that rise must happen.',
  'cfg.control_stove_backoff_k.label': 'Back-off',
  'cfg.control_stove_backoff_k.help':
    'How far the heating curve is lowered while the stove burns, in K. The pump keeps running, so the rest of the house is still heated; a reference room makes sure it stays warm.',
  'cfg.control_stove_to_minimum.label': 'Back off to the minimum',
  'cfg.control_stove_to_minimum.help':
    'Lower the water temperature all the way to the safety minimum instead of by the back-off.',
  'cfg.control_stove_min_active_s.label': 'Shortest episode',
  'cfg.control_stove_min_active_s.help':
    'Wood-stove mode stays on at least this long once it started automatically.',
  'cfg.control_stove_max_active_s.label': 'Longest episode',
  'cfg.control_stove_max_active_s.help':
    'It ends after this long at the latest, also when the room is still warm.',
  'cfg.control_stove_reentry_hold_s.label': 'Wait after an untrusted room value',
  'cfg.control_stove_reentry_hold_s.help':
    'After the room value lost trust, it must be trusted this long again before the stove can be detected.',
  'cfg.control_stove_reference_signal.label': 'Reference room',
  'cfg.control_stove_reference_signal.help':
    'Optional: a sensor in another room, such as the hall. When it gets too cold there, the back-off shrinks.',
  'cfg.control_stove_reference_floor_c.label': 'Reference room at least',
  'cfg.control_stove_reference_floor_c.help':
    'Below this temperature in the reference room the back-off starts to shrink.',
  'cfg.control_stove_reference_band_k.label': 'Reference band',
  'cfg.control_stove_reference_band_k.help':
    'Over this many K below the floor the back-off shrinks to zero.',
  'cfg.house_floor_area_m2.label': 'Heated floor area',
  'cfg.house_floor_area_m2.help':
    'The heated floor area of the house in m², for the indicative insulation score on the House page (heat loss per m²). Leave empty to see only the heat loss in W/K.',
  'cfg.house_learn_enabled.label': 'Learn the house model',
  'cfg.house_learn_enabled.help':
    'Lets ovenbird fit the house model itself, on its own history. Switch it off to stop new runs; the model in use stays.',
  'cfg.house_learn_interval_h.label': 'Learning interval',
  'cfg.house_learn_interval_h.help':
    'Hours between two learning runs, from 24 (daily) to 720 (monthly). The default is 168, once a week.',
  'cfg.house_volume_m3.label': 'Heated volume',
  'cfg.house_volume_m3.help':
    'The heated volume of the house in m³, roughly the floor area times the room height. A starting point for the model: the measurements overrule it when they disagree.',
  'cfg.house_build_period.label': 'Build period',
  'cfg.house_build_period.help':
    'When the house was built. Older houses usually lose more heat; the model uses this as a starting point and the measurements overrule it. Leave it unset if you are not sure.',
  'cfg.house_build_period.opt.before_1945': 'Before 1945',
  'cfg.house_build_period.opt.1945_1974': '1945–1974',
  'cfg.house_build_period.opt.1975_1991': '1975–1991',
  'cfg.house_build_period.opt.1992_2005': '1992–2005',
  'cfg.house_build_period.opt.2006_2014': '2006–2014',
  'cfg.house_build_period.opt.2015_later': '2015 or later',
  'cfg.house_floor_heating_share.label': 'Share of floor heating',
  'cfg.house_floor_heating_share.help':
    'The share of the heated area that has floor heating, from 0 % (radiators only) to 100 %. Floor heating reacts slowly, which the model takes as a starting point.',
  'cfg.house_window_area_m2.label': 'Window area',
  'cfg.house_window_area_m2.help':
    'The total glass area in m². It tells the model how much sun can come in; the measurements overrule it.',
  'cfg.house_window_orientation.label': 'Main window orientation',
  'cfg.house_window_orientation.help':
    'The side most of the glass faces. Choose Mixed when it is spread over several sides.',
  'cfg.house_window_orientation.opt.north': 'North',
  'cfg.house_window_orientation.opt.east': 'East',
  'cfg.house_window_orientation.opt.south': 'South',
  'cfg.house_window_orientation.opt.west': 'West',
  'cfg.house_window_orientation.opt.mixed': 'Mixed',
  'cfg.house_occupants.label': 'Occupants',
  'cfg.house_occupants.help':
    'How many people live in the house. People give off heat, which the model counts as a starting point for the internal gains.',
  'cfg.house_ua_min_w_per_k.label': 'Heat loss, at least',
  'cfg.house_ua_min_w_per_k.help':
    'The learned heat loss will not go below this value (30 to 1500 W/K). Set minimum and maximum equal to pin it. Applies at the next learner run.',
  'cfg.house_ua_max_w_per_k.label': 'Heat loss, at most',
  'cfg.house_ua_max_w_per_k.help':
    'The learned heat loss will not go above this value (30 to 1500 W/K). Applies at the next learner run.',
  'cfg.house_time_constant_min_h.label': 'Time constant, at least',
  'cfg.house_time_constant_min_h.help':
    'The learned time constant, how slowly the house cools, will not go below this value (5 to 500 h). Equal minimum and maximum pin it. Applies at the next learner run.',
  'cfg.house_time_constant_max_h.label': 'Time constant, at most',
  'cfg.house_time_constant_max_h.help':
    'The learned time constant will not go above this value (5 to 500 h). Applies at the next learner run.',
  'cfg.house_solar_aperture_min_m2.label': 'Solar aperture, at least',
  'cfg.house_solar_aperture_min_m2.help':
    'The learned solar aperture, the glass area the sun effectively heats through, will not go below this value (0 to 40 m²). Applies at the next learner run.',
  'cfg.house_solar_aperture_max_m2.label': 'Solar aperture, at most',
  'cfg.house_solar_aperture_max_m2.help':
    'The learned solar aperture will not go above this value (0 to 40 m²). Equal minimum and maximum pin it. Applies at the next learner run.',
  'cfg.house_internal_gain_min_w.label': 'Internal gains, at least',
  'cfg.house_internal_gain_min_w.help':
    'The learned heat from people and appliances will not go below this value (0 to 2000 W). Applies at the next learner run.',
  'cfg.house_internal_gain_max_w.label': 'Internal gains, at most',
  'cfg.house_internal_gain_max_w.help':
    'The learned heat from people and appliances will not go above this value (0 to 2000 W). Equal minimum and maximum pin it. Applies at the next learner run.',
  'cfg.house_learn_fit_days.label': 'Days to learn from',
  'cfg.house_learn_fit_days.help':
    'How many days of history the learner fits on, from 21 to 90. The default is 60. It must be at least 8 days more than the days kept for testing.',
  'cfg.house_learn_test_days.label': 'Days kept for testing',
  'cfg.house_learn_test_days.help':
    'The most recent days the learner does not fit on but uses to test a new model, from 7 to 21. The default is 14.',
  'cfg.house_learn_tolerance_k.label': 'Tolerance for a new model',
  'cfg.house_learn_tolerance_k.help':
    'How much worse than the model in use a new model may predict the room, in K, and still be taken. 0 means at least as good; a negative value asks for a clearly better one. From −0.1 to 0.2.',
  'cfg.house_learn_excluded_days.label': 'Days left out',
  'cfg.house_learn_excluded_days.help':
    'Days the learner skips: a holiday, windows open all day, visitors. At most 60. Applies at the next learner run.',
  'cfg.mqtt_host.help':
    'Host name or IP address of the MQTT broker HeishaMon publishes to, such as 192.0.2.20 or mosquitto.',
  'cfg.mqtt_port.help': "The broker's port: usually 1883, or 8883 with TLS.",
  'cfg.mqtt_username.help':
    'User name for the broker. Leave it empty when the broker admits anonymous clients.',
  'cfg.mqtt_password.help': 'Password for the broker. It is stored but never shown again.',
  'cfg.mqtt_tls.help': "Connect encrypted (TLS). The broker's certificate is checked.",
  'cfg.mqtt_ca_file.help':
    "Path on the ovenbird server to a CA certificate, for a broker with its own certificate authority. Empty uses the system's trusted certificates.",
  'cfg.mqtt_client_id.help':
    'The name ovenbird connects with. Empty picks one; set it when the broker only admits known clients.',
  'cfg.heishamon_base.help':
    'The base topic HeishaMon publishes under (its MQTT topic base), usually panasonic_heat_pump.',
  'cfg.mqtt_inputs.help':
    'Extra MQTT topics ovenbird reads as sensors, such as a thermometer that publishes to MQTT. They appear in the sensor lists next to the Home Assistant sensors.',
  'cfg.control_outside_signal.label': 'Outside sensor for the curve',
  'cfg.control_outside_signal.help':
    "Optional: an outside thermometer (a Home Assistant sensor or an MQTT input, in °C) for the heating curve instead of the pump's own sensor. The safety envelope keeps using the pump's sensor. Without a fresh, plausible value the curve falls back to the pump's sensor.",
  'cfg.control_outside_max_age_s.label': 'Outside sensor counts as fresh for',
  'cfg.control_outside_max_age_s.help':
    "How old the chosen outside sensor's value may be. When it is older, the curve uses the pump's sensor until the chosen one reports again.",
  'cfg.control_outside_plausible_min_c.label': 'Outside sensor plausible from',
  'cfg.control_outside_plausible_min_c.help':
    "The lowest outside temperature the chosen sensor may report. A colder value counts as a fault: the curve uses the pump's sensor until the chosen one reads a plausible value again.",
  'cfg.control_outside_plausible_max_c.label': 'Outside sensor plausible up to',
  'cfg.control_outside_plausible_max_c.help':
    "The highest outside temperature the chosen sensor may report. A warmer value counts as a fault: the curve uses the pump's sensor until the chosen one reads a plausible value again.",
  'cfg.control_outside_max_deviation_k.label': 'Outside sensor may differ from the pump by',
  'cfg.control_outside_max_deviation_k.help':
    "How far the chosen sensor may be from the pump's own outside sensor. Further apart, one of the two is wrong and the curve uses the pump's sensor until they agree again.",
  'cfg.control_model_use.label': 'Controller use of the house model',
  'cfg.control_model_use.help':
    'Off: the controller ignores the model. Shadow: it computes every 15 minutes how sun and the forecast would move the room and records what it would do, but changes nothing. On: it shifts the room target a little within the bounds. On is locked until an evaluation and a shadow period are done.',
  'cfg.control_model_use.opt.off': 'Off',
  'cfg.control_model_use.opt.shadow': 'Shadow (computes only)',
  'cfg.control_model_use.opt.on': 'On (locked for now)',
  'cfg.control_model_max_setback_k.label': 'Largest shift down',
  'cfg.control_model_max_setback_k.help':
    'How far the model plan may lower the room target before free heat arrives, in K.',
  'cfg.control_model_max_preheat_k.label': 'Largest shift up',
  'cfg.control_model_max_preheat_k.help':
    'How far the model plan may raise the room target before a cold turn, in K.',
  'cfg.control_model_horizon_h.label': 'Hours looked ahead',
  'cfg.control_model_horizon_h.help':
    'How far ahead the planner predicts the room from the sun and the outside forecast, in hours.',
  'cfg.control_model_max_rmse_k.label': 'Largest model error accepted',
  'cfg.control_model_max_rmse_k.help':
    'The planner stays out while the model’s typical room error is above this, in K.',
};
