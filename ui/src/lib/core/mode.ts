import type { ConfigDoc, ControlStatus, Decision, Mode } from './types';

export type ModeKey = 'auto' | 'shadow' | 'paused' | 'off' | 'manual' | 'unknown';
export type ModeTone = 'good' | 'info' | 'warn' | 'neutral';

export interface ModeView {
  key: ModeKey;
  tone: ModeTone;
  canPause: boolean;
  canResume: boolean;
}

const KNOWN: Mode[] = ['off', 'shadow', 'auto', 'manual'];

/**
 * Derive how the controller mode is shown: `shadow` is the owner's "Shadow"; a paused auto
 * configuration is shown as Paused. Pause is offered while effectively auto, resume while paused.
 */
export function modeView(
  control: ControlStatus | null,
  decision: Decision | null,
  config: ConfigDoc | null,
): ModeView {
  const effective = control?.mode ?? decision?.mode ?? config?.mode.effective ?? null;
  const paused = control?.paused ?? config?.mode.paused ?? false;
  if (paused) {
    return { key: 'paused', tone: 'warn', canPause: false, canResume: true };
  }
  if (effective === null || !KNOWN.includes(effective)) {
    return { key: 'unknown', tone: 'neutral', canPause: false, canResume: false };
  }
  const tone: ModeTone =
    effective === 'auto'
      ? 'good'
      : effective === 'shadow'
        ? 'info'
        : effective === 'off'
          ? 'neutral'
          : 'warn';
  return { key: effective, tone, canPause: effective === 'auto', canResume: false };
}

export type ControlKind =
  'controlling' | 'simulated' | 'watching' | 'held' | 'paused' | 'refused' | 'off' | 'unknown';

export interface PumpPair {
  kind: string;
  wouldSend: number | null;
  pumpHas: number | null;
}

export interface ControlFact {
  kind: ControlKind;
  sending: boolean;
  tone: ModeTone;
  holdReason: string | null;
  holdUntil: string | null;
  holdLatched: boolean;
  refusal: string | null;
  refusals: string[];
  safetyHold: string[];
  water: PumpPair;
}

export interface ControlInputs {
  control: ControlStatus | null;
  decision: Decision | null;
  config: ConfigDoc | null;
  pumpTarget?: number | null;
}

const CONTROL_TONE: Record<ControlKind, ModeTone> = {
  controlling: 'good',
  simulated: 'good',
  watching: 'info',
  held: 'warn',
  paused: 'warn',
  refused: 'warn',
  off: 'neutral',
  unknown: 'neutral',
};

/**
 * Whether the installation runs against a simulated pump (`simulation` config field).
 */
export function isSimulation(config: ConfigDoc | null): boolean {
  return config?.fields['simulation']?.value === true;
}

function waterPair(decision: Decision | null, pumpTarget: number | null): PumpPair {
  const entry = decision?.arbiter.find((item) => item.kind === 'water_setpoint');
  return {
    kind: 'water_setpoint',
    wouldSend: entry?.intent ?? decision?.setpoint ?? null,
    pumpHas: entry?.actual ?? pumpTarget,
  };
}

function kindOf(
  control: ControlStatus | null,
  decision: Decision | null,
  config: ConfigDoc | null,
): ControlKind {
  const effective = control?.mode ?? decision?.mode ?? config?.mode.effective ?? null;
  if (effective === null) return 'unknown';
  if (control?.paused ?? config?.mode.paused ?? false) return 'paused';
  if (effective === 'off') return 'off';
  if (control?.reset_pending ?? config?.reset_pending ?? false) return 'refused';
  const configured = control?.configured_mode ?? config?.mode.configured ?? null;
  if (configured === 'shadow' || (configured === null && effective === 'shadow')) return 'watching';
  if (!control) return 'unknown';
  if (!control.publishing) return 'refused';
  if (control.adapter?.hold) return 'held';
  return isSimulation(config) ? 'simulated' : 'controlling';
}

/**
 * Who controls the pump right now, derived in one place from the mode, `publishing`, a pause and
 * the adapter hold: ovenbird controls (or controls a simulation), only watches while another
 * controller writes (configured Shadow), waits out a hold, is paused, may not send (an unmet
 * publish condition) or is off. `water` pairs what ovenbird would send with what the pump has.
 */
