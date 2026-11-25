import type { IconName } from '$lib/core/icons';
import type { DecisionRecord, StateValue } from '$lib/core/types';

export type Translate = (
  key: string,
  params?: Record<string, string | number>,
) => string | undefined;

export interface NumberFormats {
  plain: (value: number, digits?: number) => string;
  signed: (value: number, digits?: number) => string;
}

export interface Explanation {
  headline: string;
  constraint: string | null;
  flip: string | null;
}

/**
 * Build number formatters for a locale: plain and sign-prefixed (with a real minus sign).
 */
export function numberFormats(locale?: string): NumberFormats {
  const plain = (value: number, digits = 1) =>
    new Intl.NumberFormat(locale, { maximumFractionDigits: digits, minimumFractionDigits: 0 })
      .format(value)
      .replace('-', '−');
  const signed = (value: number, digits = 1) => {
    const text = plain(Math.abs(value), digits);
    if (Math.abs(value) < 10 ** -digits / 2) return `${text} K`;
    return `${value < 0 ? '−' : '+'}${text} K`;
  };
  return { plain, signed };
}

function state(record: DecisionRecord, key: string): number | null {
  const value: StateValue | undefined = record.controller_state[key];
  return typeof value === 'number' && Number.isFinite(value) ? value : null;
}

function termValue(record: DecisionRecord, name: string): number {
  return record.terms.find((term) => term.name === name)?.value ?? 0;
}

/**
 * Template parameters derived from a decision record, all pre-formatted for display.
 */
export function explainParams(
  record: DecisionRecord,
  fmt: NumberFormats,
): Record<string, string | number> {
  const dash = '–';
  const target = state(record, 'room_target_c');
  const error = state(record, 'room_error_k');
  const outside = state(record, 'outside_filtered_c');
  const dwell = state(record, 'dwell_remaining_s');
  const low = state(record, 'safety_low_c');
  const high = state(record, 'safety_high_c');
  const safety = record.terms.find((term) => term.name === 'safety');
  const ramp = termValue(record, 'start_ramp');
  const params: Record<string, string | number> = {
    setpoint: record.setpoint === null ? dash : record.setpoint,
    preRound: record.pre_round === null ? dash : fmt.plain(record.pre_round, 1),
    raw: safety ? fmt.plain(safety.raw, 1) : dash,
    curve: fmt.plain(termValue(record, 'curve'), 1),
    feedback: fmt.signed(termValue(record, 'room_feedback')),
    plan: fmt.signed(termValue(record, 'plan')),
    ramp: fmt.signed(ramp),
    rampAbs: fmt.plain(Math.abs(ramp), 1),
    cycling: fmt.signed(termValue(record, 'cycling_floor')),
    stove: fmt.signed(termValue(record, 'stove')),
    outside: outside === null ? dash : fmt.plain(outside, 1),
    target: target === null ? dash : fmt.plain(target, 1),
    room: target !== null && error !== null ? fmt.plain(target - error, 1) : dash,
    low: low === null ? dash : fmt.plain(low, 1),
    high: high === null ? dash : fmt.plain(high, 1),
    dwellMin: dwell === null ? dash : Math.ceil(dwell / 60),
    actor: record.actor ?? '',
  };
  return params;
}

function flipKey(input: string): string {
  if (input === 'pre_round') return 'explain_flip_water';
  if (input === 'main/Outside_Temp') return 'explain_flip_outside';
  return 'explain_flip_room';
}

/**
 * Explain a decision in plain language: the reason sentence, the binding constraint and how far
 * an input must move to change the setpoint. Texts come from `translate` by code; an unknown
 * code falls back to the raw code.
 */
/** True when the decision's base is the fixed water temperature (weather-dependent control off). */
export function fixedBase(record: DecisionRecord): boolean {
  return record.controller_state['base'] === 'fixed';
}

export function explain(
  record: DecisionRecord,
  translate: Translate,
  fmt: NumberFormats,
): Explanation {
  const params = explainParams(record, fmt);
  if (record.actor === null) params['actor'] = translate('explain_actor_unknown') ?? '';
  const headline =
    (fixedBase(record) ? translate(`explain_reason_${record.reason}_fixed`, params) : undefined) ??
    translate(`explain_reason_${record.reason}`, params) ??
    record.reason;
  const constraint =
    record.binding === null
      ? null
      : (translate(`explain_binding_${record.binding}`, params) ?? record.binding);
  let flip: string | null = null;
  if (record.flip_distance !== null && record.flip_input !== null) {
    flip =
      translate(flipKey(record.flip_input), {
        ...params,
        distance: fmt.plain(record.flip_distance, 2),
      }) ?? null;
  }
  return { headline, constraint, flip };
}

