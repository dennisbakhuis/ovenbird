import { formatDateTime, formatNumber } from './format';
import { translateOptional, type Language } from '$lib/i18n';
import { minus } from './minus';
import {
  controlFact,
  controlSentence,
  firstWrites,
  refusalText,
  type ControlFact,
  type PumpPair,
  type Say,
} from './mode';
import type { ConfigDoc, ControlStatus, Decision, Snapshot } from './types';

export const PUMP_TARGET_SIGNAL = 'main/Z1_Water_Target_Temp';

export interface ControlSources {
  control: ControlStatus | null;
  decision: Decision | null;
  config: ConfigDoc | null;
}

/**
 * The control fact from the control store and the live snapshot; the pump's water target from
 * the snapshot stands in when the latest decision has no arbiter entry for it. `sources` is read
 * field by field (never spread): the control store keeps them as class getters.
 */
export function liveFact(sources: ControlSources, snapshot: Snapshot | null): ControlFact {
  const target = snapshot?.signals[PUMP_TARGET_SIGNAL]?.value;
  return controlFact({
    control: sources.control,
    decision: sources.decision,
    config: sources.config,
    pumpTarget: typeof target === 'number' ? target : null,
  });
}

function sayIn(language: Language): Say {
  return (key, params) => translateOptional(language, key, params);
}

/**
 * A water temperature as "29 °C" in the UI language; `digits` 0 for a setpoint as issued (whole
 * degrees).
 */
export function celsius(value: number, language: Language, digits = 1): string {
  return `${minus(formatNumber(value, digits, language))} °C`;
}

/**
 * When a timed hold ends, as "today 18:25", measured against the service clock; null when there
 * is no timed hold.
 */
export function holdEnd(fact: ControlFact, language: Language, clockMs: number): string | null {
  if (fact.holdLatched || fact.holdUntil === null) return null;
  return formatDateTime(fact.holdUntil, language, clockMs);
}

/**
 * The control fact as one sentence in the UI language.
 */
export function sentenceFor(
  fact: ControlFact,
  language: Language,
  clockMs: number,
  brief = false,
  terse = false,
): string {
  return controlSentence(fact, {
    say: sayIn(language),
    until: holdEnd(fact, language, clockMs),
    value: (v) => celsius(v, language),
    brief,
    terse,
  });
}

/**
 * A publish refusal in plain words in the UI language.
 */
export function refusalFor(reason: string, language: Language): string {
  return refusalText(reason, sayIn(language));
}

function writeText(pair: PumpPair, language: Language): string | null {
  if (pair.wouldSend === null) return null;
  const to =
    pair.kind === 'water_setpoint'
      ? minus(formatNumber(pair.wouldSend, 1, language))
      : String(pair.wouldSend);
  const from =
    pair.pumpHas === null
      ? null
      : pair.kind === 'water_setpoint'
        ? minus(formatNumber(pair.pumpHas, 1, language))
        : String(pair.pumpHas);
  const key = from === null ? `writeNew_${pair.kind}` : `write_${pair.kind}`;
  return translateOptional(language, key, { to, from: from ?? '' }) ?? null;
}

/**
 * What a resume would write first, as a sentence: "First, ovenbird will set the water
 * temperature to 29 °C (the pump has 31 °C)." When nothing differs it says so.
 */
export function firstWriteText(decision: Decision | null, language: Language): string {
  const parts = firstWrites(decision)
    .map((pair) => writeText(pair, language))
    .filter((part): part is string => part !== null);
  if (parts.length === 0) return translateOptional(language, 'resumeNothing') ?? '';
  const list = parts.join(translateOptional(language, 'listAnd') ?? ' and ');
  return translateOptional(language, 'resumeFirst', { list }) ?? list;
}

/**
 * The sentence added to "Version 13 saved" while ovenbird does not send ("But ovenbird sends
 * nothing to the pump until 18:25."); null while it sends.
 */
export function notSendingNote(
  fact: ControlFact,
  language: Language,
  clockMs: number,
): string | null {
  if (fact.sending || fact.kind === 'unknown') return null;
  if (fact.kind === 'held') {
    const time = holdEnd(fact, language, clockMs);
    return time === null
      ? (translateOptional(language, 'appliedBut_heldLatched') ?? null)
      : (translateOptional(language, 'appliedBut_held', { time }) ?? null);
  }
  if (fact.kind === 'refused') {
    const reason = fact.refusal ? refusalFor(fact.refusal, language) : '';
    return translateOptional(language, 'appliedBut_refused', { reason }) ?? null;
  }
  return translateOptional(language, `appliedBut_${fact.kind}`) ?? null;
}