export function controlFact({
  control,
  decision,
  config,
  pumpTarget = null,
}: ControlInputs): ControlFact {
  const kind = kindOf(control, decision, config);
  const adapter = control?.adapter ?? null;
  const refusals = control && !control.publishing ? control.refusals : [];
  return {
    kind,
    sending: kind === 'controlling' || kind === 'simulated',
    tone: CONTROL_TONE[kind],
    holdReason: adapter?.hold ?? null,
    holdUntil: adapter?.hold_until ?? null,
    holdLatched: adapter?.hold_latched ?? false,
    refusal: refusals[0] ?? null,
    refusals,
    safetyHold: adapter?.safety_hold ?? [],
    water: waterPair(decision, pumpTarget),
  };
}

/**
 * What ovenbird would write first after a resume: the latest decision's intents whose value
 * differs from what the pump reports (water setpoint, pump duty, quiet mode).
 */
export function firstWrites(decision: Decision | null): PumpPair[] {
  return (decision?.arbiter ?? []).flatMap((entry): PumpPair[] =>
    entry.intent !== null && entry.intent !== entry.actual
      ? [{ kind: entry.kind, wouldSend: entry.intent, pumpHas: entry.actual }]
      : [],
  );
}

export type Say = (key: string, params?: Record<string, string | number>) => string | undefined;

const REFUSALS: [RegExp, (match: RegExpExecArray, say: Say) => string | undefined][] = [
  [
    /^(?:control )?mode is (\w+)(?:, not auto)?$/,
    (match, say) =>
      say('refusalMode', { mode: say(`modeShort_${match[1]}`) ?? (match[1] as string) }),
  ],
  [/^control is paused/, (_, say) => say('refusalPaused')],
  [/^the configuration was reset/, (_, say) => say('refusalReset')],
  [/OVENBIRD_ALLOW_COMMANDS/, (_, say) => say('refusalAllow')],
  [/OVENBIRD_COMMAND_BROKERS/, (_, say) => say('refusalBroker')],
  [/clock is scaled/, (_, say) => say('refusalClock')],
  [/^simulation mode refuses broker/, (_, say) => say('refusalSimBroker')],
];

/**
 * A publish refusal of the service in plain words ("mode is shadow" reads "the mode is
 * Shadow"); the service's own text when it is not known.
 */
export function refusalText(reason: string, say: Say): string {
  for (const [pattern, text] of REFUSALS) {
    const match = pattern.exec(reason);
    if (match) return text(match, say) ?? reason;
  }
  return reason;
}

export interface SentenceParts {
  say: Say;
  until: string | null;
  value: (celsius: number) => string;
  /** Leave out what the pump keeps: for places that show "pump has" right next to it. */
  brief?: boolean;
  /** Leave out the reason of a hold too: for Home, where the verdict right below names it. */
  terse?: boolean;
}

/**
 * The control fact as one plain sentence: "ovenbird controls the pump", "ovenbird is waiting
 * until 18:25: someone else changed the pump; the pump keeps 31 °C", "Paused: …".
 */
export function controlSentence(fact: ControlFact, parts: SentenceParts): string {
  const { say, until, value, brief = false, terse = false } = parts;
  const text = (key: string, params: Record<string, string | number> = {}) =>
    say(key, params) ?? key;
  switch (fact.kind) {
    case 'controlling':
    case 'simulated': {
      const key = fact.kind === 'simulated' ? 'control_simulated' : 'control_controlling';
      if (fact.safetyHold.length === 0) return text(key);
      return text('control_safety', { sentence: text(key) });
    }
    case 'held': {
      const reason = fact.holdReason
        ? (say(`holdWhy_${fact.holdReason}`) ?? fact.holdReason)
        : text('holdWhy_unknown');
      const keeps =
        fact.water.pumpHas === null ? text('controlPumpOwn') : value(fact.water.pumpHas);
      const suffix = terse ? 'Terse' : brief ? 'Brief' : '';
      if (fact.holdLatched || until === null)
        return text(`control_heldLatched${suffix}`, { reason, value: keeps });
      return text(`control_held${suffix}`, { time: until, reason, value: keeps });
    }
    case 'refused':
      return text('control_refused', {
        reason: fact.refusal ? refusalText(fact.refusal, say) : text('refusalUnknown'),
      });
    case 'paused':
      return text(brief ? 'control_pausedBrief' : 'control_paused');
    default:
      return text(`control_${fact.kind}`);
  }
}
