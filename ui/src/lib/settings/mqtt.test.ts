import { describe, expect, it } from 'vitest';
import schemaJson from '$mock/fixtures/schema.json';
import configJson from '$mock/fixtures/config.json';
import {
  initialMqtt,
  integrationAlarms,
  mqttApply,
  mqttFields,
  mqttStatus,
  mqttTest,
  APPLY_MS,
} from '$mock/integrations';
import { makeSignals } from '$mock/config';
import { checkField } from '$lib/core/schema';
import type { ConfigDoc, ConfigSchema, MqttStatus, MqttTestResult } from '$lib/core/types';
import {
  asMqttInputs,
  cleanInput,
  dropsPassword,
  inputSignal,
  mqttBody,
  mqttFormOf,
  mqttInputProblems,
  mqttLocked,
  mqttPasswordSet,
  mqttProblem,
  mqttProblems,
  mqttSaveBlock,
  mqttVerdict,
  sameMqttBody,
  type MqttForm,
} from './mqtt';

const schema = schemaJson as unknown as ConfigSchema;
const NOW = Date.parse('2026-11-24T12:00:00Z');

function configWith(fields: Record<string, unknown>): ConfigDoc {
  const base = structuredClone(configJson) as unknown as ConfigDoc;
  for (const [id, patch] of Object.entries(fields))
    base.fields[id] = { ...(base.fields[id] as object), ...(patch as object) } as never;
  return base;
}

const saved: MqttForm = {
  host: 'mosquitto',
  port: '1883',
  username: '',
  password: '',
  tls: false,
  ca_file: '',
  client_id: '',
  base: 'panasonic_heat_pump',
};

function status(state: MqttStatus['apply']['state'], commands = false): MqttStatus {
  return {
    connected: true,
    host: 'mosquitto',
    port: 1883,
    base: 'panasonic_heat_pump',
    heishamon_messages: 10,
    commands_enabled: commands,
    apply: { state, message: null, at: null },
  };
}

function result(patch: Partial<MqttTestResult>): MqttTestResult {
  return {
    ok: false,
    host: 'h',
    port: 1883,
    base: 'b',
    connected: false,
    heishamon: false,
    topic: null,
    latency_ms: null,
    error: null,
    error_code: null,
    ...patch,
  } as MqttTestResult;
}

describe('mqtt form', () => {
  it('reads effective values, never the password, and the locks', () => {
    const config = configWith({
      mqtt_password: { value: 'set' },
      mqtt_tls: { value: true },
    });
    const form = mqttFormOf(config);
    expect(form.host).toBe('mosquitto');
    expect(form.port).toBe('1883');
    expect(form.password).toBe('');
    expect(form.tls).toBe(true);
    expect(mqttPasswordSet(config)).toBe(true);
    expect([...mqttLocked(config)].sort()).toEqual(['host', 'port']);
    expect(mqttFormOf(null).host).toBe('');
  });

  it('sends only what differs, a typed password, null for empty and the port as a number', () => {
    const none = new Set<never>();
    expect(mqttBody(saved, saved, none)).toEqual({});
    expect(mqttBody({ ...saved, host: ' broker.lan ', port: '8883' }, saved, none)).toEqual({
      host: 'broker.lan',
      port: 8883,
    });
    expect(mqttBody({ ...saved, password: 'secret', tls: true }, saved, none)).toEqual({
      password: 'secret',
      tls: true,
    });
    expect(mqttBody({ ...saved, base: '' }, saved, none)).toEqual({ base: null });
    expect(mqttBody({ ...saved, host: 'other' }, saved, new Set(['host']))).toEqual({});
  });

  it('compares bodies key by key', () => {
    expect(sameMqttBody({ host: 'a', port: 1 }, { port: 1, host: 'a' })).toBe(true);
    expect(sameMqttBody({ host: 'a' }, { host: 'a', port: null })).toBe(false);
    expect(sameMqttBody({}, {})).toBe(true);
  });

  it('warns when a new broker drops the stored password', () => {
    expect(dropsPassword({ host: 'x' }, true)).toBe(true);
    expect(dropsPassword({ host: 'x', password: 'p' }, true)).toBe(false);
    expect(dropsPassword({ base: 'x' }, true)).toBe(false);
    expect(dropsPassword({ host: 'x' }, false)).toBe(false);
    expect(dropsPassword({ tls: false }, true)).toBe(true);
    expect(dropsPassword({ tls: true }, true)).toBe(false);
    expect(dropsPassword({ ca_file: '/ca.pem' }, true)).toBe(true);
  });

  it('mirrors the service checks on typed values', () => {
    expect(mqttProblem('port', '0')).toBe('port');
    expect(mqttProblem('port', '65536')).toBe('port');
    expect(mqttProblem('port', '1.5')).toBe('port');
    expect(mqttProblem('port', '8883')).toBeNull();
    expect(mqttProblem('host', ' ')).toBe('host');
    expect(mqttProblem('host', 'my broker')).toBe('spaces');
    expect(mqttProblem('base', 'panasonic/#')).toBe('base');
    expect(mqttProblem('username', 'a b')).toBe('spaces');
    expect(mqttProblems({ ...saved, host: '', port: 'x' }, new Set(['port']))).toEqual({
      host: 'host',
    });
  });

  it('names the verdict of a test', () => {
    expect(mqttVerdict(result({ ok: true, connected: true }))).toBe('ok');
    expect(mqttVerdict(result({ connected: true, error_code: 'no_heishamon' }))).toBe(
      'no_heishamon',
    );
    expect(mqttVerdict(result({ error_code: 'unreachable' }))).toBe('failed');
  });

  it('allows saving only exactly what was tested successfully', () => {
    const body = { host: 'broker.lan' };
    const block = (patch: Partial<Parameters<typeof mqttSaveBlock>[0]>) =>
      mqttSaveBlock({
        body,
        tested: { body, ok: true },
        status: status('idle'),
        allLocked: false,
        ...patch,
      });
    expect(block({})).toBeNull();
    expect(block({ status: status('idle', true) })).toBe('commands');
    expect(block({ status: status('applying') })).toBe('applying');
    expect(block({ allLocked: true })).toBe('locked');
    expect(block({ body: {} })).toBe('unchanged');
    expect(block({ tested: null })).toBe('untested');
    expect(block({ tested: { body: { host: 'other' }, ok: true } })).toBe('changed');
    expect(block({ tested: { body, ok: false } })).toBe('failed');
  });
});

