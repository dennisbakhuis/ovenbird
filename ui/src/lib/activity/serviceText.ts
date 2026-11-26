import { clockNow, formatDuration, UNIT_SPACE } from '$lib/core/format';
import type { MonitorWithLimit } from './monitors';

export interface TextTools {
  say: (key: string, params?: Record<string, string | number>) => string | undefined;
  locale: string;
}

const DURATION_UNITS = new Set(['s', 'sec', 'seconds']);

function amount(value: number, unit: string | null | undefined, locale: string): string {
  if (unit && DURATION_UNITS.has(unit)) return formatDuration(value);
  const text = new Intl.NumberFormat(locale, {
    minimumFractionDigits: Number.isInteger(value) ? 0 : 1,
    maximumFractionDigits: 1,
  }).format(value);
  return unit ? `${text}${UNIT_SPACE}${unit}` : text;
}

/**
 * One readable sentence for a monitor, composed from its code, value, limit and unit; null when
 * nothing sensible can be said (the caller then falls back to the service's own message).
 */
export function monitorText(
  monitor: MonitorWithLimit,
  tools: TextTools,
  nowMs = clockNow(),
): string | null {
  const { say, locale } = tools;
  const { code, value, limit, unit } = monitor;
  if (code === 'defrost_stuck' && typeof limit === 'number') {
    const since = monitor.since ? Date.parse(monitor.since) : NaN;
    const limitText = amount(limit, unit, locale);
    if (monitor.status === 'ok' || !Number.isFinite(since)) {
      return say('monDefrostIdle', { limit: limitText }) ?? null;
    }
    const elapsed = formatDuration(Math.max(0, (nowMs - since) / 1000));
    return say('monDefrostRunning', { elapsed, limit: limitText }) ?? null;
  }
  const idle = monitor.status === 'ok' && typeof value !== 'number';
  if (code === 'low_flow_defrost' && idle && typeof limit === 'number') {
    return say('monFlowDefrostIdle', { limit: amount(limit, unit, locale) }) ?? null;
  }
  if (typeof value === 'number' && !Number.isFinite(value)) return null;
  if (typeof value === 'number' && typeof limit === 'number') {
    return (
      say(`mon_${code}`, {
        value: amount(value, unit, locale),
        limit: amount(limit, unit, locale),
      }) ??
      say('monGeneric', {
        value: amount(value, unit, locale),
        limit: amount(limit, unit, locale),
      }) ??
      null
    );
  }
  if (typeof value === 'number') {
    return say(`mon_${code}_${value ? 'on' : 'off'}`) ?? null;
  }
  if (typeof value === 'string' && value) {
    return say(`mon_${code}_${monitor.status === 'ok' ? 'ok' : 'text'}`, { value }) ?? null;
  }
  if (value === null || value === undefined) return say('monNoReading') ?? null;
  return null;
}

/**
 * Hold incident text from the journal detail (incident number and reason).
 */
export function holdIncidentText(
  detail: Record<string, unknown>,
  reasonName: (reason: string) => string,
  say: TextTools['say'],
): string | null {
  const reason = typeof detail['reason'] === 'string' ? detail['reason'] : null;
  const incident = typeof detail['incident'] === 'number' ? detail['incident'] : null;
  if (reason === null) return null;
  const name = reasonName(reason);
  if (incident === null) return name;
  return say('holdIncidentText', { n: incident, reason: name }) ?? name;
}

const COMMAND_DETAILS: [RegExp, string, (match: RegExpExecArray) => Record<string, string>][] = [
  [/^queued$/, 'cmdDetailQueued', () => ({})],
  [/^published to (\S+)$/, 'cmdDetailPublished', (m) => ({ topic: m[1] ?? '' })],
  [/^applied in (\d+) s$/, 'cmdDetailApplied', (m) => ({ time: formatDuration(Number(m[1])) })],
  [/^hold: (.+)$/, 'cmdDetailHold', (m) => ({ reason: m[1] ?? '' })],
  [
    /^not applied after (\d+) attempts, pump reports (\S+)$/,
    'cmdDetailFailedAfter',
    (m) => ({ n: m[1] ?? '', value: m[2] ?? '' }),
  ],
  [/^not applied, pump reports (\S+)$/, 'cmdDetailNotApplied', (m) => ({ value: m[1] ?? '' })],
  [/^control is paused$/, 'cmdDetailPaused', () => ({})],
  [/^defrost: the pump sets its own duty; not sent$/, 'cmdDetailDefrostDuty', () => ({})],
];

/**
 * A command journal detail ("published to …", "hold: foreign writer") in the UI language; null
 * when the text is not one of the known service phrases (the caller then shows it as sent).
 */
export function commandDetailText(
  detail: string,
  say: TextTools['say'],
  reasonName: (reason: string) => string,
): string | null {
  for (const [pattern, key, params] of COMMAND_DETAILS) {
    const match = pattern.exec(detail);
    if (!match) continue;
    const values = params(match);
    if (values['reason'] !== undefined) values['reason'] = reasonName(values['reason']);
    return say(key, values) ?? null;
  }
  return null;
}

const NUM = String.raw`(-?\d+(?:\.\d+)?)`;

