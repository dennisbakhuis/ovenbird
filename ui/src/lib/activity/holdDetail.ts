/**
 * Forensics of a foreign-writer hold as the service puts them in the alarm `detail` of
 * `foreign_writer` and `command_hold` events: which setting changed, what ovenbird had set, what
 * the pump reports since when, what the pump keeps and what happens when the hold ends.
 */
export interface HoldForensics {
  setting: string | null;
  signal: string | null;
  register: string | null;
  ovenbirdValue: number | null;
  seenValue: number | null;
  seenSince: string | null;
  pumpKeeps: number | null;
  correction: number | null;
  holdUntil: string | null;
  atHoldEnd: 'write_again' | 'await_release' | null;
  controllerWants: number | null;
}

const num = (value: unknown): number | null =>
  typeof value === 'number' && Number.isFinite(value) ? value : null;
const text = (value: unknown): string | null =>
  typeof value === 'string' && value !== '' ? value : null;

/**
 * The forensics in an alarm `detail`, or null when it carries none (an older service).
 */
export function holdForensics(
  detail: Record<string, unknown> | null | undefined,
): HoldForensics | null {
  if (!detail || typeof detail !== 'object') return null;
  const setting = text(detail['setting']);
  const seenValue = num(detail['seen_value']);
  if (setting === null && seenValue === null) return null;
  const end = detail['at_hold_end'];
  return {
    setting,
    signal: text(detail['signal']),
    register: text(detail['register']),
    ovenbirdValue: num(detail['ovenbird_value']),
    seenValue,
    seenSince: text(detail['seen_since']),
    pumpKeeps: num(detail['pump_keeps']),
    correction: num(detail['correction']),
    holdUntil: text(detail['hold_until']),
    atHoldEnd: end === 'write_again' || end === 'await_release' ? end : null,
    controllerWants: num(detail['controller_wants']),
  };
}

/**
 * The unit a setting's value is shown in: °C for the water setpoint, none for pump duty and the
 * quiet level.
 */
export function settingUnit(setting: string | null): string {
  return setting === 'water_setpoint' ? ' °C' : '';
}

/**
 * What happens when the hold ends: a latched hold always waits for a release, whatever the detail
 * recorded at its start.
 */
export function holdEnd(
  forensics: HoldForensics,
  latched: boolean,
): 'write_again' | 'await_release' | null {
  return latched ? 'await_release' : forensics.atHoldEnd;
}
