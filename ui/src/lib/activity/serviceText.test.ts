import { describe, expect, it } from 'vitest';
import { actorText, auditActor, auditDetail } from './audit';
import { dominantReasonRuns } from '$lib/setpoint/series';
import {
  commandDetailText,
  holdIncidentText,
  monitorText,
  serviceMessageText,
  type TextTools,
} from './serviceText';
import { dictionaries } from '$lib/i18n';
import { valueLabelKey } from '$lib/core/signalView';

const tools = (language: 'en' | 'nl'): TextTools => ({
  locale: language,
  say: (key, params = {}) => {
    const text = (dictionaries[language] as Record<string, string>)[key];
    return text?.replace(/\{(\w+)\}/g, (_, name: string) => String(params[name] ?? ''));
  },
});

const monitor = (extra: object) => ({
  code: 'outlet_overshoot',
  severity: 'critical' as const,
  status: 'ok' as const,
  message: 'raw',
  value: 33,
  since: null,
  limit: 45,
  unit: '°C',
  direction: 'above' as const,
  ...extra,
});

describe('monitorText', () => {
  it('composes value and limit in English and Dutch', () => {
    expect(monitorText(monitor({}), tools('en'))).toBe('Outlet 33\u202f°C, limit 45\u202f°C');
    expect(monitorText(monitor({ value: 32.8, limit: 45.5 }), tools('nl'))).toBe(
      'Aanvoer 32,8\u202f°C, grens 45,5\u202f°C',
    );
  });

  it('formats duration limits and handles flags and missing values', () => {
    const silent = monitor({ code: 'room_sensor_silent', value: 3070, limit: 86400, unit: 's' });
    expect(monitorText(silent, tools('en'))).toBe('Last report 51 min ago, limit 1 d');
    const heater = monitor({ code: 'backup_heater', value: 0, limit: null, unit: null });
    expect(monitorText(heater, tools('en'))).toBe('Backup heater is off');
    const none = monitor({ code: 'room_sensor_quiet', value: null, limit: null });
    expect(monitorText(none, tools('nl'))).toBe('Nog geen waarde');
    const idle = monitor({ code: 'low_flow_defrost', value: null, limit: 8, unit: 'l/min' });
    expect(monitorText(idle, tools('en'))).toBe('Not defrosting, minimum 8\u202fl/min');
    expect(monitorText({ ...idle, value: 0.1, status: 'active' }, tools('nl'))).toBe(
      'Debiet tijdens het ontdooien 0,1\u202fl/min, minimaal 8\u202fl/min',
    );
    expect(monitorText(monitor({ code: 'unknown_code' }), tools('en'))).toBe(
      '33\u202f°C, limit 45\u202f°C',
    );
  });
});

describe('serviceMessageText', () => {
  it('translates the known alarm sentences of the service', () => {
    expect(serviceMessageText('outlet 48.2 °C above the 45.0 °C limit', tools('nl'))).toBe(
      'Aanvoerwater 48,2 °C, boven de grens van 45 °C.',
    );
    expect(
      serviceMessageText(
        'Pump_Flow 3.0 l/min with the compressor running (minimum 8.0 l/min)',
        tools('nl'),
      ),
    ).toBe('Doorstroming 3 l/min terwijl de compressor draait (minimaal 8 l/min).');
    expect(
      serviceMessageText(
        'hold 3 within 12 h (foreign writer), latched until an operator releases it',
        tools('nl'),
      ),
    ).toContain('iemand anders heeft de pomp aangepast');
    expect(serviceMessageText('the pump reports error H23', tools('en'))).toBe(
      'The pump reports error H23.',
    );
  });

  it('translates the low-flow-during-defrost sentences', () => {
    expect(
      serviceMessageText(
        'deice mode 2 (hot-gas defrost): the heat pump stops its water pump by design because the return water was 25.5 °C (below 27 °C); Pump_Flow 0.1 l/min, compressor 86 Hz',
        tools('nl'),
      ),
    ).toBe(
      'Ontdooimodus 2 (ontdooien met heet gas): de warmtepomp zet haar waterpomp bewust stil omdat het retourwater 25,5 °C was (onder 27 °C); doorstroming 0,1 l/min, compressor 86 Hz.',
    );
    expect(
      serviceMessageText(
        'deice mode 2 (hot-gas defrost): the heat pump stops its water pump by design because the outdoor air was -12.0 °C (below -10 °C) with return water 45.0 °C (below 60 °C); Pump_Flow 0.1 l/min, compressor 86 Hz',
        tools('nl'),
      ),
    ).toContain('omdat de buitenlucht -12 °C was (onder -10 °C) bij retourwater van 45 °C');
    expect(
      serviceMessageText(
        'low water flow during a defrost (deice mode 1, the pump should run): Pump_Flow 3.0 l/min with the compressor at 42 Hz (minimum 8.0 l/min)',
        tools('nl'),
      ),
    ).toBe(
      'Lage doorstroming tijdens het ontdooien (ontdooimodus 1, de waterpomp hoort te draaien): 3 l/min met de compressor op 42 Hz (minimaal 8 l/min).',
    );
    expect(
      serviceMessageText('suspended during a defrost (see low_flow_defrost)', tools('nl')),
    ).toBe('Gepauzeerd tijdens het ontdooien (zie Geen doorstroming tijdens ontdooien).');
    expect(
      serviceMessageText('Pump_Flow 24.8 l/min during the defrost (deice mode 1)', tools('nl')),
    ).toBe('Doorstroming 24,8 l/min tijdens het ontdooien (ontdooimodus 1).');
    expect(serviceMessageText('Pump_Flow 24.8 l/min during the defrost', tools('en'))).toBe(
      'Flow 24.8 l/min during the defrost.',
    );
    expect(
      serviceMessageText(
        'low water flow during a defrost: Pump_Flow 0.1 l/min with the compressor at 86 Hz (minimum 8.0 l/min); the heat pump slowed or stopped its water pump while defrosting',
        tools('nl'),
      ),
    ).toBe(
      'Lage doorstroming tijdens het ontdooien: 0,1 l/min met de compressor op 86 Hz (minimaal 8 l/min); de warmtepomp liet haar waterpomp tijdens het ontdooien trager draaien of zette hem stil.',
    );
    expect(
      serviceMessageText('logged only from now on (safety_defrost_low_flow)', tools('nl')),
    ).toContain('alleen vastgelegd');
  });

  it('leaves unknown sentences to the caller', () => {
    expect(serviceMessageText('something new', tools('nl'))).toBeNull();
  });
});

