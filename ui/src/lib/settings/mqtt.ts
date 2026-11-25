import type { ConfigDoc, MqttStatus, MqttTestResult } from '$lib/core/types';

export {
  MAX_INPUTS,
  asMqttInputs,
  cleanInput,
  inputSignal,
  mqttInputProblems,
  type MqttInput,
  type MqttInputProblem,
} from '$lib/core/mqttInputs';

/** The broker form's keys, as the `config/mqtt` endpoints name them. */
export const MQTT_KEYS = [
  'host',
  'port',
  'username',
  'password',
  'tls',
  'ca_file',
  'client_id',
  'base',
] as const;

export type MqttKey = (typeof MQTT_KEYS)[number];

/** The settings field behind each form key. */
export const MQTT_FIELDS: Record<MqttKey, string> = {
  host: 'mqtt_host',
  port: 'mqtt_port',
  username: 'mqtt_username',
  password: 'mqtt_password',
  tls: 'mqtt_tls',
  ca_file: 'mqtt_ca_file',
  client_id: 'mqtt_client_id',
  base: 'heishamon_base',
};

export interface MqttForm {
  host: string;
  port: string;
  username: string;
  password: string;
  tls: boolean;
  ca_file: string;
  client_id: string;
  base: string;
}

export type MqttBody = Partial<Record<MqttKey, string | number | boolean | null>>;

export type MqttProblem = 'host' | 'port' | 'base' | 'spaces';

export type MqttVerdict = 'ok' | 'no_heishamon' | 'failed';

export type MqttSaveBlock =
  'commands' | 'applying' | 'locked' | 'unchanged' | 'untested' | 'failed' | 'changed' | null;

export interface MqttTested {
  body: MqttBody;
  ok: boolean;
}

const text = (value: unknown): string =>
  value === null || value === undefined ? '' : String(value);

/**
 * The broker form as the configuration has it now: effective values, the password always empty
 * (it is write-only; the service only says whether one is stored).
 */
export function mqttFormOf(config: ConfigDoc | null): MqttForm {
  const value = (key: MqttKey) => config?.fields[MQTT_FIELDS[key]]?.value;
  return {
    host: text(value('host')),
    port: text(value('port')),
    username: text(value('username')),
    password: '',
    tls: value('tls') === true,
    ca_file: text(value('ca_file')),
    client_id: text(value('client_id')),
    base: text(value('base')),
  };
}

/**
 * The form keys locked by the deployment (environment or options file).
 */
export function mqttLocked(config: ConfigDoc | null): Set<MqttKey> {
  return new Set(MQTT_KEYS.filter((key) => config?.fields[MQTT_FIELDS[key]]?.locked === true));
}

/**
 * Whether a password is stored for the broker.
 */
export function mqttPasswordSet(config: ConfigDoc | null): boolean {
  return config?.fields[MQTT_FIELDS.password]?.value === 'set';
}

/**
 * The request body for a test or a change: only what differs from the configuration now, a typed
 * password, an empty text as `null` (the default) and the port as a number. Locked keys are never
 * sent. Test and change send the same body, so a change matches its test.
 */
export function mqttBody(form: MqttForm, saved: MqttForm, locked: Set<MqttKey>): MqttBody {
  const body: MqttBody = {};
  for (const key of MQTT_KEYS) {
    if (locked.has(key)) continue;
    if (key === 'password') {
      if (form.password !== '') body.password = form.password;
      continue;
    }
    if (key === 'tls') {
      if (form.tls !== saved.tls) body.tls = form.tls;
      continue;
    }
    const now = form[key].trim();
    if (now === saved[key].trim()) continue;
    if (key === 'port') {
      const port = Number(now);
      body.port = now === '' ? null : Number.isInteger(port) ? port : now;
      continue;
    }
    body[key] = now === '' ? null : now;
  }
  return body;
}

/**
 * Whether two request bodies ask for the same broker settings.
 */
export function sameMqttBody(a: MqttBody, b: MqttBody): boolean {
  const keys = new Set([...Object.keys(a), ...Object.keys(b)] as MqttKey[]);
  return [...keys].every((key) => key in a && key in b && a[key] === b[key]);
}

/**
 * Whether the body changes the broker: any key but none at all means "test what runs now".
 */
export function mqttChanges(body: MqttBody): boolean {
  return Object.keys(body).length > 0;
}

/**
 * Whether the body would drop the stored password: a new host or port, TLS switched off or another
 * CA file without a password (the service never sends a stored password to another broker).
 */
export function dropsPassword(body: MqttBody, passwordSet: boolean): boolean {
  const moved = 'host' in body || 'port' in body || body.tls === false || 'ca_file' in body;
  return passwordSet && moved && !('password' in body);
}

/**
 * What is wrong with one typed value, mirroring the service's checks (null when it passes). The
 * service has the final word.
 */
export function mqttProblem(key: MqttKey, value: string): MqttProblem | null {
  const typed = value.trim();
  if (key === 'port') {
    if (typed === '') return null;
    const port = Number(typed);
    return /^\d+$/.test(typed) && port >= 1 && port <= 65535 ? null : 'port';
  }
  if (key === 'host' && typed === '') return 'host';
  if (key === 'base' && /[#+]/.test(typed)) return 'base';
  if ((key === 'host' || key === 'username' || key === 'client_id') && /\s/.test(typed))
    return 'spaces';
  return null;
}

/**
 * Every problem of the form, by key.
 */
export function mqttProblems(
  form: MqttForm,
  locked: Set<MqttKey>,
): Partial<Record<MqttKey, MqttProblem>> {
  const out: Partial<Record<MqttKey, MqttProblem>> = {};
  for (const key of MQTT_KEYS) {
    if (locked.has(key) || key === 'tls' || key === 'password') continue;
    const problem = mqttProblem(key, form[key]);
    if (problem) out[key] = problem;
  }
  return out;
}

/**
 * The headline of a broker test: everything fine, connected but no HeishaMon data on that base,
 * or no connection.
 */
export function mqttVerdict(result: MqttTestResult): MqttVerdict {
  if (result.ok) return 'ok';
  if (result.connected && result.error_code === 'no_heishamon') return 'no_heishamon';
  return 'failed';
}

/**
 * Why "Save connection" is not possible, in order of importance; null when it is. A change
 * needs a successful test of exactly the same body.
 */
export function mqttSaveBlock(options: {
  body: MqttBody;
  tested: MqttTested | null;
  status: MqttStatus | null;
  allLocked: boolean;
}): MqttSaveBlock {
  const { body, tested, status, allLocked } = options;
  if (status?.commands_enabled) return 'commands';
  if (status?.apply.state === 'applying') return 'applying';
  if (allLocked) return 'locked';
  if (!mqttChanges(body)) return 'unchanged';
  if (!tested) return 'untested';
  if (!sameMqttBody(tested.body, body)) return 'changed';
  if (!tested.ok) return 'failed';
  return null;
}
