import { describe, expect, it } from 'vitest';
import type { ControlFact } from '$lib/core/mode';
import type { Alarm, ForecastPoint } from '$lib/core/types';
import { nightWindow, tonightHeating, tonightOf, verdictOf, type VerdictInputs } from './verdict';

const fact = (over: Partial<ControlFact> = {}): ControlFact => ({
  kind: 'controlling',
  sending: true,
  tone: 'good',
  holdReason: null,
  holdUntil: null,
  holdLatched: false,
  refusal: null,
  refusals: [],
  safetyHold: [],
  water: { kind: 'sending', wouldSend: 32, pumpHas: 32 },
  ...over,
});
const alarm = (code: string, severity: Alarm['severity']): Alarm => ({
  code,
  severity,
  message: code,
  since: '2026-11-18T10:00:00Z',
  detail: {},
});
const base: VerdictInputs = {
  alarms: [],
  fact: fact(),
  room: 21.0,
  target: 21.0,
  halfBand: 0.3,
  fresh: true,
  trust: 'ok',
  stove: false,
};

describe('verdictOf', () => {
  it('says at temperature, warming up and warmer against the comfort band', () => {
    expect(verdictOf(base).kind).toBe('ok');
    expect(verdictOf({ ...base, room: 20.4 }).kind).toBe('warming');
    expect(verdictOf({ ...base, room: 21.6 }).kind).toBe('warm');
    expect(verdictOf({ ...base, room: null }).kind).toBe('unknown');
  });

  it('puts a critical alarm above a hold, a hold above a warning, and ignores info', () => {
    const held = fact({ kind: 'held', sending: false, holdReason: 'foreign writer' });
    const crit = verdictOf({
      ...base,
      fact: held,
      alarms: [alarm('low_flow', 'warning'), alarm('pump_error', 'critical')],
    });
    expect(crit).toMatchObject({ kind: 'attention', tone: 'bad' });
    expect(crit.attention).toMatchObject({ kind: 'alarm', code: 'pump_error', more: 1 });
    const hold = verdictOf({ ...base, fact: held, alarms: [alarm('low_flow', 'warning')] });
    expect(hold.attention).toMatchObject({ kind: 'held', reason: 'foreign writer' });
    const info = verdictOf({ ...base, alarms: [alarm('backup_heater_allowed', 'info')] });
    expect(info.kind).toBe('ok');
  });

  it('flags a refusal and an untrusted or stale room before the stove', () => {
    expect(
      verdictOf({ ...base, fact: fact({ kind: 'refused', sending: false }) }).attention,
    ).toMatchObject({ kind: 'refused' });
    expect(verdictOf({ ...base, fresh: false, stove: true }).attention).toMatchObject({
      kind: 'room',
      trust: 'stale',
    });
    expect(verdictOf({ ...base, trust: 'implausible' }).attention).toMatchObject({
      kind: 'room',
      trust: 'implausible',
    });
    expect(verdictOf({ ...base, stove: true, room: 22.8 }).kind).toBe('stove');
  });

  it('does not treat Shadow or a pause as a problem of the house', () => {
    expect(verdictOf({ ...base, fact: fact({ kind: 'simulated', sending: false }) }).kind).toBe(
      'ok',
    );
    expect(verdictOf({ ...base, fact: fact({ kind: 'paused', sending: false }) }).kind).toBe('ok');
  });

  it('asks for attention when alerts do not reach anyone, after the house itself', () => {
    expect(verdictOf({ ...base, notifyFailing: true }).attention).toEqual({ kind: 'notify' });
    expect(verdictOf({ ...base, notifyFailing: true, fresh: false }).attention?.kind).toBe('room');
    expect(verdictOf({ ...base, notifyFailing: true, stove: true }).attention?.kind).toBe('notify');
  });

  it('says the stove backs nothing off while ovenbird does not send', () => {
    const watching = fact({ kind: 'watching', sending: false });
    expect(verdictOf({ ...base, stove: true, fact: watching })).toMatchObject({
      kind: 'stove_idle',
      control: 'watching',
    });
    const paused = fact({ kind: 'paused', sending: false });
    expect(verdictOf({ ...base, stove: true, fact: paused }).control).toBe('paused');
    const held = fact({ kind: 'held', sending: false });
    expect(verdictOf({ ...base, stove: true, fact: held }).attention?.kind).toBe('held');
    expect(
      verdictOf({ ...base, stove: true, fact: fact({ kind: 'unknown', sending: false }) }).kind,
    ).toBe('stove');
  });
});

describe('tonight', () => {
  const at = (y: number, mo: number, d: number, h: number) => new Date(y, mo, d, h).getTime();

  it('takes the coming night from 18:00 to 08:00, or the rest of it after midnight', () => {
    const noon = at(2026, 10, 18, 12);
    expect(nightWindow(noon)).toEqual({ from: at(2026, 10, 18, 18), to: at(2026, 10, 19, 8) });
    const late = at(2026, 10, 18, 21);
    expect(nightWindow(late)).toEqual({ from: late, to: at(2026, 10, 19, 8) });
    const early = at(2026, 10, 19, 3);
    expect(nightWindow(early)).toEqual({ from: early, to: at(2026, 10, 19, 8) });
  });

  it('finds the coldest forecast point of the night', () => {
    const noon = at(2026, 10, 18, 12);
    const point = (ms: number, c: number | null): ForecastPoint => [
      new Date(ms).toISOString(),
      c,
      null,
      null,
      null,
    ];
    const forecast = [
      point(at(2026, 10, 18, 14), -5),
      point(at(2026, 10, 18, 22), 1),
      point(at(2026, 10, 19, 5), -1.5),
      point(at(2026, 10, 19, 6), null),
      point(at(2026, 10, 19, 12), -8),
    ];
    expect(tonightOf(forecast, noon)).toEqual({ minC: -1.5, at: at(2026, 10, 19, 5) });
    expect(tonightOf(null, noon)).toBeNull();
    expect(tonightOf([point(at(2026, 10, 18, 13), 3)], noon)).toBeNull();
  });

  it('says whether the heating continues', () => {
    expect(tonightHeating(fact(), false, 2, 18)).toBe('continues');
    expect(tonightHeating(fact(), true, 2, 18)).toBe('stove');
    expect(tonightHeating(fact({ kind: 'simulated', sending: false }), false, 2, 18)).toBe(
      'not_sending',
    );
    expect(tonightHeating(fact(), false, 19, 18)).toBe('mild');
    expect(tonightHeating(fact({ kind: 'watching', sending: false }), true, 2, 18)).toBe(
      'other_controller',
    );
    expect(tonightHeating(fact({ kind: 'paused', sending: false }), true, 2, 18)).toBe(
      'not_sending',
    );
  });
});
