import type {
  Alarm,
  AuditEvent,
  ConfigDoc,
  ConfigField,
  Decision,
  MqttStatus,
  ValidationIssue,
} from '../src/lib/core/types';
import type { Scenario } from './scenario.ts';

/**
 * The mock broker connection (`config/mqtt`), kept per browser (scenario cookie) so parallel
 * tests do not see each other's changes, and the chosen outside sensor of the heating curve in
 * the latest decision.
 *
 * Deterministic answers of the broker test: a host containing `bad` cannot be reached, the user
 * name `wrong` is rejected, the base `empty` brings no HeishaMon data; anything else works. After
 * a change the watch settles after {@link APPLY_MS}: `applied`, or `reverted` (back to the
 * previous broker, with the `mqtt_connection_reverted` alarm) for a host containing `flaky`.
 */

export interface MqttConn {
  host: string;
  port: number;
  username: string | null;
  password: string | null;
  tls: boolean;
  ca_file: string | null;
  client_id: string | null;
  base: string;
}

export interface MqttMock {
  conn: MqttConn;
  previous: MqttConn | null;
  tested: { fingerprint: string; atMs: number } | null;
  apply: MqttStatus['apply'];
  applyMs: number | null;
  reverted: { atMs: number; message: string } | null;
  audit: AuditEvent[];
}

export const APPLY_MS = 3_000;
const TEST_VALID_MS = 10 * 60_000;
const ACTOR = 'admin from 127.0.0.1';

export const MQTT_DEFAULTS: MqttConn = {
  host: 'localhost',
  port: 1883,
  username: null,
  password: null,
  tls: false,
  ca_file: null,
  client_id: null,
  base: 'panasonic_heat_pump',
};

const INITIAL: MqttConn = { ...MQTT_DEFAULTS, host: 'mosquitto' };

const KEYS = [
  'host',
  'port',
  'username',
  'password',
  'tls',
  'ca_file',
  'client_id',
  'base',
] as const;
type Key = (typeof KEYS)[number];

export const MQTT_FIELD: Record<Key, string> = {
  host: 'mqtt_host',
  port: 'mqtt_port',
  username: 'mqtt_username',
  password: 'mqtt_password',
  tls: 'mqtt_tls',
  ca_file: 'mqtt_ca_file',
  client_id: 'mqtt_client_id',
  base: 'heishamon_base',
};

/** The broker fields `mqtt:env` sets from the environment. */
const ENV_LOCKED: ReadonlySet<Key> = new Set(['host', 'port', 'username', 'password']);

const ENV_CONN: MqttConn = { ...INITIAL, host: 'mosquitto', username: 'ovenbird', password: 'env' };

/** The chosen outside sensor of the scenarios `outside:sensor` and `outside:stale`. */
export const OUTSIDE_SIGNAL = 'ha/sensor.garden_temperature';

/** Age of the chosen outside sensor in the scenario `outside:stale`, in seconds. */
export const OUTSIDE_STALE_S = 42 * 60;

/**
 * A fresh broker state for one browser.
 */
export function initialMqtt(): MqttMock {
  return {
    conn: { ...INITIAL },
    previous: null,
    tested: null,
    apply: { state: 'idle', message: null, at: null },
    applyMs: null,
    reverted: null,
    audit: [],
  };
}

function locked(scenario: Scenario): ReadonlySet<Key> {
  return scenario.mqtt === 'env' ? ENV_LOCKED : new Set();
}

function effective(mock: MqttMock, scenario: Scenario): MqttConn {
  if (scenario.mqtt !== 'env') return mock.conn;
  const out = { ...mock.conn };
  for (const key of ENV_LOCKED) (out as Record<Key, unknown>)[key] = ENV_CONN[key];
  return out;
}

/**
 * Settle a running change once its watch time is over: applied, or back to the previous broker.
 */