describe('mqtt inputs', () => {
  it('keeps rows as stored and drops what is not a row', () => {
    const stored = [{ topic: 'a/b', signal: null, unit: '°C', minimum: -10, maximum: null }, 3];
    expect(asMqttInputs(stored)).toEqual([
      { topic: 'a/b', signal: null, unit: '°C', minimum: -10, maximum: null },
    ]);
    expect(asMqttInputs('nope')).toEqual([]);
  });

  it('names the signal and cleans a row', () => {
    expect(inputSignal({ topic: ' garden/temp ' })).toBe('mqtt/garden/temp');
    expect(inputSignal({ topic: 'garden/temp', signal: ' garden ' })).toBe('garden');
    expect(cleanInput({ topic: 'a', signal: ' ', unit: '°C', minimum: null, maximum: 40 })).toEqual(
      { topic: 'a', unit: '°C', maximum: 40 },
    );
  });

  it('finds the first problem per row and the schema check summarises them', () => {
    const inputs = [
      { topic: '' },
      { topic: 'a/#' },
      { topic: 'x' },
      { topic: ' x' },
      { topic: 'y', minimum: 5, maximum: 1 },
      { topic: 'z', minimum: 1, maximum: 5 },
    ];
    expect(mqttInputProblems(inputs)).toEqual([
      'topic_missing',
      'topic_wildcard',
      null,
      'topic_duplicate',
      'range',
      null,
    ]);
    expect(checkField(schema, 'mqtt_inputs', inputs, null).error).toBe('mqtt_inputs_invalid');
    expect(checkField(schema, 'mqtt_inputs', [{ topic: 'z' }], null).error).toBeNull();
    expect(checkField(schema, 'mqtt_inputs', 'x', null).error).toBe('not_mqtt_inputs');
  });

  it('refuses the board topics and reserved or repeated signal names', () => {
    const inputs = [
      { topic: 'garden/temp', signal: 'main/Outside_Temp' },
      { topic: 'base/main/Outside_Temp', signal: 'garden' },
      { topic: 'base/commands/SetHeatpump' },
      { topic: 'base/stats' },
      { topic: 'base/1wire/28ab', signal: 'room' },
      { topic: 'a', signal: 'ha/sensor.t' },
      { topic: 'b', signal: 'room' },
      { topic: 'c', signal: 'mqtt/b' },
      { topic: 'b2' },
      { topic: 'x'.repeat(257) },
    ];
    expect(mqttInputProblems(inputs, 'base')).toEqual([
      'signal_reserved',
      'topic_reserved',
      'topic_reserved',
      'topic_reserved',
      null,
      'signal_reserved',
      'signal_duplicate',
      null,
      null,
      'topic_too_long',
    ]);
  });
});