export type FlipSubject = 'room' | 'outside' | 'water';

export interface FlipPoint {
  at: number;
  move: number;
  setpoint: number;
}

export interface FlipModel {
  subject: FlipSubject;
  value: number;
  distance: number;
  points: FlipPoint[];
  stays: number;
  target: number | null;
}

/**
 * Where the flip input must go to change the issued setpoint. The controller reports the distance
 * to the nearest change threshold; its side follows from `pre_round` against the issued setpoint
 * (above: the next step is up). Room and outside temperature move the water the other way, so
 * their flip point lies on the opposite side. When `pre_round` equals the setpoint both sides are
 * equally far. Null without a flip distance, setpoint or current value of the input.
 */
export function flipModel(record: DecisionRecord): FlipModel | null {
  const distance = record.flip_distance;
  const setpoint = record.setpoint;
  const preRound = record.pre_round;
  if (distance === null || setpoint === null || preRound === null || !record.flip_input)
    return null;
  const subject: FlipSubject =
    record.flip_input === 'pre_round'
      ? 'water'
      : record.flip_input === 'main/Outside_Temp'
        ? 'outside'
        : 'room';
  const target = state(record, 'room_target_c');
  let value: number | null = null;
  if (subject === 'water') value = preRound;
  if (subject === 'outside') {
    const chosen = curveOutside(record);
    const signal = chosen && !chosen.fallback ? chosen.signal : 'main/Outside_Temp';
    const input = record.inputs_used.find((item) => item.signal === signal);
    value = typeof input?.value === 'number' ? input.value : state(record, 'outside_filtered_c');
  }
  if (subject === 'room') {
    const error = state(record, 'room_error_k');
    const input = record.inputs_used.find(
      (item) => item.signal === record.flip_input || item.source === 'room',
    );
    value =
      target !== null && error !== null
        ? target - error
        : typeof input?.value === 'number'
          ? input.value
          : null;
  }
  if (value === null) return null;
  const sign = subject === 'water' ? 1 : -1;
  const sides: number[] =
    preRound > setpoint + 1e-9 ? [1] : preRound < setpoint - 1e-9 ? [-1] : [-1, 1];
  const points = sides
    .map((side) => ({
      at: value + sign * side * distance,
      move: sign * side * distance,
      setpoint: setpoint + side,
    }))
    .sort((a, b) => a.at - b.at);
  return {
    subject,
    value,
    distance,
    points,
    stays: setpoint,
    target: subject === 'room' ? target : null,
  };
}

export interface RoomFacts {
  profile: string | null;
  value: number | null;
  heldS: number | null;
  aliveS: number | null;
  aliveBy: string | null;
  quantumK: number | null;
  authority: number | null;
  plausible: boolean | null;
  deviationK: number | null;
  signal: string | null;
}

function stringState(record: DecisionRecord, key: string): string | null {
  const value = record.controller_state[key];
  return typeof value === 'string' && value !== '' ? value : null;
}

/**
 * The room value as the controller judged it: profile, how long the value has been held, the
 * last proof of life (and which signal gave it), sensor step, cooling authority and the
 * cross-check. Null when the record carries no room input.
 */
export function roomFacts(record: DecisionRecord): RoomFacts | null {
  const input = record.inputs_used.find((item) => item.source === 'room') ?? null;
  const profile = stringState(record, 'room_profile');
  if (!input && profile === null) return null;
  const plausible = record.controller_state['room_plausible'];
  return {
    profile,
    value: typeof input?.value === 'number' ? input.value : null,
    heldS: state(record, 'room_held_s'),
    aliveS: state(record, 'room_alive_s') ?? input?.age ?? null,
    aliveBy: stringState(record, 'room_alive_by'),
    quantumK: state(record, 'room_quantum_k'),
    authority: state(record, 'room_authority'),
    plausible: typeof plausible === 'boolean' ? plausible : null,
    deviationK: state(record, 'room_crosscheck_deviation_k'),
    signal: input?.signal ?? null,
  };
}