export function settleMqtt(mock: MqttMock, now: number): void {
  if (mock.apply.state !== 'applying' || mock.applyMs === null || now - mock.applyMs < APPLY_MS)
    return;
  const at = new Date(mock.applyMs + APPLY_MS).toISOString();
  if (mock.conn.host.includes('flaky') && mock.previous) {
    const failed = mock.conn;
    mock.conn = mock.previous;
    const message = `the broker change was reverted: no connection to ${failed.host}:${failed.port} within 60 s; back on ${mock.conn.host}:${mock.conn.port}`;
    mock.apply = { state: 'reverted', message, at };
    mock.reverted = { atMs: mock.applyMs + APPLY_MS, message };
    mock.audit.push({
      at,
      actor: 'ovenbird',
      source_ip: null,
      action: 'mqtt_connection_reverted',
      detail: auditDetail(mock.conn, ['host']),
    });
  } else {
    mock.apply = { state: 'applied', message: 'connected; HeishaMon data arrives', at };
  }
  mock.previous = null;
  mock.applyMs = null;
}

/**
 * `GET config/mqtt`: the link, the HeishaMon message count and the last change.
 */
export function mqttStatus(mock: MqttMock, scenario: Scenario, now: number): MqttStatus {
  settleMqtt(mock, now);
  const conn = effective(mock, scenario);
  const applying = mock.apply.state === 'applying';
  return {
    connected: true,
    host: conn.host,
    port: conn.port,
    base: conn.base,
    heishamon_messages: applying ? 0 : 144 + Math.floor((now / 60_000) % 60),
    commands_enabled: scenario.mqtt === 'commands',
    apply: { ...mock.apply },
  };
}

/**
 * The broker fields of `GET config` for this browser: effective values, the password as
 * "set"/"unset", locked with the environment as source under `mqtt:env`.
 */
export function mqttFields(mock: MqttMock, scenario: Scenario): Record<string, ConfigField> {
  const conn = effective(mock, scenario);
  const lockedKeys = locked(scenario);
  const out: Record<string, ConfigField> = {};
  for (const key of KEYS) {
    const raw = conn[key];
    const isDefault = raw === MQTT_DEFAULTS[key];
    const shown = key === 'password' ? (raw ? 'set' : 'unset') : raw;
    const env = lockedKeys.has(key);
    out[MQTT_FIELD[key]] = {
      value: shown,
      source: env ? 'env' : isDefault ? 'default' : 'store',
      locked: env,
      stored: env || isDefault ? null : key === 'password' ? 'set' : raw,
      default: key === 'password' ? null : MQTT_DEFAULTS[key],
    };
  }
  return out;
}

/**
 * The configuration document with this browser's broker fields.
 */
export function withMqtt(doc: ConfigDoc, mock: MqttMock, scenario: Scenario): ConfigDoc {
  return { ...doc, fields: { ...doc.fields, ...mqttFields(mock, scenario) } };
}

function issue(field: string | null, code: string, message: string, params = {}): ValidationIssue {
  return { field, code, message, params };
}

/**
 * The candidate of a request body: absent keys keep the effective value, `null` or `""` the
 * default; a new host or port without a password drops the stored one. Errors as the service
 * gives them.
 */