describe('hold incidents', () => {
  it('names the incident and the reason', () => {
    const say = tools('en').say;
    expect(holdIncidentText({ reason: 'foreign writer', incident: 2 }, (r) => r, say)).toBe(
      'Hold 2: foreign writer',
    );
    expect(holdIncidentText({}, (r) => r, say)).toBeNull();
  });
});

describe('audit helpers', () => {
  it('writes the actor with a dot and booleans as words', () => {
    expect(auditActor({ actor: 'admin from 192.168.1.20', source_ip: '192.168.1.20' })).toBe(
      'admin · 192.168.1.20',
    );
    expect(auditActor({ actor: 'ingress user', source_ip: null })).toBe('ingress user');
    expect(actorText('admin from 192.0.2.10')).toBe('admin · 192.0.2.10');
    expect(actorText('Home Assistant user')).toBe('Home Assistant user');
    expect(actorText(null)).toBe('');
    const detail = auditDetail(
      {
        at: '',
        actor: '',
        source_ip: null,
        action: 'config_apply',
        detail: { changed: [{ field: 'x', from: false, to: 21.6 }] },
      },
      {
        version: String,
        rollbackTo: String,
        field: (id) => id,
        bool: (v) => (v ? 'aan' : 'uit'),
        number: (v) => String(v).replace('.', ','),
      },
    );
    expect(detail).toBe('x uit → 21,6');
    const connection = auditDetail(
      {
        at: '',
        actor: '',
        source_ip: null,
        action: 'ha_connection',
        detail: { changed: ['ha_token', 'ha_url'], url: 'http://ha:8123', token: 'set' },
      },
      { version: String, rollbackTo: String, field: (id) => `<${id}>` },
    );
    expect(connection).toBe('<ha_token> · <ha_url> · http://ha:8123');
  });
});

describe('dominantReasonRuns', () => {
  it('picks the dominant category per hour and merges equal hours', () => {
    const h = 3_600_000;
    const reasons = [
      { from: 0, to: 40 * 60_000, reason: 'defrost_freeze' },
      { from: 40 * 60_000, to: h + 10 * 60_000, reason: 'deadband_hold' },
      { from: h + 10 * 60_000, to: 3 * h, reason: 'deadband_hold' },
    ];
    const runs = dominantReasonRuns(reasons, 0, 3 * h);
    expect(runs.length).toBeGreaterThanOrEqual(2);
    expect(runs[0]?.from).toBe(0);
    expect(runs[runs.length - 1]?.to).toBe(3 * h);
    expect(new Set(runs.map((r) => r.state)).size).toBe(2);
  });
});

describe('valueLabelKey', () => {
  it('normalises pump labels', () => {
    expect(valueLabelKey('No error')).toBe('sigval_no_error');
    expect(valueLabelKey('max_flow')).toBe('sigval_max_flow');
  });
});

describe('command details', () => {
  const reason = (code: string) => (code === 'foreign writer' ? 'vreemde schrijver' : code);
  it('translates the known service phrases and leaves the rest alone', () => {
    const say = tools('nl').say;
    expect(commandDetailText('hold: foreign writer', say, reason)).toBe(
      'niet verstuurd: blokkade (vreemde schrijver)',
    );
    expect(
      commandDetailText('published to panasonic_heat_pump/commands/SetCurves', say, reason),
    ).toBe('verstuurd naar panasonic_heat_pump/commands/SetCurves');
    expect(commandDetailText('not applied after 2 attempts, pump reports 31', say, reason)).toBe(
      'niet doorgevoerd na 2 pogingen, de pomp meldt 31',
    );
    expect(commandDetailText('defrost: the pump sets its own duty; not sent', say, reason)).toBe(
      'niet verstuurd: tijdens het ontdooien regelt de pomp zelf de pompsnelheid',
    );
    expect(commandDetailText('superseded: the controller now wants 30', say, reason)).toBeNull();
  });
});