/**
 * Short name of a liveness signal relative to the room signal, as the controller writes it:
 * `room_humidity` next to `room_temperature` is "humidity".
 */
export function livenessLabel(signal: string, room: string | null): string {
  const tail = (id: string) => id.split('.').pop()?.split('/').pop() ?? id;
  const name = tail(signal);
  const base = room ? tail(room) : '';
  let common = 0;
  while (common < name.length && common < base.length && name[common] === base[common]) common++;
  const cut = name.lastIndexOf('_', common - 1) + 1;
  return name.slice(cut) || name;
}

/**
 * A liveness signal name with its trailing kind word ("humidity", "battery") in the UI language;
 * `say` resolves `liveKind_<word>`. Unknown words stay as they are.
 */
export function livenessKind(name: string, say: (key: string) => string | undefined): string {
  const match = /([A-Za-z]+)$/.exec(name);
  if (!match) return name;
  const word = match[1] as string;
  const translated = say(`liveKind_${word.toLowerCase()}`);
  if (translated === undefined || translated.toLowerCase() === word.toLowerCase()) return name;
  const cased =
    word[0] === word[0]?.toUpperCase()
      ? translated.charAt(0).toUpperCase() + translated.slice(1)
      : translated;
  return name.slice(0, match.index) + cased;
}

export type FactKind =
  | 'defrost'
  | 'dhw'
  | 'duty_skipped'
  | 'cycling_raise'
  | 'cycling_limit'
  | 'ramp_cap'
  | 'held_clamped'
  | 'integrator_frozen'
  | 'stove'
  | 'stove_blocked'
  | 'stove_level_blocked'
  | 'stove_reentry_wait'
  | 'stove_reference_short'
  | 'stove_fault'
  | 'stove_exited'
  | 'outside_source'
  | 'outside_fallback';

export interface Fact {
  kind: FactKind;
  params: Record<string, string | number>;
}

function frozenBy(record: DecisionRecord): string[] {
  return (stringState(record, 'frozen_by') ?? '').split(',').filter(Boolean);
}

/**
 * What shaped the decision beyond the terms, in a fixed order: a defrost or hot-water run, the
 * skipped duty command, whether the cycling floor raised the setpoint or only limited a decrease,
 * a held setpoint moved into the safety band, the start-ramp cap and other reasons the integrator is frozen. Read from the controller state
 * and bindings; the note is consulted only for what the record carries nowhere else.
 */
export function decisionFacts(record: DecisionRecord, fmt: NumberFormats): Fact[] {
  const out: Fact[] = [];
  const frozen = frozenBy(record);
  const note = record.note;
  const setpoint = record.setpoint ?? '–';
  if (
    frozen.includes('defrost') ||
    record.reason === 'defrost_freeze' ||
    record.binding === 'defrost_hold'
  )
    if (record.reason !== 'defrost_freeze') out.push({ kind: 'defrost', params: { setpoint } });
  if (frozen.includes('dhw') || record.reason === 'dhw_freeze' || record.binding === 'dhw_hold')
    if (record.reason !== 'dhw_freeze') out.push({ kind: 'dhw', params: { setpoint } });
  if (/no duty command/.test(note)) out.push({ kind: 'duty_skipped', params: {} });
  if (record.binding === 'cycling_floor') {
    const limit = /cycling floor (-?\d+(?:\.\d+)?) °C limits the decrease/.exec(note);
    if (limit)
      out.push({
        kind: 'cycling_limit',
        params: { floor: fmt.plain(Number(limit[1]), 1), setpoint },
      });
    else if (record.reason !== 'cycling_protect')
      out.push({ kind: 'cycling_raise', params: { setpoint } });
  }
  const held = /clamps the held (-?\d+(?:\.\d+)?) → (-?\d+(?:\.\d+)?) °C/.exec(note);
  if (held)
    out.push({
      kind: 'held_clamped',
      params: { held: fmt.plain(Number(held[1]), 0), setpoint: fmt.plain(Number(held[2]), 0) },
    });
  const cap = state(record, 'ramp_cap_c');
  const ramp = termValue(record, 'start_ramp');
  if (cap !== null && ramp < 0) out.push({ kind: 'ramp_cap', params: { cap: fmt.plain(cap, 1) } });
  const stove = stoveFact(record, fmt);
  if (stove) out.push(stove);
  out.push(...stoveDetails(record, fmt));
  const outside = outsideFact(record, fmt);
  if (outside) out.push(outside);
  const other = frozen.filter(
    (name) => name !== 'defrost' && name !== 'dhw' && !(name === 'stove' && stove),
  );
  if (other.length > 0 && record.ladder !== 'hold' && record.ladder !== 'refuse')
    out.push({ kind: 'integrator_frozen', params: { by: other.join(',') } });
  return out;
}

