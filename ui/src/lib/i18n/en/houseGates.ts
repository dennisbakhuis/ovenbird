export const houseGates = {
  houseGatesTitle: 'What the model can be trusted for',
  houseGatesLead: 'Each use has its own check. One passing does not vouch for the others.',
  houseGateName_heat_loss: 'Heat loss',
  houseGateName_dynamics: 'Room dynamics',
  houseGateName_sun: 'Sun response',
  houseGateUses_heat_loss: 'Used for the insulation score, the curve suggestion and What if.',
  houseGateUses_dynamics: 'Used for the cool-down prediction.',
  houseGateUses_sun: 'Not used yet: kept for a later version of the model plan.',
  houseGateOk: 'Trusted',
  houseGateNotYet: 'Not yet',
  houseGateSource_fitted: 'Judged when the model was made.',
  houseGateSource_revalidated: 'Judged again on newer data.',
  houseGateSource_legacy: 'Made by an older version; not judged in full yet.',
  houseGateNeedUnknown: 'There is not enough evidence yet.',

  houseGateNeed_no_signature:
    'The daily energy figures do not show a clear heating pattern in the data yet.',
  houseGateNeed_more_heating_days:
    'More heating days are needed: days that were cold enough for the heat pump to run.',
  houseGateNeedAmount_more_heating_days:
    '{n} more heating days are needed: days that were cold enough for the heat pump to run.',
  houseGateNeedAmountOne_more_heating_days:
    '1 more heating day is needed: a day that was cold enough for the heat pump to run.',
  houseGateNeed_more_outside_spread:
    'A wider range of outside temperatures is needed to tell heat loss from free heat.',
  houseGateNeedAmount_more_outside_spread:
    '{n} K more spread in outside temperature is needed to tell heat loss from free heat.',
  houseGateNeed_ua_interval_wide: 'The heat-loss figure is still too uncertain: its range is wide.',
  houseGateNeed_ua_disagrees:
    'The two ways of estimating the heat loss disagree: the model and the daily energy figures.',
  houseGateNeed_ua_unstable:
    'The heat-loss figure changes too much between separate training periods.',
  houseGateNeed_no_dynamics_skill:
    'The model does not yet predict the room over the next hours better than "the room stays as it is".',
  houseGateNeed_more_sunny_days:
    'More sunny days are needed to check how the model handles the sun.',
  houseGateNeed_no_sun_skill:
    'With the sun in, the model does not yet predict the room better than without it.',
  houseGateNeed_sun_response_off:
    "The room's measured reaction to the sun differs too much from the model's.",
  houseGateNeed_legacy_model: 'This model was made by an older version; the next run checks it.',

  houseGateDetails: 'How the checks came out',
  houseGateDetailsGate: '{gate}: {state}',
  houseCheck_signature: 'Daily energy figures show a heating pattern',
  houseCheck_excitation: 'Enough heating weather in the data',
  houseCheck_ua_interval: 'Heat-loss range narrow enough',
  houseCheck_ua_agreement: 'Both heat-loss estimates agree',
  houseCheck_ua_stability: 'Heat loss steady between training periods',
  houseCheck_skill_6h: 'Beats "no change" for the next 6 hours',
  houseCheck_sunny_days: 'Sunny days to check on',
  houseCheck_sun_skill: 'Sun improves the room prediction',
  houseCheck_sun_response: "Room's reaction to the sun matches the model's",
  houseCheckPass: 'passes',
  houseCheckFail: 'not yet',
  houseCheckValue: '{value}, limit {limit}',
  houseCheckValueOnly: '{value}',
  houseSkill24:
    'Over a full day ahead the model scores {value} against "no change". This is shown for information and never judged: a house held at a steady temperature is hard to out-predict.',

  houseSunLineOk: 'Sun response: trusted',
  houseSunLineNot: 'Sun response: not yet. {reason}.',
  houseSunLineNotPlain: 'Sun response: not yet',
  houseSunLineUse: 'Not used yet: kept for a later version of the model plan.',

  houseDriftNotTrusted:
    'The cool-down is not trusted yet: the model does not yet predict how the room reacts well enough, so treat it as rough.',
  houseStatusTrusted: 'Trusted',
  houseStatusPartly: 'Trusted for some uses',
};