const SERVICE_MESSAGES: [RegExp, string, string[]][] = [
  [
    new RegExp(String.raw`^outlet ${NUM} °C above the ${NUM} °C limit$`),
    'svc_outlet_over',
    ['value', 'limit'],
  ],
  [
    new RegExp(String.raw`^Main_Outlet_Temp ${NUM} °C against a limit of ${NUM} °C$`),
    'svc_outlet_over',
    ['value', 'limit'],
  ],
  [
    new RegExp(String.raw`^\S+ is ${NUM} °C, above the maximum supply of ${NUM} °C$`),
    'svc_setpoint_over',
    ['value', 'limit'],
  ],
  [
    new RegExp(
      String.raw`^Pump_Flow ${NUM} l/min with the compressor running \(minimum ${NUM} l/min\)$`,
    ),
    'svc_low_flow',
    ['value', 'limit'],
  ],
  [
    new RegExp(
      String.raw`^low water flow during a defrost \(deice mode 1, the pump should run\): Pump_Flow ${NUM} l/min with the compressor at ${NUM} Hz \(minimum ${NUM} l/min\)$`,
    ),
    'svc_low_flow_defrost',
    ['value', 'freq', 'limit'],
  ],
  [
    new RegExp(
      String.raw`^deice mode 2 \(hot-gas defrost\): the heat pump stops its water pump by design because the return water was ${NUM} °C \(below ${NUM} °C\); Pump_Flow ${NUM} l/min, compressor ${NUM} Hz$`,
    ),
    'svc_deice_mode2_inlet',
    ['inlet', 'limit', 'value', 'freq'],
  ],
  [
    new RegExp(
      String.raw`^deice mode 2 \(hot-gas defrost\): the heat pump stops its water pump by design because the outdoor air was ${NUM} °C \(below ${NUM} °C\) with return water ${NUM} °C \(below ${NUM} °C\); Pump_Flow ${NUM} l/min, compressor ${NUM} Hz$`,
    ),
    'svc_deice_mode2_cold',
    ['outside', 'cold', 'inlet', 'limit', 'value', 'freq'],
  ],
  [
    new RegExp(
      String.raw`^low water flow during a defrost: Pump_Flow ${NUM} l/min with the compressor at ${NUM} Hz \(minimum ${NUM} l/min\); the heat pump slowed or stopped its water pump while defrosting$`,
    ),
    'svc_low_flow_defrost_generic',
    ['value', 'freq', 'limit'],
  ],
  [/^suspended during a defrost \(see low_flow_defrost\)$/, 'svc_low_flow_suspended', []],
  [
    new RegExp(String.raw`^Pump_Flow ${NUM} l/min during the defrost \(deice mode (1|2)\)$`),
    'svc_defrost_flow_mode',
    ['value', 'mode'],
  ],
  [
    new RegExp(String.raw`^Pump_Flow ${NUM} l/min during the defrost$`),
    'svc_defrost_flow',
    ['value'],
  ],
  [/^no defrost running$/, 'svc_no_defrost', []],
  [/^logged only from now on \(safety_defrost_low_flow\)$/, 'svc_flow_defrost_logged', []],
  [/^raised as an alarm from now on \(safety_defrost_low_flow\)$/, 'svc_flow_defrost_alarm', []],
  [/^the pump reports error (.+)$/, 'svc_pump_error', ['text']],
  [/^backup heater running \((.+)\); it heats at COP 1$/, 'svc_backup_heater', ['text']],
  [
    /^Room_Heater_State is free: the pump may use its backup heater for heating$/,
    'svc_backup_allowed',
    [],
  ],
  [
    new RegExp(
      String.raw`^Outside_Temp ${NUM} °C against the pump's heating cut-off of ${NUM} °C$`,
    ),
    'svc_heating_off',
    ['value', 'limit'],
  ],
  [new RegExp(String.raw`^defrost running \(limit ${NUM} min\)$`), 'svc_defrost', ['limit']],
  [
    new RegExp(String.raw`^room ${NUM} °C against a comfort floor of ${NUM} °C$`),
    'svc_room_floor',
    ['value', 'limit'],
  ],
  [/^room back above the comfort floor$/, 'svc_room_floor_ok', []],
  [
    new RegExp(
      String.raw`^no report from the room sensor or its liveness signals for ${NUM} min \(limit ${NUM} min\)$`,
    ),
    'svc_room_silent',
    ['value', 'limit'],
  ],
  [
    new RegExp(
      String.raw`^periodic room sensor profile configured but no report.* for ${NUM} min \(limit ${NUM} min\)$`,
    ),
    'svc_room_overdue',
    ['value', 'limit'],
  ],
  [/^Home Assistant link down/, 'svc_ha_down', []],
  [/^(.+) unknown or stale$/, 'svc_unknown', ['what']],
  [
    /^hold (\d+) within (\d+) h \((.+)\), latched until an operator releases it$/,
    'svc_hold_latched',
    ['n', 'hours', 'reason'],
  ],
];

/**
 * A known English alarm or monitor sentence of the service in the UI language ("outlet 48.2 °C
 * above the 45.0 °C limit" reads "aanvoer 48,2 °C, boven de grens van 45 °C"); null when the
 * sentence is not one the UI knows (the caller then shows it as the service wrote it).
 */
export function serviceMessageText(message: string, tools: TextTools): string | null {
  const { say, locale } = tools;
  for (const [pattern, key, names] of SERVICE_MESSAGES) {
    const match = pattern.exec(message.trim());
    if (!match) continue;
    const params: Record<string, string> = {};
    names.forEach((name, i) => {
      const raw = match[i + 1] ?? '';
      const value = Number(raw);
      params[name] =
        /^-?\d+(\.\d+)?$/.test(raw) && Number.isFinite(value) ? amount(value, null, locale) : raw;
    });
    if (params['reason'] !== undefined)
      params['reason'] = say(`holdWhy_${params['reason']}`) ?? params['reason'];
    return say(key, params) ?? null;
  }
  return null;
}
