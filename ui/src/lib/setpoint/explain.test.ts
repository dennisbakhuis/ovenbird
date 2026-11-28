import { describe, expect, it } from 'vitest';
import { buildRecord } from '$mock/decisions';
import codes from '$mock/fixtures/codes.json';
import recorded from '$mock/fixtures/decisions-sim.json';
import { withOutsideDecision } from '$mock/integrations';
import {
  curveOutside,
  decisionFacts,
  explain,
  flipModel,
  inputViews,
  livenessKind,
  livenessLabel,
  noteClauses,
  numberFormats,
  outsideFact,
  parseCurveNote,
  roomFacts,
  stoveDetails,
  stoveFact,
} from './explain';
import { dictionaries, translateOptional, type Language } from '$lib/i18n';
import type { Decision, DecisionRecord } from '$lib/core/types';

const languages: Language[] = ['en', 'nl'];
const translator =
  (language: Language) =>
  (key: string, params = {}) =>
    translateOptional(language, key, params);

function record(overrides: Partial<DecisionRecord> = {}): DecisionRecord {
  const base = (recorded.decisions as unknown as Decision[])[0] as Decision;
  return { ...structuredClone(base.record), ...overrides };
}

describe('explain', () => {
  it.each(languages)('has a complete sentence for every reason code in %s', (language) => {
    const fmt = numberFormats(language);
    for (const reason of codes.reason) {
      const result = explain(record({ reason, binding: null }), translator(language), fmt);
      expect(result.headline, reason).not.toBe(reason);
      expect(result.headline, reason).not.toMatch(/\{\w+\}/);
      expect(result.headline.length, reason).toBeGreaterThan(10);
    }
  });

  it.each(languages)('has a complete sentence for every binding code in %s', (language) => {
    const fmt = numberFormats(language);
    for (const binding of codes.binding) {
      const result = explain(record({ binding }), translator(language), fmt);
      expect(result.constraint, binding).not.toBeNull();
      expect(result.constraint, binding).not.toBe(binding);
      expect(result.constraint, binding).not.toMatch(/\{\w+\}/);
    }
  });

  it('fills the room-feedback sentence of a service decision with its numbers', () => {
    const decision = (recorded.decisions as unknown as Decision[])[0] as Decision;
    const fmt = numberFormats('en');
    const result = explain(decision.record, translator('en'), fmt);
    const target = decision.record.controller_state['room_target_c'] as number;
    const error = decision.record.controller_state['room_error_k'] as number;
    const feedback = decision.record.terms.find((term) => term.name === 'room_feedback');
    expect(result.headline).toContain(fmt.plain(target - error, 1));
    expect(result.headline).toContain(fmt.plain(target, 1));
    expect(result.headline).toContain(fmt.signed(feedback?.value ?? 0));
    expect(result.headline).toContain(`${decision.setpoint} °C`);
    expect(result.constraint).toBeNull();
    expect(result.flip).toMatch(/room temperature/);
  });

  it('speaks Dutch with the fixed terms', () => {
    const decision = (recorded.decisions as unknown as Decision[])[0] as Decision;
    const result = explain(decision.record, translator('nl'), numberFormats('nl'));
    expect(result.headline).toContain('ruimtecorrectie');
    expect(result.headline).toContain('stooklijn');
    const ramp = explain(
      buildRecord(5 * 60_000 + 360 * 4000 * 60_000).record,
      translator('nl'),
      numberFormats('nl'),
    );
    expect(ramp.headline).toContain('zachte start');
  });

  it('falls back to the raw code for unknown codes', () => {
    const result = explain(
      record({ reason: 'brand_new_reason', binding: 'brand_new_binding' }),
      translator('en'),
      numberFormats('en'),
    );
    expect(result.headline).toBe('brand_new_reason');
    expect(result.constraint).toBe('brand_new_binding');
  });

  it('names the actor of an override, with a fallback', () => {
    const named = explain(
      record({ reason: 'override', actor: 'admin' }),
      translator('en'),
      numberFormats('en'),
    );
    expect(named.headline).toContain('by admin');
    const anonymous = explain(
      record({ reason: 'override', actor: null }),
      translator('en'),
      numberFormats('en'),
    );
    expect(anonymous.headline).toContain('an operator');
  });

  it('picks the flip subject from the flip input', () => {
    const fmt = numberFormats('en');
    const outside = explain(
      record({ flip_input: 'main/Outside_Temp', flip_distance: 1.5 }),
      translator('en'),
      fmt,
    );
    expect(outside.flip).toContain('outside temperature');
    const water = explain(
      record({ flip_input: 'pre_round', flip_distance: 0.3 }),
      translator('en'),
      fmt,
    );
    expect(water.flip).toContain('water temperature');
    const none = explain(record({ flip_distance: null }), translator('en'), fmt);
    expect(none.flip).toBeNull();
  });

  it('has the Shadow wording the owner asked for', () => {
    expect(dictionaries.en.mode_shadow).toBe('Shadow (reads and decides, never sends)');
    expect(dictionaries.nl.mode_shadow).toBe('Schaduw (leest en beslist, stuurt nooit)');
  });
});

