import { describe, expect, it } from 'vitest';
import { initialState, makeControl, makeDecision } from '$mock/decisions';
import { firstWriteText, notSendingNote, refusalFor } from './controlText';
import { controlFact } from './mode';
import type { Decision } from './types';

const decision = (water: [number, number | null], duty: [number, number]): Decision => ({
  ...makeDecision(0, 0),
  arbiter: [
    { kind: 'water_setpoint', intent: water[0], actual: water[1], action: 'send', reason: '' },
    { kind: 'max_pump_duty', intent: duty[0], actual: duty[1], action: 'send', reason: '' },
  ],
});

describe('firstWriteText', () => {
  it('names each value the resume would write next to what the pump has', () => {
    expect(firstWriteText(decision([26, 31], [159, 120]), 'en')).toBe(
      'First, ovenbird will set the water temperature to 26 °C (the pump has 31 °C) and the pump duty to 159 (the pump has 120).',
    );
    expect(firstWriteText(decision([26, 31], [159, 159]), 'nl')).toBe(
      'Eerst zet ovenbird de watertemperatuur op 26 °C (de pomp heeft 31 °C).',
    );
  });

  it('says when nothing needs to be written', () => {
    expect(firstWriteText(decision([31, 31], [159, 159]), 'en')).toMatch(/already has/);
    expect(firstWriteText(decision([29, null], [159, 159]), 'en')).toBe(
      'First, ovenbird will set the water temperature to 29 °C.',
    );
  });
});

describe('notSendingNote', () => {
  const at = Date.parse('2026-11-18T12:00:00Z');

  it('adds nothing while ovenbird sends', () => {
    const control = makeControl(at, { paused: false, holdReleased: true });
    const fact = controlFact({ control, decision: null, config: null });
    expect(notSendingNote(fact, 'en', at)).toBeNull();
  });

  it('says until when nothing is sent during a hold, and while paused', () => {
    const held = controlFact({
      control: makeControl(at, initialState()),
      decision: null,
      config: null,
    });
    expect(notSendingNote(held, 'en', at)).toMatch(
      /^But ovenbird sends nothing to the pump until today \d/,
    );
    const paused = controlFact({
      control: { ...makeControl(at, initialState()), paused: true, publishing: false },
      decision: null,
      config: null,
    });
    expect(notSendingNote(paused, 'nl', at)).toBe(
      'Maar ovenbird stuurt niets naar de pomp zolang hij gepauzeerd is.',
    );
  });

  it('translates the refusal', () => {
    expect(refusalFor('control mode is shadow, not auto', 'en')).toBe('the mode is Shadow');
  });
});
