export const houseControl = {
  houseTab_control: 'Control',
  houseCtlAbsent: 'This service does not offer the use of the model by the controller yet.',
  wfModelPlan_down:
    'The house model lowered the room target by {k}; room feedback works on the lowered target.',
  wfModelPlan_up:
    'The house model raised the room target by {k}; room feedback works on the raised target.',
  houseCtlTitle: 'How the controller uses the model',
  houseCtlSubtitle: 'Can shift the room target a little ahead of sun or colder weather.',
  houseCtlSwitchLabel: 'Controller use of the model',
  houseCtlUse_off: 'Off',
  houseCtlUse_shadow: 'Shadow (computes only)',
  houseCtlUse_on: 'On',
  houseCtlUseShort_off: 'Off',
  houseCtlUseShort_shadow: 'Shadow',
  houseCtlUseShort_on: 'On',
  houseCtlMeaning_off:
    'The controller ignores the model and heats to your room target, as it always did.',
  houseCtlMeaning_shadow:
    'Every 15 minutes the planner works out what it would do and records it here. It changes nothing: the room target stays as you set it.',
  houseCtlMeaning_on:
    'Every 15 minutes the planner shifts the room target within the bounds below: down before free heat arrives, up before a cold turn.',
  houseCtlLocked:
    'On is locked for now: it opens after an evaluation and a period in Shadow. Until then, choosing it is refused.',
  houseCtlDraftHint: 'A change goes through the bar at the bottom, like any setting.',
  houseCtlChangeLink: 'Change',

  houseCtlNowTitle: 'Right now',
  houseCtlNowOff: 'The planner is not running while the switch is off.',
  houseCtlNowNever:
    'The planner has not evaluated yet. The first evaluation comes within 15 minutes.',
  houseCtlEvaluated: 'Last evaluated {when}',
  houseCtlUntilNext: 'the next evaluation',
  houseCtlShift_would_down: 'Would lower the room target by {k} K until {until}.',
  houseCtlShift_would_up: 'Would raise the room target by {k} K until {until}.',
  houseCtlShift_is_down: 'Lowers the room target by {k} K until {until}.',
  houseCtlShift_is_up: 'Raises the room target by {k} K until {until}.',
  houseCtlHeld_down:
    'The plan wants to lower the room target by {k} K, but the controller does not apply it right now.',
  houseCtlHeld_up:
    'The plan wants to raise the room target by {k} K, but the controller does not apply it right now.',
  houseCtlStatus_blocked: 'No shift now: the planner may not act, see below.',
  houseCtlStatus_issued: 'A shift is issued.',
  houseCtlStatus_inside_dead_zone: 'No shift now: the expected change stays within the dead zone.',
  houseCtlStatus_crossing_zero:
    'No shift now: the shift would have to change direction, so it is held at zero for the moment.',
  houseCtlStatus_forecast_gap: 'No shift now: the weather forecast has a gap in the coming hours.',
  houseCtlStatus_forecast_mismatch:
    'No shift now: the forecast does not match the outside temperature that was measured.',
  houseCtlStatus_model_invalid: 'No shift now: the model gave no usable prediction.',
  houseCtlStatus_planner_error: 'No shift now: the planner ran into an error.',
  houseCtlRise:
    'In the next {h} hours {cause} is expected to warm the room by about {k} °C, around {at}.',
  houseCtlFall:
    'In the next {h} hours {cause} is expected to cool the room by about {k} °C, around {at}.',
  houseCtlFallThen: 'Later {cause} is expected to cool it by about {k} °C, around {at}.',
  houseCtlCause_sun: 'the sun',
  houseCtlCause_mild: 'the milder outside air',
  houseCtlCause_cold: 'the colder outside air',
  houseCtlCause_lessSun: 'less sun',
  houseCtlEffectNone:
    'No notable warming or cooling of the room is expected in the next {h} hours.',

  houseCtlBlocksTitle: 'May the planner act?',
  houseCtlReady: 'Nothing stops the planner right now.',
  houseCtlBlock_weather_off: 'The weather forecast is switched off.',
  houseCtlBlock_model_missing: 'There is no learned house model yet.',
  houseCtlBlock_model_not_credible: 'The model is not trusted yet.',
  houseCtlBlock_model_error_high:
    'The model’s room error ({rmse} K) is above the limit of {max} K.',
  houseCtlBlock_model_stale: 'The model is out of date.',
  houseCtlBlock_forecast_stale: 'The weather forecast is older than 3 hours.',
  houseCtlBlock_room_untrusted: 'The room temperature is not trusted right now.',
  houseCtlBlock_stove_active: 'A wood stove is burning.',
  houseCtlBlock_stove_tail: 'A wood stove was burning in the last 12 hours.',
  houseCtlBlockUnknown: 'Reason: {code}',

  houseCtlChartTitle: 'Computed shift of the room target, last 7 days',
  houseCtlComputed: 'Computed shift',
  houseCtlApplied: 'Applied',
  houseCtlBand: 'Allowed range',
  houseCtlChartNote:
    'Dashed: what the planner computed. Solid: what the controller applied. A break: not computed.',
  houseCtlDay_one: '{n} day',
  houseCtlDay_other: '{n} days',
  houseCtlSumNone: 'In the last {n} days the planner did not evaluate.',
  houseCtlSumFlat_would: 'In the last {n} days the model would not have shifted the room target.',
  houseCtlSumFlat_did: 'In the last {n} days the model did not shift the room target.',
  houseCtlSumDown_would_first:
    'In the last {n} days the model would have lowered the room target on {days}, by at most {k} K.',
  houseCtlSumDown_would_next: 'It would have lowered the room target on {days}, by at most {k} K.',
  houseCtlSumDown_did_first:
    'In the last {n} days the model lowered the room target on {days}, by at most {k} K.',
  houseCtlSumDown_did_next: 'It lowered the room target on {days}, by at most {k} K.',
  houseCtlSumUp_would_first:
    'In the last {n} days the model would have raised the room target on {days}, by at most {k} K.',
  houseCtlSumUp_would_next: 'It would have raised it on {days}, by at most {k} K.',
  houseCtlSumUp_did_first:
    'In the last {n} days the model raised the room target on {days}, by at most {k} K.',
  houseCtlSumUp_did_next: 'It raised it on {days}, by at most {k} K.',
  houseCtlSumApplied: 'About {h} hours of the shifts were applied.',

  houseCtlBounds: 'At most {down} K down and {up} K up, looking {h} hours ahead.',
  houseCtlAdvanced: 'Bounds and limits',
  houseCtlNoteTitle: 'What can go wrong',
  houseCtlNote:
    'The model is a simplification of your house and a forecast can be wrong, so a shift can be a little off. What protects you: the bounds above cap every shift, the room sensor still decides (the room correction keeps working on the shifted target), and the safety limits stay as they are.',
  houseCtlFailed: 'The model use could not be loaded.',
  houseStatusUse: 'Controller use: {use}',
  houseStatusUseLink: 'Details',
  houseCtlModelLine: 'Model {model}, typical room error {rmse} K.',

  explain_reason_plan_setback_model:
    'Room target lowered by {planApplied}: the house model expects the room to warm up on its own in the next hours (sun or milder weather), so there is less need to heat now. Water setpoint {setpoint} °C.',
  explain_reason_plan_preheat_model:
    'Room target raised by {planApplied}: the house model expects the room to cool down in the next hours (a cold turn or less sun), so heating starts a little early. Water setpoint {setpoint} °C.',
  explain_plan_requested: 'The plan asked for {planRequested}; the bounds limited it.',
  explain_plan_ignored: 'The house model’s plan was not used: {why}.',
  houseCtlIgnored_room_untrusted: 'the room temperature is not trusted',
  houseCtlIgnored_stove_active: 'a wood stove is burning',
  houseCtlIgnored_stove_recovery:
    'the wood-stove detection is still waiting after a fire or a sensor fault',
  houseCtlIgnored_slice_too_long: 'the plan was valid for longer than allowed',
} as const;