const LIVE_NOTE =
  "Room 0.1 K above target; PI adds +0.2 K to the curve's 30.4 °C at 5.9 °C outside; held value 21.9 °C (2 h 10 m), device alive (humidity 4 min ago), ±0.2 K, cooling authority 80 %; defrost in progress: integrator frozen, no decrease; defrost: the pump sets its own duty; no duty command; cycling floor 30.5 °C limits the decrease; setpoint stays 31 °C, no decrease during defrost.";

describe('explain with a plan reason', () => {
  it('keeps the plain plan sentence for a plan that is not a model plan', () => {
    const text = explain(
      record({ reason: 'plan_setback', ladder: 'optimiser_plan', binding: null }),
      translator('en'),
      numberFormats('en'),
    );
    expect(text.headline).toContain('The plan asks for a setback');
  });
});

describe('flipModel', () => {
  it('puts the room flip point below the room when the water would step up', () => {
    const model = flipModel(
      record({
        setpoint: 31,
        pre_round: 31.3,
        flip_distance: 0.3,
        flip_input: 'room_temperature',
        controller_state: { room_target_c: 21.0, room_error_k: 0.4 },
      }),
    );
    expect(model?.subject).toBe('room');
    expect(model?.value).toBeCloseTo(20.6, 9);
    expect(model?.points).toHaveLength(1);
    expect(model?.points[0]?.at).toBeCloseTo(20.3, 9);
    expect(model?.points[0]?.setpoint).toBe(32);
    expect(model?.target).toBe(21.0);
  });

  it('puts the flip point above for a water step down, and in water terms when clamped', () => {
    const room = flipModel(
      record({
        setpoint: 31,
        pre_round: 30.8,
        flip_distance: 0.2,
        flip_input: 'room_temperature',
        controller_state: { room_target_c: 21.0, room_error_k: 0 },
      }),
    );
    expect(room?.points[0]?.at).toBeCloseTo(21.2, 9);
    expect(room?.points[0]?.setpoint).toBe(30);
    const water = flipModel(
      record({ setpoint: 31, pre_round: 31.2, flip_distance: 0.3, flip_input: 'pre_round' }),
    );
    expect(water?.subject).toBe('water');
    expect(water?.points[0]?.at).toBeCloseTo(31.5, 9);
    expect(water?.target).toBeNull();
  });

  it('shows both sides when the calculated value sits on the setpoint', () => {
    const model = flipModel(
      record({
        setpoint: 31,
        pre_round: 31,
        flip_distance: 0.5,
        flip_input: 'room_temperature',
        controller_state: { room_target_c: 21.0, room_error_k: 0 },
      }),
    );
    expect(model?.points.map((p) => p.setpoint)).toEqual([32, 30]);
  });

  it('is null without a distance or setpoint', () => {
    expect(flipModel(record({ flip_distance: null }))).toBeNull();
    expect(flipModel(record({ setpoint: null }))).toBeNull();
  });
});