/**
 * Wood-stove mode in the decision: the active episode (since, how it started, the back-off and
 * the held integrator), or why the detection waits (after a manual stop, after the longest
 * episode, after an untrusted room value). Null when the record has no stove state or nothing to
 * say. `since` stays an ISO time for the caller to format.
 */
export function stoveFact(record: DecisionRecord, fmt: NumberFormats): Fact | null {
  const s = record.controller_state;
  const exit = state(record, 'stove_exit_c');
  if (s['stove_state'] === 'active') {
    const backoff = state(record, 'stove_backoff_k');
    const integral = state(record, 'stove_integral_k');
    const trigger = stringState(record, 'stove_trigger');
    return {
      kind: 'stove',
      params: {
        since: stringState(record, 'stove_started') ?? '',
        source: trigger === 'handover' ? 'handover' : (stringState(record, 'stove_source') ?? ''),
        backoff: backoff === null ? '–' : fmt.plain(backoff, 1),
        integral: integral === null ? '–' : fmt.signed(integral),
      },
    };
  }
  const exitText = exit === null ? '–' : fmt.plain(exit, 1);
  if (s['stove_blocked'] === true) return { kind: 'stove_blocked', params: { exit: exitText } };
  if (s['stove_reentry_wait'] === true) return { kind: 'stove_reentry_wait', params: {} };
  if (s['stove_level_blocked'] === true)
    return { kind: 'stove_level_blocked', params: { exit: exitText } };
  return null;
}

/**
 * What else the wood-stove state says this minute: an episode that ended (and why, such as a jump
 * of the room value taken for a sensor fault, or a reference room that is warm again), part of the
 * back-off only while a configured reference room has no fresh value, and a detection that stays
 * off after such a jump until the room has cooled.
 */
export function stoveDetails(record: DecisionRecord, fmt: NumberFormats): Fact[] {
  const s = record.controller_state;
  const out: Fact[] = [];
  const exit = state(record, 'stove_exit_c');
  const reason = stringState(record, 'stove_exit');
  if (s['stove_event'] === 'exited' && reason)
    out.push({ kind: 'stove_exited', params: { reason } });
  const share = state(record, 'stove_reference_share');
  if (s['stove_state'] === 'active' && share !== null && share < 1)
    out.push({
      kind: 'stove_reference_short',
      params: { share: fmt.plain(share * 100, 0) },
    });
  if (s['stove_fault'] === true && s['stove_state'] !== 'active') {
    const jump = state(record, 'stove_jump_k');
    out.push({
      kind: 'stove_fault',
      params: {
        jump: jump === null ? '–' : fmt.plain(jump, 1),
        exit: exit === null ? '–' : fmt.plain(exit, 1),
      },
    });
  }
  return out;
}

export interface CurveNote {
  filtered: number;
  raw: number;
  from: string | null;
  fallback: { signal: string; why: OutsideWhy | null; ageMin: number | null } | null;
}

/** Why the curve did not use the chosen outside sensor (the controller's `outside_reason`). */
export type OutsideWhy = 'stale' | 'missing' | 'implausible' | 'deviates';

const OUTSIDE_WHY: readonly string[] = ['stale', 'missing', 'implausible', 'deviates'];
const NUMBER = String.raw`-?\d+(?:\.\d+)?(?:e[+-]?\d+)?`;
const CURVE_NOTE = new RegExp(
  String.raw`^curve at (${NUMBER}) °C filtered outside \((${NUMBER}) °C raw(?: from (.+))?\)$`,
);
const FALLBACK =
  /^the pump: (\S+) (?:is stale, (\d+(?:\.\d+)?) min old|has no (?:usable )?value(?:, .*)?|is (implausible|too far from the pump), .*)$/;

