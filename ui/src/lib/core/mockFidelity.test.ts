import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import { initialConfigState, makeSignals, previewLimitations } from '$mock/config';
import {
  makeCommands,
  makeControl,
  makeDecision,
  initialState,
  ROOM_STALE_S,
} from '$mock/decisions';
import { makeHistory, makeSnapshot } from '$mock/fixtures';
import { makeInsightDaily } from '$mock/insight';
import { rangeError } from '$mock/plugin';
import type { Decision } from './types';
import { dayEnergy, startOfLocalDay } from '$lib/home/energy';

const NOW = new Date(2026, 10, 15, 14, 7, 30).getTime();

const recorded = JSON.parse(
  readFileSync(new URL('../../../mock/fixtures/real/decisions.json', import.meta.url), 'utf8'),
) as { decisions: Decision[] };

const points = (history: ReturnType<typeof makeHistory>, id: string): [number, number][] =>
  (history.series[id]?.points ?? []).map(([t, v]) => [Date.parse(t), Number(v)]);

describe('mock fidelity', () => {
  it('reports the defrost duty above the maximum, as the pump does', () => {
    const snapshot = makeSnapshot(NOW, { pump: 'defrost' });
    expect(snapshot.signals['main/Pump_Duty']?.value).toBe(220);
    expect(snapshot.signals['main/Max_Pump_Duty']?.value).toBe(159);
  });

  it('carries the recorded controller state keys and note shapes in decisions', () => {
    const real = recorded.decisions.at(-1) as Decision;
    const mock = makeDecision(NOW, NOW);
    const missing = Object.keys(real.record.controller_state).filter(
      (key) =>
        !(key in mock.record.controller_state) && !key.startsWith('ramp_') && !key.endsWith('_at'),
    );
    expect(missing).toEqual([]);
    expect(mock.record.controller_state['room_profile']).toBe('on_change');
    expect(typeof mock.record.controller_state['room_held_s']).toBe('number');
    const shape = (text: string) =>
      text
        .replace(/[+-]?\d+(\.\d+)?/g, '#')
        .replace(/# h # m|# min|# s\b/g, '<d>')
        .replace(/ (below|above) /, ' ~ ');
    const roomNote = (d: Decision) =>
      d.record.terms.find((term) => term.name === 'room_feedback')?.note ?? '';
    const realRoom = recorded.decisions.find((d) =>
      roomNote(d as Decision).includes('device alive'),
    ) as Decision;
    const mockRoom = Array.from({ length: 360 }, (_, i) =>
      makeDecision(NOW + i * 60_000, NOW),
    ).find((d) => d.reason === 'room_feedback' && !roomNote(d).includes('cooling')) as Decision;
    expect(shape(roomNote(mockRoom))).toBe(
      shape(roomNote(realRoom)).replace(', cooling authority # %', ''),
    );
    expect(shape(mockRoom.note)).toMatch(
      /^Room # K ~ target; PI adds # K to the curve's # °C at # °C outside; held value # °C/,
    );
    expect(mockRoom.arbiter.map((entry) => entry.kind)).toEqual([
      'water_setpoint',
      'max_pump_duty',
    ]);
  });

  it('lets room:stale reach the decisions', () => {
    const latest = makeDecision(NOW, NOW, 'auto', { roomStaleSince: NOW - ROOM_STALE_S * 1000 });
    const room = latest.record.inputs_used.find((input) => input.signal === 'room_temperature');
    expect(room?.fresh).toBe(false);
    expect(latest.reason).toBe('room_stale');
    expect(latest.note).toContain('No usable room temperature');
  });

  it('lists the replay limitations the service reports', () => {
    const state = initialConfigState(NOW);
    expect(previewLimitations(state, { control_comfort_c: 22 })).toEqual([]);
    expect(
      previewLimitations(state, { control_room_signal: 'ha/sensor.bedroom_temperature' }),
    ).toHaveLength(1);
    expect(previewLimitations(state, { control_room_profile: 'periodic' })).toEqual([
      "the room value's freshness is as recorded under the active sensor profile",
    ]);
  });

  it('agrees with its own history on today’s energy and COP', () => {
    const from = startOfLocalDay(NOW);
    const history = makeHistory(
      ['main/Heat_Power_Consumption', 'main/Heat_Power_Production'],
      from,
      NOW,
      60,
    );
    const day = dayEnergy(
      points(history, 'main/Heat_Power_Consumption'),
      points(history, 'main/Heat_Power_Production'),
      from,
      NOW,
    );
    const today = makeInsightDaily(7, NOW).days.at(-1);
    expect(today?.partial).toBe(true);
    expect(today?.electric_kwh).toBeCloseTo(day.electricKwh, 0);
    expect(Math.abs((today?.electric_kwh ?? 0) - day.electricKwh)).toBeLessThan(0.1);
    expect(Math.abs((today?.cop ?? 0) - (day.cop ?? 0))).toBeLessThan(0.05);
  });

  it('uses the adapter’s command texts', () => {
    const details = makeCommands(NOW).map((c) => `${c.status}: ${c.detail}`);
    expect(details).toContain('sent: published to panasonic_heat_pump/commands/SetCurves');
    expect(
      details.filter((d) => d.startsWith('verified')).every((d) => /applied in \d+ s$/.test(d)),
    ).toBe(true);
    expect(details.some((d) => d.startsWith('dropped: hold: '))).toBe(true);
  });

  it('answers 422 for an out-of-range weather window like the service', () => {
    expect(rangeError('back_h', '0', 168)?.[0]?.msg).toBe('Input should be greater than 0');
    expect(rangeError('ahead_h', '73', 72)?.[0]?.type).toBe('less_than_equal');
    expect(rangeError('back_h', 'x', 168)?.[0]?.type).toBe('float_parsing');
    expect(rangeError('back_h', '1', 168)).toBeNull();
    expect(rangeError('back_h', null, 168)).toBeNull();
  });

  it('gives the room candidate the snapshot value and held time', () => {
    const snapshot = makeSnapshot(NOW, {});
    const room = snapshot.signals['ha/sensor.living_room_temperature'];
    const candidate = makeSignals(NOW).room.find((c) => c.signal === 'room_temperature');
    expect(candidate?.value).toBe(room?.value);
    expect(candidate?.held_s).toBe(room?.held);
    expect(makeControl(NOW, initialState()).room?.value).toBe(room?.value);
  });
});