describe('roomFacts and livenessLabel', () => {
  it('reads the held value, proof of life and authority from the controller state', () => {
    const facts = roomFacts(
      record({
        controller_state: {
          room_profile: 'on_change',
          room_held_s: 7800,
          room_alive_s: 240,
          room_alive_by: 'room_humidity',
          room_quantum_k: 0.2,
          room_authority: 0.8,
          room_plausible: true,
          room_crosscheck_deviation_k: 0.3,
        },
      }),
    );
    expect(facts).toMatchObject({
      profile: 'on_change',
      heldS: 7800,
      aliveS: 240,
      aliveBy: 'room_humidity',
      quantumK: 0.2,
      authority: 0.8,
      plausible: true,
      signal: 'room_temperature',
    });
    expect(livenessLabel('room_humidity', 'room_temperature')).toBe('humidity');
    expect(
      livenessLabel('ha/sensor.living_room_humidity', 'ha/sensor.living_room_temperature'),
    ).toBe('humidity');
    expect(livenessLabel('sensor.motion', null)).toBe('motion');
  });

  it('names the liveness kind in the UI language', () => {
    const nl = (key: string) => translateOptional('nl', key);
    expect(livenessKind('humidity', nl)).toBe('luchtvochtigheid');
    expect(livenessKind('Living room climate humidity', nl)).toBe(
      'Living room climate luchtvochtigheid',
    );
    expect(livenessKind('Living room climate Battery', nl)).toBe('Living room climate Batterij');
    expect(livenessKind('sensor_xyz', nl)).toBe('sensor_xyz');
  });

  it('is null without a room input', () => {
    const base = record({ controller_state: {} });
    expect(
      roomFacts({ ...base, inputs_used: base.inputs_used.filter((i) => i.source !== 'room') }),
    ).toBeNull();
  });
});

describe('decisionFacts', () => {
  const fmt = numberFormats('en');

  it('names defrost, the skipped duty command and a limited decrease', () => {
    const facts = decisionFacts(
      record({
        reason: 'cycling_protect',
        binding: 'cycling_floor',
        note: LIVE_NOTE,
        controller_state: { frozen_by: 'defrost' },
      }),
      fmt,
    );
    expect(facts.map((f) => f.kind)).toEqual(['defrost', 'duty_skipped', 'cycling_limit']);
    expect(facts[2]?.params['floor']).toBe('30.5');
  });

  it('tells a raise apart, and leaves out what the headline already says', () => {
    const raise = decisionFacts(
      record({
        reason: 'safety_clamp',
        binding: 'cycling_floor',
        note: 'Room 0.1 K below target; cycling floor raises to 30 °C; setpoint 30 °C.',
      }),
      fmt,
    );
    expect(raise.map((f) => f.kind)).toEqual(['cycling_raise']);
    const headline = decisionFacts(
      record({ reason: 'defrost_freeze', binding: 'defrost_hold', note: '' }),
      fmt,
    );
    expect(headline).toEqual([]);
  });

  it('reports a ramp cap and other reasons for a frozen integrator', () => {
    const facts = decisionFacts(
      record({
        terms: [
          { name: 'curve', raw: 30, value: 30, unit: '°C', note: '' },
          { name: 'start_ramp', raw: -2, value: -2, unit: 'K', note: '' },
        ],
        controller_state: { ramp_cap_c: 28, frozen_by: 'anti_windup' },
      }),
      fmt,
    );
    expect(facts).toEqual([
      { kind: 'ramp_cap', params: { cap: '28' } },
      { kind: 'integrator_frozen', params: { by: 'anti_windup' } },
    ]);
  });
});