export function mqttCandidate(
  mock: MqttMock,
  body: Record<string, unknown>,
  scenario: Scenario,
): { candidate: MqttConn; errors: ValidationIssue[] } {
  const current = effective(mock, scenario);
  const candidate: MqttConn = { ...current };
  const errors: ValidationIssue[] = [];
  const lockedKeys = locked(scenario);
  for (const [name, value] of Object.entries(body)) {
    if (!(KEYS as readonly string[]).includes(name)) {
      errors.push(issue(null, 'unknown_field', `unknown fields: ${name}`));
      continue;
    }
    const key = name as Key;
    const field = MQTT_FIELD[key];
    if (lockedKeys.has(key)) {
      errors.push(
        issue(field, 'locked', `${field} is set by the deployment`, {
          source: 'env',
          env: `OVENBIRD_${field.toUpperCase()}`,
        }),
      );
      continue;
    }
    if (value === null || value === '') {
      (candidate as Record<Key, unknown>)[key] = MQTT_DEFAULTS[key];
      continue;
    }
    if (key === 'port') {
      if (typeof value !== 'number' || !Number.isInteger(value))
        errors.push(issue(field, 'type', 'mqtt_port must be a whole number'));
      else if (value < 1) errors.push(issue(field, 'below_min', 'below 1', { min: 1 }));
      else if (value > 65535) errors.push(issue(field, 'above_max', 'above 65535', { max: 65535 }));
      else candidate.port = value;
      continue;
    }
    if (key === 'tls') {
      if (typeof value !== 'boolean')
        errors.push(issue(field, 'type', 'mqtt_tls must be true or false'));
      else candidate.tls = value;
      continue;
    }
    if (typeof value !== 'string') {
      errors.push(issue(field, 'type', `${field} must be a string`));
      continue;
    }
    const text = value.trim();
    if ((key === 'host' || key === 'username' || key === 'client_id') && /\s/.test(text))
      errors.push(issue(field, 'invalid', `${field} must not contain spaces`));
    else if (key === 'base' && /[#+]/.test(text))
      errors.push(issue(field, 'invalid', 'heishamon_base must not contain wildcards'));
    else if (key === 'ca_file' && text.includes('missing'))
      errors.push(issue(field, 'ca_file_missing', `${text} does not exist`));
    else (candidate as Record<Key, unknown>)[key] = text;
  }
  if ((candidate.host !== current.host || candidate.port !== current.port) && !('password' in body))
    candidate.password = null;
  return { candidate, errors };
}

function fingerprint(conn: MqttConn): string {
  return JSON.stringify(KEYS.map((key) => conn[key]));
}

/**
 * `POST config/mqtt/test`: validate the candidate and answer the deterministic test.
 */
export function mqttTest(
  mock: MqttMock,
  body: Record<string, unknown>,
  scenario: Scenario,
  now: number,
): { status: number; body: unknown } {
  const { candidate, errors } = mqttCandidate(mock, body, scenario);
  if (errors.length > 0) return { status: 422, body: { errors, warnings: [] } };
  const base = {
    ok: false,
    host: candidate.host,
    port: candidate.port,
    base: candidate.base,
    connected: false,
    heishamon: false,
    topic: null as string | null,
    latency_ms: null as number | null,
    error: null as string | null,
    error_code: null as string | null,
  };
  if (candidate.host.includes('bad'))
    return {
      status: 200,
      body: {
        ...base,
        error_code: 'unreachable',
        error: `cannot connect to ${candidate.host}:${candidate.port}: [Errno -2] Name or service not known`,
      },
    };
  if (candidate.username === 'wrong')
    return {
      status: 200,
      body: {
        ...base,
        latency_ms: 18,
        error_code: 'auth_failed',
        error: 'the broker refused the connection: not authorised',
      },
    };
  if (candidate.base === 'empty')
    return {
      status: 200,
      body: {
        ...base,
        connected: true,
        latency_ms: 21,
        error_code: 'no_heishamon',
        error: 'connected, but no value under empty/main/# within 10 s',
      },
    };
  mock.tested = { fingerprint: fingerprint(candidate), atMs: now };
  mock.reverted = null;
  return {
    status: 200,
    body: {
      ...base,
      ok: true,
      connected: true,
      heishamon: true,
      topic: `${candidate.base}/main/Heatpump_State`,
      latency_ms: 23,
    },
  };
}

function auditDetail(conn: MqttConn, changed: string[]): Record<string, unknown> {
  return {
    changed,
    host: conn.host,
    port: conn.port,
    username: conn.username,
    password: conn.password ? 'set' : 'unset',
    tls: conn.tls,
    base: conn.base,
  };
}

/**
 * `PUT config/mqtt`: apply exactly a tested candidate and start the watch. The caller adds the
 * configuration document to a 200 answer.
 */
export function mqttApply(
  mock: MqttMock,
  body: Record<string, unknown>,
  scenario: Scenario,
  now: number,
): { status: number; body: unknown } {
  settleMqtt(mock, now);
  const refused = (status: number, code: string, message: string) => ({
    status,
    body: { errors: [issue(null, code, message)], warnings: [] },
  });
  if (scenario.mqtt === 'commands')
    return refused(
      409,
      'commands_enabled',
      'commands are enabled: the command link keeps its broker until a restart, so change the broker in the deployment and restart',
    );
  if (mock.apply.state === 'applying')
    return refused(409, 'apply_pending', 'the last broker change is still being checked');
  const { candidate, errors } = mqttCandidate(mock, body, scenario);
  if (errors.length > 0) return { status: 422, body: { errors, warnings: [] } };
  if (fingerprint(candidate) === fingerprint(effective(mock, scenario)))
    return {
      status: 422,
      body: { errors: [issue(null, 'no_change', 'nothing changed')], warnings: [] },
    };
  const tested = mock.tested;
  if (!tested || now - tested.atMs > TEST_VALID_MS || tested.fingerprint !== fingerprint(candidate))
    return refused(409, 'test_required', 'test exactly these broker settings successfully first');
  const changed = KEYS.filter((key) => candidate[key] !== mock.conn[key]).map(
    (key) => MQTT_FIELD[key],
  );
  mock.previous = mock.conn;
  mock.conn = candidate;
  mock.tested = null;
  mock.reverted = null;
  mock.applyMs = now;
  mock.apply = {
    state: 'applying',
    message: 'waiting up to 60 s for HeishaMon data',
    at: new Date(now).toISOString(),
  };
  mock.audit.push({
    at: new Date(now).toISOString(),
    actor: ACTOR,
    source_ip: '127.0.0.1',
    action: 'mqtt_connection',
    detail: auditDetail(candidate, changed),
  });
  return { status: 200, body: null };
}

/**
 * The alarms of the broker and the outside sensor: `mqtt_connection_reverted` after a revert
 * (until the next successful test or change), `outside_sensor_stale` for `outside:stale`.
 */
export function integrationAlarms(mock: MqttMock, scenario: Scenario, now: number): Alarm[] {
  settleMqtt(mock, now);
  const out: Alarm[] = [];
  if (mock.reverted)
    out.push({
      code: 'mqtt_connection_reverted',
      severity: 'warning',
      message: mock.reverted.message,
      since: new Date(mock.reverted.atMs).toISOString(),
      detail: {},
    });
  if (scenario.outside === 'stale')
    out.push({
      code: 'outside_sensor_stale',
      severity: 'warning',
      message: `outside sensor ${OUTSIDE_SIGNAL} has no value younger than 30 min; the curve uses the pump's sensor`,
      since: new Date(now - OUTSIDE_STALE_S * 1000).toISOString(),
      detail: { signal: OUTSIDE_SIGNAL },
    });
  return out;
}

/**
 * The configuration under `outside:*`: the chosen outside sensor stored.
 */
export function withOutside(doc: ConfigDoc, scenario: Scenario): ConfigDoc {
  if (!scenario.outside) return doc;
  const field = doc.fields['control_outside_signal'];
  if (!field) return doc;
  return {
    ...doc,
    fields: {
      ...doc.fields,
      control_outside_signal: {
        ...field,
        value: OUTSIDE_SIGNAL,
        source: 'store',
        stored: OUTSIDE_SIGNAL,
      },
    },
  };
}

const RAW = /\((-?\d+(?:\.\d+)?) °C raw\)$/;

/**
 * A decision with a chosen outside sensor, as the controller records it: the signal in
 * `inputs_used`, `outside_source`, `outside_fallback` and `outside_reason` in the controller
 * state and the source at the end of the curve term's note. Stale: the pump's value with the
 * reason. Without a chosen sensor the decision stays as it is.
 */
export function withOutsideDecision(
  decision: Decision,
  signal: string | null,
  stale: boolean,
): Decision {
  const record = decision.record;
  if (!signal || !record) return decision;
  const curve = record.terms.find((term) => term.name === 'curve');
  const match = curve ? RAW.exec(curve.note) : null;
  if (!curve || !match) return decision;
  const pump = Number(match[1]);
  const own = Math.round((pump - 0.6) * 10) / 10;
  const note = stale
    ? curve.note.replace(
        RAW,
        `(${pump} °C raw from the pump: ${signal} is stale, ${OUTSIDE_STALE_S / 60} min old)`,
      )
    : curve.note.replace(RAW, `(${own} °C raw from ${signal})`);
  return {
    ...decision,
    record: {
      ...record,
      terms: record.terms.map((term) => (term === curve ? { ...term, note } : term)),
      inputs_used: [
        ...record.inputs_used,
        {
          signal,
          value: stale ? null : own,
          age: stale ? OUTSIDE_STALE_S : 120,
          fresh: !stale,
          source: null,
          issued: null,
        },
      ],
      controller_state: {
        ...record.controller_state,
        outside_source: stale ? 'main/Outside_Temp' : signal,
        outside_fallback: stale,
        outside_reason: stale ? 'stale' : null,
      },
    },
  };
}
