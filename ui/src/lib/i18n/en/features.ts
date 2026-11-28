export const features = {
  section_features: 'Features',
  overviewFeaturesOn: '{n} of {total} on',
  overviewFeaturesLine: 'Switch each feature on or off',
  settingsFeaturesIntro:
    'Every feature has its own switch. Switch off what you do not want. The pill shows what each one is doing right now.',
  featuresLegend:
    'Off: switched off. Shadow: on, but only recording what it would do. On: switched on. Active now: acting at this moment.',
  featuresNoStatus: 'The live state of the features is not available right now.',
  feature_weather_compensation: 'Weather compensation',
  feature_room_feedback: 'Room correction',
  feature_slow_start: 'Slow start',
  feature_minimum_run: 'Minimum run',
  feature_pump_duty: 'Pump duty',
  feature_quiet: 'Quiet mode',
  feature_stove: 'Wood-stove mode',
  feature_dayshift: 'Sun day shift',
  feature_summer: 'Summer switch',
  feature_away: 'Away',
  feature_boost: 'Boost',
  feature_starts_alarm: 'Start-count alarm',
  feature_house_basics: 'House basics',
  featureHelp_weather_compensation:
    'Sets the water temperature from the outside temperature along your heating curve. Off, it uses one fixed water temperature.',
  featureHelp_room_feedback:
    'Nudges the water temperature up or down until the room reaches your comfort target.',
  featureHelp_slow_start:
    'After the compressor starts, holds the water a little below the curve and lets it rise slowly, so it does not overshoot.',
  featureHelp_minimum_run:
    'Keeps the compressor from stopping early after a start, so it runs longer in fewer, steadier cycles.',
  featureHelp_pump_duty:
    'Sets the speed of the water pump: faster while heating, slower when idle.',
  featureHelp_quiet:
    'Runs the heat pump quietly in set time windows and for a few minutes after every compressor start.',
  featureHelp_stove:
    'Backs the heating off while a wood stove warms the room, and picks up again when it is out.',
  featureHelp_dayshift:
    'On sunny, mild days the room gets a little warmer by day and a little cooler at night, so the pump runs less at night.',
  featureHelp_summer:
    'Switches space heating off when it has been warm outside for a while, and back on when it cools down.',
  featureHelp_away:
    'Lets you set a lower room temperature while you are away, with the house warm again when you return.',
  featureHelp_boost: 'Lets you make the room warmer or cooler for a few hours from the Home page.',
  featureHelp_starts_alarm:
    'Raises an alarm when the compressor starts too often. It only watches and never changes the heating.',
  featureHelp_house_basics:
    'Estimates how much heat your house loses, from the data ovenbird records. It only watches and never changes the heating.',
  featureState_off: 'Off',
  featureState_shadow: 'Shadow',
  featureState_on: 'On',
  featureState_active_now: 'Active now',
  featureMore: 'More options',
  featureFixed: 'Fixed by the installation',
  featureFixedHint:
    'These values are set when ovenbird is installed. They are shown here, not editable.',
  featureNotWorking:
    'Switched on, but not doing anything right now, for example because it has no room sensor to go by.',
  featureEditor: 'All settings: {section}',
  featureExperimental: 'Experimental',
  featureAck_dayshift:
    'Experimental. In the simulator this made houses with large sun-facing windows too warm. I want to try it on my house.',
  featureAckWhy: 'Tick the box above to make On available.',

  homeBoostTitle: 'Warmer for a while',
  homeBoostHow: 'Change the room target by',
  homeBoostFor: 'For',
  homeBoostHours: '{n} h',
  homeBoostStart: 'Start',
  homeBoostActive: 'Room target {offset} K until {until}',
  homeBoostLeft: '{left} left',
  homeBoostStop: 'Stop boost',
  homeBoostPaused_stove: 'Paused while wood-stove mode is active. The clock keeps running.',
  homeBoostPaused_summer: 'Paused by the summer switch. The clock keeps running.',
  homeBoostAway: 'Away is set. End away first to use a boost.',
  homeAwayTitle: 'Away',
  homeAwayTarget: 'Room target while away',
  homeAwayDate: 'Back on',
  homeAwayTime: 'at',
  homeAwaySet: 'Set away',
  homeAwayNote: 'Setting away ends a running boost.',
  homeAwayActive: 'Away until {until}',
  homeAwayReturning: 'Warming up for your return',
  homeAwayTargetLine: 'Room target {target} °C',
  homeAwayComfortFrom: 'Back to comfort from {time}',
  homeAwayEnd: 'I’m back',
  homeAwayTooSoon: 'Pick a moment more than {hours} h from now, so the house has time to warm up.',
  homeAwayTooFar: 'Pick a moment within 60 days.',
  homeAwayPaused_stove: 'The away target is paused while wood-stove mode is active.',
  homeAwayPaused_summer: 'The away target is paused by the summer switch.',
  homeSummerActive: 'Summer switch: no space heating (slow outside mean {mean} °C)',
  homeSummerWarming: 'Summer switch: collecting the outside mean first',

  dayshiftTitle: 'Sun day shift',
  dayshiftMode_off: 'Off',
  dayshiftMode_shadow: 'Shadow: records only',
  dayshiftMode_on: 'On',
  dayshiftPhase_idle: 'Idle',
  dayshiftPhase_boost: 'Warmer by day',
  dayshiftPhase_setback: 'Cooler at night',
  dayshiftPhase_recovery: 'Warming back up',
  dayshiftPhase_blocked: 'Blocked',
  dayshiftOffset: 'Offset',
  dayshiftOffsetApplied: '{offset} K applied',
  dayshiftOffsetShadow: '{offset} K computed, not applied',
  dayshiftGuards: 'Held back by',
  dayshiftNext: 'Next: {phase} at {time}',
  dayshiftNextNone: 'No change planned.',
  dayshiftShadow_up: 'In shadow: it would raise the room target by {k} K now. Nothing is sent.',
  dayshiftShadow_down: 'In shadow: it would lower the room target by {k} K now. Nothing is sent.',
  dayshiftShadow_none: 'In shadow: it would change nothing now.',
  dayshiftForecast: 'Today',
  dayshiftForecastLine:
    'Sun {sun} W/m² (needs {sunLimit}), outside now {outside} °C, lowest {min} °C (needs {limit}), tonight {night} °C',
  dayshiftForecastNone: 'No forecast has been read yet.',
  dayshiftForecastIssued: 'Forecast from {time}',
  dayshiftWindows:
    'Day {dayStart}–{dayEnd}, night {nightStart}–{nightEnd}, warm again at {comfortAt}',
  dayshiftSeeNow: 'See what it is doing now',
  dayshiftReason_off: 'The day shift is off.',
  dayshiftReason_outside_windows: 'Outside the day and night windows.',
  dayshiftReason_sun_forecast: 'Enough sun is forecast.',
  dayshiftReason_sun_low: 'Not enough sun for the rest of the day.',
  dayshiftReason_outside_mild: 'Mild enough outside.',
  dayshiftReason_outside_cold: 'Too cold outside.',
  dayshiftReason_outside_unknown: 'No outside temperature yet.',
  dayshiftReason_forecast_missing: 'No forecast for this period.',
  dayshiftReason_night_after_boost: 'A night after a sunny day: the room may be cooler.',
  dayshiftReason_no_boost_today: 'The day was not sunny for long enough, so no cooler night.',
  dayshiftReason_night_cold: 'The night is forecast too cold for a cooler room.',
  dayshiftReason_recovery_lead: 'Warming the room back up in time.',
  dayshiftReason_room_below_target: 'The room got too cold, so no more cooling tonight.',
  dayshiftReason_room_warm: 'The room is warm enough, so no more extra warmth today.',
  dayshiftReason_forecast_stale: 'The weather forecast is too old.',
  dayshiftReason_room_untrusted: 'The room temperature is not trusted right now.',
  dayshiftReason_stove_active: 'Wood-stove mode is active.',
  dayshiftReason_stove_tail: 'Wood-stove mode ended less than 12 h ago.',
  dayshiftReason_away: 'Away is set.',

  group_dayshift: 'Sun day shift',
  group_summer: 'Summer switch',
  group_manual: 'Boost and away',
  check_dayshift_windows:
    'The times do not fit: the day must start before it ends, and the night must run from its start to its end and give the room time to warm up before the next day.',
  check_dayshift_on_needs_ack:
    'The sun day shift is experimental. Tick that you want to try it before you switch it on, or use Shadow.',
  houseExcluded_away: 'Away: {n}',

  reason_quiet_start: 'Quiet after a start',
  reason_room_target: 'Boost',
  reason_away: 'Away',
  reason_summer: 'Summer switch',
  explain_reason_quiet_start:
    'The compressor just started, so the pump runs quietly for a few minutes.',
  explain_reason_room_target: 'You asked for a different room temperature for a while (boost).',
  explain_reason_away:
    'You are away, so the room target is lowered until shortly before you return.',
  explain_reason_summer:
    'The summer switch is holding the water at its minimum because it has been warm outside for a while.',
  term_room_target: 'Boost or away',
  term_summer: 'Summer switch',
  alarm_compressor_starts: 'Many compressor starts',
  alarmText_compressor_starts: 'The compressor started more often than the limit allows.',
  alarmWhy_compressor_starts:
    'Frequent short runs wear the compressor and usually mean the heating is not matched to the load.',
  alarmNow_compressor_starts: 'Nothing is changed; the alarm only reports it.',
  alarmYou_compressor_starts:
    'Check that the heating curve is not too low and that minimum run is switched on. If it keeps happening, ask your installer.',
  mon_compressor_starts: '{value} in the last hour, limit {limit}',
  alarm_dayshift: 'Sun day shift',
  alarmText_dayshift: 'The sun day shift started or ended a warmer or cooler period.',

  'cfg.control_dayshift_use.label': 'Sun day shift',
  'cfg.control_dayshift_use.help':
    'On a sunny, mild day ovenbird raises the room target a little by day and lowers it a little the night after, so the house stores the sun’s heat. Shadow only records what it would do.',
  'cfg.control_dayshift_use.opt.off': 'Off',
  'cfg.control_dayshift_use.opt.shadow': 'Shadow',
  'cfg.control_dayshift_use.opt.on': 'On',
  'cfg.control_dayshift_experimental_ok.label': 'Try the experimental day shift',
  'cfg.control_dayshift_experimental_ok.help':
    'You accept that the sun day shift is experimental: in the simulator it made houses with large sun-facing windows too warm. Needed to switch it on.',
  'cfg.control_dayshift_day_start.label': 'Day starts',
  'cfg.control_dayshift_day_start.help':
    'When the day starts, in the service’s time zone. On a sunny day the room target rises from here.',
  'cfg.control_dayshift_day_end.label': 'Day ends',
  'cfg.control_dayshift_day_end.help':
    'When the day ends. After this the room target is normal again.',
  'cfg.control_dayshift_boost_k.label': 'Warmer by day',
  'cfg.control_dayshift_boost_k.help':
    'How much warmer the room may get on a sunny, mild day, in K.',
  'cfg.control_dayshift_setback_k.label': 'Cooler at night',
  'cfg.control_dayshift_setback_k.help':
    'How much cooler the room may get in the night after such a day, in K.',
  'cfg.control_dayshift_min_outside_c.label': 'Not colder outside than',
  'cfg.control_dayshift_min_outside_c.help':
    'The shift only starts when the outside temperature, now and forecast, is at least this. Once it runs it carries on down to 1 °C lower.',
  'cfg.control_dayshift_min_sun_wm2.label': 'Enough sun',
  'cfg.control_dayshift_min_sun_wm2.help':
    'The average sunshine forecast for the rest of the day, in W/m², that counts as a sunny day. A running shift carries on down to half of it.',
  'cfg.control_dayshift_night_start.label': 'Night starts',
  'cfg.control_dayshift_night_start.help':
    'When the night starts, in which the room may be cooler.',
  'cfg.control_dayshift_night_end.label': 'Night ends',
  'cfg.control_dayshift_night_end.help': 'The latest moment the cooler night ends.',
  'cfg.control_dayshift_comfort_at.label': 'Warm again at',
  'cfg.control_dayshift_comfort_at.help':
    'When the room must be back at its normal temperature after a cooler night.',
  'cfg.control_dayshift_recovery_s.label': 'Time to warm up',
  'cfg.control_dayshift_recovery_s.help':
    'How long before that moment the cooler night stops. Floor heating needs about 4 to 5 hours.',
  'cfg.control_plan_rule_max_k.label': 'Largest planned shift',
  'cfg.control_plan_rule_max_k.help':
    'The most a planned rule such as the day shift may move the room target, in K. It also limits how far a cooler night lowers the too-cold alarm.',
  'cfg.control_summer_enabled.label': 'Summer switch',
  'cfg.control_summer_enabled.help':
    'Switches space heating off while it is warm outside. The pump itself stays on.',
  'cfg.control_summer_off_c.label': 'Heating off above',
  'cfg.control_summer_off_c.help':
    'No space heating while the slow average of the outside temperature is above this.',
  'cfg.control_summer_hysteresis_k.label': 'Resume below the limit by',
  'cfg.control_summer_hysteresis_k.help':
    'Heating comes back when the slow average is this many K below the limit. This stops it switching back and forth.',
  'cfg.control_summer_mean_s.label': 'Averaging time',
  'cfg.control_summer_mean_s.help':
    'How slowly the outside average follows the weather. A full day or more means one warm afternoon does not stop the heating.',
  'cfg.control_boost_enabled.label': 'Allow boost',
  'cfg.control_boost_enabled.help': 'Shows the boost control on the Home page. Off hides it.',
  'cfg.control_boost_default_k.label': 'Default boost',
  'cfg.control_boost_default_k.help':
    'How much warmer the room target is when a boost is started without a choice, in K.',
  'cfg.control_boost_default_s.label': 'Default boost length',
  'cfg.control_boost_default_s.help': 'How long a boost lasts when no length is chosen.',
  'cfg.control_away_enabled.label': 'Allow away',
  'cfg.control_away_enabled.help': 'Shows the away control on the Home page. Off hides it.',
  'cfg.control_away_target_c.label': 'Room target while away',
  'cfg.control_away_target_c.help':
    'The room temperature kept while you are away, between 10 and 20 °C.',
  'cfg.control_away_comfort_lead_s.label': 'Warm again before you return',
  'cfg.control_away_comfort_lead_s.help':
    'How long before your return the house is brought back to the comfort temperature. Floor heating is slow, so allow hours.',
  'cfg.control_quiet_enabled.label': 'Use quiet windows',
  'cfg.control_quiet_enabled.help':
    'Off ignores the time windows of the quiet mode. Quiet after a start keeps its own switch.',
  'cfg.control_quiet_start_enabled.label': 'Quiet after a start',
  'cfg.control_quiet_start_enabled.help':
    'Runs the heat pump quietly for the first minutes after the compressor starts, the loudest moment.',
  'cfg.control_quiet_start_minutes.label': 'Quiet minutes after a start',
  'cfg.control_quiet_start_minutes.help': 'How long the heat pump stays quiet after a start.',
  'cfg.control_quiet_start_level.label': 'Quiet level after a start',
  'cfg.control_quiet_start_level.help':
    'From 1 to 3. A higher level is quieter. A defrost keeps it quiet too.',
  'cfg.control_cycling_max_raise_k.label': 'Largest raise against stopping',
  'cfg.control_cycling_max_raise_k.help':
    'How many K above the curve the water temperature may be raised to stop the compressor switching off early.',
  'cfg.safety_starts_alarm_enabled.label': 'Start-count alarm',
  'cfg.safety_starts_alarm_enabled.help': 'Raises an alarm when the compressor starts too often.',
  'cfg.safety_starts_per_hour_max.label': 'Most starts per hour',
  'cfg.safety_starts_per_hour_max.help': 'More starts than this in one hour raise the alarm.',
  'cfg.safety_starts_per_day_max.label': 'Most starts per day',
  'cfg.safety_starts_per_day_max.help': 'More starts than this in one day raise the alarm.',
};