describe('noteClauses', () => {
  it('names a hot-water run "pump busy elsewhere" while hot water is hidden', () => {
    const note = 'DHW run in progress: integrator frozen, no decrease; setpoint 30 °C.';
    expect(noteClauses(note)[0]).toEqual({
      kind: 'dhw',
      text: 'DHW run in progress: integrator frozen, no decrease',
    });
    expect(noteClauses(note, false)[0]).toEqual({
      kind: 'dhw',
      text: 'Pump busy elsewhere: integrator frozen, no decrease',
    });
  });

  it('splits the live note into tagged clauses and keeps the duty clause whole', () => {
    const clauses = noteClauses(LIVE_NOTE);
    expect(clauses.map((c) => c.kind)).toEqual([
      'room',
      'room',
      'sensor',
      'defrost',
      'defrost',
      'cycling',
      'outcome',
    ]);
    expect(clauses[2]?.text).toBe(
      'Held value 21.9 °C (2 h 10 m), device alive (humidity 4 min ago), ±0.2 K, cooling authority 80 %',
    );
    expect(clauses[4]?.text).toBe('Defrost: the pump sets its own duty; no duty command');
    expect(clauses[6]?.text).not.toMatch(/\.$/);
  });
});

describe('inputViews', () => {
  it('labels the recorded inputs, keeps enums and drops internal flags', () => {
    const views = inputViews(record());
    expect(views.map((v) => v.signal)).not.toContain('stats');
    const byKey = Object.fromEntries(views.map((v) => [v.key, v]));
    expect(byKey['outside']?.unit).toBe('°C');
    expect(byKey['room']?.signal).toBe('room_temperature');
    expect(byKey['defrost']?.enumKey).toBe('defrost_0');
    for (const language of languages) {
      for (const view of views) {
        expect(translateOptional(language, `input_${view.key}`), view.key).toBeDefined();
        if (view.enumKey)
          expect(translateOptional(language, `inputEnum_${view.enumKey}`)).toBeDefined();
      }
    }
  });
});

describe('stoveFact', () => {
  const fmt = numberFormats('en');
  const NOW = Date.parse('2026-11-18T19:00:00Z');
  const stove = {
    enabled: true,
    auto: true,
    backoffK: 3,
    episode: {
      source: 'auto' as const,
      trigger: 'level' as const,
      sinceMs: NOW - 80 * 60_000,
      untilMs: null,
      entryC: 23.3,
    },
    waiting: null,
  };

  it('describes an active episode with its back-off and freezes the integrator for the stove', () => {
    const built = buildRecord(NOW, 'auto', { stove }).record;
    const fact = stoveFact(built, fmt);
    expect(fact?.kind).toBe('stove');
    expect(fact?.params['backoff']).toBe('3');
    expect(built.terms.find((term) => term.name === 'stove')?.value).toBe(-3);
    const facts = decisionFacts(built, fmt);
    expect(facts.some((f) => f.kind === 'stove')).toBe(true);
    expect(
      facts.some((f) => f.kind === 'integrator_frozen' && /stove/.test(JSON.stringify(f.params))),
    ).toBe(false);
  });

  it.each(['blocked', 'level_blocked', 'reentry_wait'] as const)(
    'explains the waiting state %s in plain words',
    (waiting) => {
      const built = buildRecord(NOW, 'auto', {
        stove: { ...stove, episode: null, waiting },
      }).record;
      const fact = stoveFact(built, fmt);
      expect(fact?.kind).toBe(`stove_${waiting}`);
      for (const language of languages) {
        const text = translateOptional(language, `fact_stove_${waiting}`, fact?.params ?? {});
        expect(text).toBeTruthy();
        expect(text).not.toMatch(/\{\w+\}/);
      }
    },
  );

  it('has nothing to say when wood-stove mode is not configured', () => {
    expect(stoveFact(buildRecord(NOW).record, fmt)).toBeNull();
  });
});