describe('mock broker', () => {
  it('answers the deterministic tests', () => {
    const mock = initialMqtt();
    const test = (body: Record<string, unknown>) =>
      mqttTest(mock, body, {}, NOW).body as MqttTestResult;
    expect(test({ host: 'bad.lan' }).error_code).toBe('unreachable');
    expect(test({ username: 'wrong' }).error_code).toBe('auth_failed');
    expect(test({ base: 'empty' }).error_code).toBe('no_heishamon');
    expect(test({ base: 'empty' }).connected).toBe(true);
    expect(test({ host: 'broker.lan' }).ok).toBe(true);
    expect(mqttTest(mock, { port: 0 }, {}, NOW).status).toBe(422);
  });

  it('applies only a tested candidate and settles after the watch', () => {
    const mock = initialMqtt();
    expect(mqttApply(mock, { host: 'broker.lan' }, {}, NOW).status).toBe(409);
    mqttTest(mock, { host: 'broker.lan' }, {}, NOW);
    expect(mqttApply(mock, { host: 'other.lan' }, {}, NOW).status).toBe(409);
    expect(mqttApply(mock, { host: 'broker.lan' }, {}, NOW).status).toBe(200);
    expect(mqttStatus(mock, {}, NOW + 1000).apply.state).toBe('applying');
    expect(mqttApply(mock, { host: 'x' }, {}, NOW + 1000).status).toBe(409);
    const done = mqttStatus(mock, {}, NOW + APPLY_MS);
    expect(done.apply.state).toBe('applied');
    expect(done.host).toBe('broker.lan');
    expect(mock.audit.map((e) => e.action)).toEqual(['mqtt_connection']);
  });

  it('reverts a flaky broker and raises the alarm until the next test', () => {
    const mock = initialMqtt();
    mqttTest(mock, { host: 'flaky.lan' }, {}, NOW);
    mqttApply(mock, { host: 'flaky.lan' }, {}, NOW);
    const back = mqttStatus(mock, {}, NOW + APPLY_MS);
    expect(back.apply.state).toBe('reverted');
    expect(back.host).toBe('mosquitto');
    expect(integrationAlarms(mock, {}, NOW + APPLY_MS).map((a) => a.code)).toEqual([
      'mqtt_connection_reverted',
    ]);
    expect(mock.audit.map((e) => e.action)).toEqual([
      'mqtt_connection',
      'mqtt_connection_reverted',
    ]);
    mqttTest(mock, { host: 'broker.lan' }, {}, NOW + APPLY_MS);
    expect(integrationAlarms(mock, {}, NOW + APPLY_MS)).toEqual([]);
  });

  it('locks the environment fields and refuses changes while commands are on', () => {
    const mock = initialMqtt();
    const fields = mqttFields(mock, { mqtt: 'env' });
    expect(fields['mqtt_host']?.locked).toBe(true);
    expect(fields['mqtt_host']?.source).toBe('env');
    expect(fields['mqtt_password']?.value).toBe('set');
    expect(fields['heishamon_base']?.locked).toBe(false);
    expect(mqttTest(mock, { host: 'x' }, { mqtt: 'env' }, NOW).status).toBe(422);
    mqttTest(mock, { base: 'other' }, { mqtt: 'commands' }, NOW);
    const refused = mqttApply(mock, { base: 'other' }, { mqtt: 'commands' }, NOW);
    expect(refused.status).toBe(409);
    expect(JSON.stringify(refused.body)).toContain('commands_enabled');
  });

  it('lists stored inputs as signal candidates', () => {
    const signals = makeSignals(NOW, false, [
      { topic: 'garden/temp', unit: '°C' },
      { topic: 'garden/humidity', signal: 'garden_rh', unit: '%' },
    ]);
    expect(signals.room.map((c) => c.signal)).toContain('mqtt/garden/temp');
    expect(signals.room.map((c) => c.signal)).not.toContain('garden_rh');
    expect(signals.liveness.map((c) => c.signal)).toContain('garden_rh');
  });
});
