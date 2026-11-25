/**
 * Neutral variants for while hot water is hidden (Settings → Pump → Hot water): `busy_<key>`
 * replaces `<key>`, so a hot-water run still shows without naming hot water.
 */
export const hotwater = {
  busy_statusDhw: 'Pump busy elsewhere',
  busy_pumpStateDhw: 'Pump busy elsewhere',
  busy_homeLaneHotWater: 'Busy elsewhere',
  busy_laneHotWater: 'Busy elsewhere',
  busy_loopState_dhw: 'Busy elsewhere',
  busy_reason_dhw_freeze: 'Pump busy elsewhere',
  busy_binding_dhw_hold: 'No decrease while the pump is busy elsewhere',
  busy_explain_reason_dhw_freeze:
    'The pump is busy elsewhere, so corrections are paused and the setpoint is not lowered meanwhile. Water setpoint {setpoint} °C.',
  busy_explain_binding_dhw_hold: 'The setpoint is not lowered while the pump is busy elsewhere.',
  busy_frozenBy_dhw: 'pump busy elsewhere',
  busy_fact_dhw:
    'The pump is busy elsewhere: corrections are paused and the setpoint is not lowered.',
  busy_reasonCat_frozen: 'Frozen (defrost, pump busy elsewhere)',
  busy_inputEnum_valve_1: 'other circuit',
  busy_sigval_dhw: 'other circuit',
  busy_pumpRefusal_dhw: 'The pump is busy elsewhere. Try again afterwards.',
};