describe('a held setpoint clamped to the safety band', () => {
  it('names the clamp as a fact and the envelope as the constraint', () => {
    const held = record({
      reason: 'defrost_freeze',
      binding: 'envelope_max',
      ladder: 'hold',
      setpoint: 34,
      note: 'Holding: defrost; keeping the last intents; safety bound envelope_max clamps the held 40 → 34 °C.',
      controller_state: { frozen_by: 'defrost', safety_low_c: 28.5, safety_high_c: 34.5 },
    });
    const fmt = numberFormats('en');
    const facts = decisionFacts(held, fmt);
    expect(facts.find((f) => f.kind === 'held_clamped')?.params).toEqual({
      held: '40',
      setpoint: '34',
    });
    const text = explain(held, translator('en'), fmt);
    expect(text.constraint).toBe(
      'The safety envelope allows no more than 34.5 °C at this outside temperature.',
    );
  });
});

describe('stoveDetails', () => {
  const fmt = numberFormats('en');
  const NOW = Date.parse('2026-11-18T19:00:00Z');
  const withState = (extra: Record<string, unknown>) => {
    const built = buildRecord(NOW);
    return {
      ...built.record,
      controller_state: { ...built.record.controller_state, ...extra },
    } as typeof built.record;
  };

  it('says why an episode ended, a halved back-off and a fault', () => {
    expect(
      stoveDetails(withState({ stove_event: 'exited', stove_exit: 'room_jump' }), fmt),
    ).toEqual([{ kind: 'stove_exited', params: { reason: 'room_jump' } }]);
    expect(
      stoveDetails(withState({ stove_state: 'active', stove_reference_share: 0.5 }), fmt),
    ).toEqual([{ kind: 'stove_reference_short', params: { share: '50' } }]);
    expect(
      stoveDetails(
        withState({
          stove_state: 'inactive',
          stove_fault: true,
          stove_jump_k: 2.4,
          stove_exit_c: 22.5,
        }),
        fmt,
      ),
    ).toEqual([{ kind: 'stove_fault', params: { jump: '2.4', exit: '22.5' } }]);
    expect(
      stoveDetails(withState({ stove_state: 'active', stove_reference_share: 1 }), fmt),
    ).toEqual([]);
  });
});

describe('fixed water temperature (weather-dependent control off)', () => {
  const fmt = numberFormats('en');
  const fixed = (reason: string) =>
    record({
      reason,
      controller_state: { ...record().controller_state, base: 'fixed' },
    } as Partial<DecisionRecord>);

  it.each(languages)('names the fixed temperature instead of the curve (%s)', (language) => {
    for (const reason of ['curve', 'room_feedback']) {
      const { headline } = explain(fixed(reason), translator(language), fmt);
      const curveWord = language === 'en' ? /heating curve/i : /stooklijn/i;
      expect(headline).not.toMatch(curveWord);
      expect(headline).toMatch(language === 'en' ? /fixed/ : /vaste/);
    }
  });

  it('keeps the curve wording while weather-dependent control is on', () => {
    const { headline } = explain(record({ reason: 'curve' }), translator('en'), fmt);
    expect(headline).toMatch(/heating curve/);
  });
});

