import type { RoomTrust } from '$lib/core/derive';
import type { ControlFact, ControlKind } from '$lib/core/mode';
import type { Alarm, ForecastPoint } from '$lib/core/types';

export type VerdictKind =
  'attention' | 'stove' | 'stove_idle' | 'ok' | 'warming' | 'warm' | 'unknown';
export type VerdictTone = 'good' | 'warn' | 'bad' | 'info' | 'neutral';

/**
 * Why Home asks for attention: the worst alarm (by code), a hold, a publish refusal, or a room
 * value ovenbird does not trust.
 */
export type Attention =
  | { kind: 'alarm'; code: string; more: number; critical: boolean }
  | { kind: 'held'; reason: string | null; until: string | null; latched: boolean }
  | { kind: 'refused' }
  | { kind: 'room'; trust: 'stale' | 'untrusted' | 'implausible' }
  | { kind: 'notify' };

export interface Verdict {
  kind: VerdictKind;
  tone: VerdictTone;
  attention: Attention | null;
  /** Who controls the pump, for `stove_idle` ("…but it only watches"). */
  control?: ControlKind;
}

export interface VerdictInputs {
  alarms: Alarm[];
  fact: ControlFact;
  room: number | null;
  target: number | null;
  halfBand: number;
  fresh: boolean;
  trust: RoomTrust;
  stove: boolean;
  /** Alerts are set up but do not reach anyone (`notifyVerdict(...).failing`). */
  notifyFailing?: boolean;
}

/**
 * One verdict for the top of Home, in this order: a critical alarm, a hold, a warning alarm, a
 * refusal to send, a room value that is stale or not trusted, alerts that do not reach anyone
 * (all "needs attention"), then wood
 * stove mode (`stove` while ovenbird sends and backs the heating off, `stove_idle` while it only
 * watches, is paused or off and so backs nothing off), then the room against the comfort band:
 * below it "warming up", above it "warmer than the target", inside it "at temperature".
 * Informational alarms never count; Shadow and a pause are not a problem of the house (the
 * control line says who controls).
 */
export function verdictOf(inputs: VerdictInputs): Verdict {
  const { alarms, fact, room, target, halfBand, fresh, trust, stove, notifyFailing } = inputs;
  const serious = alarms.filter((a) => a.severity === 'critical' || a.severity === 'warning');
  const critical = serious.filter((a) => a.severity === 'critical');
  const attention = (value: Attention, tone: VerdictTone = 'warn'): Verdict => ({
    kind: 'attention',
    tone,
    attention: value,
  });
  if (critical[0])
    return attention(
      { kind: 'alarm', code: critical[0].code, more: serious.length - 1, critical: true },
      'bad',
    );
  if (fact.kind === 'held')
    return attention({
      kind: 'held',
      reason: fact.holdReason,
      until: fact.holdUntil,
      latched: fact.holdLatched,
    });
  if (serious[0])
    return attention({
      kind: 'alarm',
      code: serious[0].code,
      more: serious.length - 1,
      critical: false,
    });
  if (fact.kind === 'refused') return attention({ kind: 'refused' });
  if (room !== null && !fresh) return attention({ kind: 'room', trust: 'stale' });
  if (room !== null && (trust === 'untrusted' || trust === 'implausible'))
    return attention({ kind: 'room', trust });
  if (notifyFailing) return attention({ kind: 'notify' });
  if (stove && !fact.sending && fact.kind !== 'unknown')
    return { kind: 'stove_idle', tone: 'info', attention: null, control: fact.kind };
  if (stove) return { kind: 'stove', tone: 'info', attention: null };
  if (room === null) return { kind: 'unknown', tone: 'neutral', attention: null };
  if (target === null) return { kind: 'ok', tone: 'good', attention: null };
  if (room < target - halfBand) return { kind: 'warming', tone: 'info', attention: null };
  if (room > target + halfBand) return { kind: 'warm', tone: 'good', attention: null };
  return { kind: 'ok', tone: 'good', attention: null };
}

export interface Tonight {
  minC: number;
  at: number;
}

const HOUR = 3_600_000;

/**
 * The coming night in local time: from 18:00 (or now, when later) until 08:00 the next morning;
 * before 06:00 the rest of the current night until 08:00.
 */
export function nightWindow(nowMs: number): { from: number; to: number } {
  const now = new Date(nowMs);
  const at = (dayOffset: number, hour: number) => {
    const d = new Date(now);
    d.setDate(d.getDate() + dayOffset);
    d.setHours(hour, 0, 0, 0);
    return d.getTime();
  };
  if (now.getHours() < 6) return { from: nowMs, to: at(0, 8) };
  return { from: Math.max(nowMs, at(0, 18)), to: at(1, 8) };
}

/**
 * The coldest forecast outside temperature tonight (see `nightWindow`), or null without forecast
 * points in that window.
 */
export function tonightOf(forecast: ForecastPoint[] | null, nowMs: number): Tonight | null {
  if (!forecast) return null;
  const { from, to } = nightWindow(nowMs);
  let best: Tonight | null = null;
  for (const [iso, temperature] of forecast) {
    const t = Date.parse(iso);
    if (!Number.isFinite(t) || t < from - HOUR || t > to) continue;
    if (temperature === null || !Number.isFinite(temperature)) continue;
    if (best === null || temperature < best.minC) best = { minC: temperature, at: t };
  }
  return best;
}

export type TonightHeating = 'continues' | 'stove' | 'not_sending' | 'other_controller' | 'mild';

/**
 * What happens to the heating tonight: it continues while ovenbird sends; it stays backed off
 * while the stove burns; in Shadow the other controller drives the pump; ovenbird sends nothing
 * (paused, held, refused, off) and the pump keeps its setting; or the night is milder than the
 * pump's own heating-off temperature, so the pump may not need to heat.
 */
export function tonightHeating(
  fact: ControlFact,
  stove: boolean,
  minC: number | null,
  heatingOffC: number | null,
): TonightHeating {
  if (minC !== null && heatingOffC !== null && minC > heatingOffC) return 'mild';
  if (fact.kind === 'watching') return 'other_controller';
  if (!fact.sending && fact.kind !== 'unknown') return 'not_sending';
  if (stove) return 'stove';
  return 'continues';
}
