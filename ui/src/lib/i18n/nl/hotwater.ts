import type { hotwater as en } from '$lib/i18n/en/hotwater';

export const hotwater: Record<keyof typeof en, string> = {
  busy_statusDhw: 'Pomp elders bezig',
  busy_pumpStateDhw: 'Pomp elders bezig',
  busy_homeLaneHotWater: 'Elders bezig',
  busy_laneHotWater: 'Elders bezig',
  busy_loopState_dhw: 'Elders bezig',
  busy_reason_dhw_freeze: 'Pomp elders bezig',
  busy_binding_dhw_hold: 'Geen verlaging terwijl de pomp elders bezig is',
  busy_explain_reason_dhw_freeze:
    'De pomp is elders bezig, dus correcties staan stil en de aanvoertemperatuur wordt ondertussen niet verlaagd. Aanvoertemperatuur {setpoint} °C.',
  busy_explain_binding_dhw_hold:
    'De aanvoertemperatuur wordt niet verlaagd terwijl de pomp elders bezig is.',
  busy_frozenBy_dhw: 'pomp elders bezig',
  busy_fact_dhw:
    'De pomp is elders bezig: correcties staan stil en de aanvoertemperatuur wordt niet verlaagd.',
  busy_reasonCat_frozen: 'Bevroren (ontdooien, pomp elders bezig)',
  busy_inputEnum_valve_1: 'ander circuit',
  busy_sigval_dhw: 'ander circuit',
  busy_pumpRefusal_dhw: 'De pomp is elders bezig. Probeer het daarna opnieuw.',
};