describe('outside sensor of the curve', () => {
  const decision = (recorded.decisions as unknown as Decision[])[0] as Decision;
  const fmt = numberFormats('en');

  it('reads the plain, chosen and fallback curve notes', () => {
    expect(parseCurveNote('curve at -2.95 °C filtered outside (-1 °C raw)')).toEqual({
      filtered: -2.95,
      raw: -1,
      from: null,
      fallback: null,
    });
    expect(
      parseCurveNote('curve at 4.25 °C filtered outside (3 °C raw from ha/sensor.garden)'),
    ).toMatchObject({ filtered: 4.25, raw: 3, from: 'ha/sensor.garden', fallback: null });
    expect(
      parseCurveNote(
        'curve at 4.25 °C filtered outside (5 °C raw from the pump: ha/sensor.garden is stale, 42 min old)',
      ),
    ).toMatchObject({
      raw: 5,
      from: null,
      fallback: { signal: 'ha/sensor.garden', why: 'stale', ageMin: 42 },
    });
    expect(
      parseCurveNote(
        'curve at 4.25 °C filtered outside (5 °C raw from the pump: ha/sensor.garden has no value)',
      )?.fallback,
    ).toEqual({ signal: 'ha/sensor.garden', why: 'missing', ageMin: null });
    expect(parseCurveNote('curve at 1e-05 °C filtered outside (2.5e-06 °C raw)')?.raw).toBe(2.5e-6);
  });

  it.each([
    ['has no usable value, unit: no temperature unit', 'missing'],
    ['is implausible, 60 °C is outside -40…50 °C', 'implausible'],
    ['is implausible, not a finite number', 'implausible'],
    ['is too far from the pump, 20 °C against 8 °C, more than 10 K apart', 'deviates'],
  ])('reads the fallback reason of "%s"', (clause, why) => {
    const note = `curve at 4.25 °C filtered outside (8 °C raw from the pump: ha/sensor.garden ${clause})`;
    expect(parseCurveNote(note)?.fallback).toEqual({
      signal: 'ha/sensor.garden',
      why,
      ageMin: null,
    });
  });

  it('takes the reason from the controller state', () => {
    const stale = withOutsideDecision(decision, 'ha/sensor.garden', true).record;
    const implausible = {
      ...stale,
      controller_state: { ...stale.controller_state, outside_reason: 'implausible' },
    };
    expect(stale.controller_state['outside_reason']).toBe('stale');
    expect(curveOutside(implausible)?.why).toBe('implausible');
    expect(outsideFact(implausible, fmt)?.params['why']).toBe('implausible');
  });

  it('keeps the note when the state has no reason', () => {
    const stale = withOutsideDecision(decision, 'ha/sensor.garden', true).record;
    const older = { ...stale, controller_state: { ...stale.controller_state } };
    delete older.controller_state['outside_reason'];
    expect(curveOutside(older)?.why).toBe('stale');
    expect(parseCurveNote('fixed water 35 °C')).toBeNull();
  });

  it('adds no fact and keeps the output without a chosen sensor', () => {
    expect(curveOutside(decision.record)).toBeNull();
    expect(outsideFact(decision.record, fmt)).toBeNull();
    const same = withOutsideDecision(decision, null, false);
    expect(decisionFacts(same.record, fmt)).toEqual(decisionFacts(decision.record, fmt));
    expect(flipModel(same.record)).toEqual(flipModel(decision.record));
  });

  it('names the chosen sensor and the value the curve used', () => {
    const chosen = withOutsideDecision(decision, 'ha/sensor.garden', false).record;
    expect(curveOutside(chosen)).toEqual({
      signal: 'ha/sensor.garden',
      fallback: false,
      why: null,
      ageMin: null,
      raw: -1.6,
    });
    expect(decisionFacts(chosen, fmt).map((f) => f.kind)).toContain('outside_source');
    expect(noteClauses(chosen.note)).toEqual(noteClauses(decision.record.note));
  });

  it('says why the curve fell back to the pump sensor', () => {
    const stale = withOutsideDecision(decision, 'ha/sensor.garden', true).record;
    expect(stale.controller_state['outside_source']).toBe('main/Outside_Temp');
    expect(curveOutside(stale)).toMatchObject({
      signal: 'ha/sensor.garden',
      fallback: true,
      why: 'stale',
      ageMin: 42,
      raw: -1,
    });
    expect(outsideFact(stale, fmt)).toEqual({
      kind: 'outside_fallback',
      params: { signal: 'ha/sensor.garden', raw: fmt.plain(-1, 1), why: 'stale', min: '42' },
    });
  });

  it.each(languages)('has the fact and reason texts in %s', (language) => {
    for (const key of [
      'fact_outside_source',
      'fact_outside_fallback',
      'outsideWhy_stale',
      'outsideWhy_missing',
      'outsideWhy_implausible',
      'outsideWhy_deviates',
      'outsideWhy_unknown',
    ])
      expect(translateOptional(language, key, {}), key).toBeDefined();
    expect(dictionaries[language]).toBeDefined();
  });
});
