import { describe, expect, it } from 'vitest';
import config from '$mock/fixtures/config.json';
import { initialState, makeControl, makeDecision } from '$mock/decisions';
import { translateOptional } from '$lib/i18n';
import {
  controlFact,
  controlSentence,
  firstWrites,
  modeView,
  refusalText,
  type ControlKind,
  type Say,
} from './mode';
import type { ConfigDoc, ControlStatus, Decision } from './types';

const doc = config as unknown as ConfigDoc;

describe('modeView', () => {
  it('shows auto with pause available', () => {
    const control = makeControl(0, initialState());
    expect(modeView(control, null, doc)).toMatchObject({
      key: 'auto',
      canPause: true,
      canResume: false,
    });
  });

  it('shows shadow as Shadow without pause', () => {
    const control = { ...makeControl(0, initialState()), mode: 'shadow' as const };
    expect(modeView(control, null, null)).toMatchObject({
      key: 'shadow',
      tone: 'info',
      canPause: false,
    });
  });

  it('shows paused with resume available', () => {
    const paused = {
      ...doc,
      mode: {
        configured: 'auto' as const,
        effective: 'shadow' as const,
        paused: true,
        reset_pending: false,
      },
    };
    const control = {
      ...makeControl(0, initialState()),
      mode: 'shadow' as const,
      paused: true,
    };
    expect(modeView(control, null, paused)).toMatchObject({
      key: 'paused',
      canResume: true,
      canPause: false,
    });
  });

  it('takes paused from the config when there is no control status', () => {
    const paused = {
      ...doc,
      mode: {
        configured: 'auto' as const,
        effective: 'shadow' as const,
        paused: true,
        reset_pending: false,
      },
    };
    expect(modeView(null, null, paused).key).toBe('paused');
  });

  it('is unknown without any data', () => {
    expect(modeView(null, null, null).key).toBe('unknown');
  });
});

describe('controlFact', () => {
  const base = () => makeControl(0, { paused: false, holdReleased: true });
  const decision = (intent: number, actual: number | null): Decision => ({
    ...makeDecision(0, 0),
    arbiter: [
      { kind: 'water_setpoint', intent, actual, action: 'send', reason: 'pump reports' },
      {
        kind: 'max_pump_duty',
        intent: 159,
        actual: 159,
        action: 'none',
        reason: 'already applied',
      },
    ],
  });
  const sim = (value: boolean): ConfigDoc => ({
    ...doc,
    fields: { ...doc.fields, simulation: { ...doc.fields['simulation']!, value } },
  });
  const real = sim(false);

  const cases: {
    name: string;
    control: ControlStatus | null;
    config?: ConfigDoc | null;
    kind: ControlKind;
    sending: boolean;
    tone: string;
  }[] = [
    { name: 'auto, publishing', control: base(), kind: 'controlling', sending: true, tone: 'good' },
    {
      name: 'auto, publishing, simulation',
      control: base(),
      config: sim(true),
      kind: 'simulated',
      sending: true,
      tone: 'good',
    },
    {
      name: 'auto with a foreign-writer hold',
      control: makeControl(0, initialState()),
      kind: 'held',
      sending: false,
      tone: 'warn',
    },
    {
      name: 'paused',
      control: {
        ...base(),
        mode: 'shadow',
        paused: true,
        publishing: false,
        refusals: ['control is paused'],
      },
      kind: 'paused',
      sending: false,
      tone: 'warn',
    },
    {
      name: 'configured Shadow next to another controller',
      control: {
        ...base(),
        mode: 'shadow',
        configured_mode: 'shadow',
        publishing: false,
        adapter: null,
        refusals: ['control mode is shadow, not auto'],
      },
      kind: 'watching',
      sending: false,
      tone: 'info',
    },
    {
      name: 'auto without permission to publish',
      control: {
        ...base(),
        publishing: false,
        adapter: null,
        refusals: ['OVENBIRD_ALLOW_COMMANDS is not true'],
      },
      kind: 'refused',
      sending: false,
      tone: 'warn',
    },
    {
      name: 'configuration reset pending',
      control: {
        ...base(),
        mode: 'shadow',
        reset_pending: true,
        publishing: false,
        refusals: ['the configuration was reset; shadow until an admin acknowledges it'],
      },
      kind: 'refused',
      sending: false,
      tone: 'warn',
    },
    {
      name: 'off',
      control: { ...base(), mode: 'off', configured_mode: 'off', publishing: false },
      kind: 'off',
      sending: false,
      tone: 'neutral',
    },
    {
      name: 'nothing known',
      control: null,
      config: null,
      kind: 'unknown',
      sending: false,
      tone: 'neutral',
    },
  ];

  for (const c of cases) {
    it(`is ${c.kind} when ${c.name}`, () => {
      const fact = controlFact({
        control: c.control,
        decision: c.control ? decision(29, 31) : null,
        config: c.config === undefined ? real : c.config,
      });
      expect(fact).toMatchObject({ kind: c.kind, sending: c.sending, tone: c.tone });
    });
  }

  it('pairs what ovenbird would send with what the pump has', () => {
    const fact = controlFact({ control: base(), decision: decision(29, 31), config: real });
    expect(fact.water).toEqual({ kind: 'water_setpoint', wouldSend: 29, pumpHas: 31 });
  });

  it('falls back to the reported pump target without an arbiter entry', () => {
    const plain = { ...makeDecision(0, 0), arbiter: [], setpoint: 30 };
    const fact = controlFact({ control: base(), decision: plain, config: real, pumpTarget: 28 });
    expect(fact.water).toMatchObject({ wouldSend: 30, pumpHas: 28 });
  });

  it('lists the first writes after a resume, only where the pump differs', () => {
    expect(firstWrites(decision(29, 31))).toEqual([
      { kind: 'water_setpoint', wouldSend: 29, pumpHas: 31 },
    ]);
    expect(firstWrites(decision(31, 31))).toEqual([]);
  });
});

