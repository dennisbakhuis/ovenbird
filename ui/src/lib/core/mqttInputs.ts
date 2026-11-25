/**
 * The `mqtt_inputs` setting: extra MQTT topics read as signals. Kept in lib/core, free of runes
 * and aliases, because the schema check (also used by the mock) needs it.
 */

/** The `mqtt_inputs` value: extra topics read as signals. */
export interface MqttInput {
  topic: string;
  signal?: string | null;
  unit?: string | null;
  minimum?: number | null;
  maximum?: number | null;
}

/**
 * Coerce a configuration value to MQTT inputs, or an empty list. Keys are kept as they came, so
 * an untouched row stays equal to the stored one.
 */
export function asMqttInputs(value: unknown): MqttInput[] {
  if (!Array.isArray(value)) return [];
  return value.flatMap((item): MqttInput[] => {
    if (!item || typeof item !== 'object') return [];
    const row = item as Record<string, unknown>;
    const out: MqttInput = { topic: typeof row['topic'] === 'string' ? row['topic'] : '' };
    for (const key of ['signal', 'unit'] as const) {
      const v = row[key];
      if (typeof v === 'string' || v === null) out[key] = v;
    }
    for (const key of ['minimum', 'maximum'] as const) {
      const v = row[key];
      if ((typeof v === 'number' && Number.isFinite(v)) || v === null) out[key] = v;
    }
    return [out];
  });
}

/**
 * The signal an input appears as: its own signal, else `mqtt/<topic>`.
 */
export function inputSignal(input: MqttInput): string {
  return input.signal?.trim() ? input.signal.trim() : `mqtt/${input.topic.trim()}`;
}

/**
 * One input as stored: the topic as typed, and only the optional keys that are set (a blank
 * signal or unit is left out, so the defaults apply).
 */
export function cleanInput(input: MqttInput): MqttInput {
  const out: MqttInput = { topic: input.topic };
  if (input.signal?.trim()) out.signal = input.signal;
  if (input.unit?.trim()) out.unit = input.unit;
  if (typeof input.minimum === 'number') out.minimum = input.minimum;
  if (typeof input.maximum === 'number') out.maximum = input.maximum;
  return out;
}

export type MqttInputProblem =
  | 'topic_missing'
  | 'topic_wildcard'
  | 'topic_too_long'
  | 'topic_reserved'
  | 'topic_duplicate'
  | 'signal_too_long'
  | 'signal_reserved'
  | 'signal_duplicate'
  | 'range';

/** Longest topic, signal or unit the service accepts. */
export const MAX_INPUT_TEXT = 256;

/** Most inputs the service accepts. */
export const MAX_INPUTS = 32;

const RESERVED_PREFIXES = ['main/', 'ha/', 'commands/', 'derived/'];
const RESERVED_SIGNALS = new Set(['stats', 'LWT']);
const BOARD_SUBTREES = ['main', 'commands'];
const BOARD_TOPICS = ['stats', 'LWT'];

/**
 * Whether a signal id belongs to the pump, Home Assistant or the service (the HeishaMon signals
 * all start with `main/`).
 */
export function reservedSignal(signal: string): boolean {
  return RESERVED_SIGNALS.has(signal) || RESERVED_PREFIXES.some((p) => signal.startsWith(p));
}

/**
 * Whether a topic belongs to the HeishaMon board itself: `<base>/main` and `<base>/commands`
 * with everything below them, `<base>/stats` and `<base>/LWT`.
 */
export function reservedTopic(topic: string, base: string): boolean {
  if (!base || !topic.startsWith(`${base}/`)) return false;
  const suffix = topic.slice(base.length + 1);
  return (
    BOARD_TOPICS.includes(suffix) ||
    BOARD_SUBTREES.some((tree) => suffix === tree || suffix.startsWith(`${tree}/`))
  );
}

/**
 * What is wrong with the inputs, the first problem per row (null for a good row), mirroring the
 * service's checks for the HeishaMon base `base`. The service has the final word.
 */
export function mqttInputProblems(
  inputs: MqttInput[],
  base = 'panasonic_heat_pump',
): (MqttInputProblem | null)[] {
  const topics = inputs.map((input) => input.topic.trim());
  const signals = inputs.map((input) => inputSignal(input));
  return inputs.map((input, index) => {
    const topic = topics[index] ?? '';
    const signal = signals[index] ?? '';
    if (topic === '') return 'topic_missing';
    if (/[#+]/.test(topic)) return 'topic_wildcard';
    if (topic.length > MAX_INPUT_TEXT) return 'topic_too_long';
    if (reservedTopic(topic, base.trim())) return 'topic_reserved';
    if (topics.indexOf(topic) !== index) return 'topic_duplicate';
    if (signal.length > MAX_INPUT_TEXT) return 'signal_too_long';
    if (reservedSignal(signal)) return 'signal_reserved';
    if (signals.indexOf(signal) !== index) return 'signal_duplicate';
    if (
      typeof input.minimum === 'number' &&
      typeof input.maximum === 'number' &&
      input.minimum > input.maximum
    )
      return 'range';
    return null;
  });
}