function fallbackWhy(fell: RegExpExecArray): OutsideWhy {
  if (fell[2] !== undefined) return 'stale';
  if (fell[3] === 'implausible') return 'implausible';
  return fell[3] === undefined ? 'missing' : 'deviates';
}

/**
 * Read the curve term's note: the filtered and raw outside temperature and, with a chosen outside
 * sensor, where the raw value came from (`from ha/sensor.garden`) or why it fell back to the pump
 * (`from the pump: ha/sensor.garden is stale, 42 min old`, `… has no value`, `… has no usable
 * value, unit: …`, `… is implausible, …` or `… is too far from the pump, …`). Null for another
 * note, such as the fixed water temperature.
 */
export function parseCurveNote(note: string): CurveNote | null {
  const match = CURVE_NOTE.exec(note.trim());
  if (!match) return null;
  const from = match[3] ?? null;
  const fell = from ? FALLBACK.exec(from) : null;
  return {
    filtered: Number(match[1]),
    raw: Number(match[2]),
    from: from && !from.startsWith('the pump') ? from : null,
    fallback: fell
      ? {
          signal: fell[1] as string,
          why: fallbackWhy(fell),
          ageMin: fell[2] !== undefined ? Number(fell[2]) : null,
        }
      : from?.startsWith('the pump')
        ? { signal: '', why: null, ageMin: null }
        : null,
  };
}

export interface CurveOutside {
  signal: string;
  fallback: boolean;
  why: OutsideWhy | null;
  ageMin: number | null;
  raw: number | null;
}

/**
 * The outside sensor chosen for the heating curve in this decision: the chosen signal, whether
 * the curve fell back to the pump's sensor (and why: the controller state's `outside_reason`, or
 * the note for a record without it) and the raw value it used. Null when no sensor was chosen
 * (the record then carries no `outside_source`).
 */
export function curveOutside(record: DecisionRecord): CurveOutside | null {
  const source = stringState(record, 'outside_source');
  if (source === null) return null;
  const fallback = record.controller_state['outside_fallback'] === true;
  const note = parseCurveNote(record.terms.find((term) => term.name === 'curve')?.note ?? '');
  const signal = fallback ? note?.fallback?.signal || source : (note?.from ?? source);
  const reason = stringState(record, 'outside_reason');
  const stated = reason !== null && OUTSIDE_WHY.includes(reason) ? (reason as OutsideWhy) : null;
  return {
    signal,
    fallback,
    why: fallback ? (stated ?? note?.fallback?.why ?? null) : null,
    ageMin: fallback ? (note?.fallback?.ageMin ?? null) : null,
    raw: note ? note.raw : null,
  };
}

/**
 * The chosen outside sensor as a fact: the curve uses it, or it fell back to the pump's sensor.
 * Null without a chosen sensor.
 */
export function outsideFact(record: DecisionRecord, fmt: NumberFormats): Fact | null {
  const outside = curveOutside(record);
  if (!outside) return null;
  const raw = outside.raw === null ? '–' : fmt.plain(outside.raw, 1);
  if (!outside.fallback) return { kind: 'outside_source', params: { signal: outside.signal, raw } };
  return {
    kind: 'outside_fallback',
    params: {
      signal: outside.signal,
      raw,
      why: outside.why ?? 'unknown',
      min: outside.ageMin === null ? '–' : fmt.plain(outside.ageMin, 0),
    },
  };
}

export type ClauseKind =
  | 'room'
  | 'sensor'
  | 'defrost'
  | 'dhw'
  | 'plan'
  | 'ramp'
  | 'cycling'
  | 'safety'
  | 'stove'
  | 'outcome'
  | 'other';

export interface Clause {
  kind: ClauseKind;
  text: string;
}

const CLAUSE_RULES: [RegExp, ClauseKind][] = [
  [/^(held value|value )/i, 'sensor'],
  [/^setpoint/i, 'outcome'],
  [/wood-stove/i, 'stove'],
  [/defrost/i, 'defrost'],
  [/DHW|hot water/i, 'dhw'],
  [/^(room|no usable room|pi adds)/i, 'room'],
  [/^(plan|boost)/i, 'plan'],
  [/start ramp/i, 'ramp'],
  [/cycling floor|min-run/i, 'cycling'],
  [/safety|clamp/i, 'safety'],
];