describe('control sentences', () => {
  const en: Say = (key, params) => translateOptional('en', key, params);
  const nl: Say = (key, params) => translateOptional('nl', key, params);
  const value = (v: number) => `${v} °C`;
  const held = controlFact({
    control: makeControl(0, initialState()),
    decision: {
      ...makeDecision(0, 0),
      arbiter: [{ kind: 'water_setpoint', intent: 26, actual: 31, action: 'skip', reason: 'hold' }],
    },
    config: null,
  });

  it('says who controls the pump in plain words', () => {
    expect(controlSentence(held, { say: en, until: '18:25', value })).toBe(
      'ovenbird is waiting until 18:25: someone else changed the pump; the pump keeps 31 °C',
    );
    expect(controlSentence(held, { say: nl, until: '18:25', value })).toBe(
      'ovenbird wacht tot 18:25: iemand anders heeft de pomp aangepast; de pomp houdt 31 °C',
    );
    expect(
      controlSentence({ ...held, holdLatched: true }, { say: en, until: null, value }),
    ).toContain('until an administrator releases it');
    expect(controlSentence({ ...held, kind: 'paused' }, { say: en, until: null, value })).toBe(
      'Paused: ovenbird sends nothing; the pump keeps its last setpoint',
    );
    expect(controlSentence({ ...held, kind: 'watching' }, { say: en, until: null, value })).toBe(
      'ovenbird only watches; another controller writes',
    );
    expect(
      controlSentence(
        { ...held, kind: 'controlling', safetyHold: [] },
        { say: en, until: null, value },
      ),
    ).toBe('ovenbird controls the pump');
  });

  it('leaves out what the pump keeps where "pump has" stands next to it', () => {
    expect(controlSentence(held, { say: nl, until: '18:25', value, brief: true })).toBe(
      'ovenbird wacht tot 18:25: iemand anders heeft de pomp aangepast',
    );
    expect(
      controlSentence({ ...held, kind: 'paused' }, { say: en, until: null, value, brief: true }),
    ).toBe('Paused: ovenbird sends nothing');
  });

  it('leaves out the reason of a hold where the verdict names it', () => {
    expect(controlSentence(held, { say: nl, until: '18:25', value, terse: true })).toBe(
      'ovenbird wacht tot 18:25',
    );
    expect(
      controlSentence({ ...held, holdLatched: true }, { say: en, until: null, value, terse: true }),
    ).toBe('ovenbird is waiting until an administrator releases it');
  });

  it('maps service refusals to the UI vocabulary', () => {
    expect(refusalText('control mode is shadow, not auto', en)).toBe('the mode is Shadow');
    expect(refusalText('mode is shadow', nl)).toBe('de modus is Schaduw');
    expect(refusalText('control is paused', en)).toBe('paused by hand');
    expect(refusalText('something new', en)).toBe('something new');
  });
});
