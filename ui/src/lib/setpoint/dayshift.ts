import type { DayShift, DayShiftPhase } from '$lib/core/types';

export type PhaseTone = 'neutral' | 'ok' | 'info' | 'warn';

const TONES: Record<DayShiftPhase, PhaseTone> = {
  idle: 'neutral',
  boost: 'ok',
  setback: 'info',
  recovery: 'info',
  blocked: 'warn',
};

/**
 * Pill tone of a day-shift phase.
 */
export function phaseTone(phase: DayShiftPhase): PhaseTone {
  return TONES[phase];
}

/**
 * Whether the rule would raise the room target, lower it or change nothing, judged on its
 * step-limited offset of the latest evaluation (what shadow records but does not apply).
 */
export function shadowKind(shift: Pick<DayShift, 'offset_k'>): 'up' | 'down' | 'none' {
  if (shift.offset_k > 0.001) return 'up';
  if (shift.offset_k < -0.001) return 'down';
  return 'none';
}

/**
 * The reasons that are not guards: guards are listed apart as what holds the shift back.
 */
export function plainReasons(shift: Pick<DayShift, 'reasons' | 'guards'>): DayShift['reasons'] {
  return shift.reasons.filter((reason) => !(shift.guards as string[]).includes(reason));
}

/**
 * Whether the card has anything to say: not while the day shift is switched off.
 */
export function dayshiftShown(shift: Pick<DayShift, 'mode' | 'configured'> | null): boolean {
  return shift !== null && (shift.mode !== 'off' || shift.configured !== 'off');
}