const HOT_WATER_WORDS = /\b(?:domestic hot[- ]water|DHW|hot[- ]water)(?: run)?(?: in progress)?/gi;

/**
 * Split the controller's note into its clauses ("; "-separated, final period dropped), each
 * tagged with what it is about so it can carry an icon. With hot water hidden, a hot-water
 * clause names the run "pump busy elsewhere" instead ("Pump busy elsewhere: integrator frozen,
 * no decrease").
 */
export function noteClauses(note: string, hotWater = true): Clause[] {
  return note
    .replace(/\.\s*$/, '')
    .split(/;\s+(?!no duty command)/)
    .map((text) => text.trim())
    .filter(Boolean)
    .map((raw) => {
      const kind = CLAUSE_RULES.find(([pattern]) => pattern.test(raw))?.[1] ?? 'other';
      const text = hotWater ? raw : raw.replace(HOT_WATER_WORDS, 'pump busy elsewhere');
      return { kind, text: text.charAt(0).toUpperCase() + text.slice(1) };
    });
}

export interface InputView {
  signal: string;
  key: string;
  icon: IconName;
  unit: string | null;
  digits: number;
  value: number | string | boolean | null;
  enumKey: string | null;
  age: number | null;
  fresh: boolean;
  source: string | null;
}

interface InputMeta {
  key: string;
  icon: IconName;
  unit: string | null;
  digits: number;
}

const INPUT_META: Record<string, InputMeta> = {
  'main/Outside_Temp': { key: 'outside', icon: 'thermometer', unit: '°C', digits: 1 },
  'main/Main_Outlet_Temp': { key: 'outlet', icon: 'droplet', unit: '°C', digits: 1 },
  'main/Main_Inlet_Temp': { key: 'inlet', icon: 'droplet', unit: '°C', digits: 1 },
  'main/Compressor_Freq': { key: 'compressor', icon: 'fan', unit: 'Hz', digits: 0 },
  'main/Defrosting_State': { key: 'defrost', icon: 'snowflake', unit: null, digits: 0 },
  'main/ThreeWay_Valve_State': { key: 'valve', icon: 'tap', unit: null, digits: 0 },
  'main/Heating_Mode': { key: 'heating_mode', icon: 'settings', unit: null, digits: 0 },
  'main/Operating_Mode_State': { key: 'operating_mode', icon: 'power', unit: null, digits: 0 },
  'main/Z1_Water_Target_Temp': { key: 'water_target', icon: 'target', unit: '°C', digits: 0 },
  'main/Main_Target_Temp': { key: 'main_target', icon: 'target', unit: '°C', digits: 0 },
  'main/Pump_Flow': { key: 'flow', icon: 'droplet', unit: 'l/min', digits: 1 },
  'main/Quiet_Mode_Level': { key: 'quiet', icon: 'moon', unit: null, digits: 0 },
};

const ENUM_INPUTS = new Set(['defrost', 'valve', 'heating_mode', 'operating_mode']);

/**
 * Inputs of a decision as display items: a label key, icon, unit and enum key per known signal,
 * the room input as "room", forecast inputs as "forecast"; internal flags without a source (such
 * as `stats`) are left out.
 */
export function inputViews(record: DecisionRecord): InputView[] {
  return record.inputs_used
    .filter((input) => !(input.source === null && typeof input.value === 'boolean'))
    .map((input) => {
      const meta: InputMeta =
        INPUT_META[input.signal] ??
        (input.source === 'room'
          ? { key: 'room', icon: 'home', unit: '°C', digits: 1 }
          : input.issued !== null
            ? { key: 'forecast', icon: 'weather', unit: null, digits: 1 }
            : { key: 'other', icon: 'chart', unit: null, digits: 2 });
      const enumKey =
        ENUM_INPUTS.has(meta.key) && input.value !== null
          ? `${meta.key}_${String(input.value)}`
          : null;
      return {
        signal: input.signal,
        key: meta.key,
        icon: meta.icon,
        unit: meta.unit,
        digits: meta.digits,
        value: input.value,
        enumKey,
        age: input.age,
        fresh: input.fresh,
        source: input.source,
      };
    });
}
