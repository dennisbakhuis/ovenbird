import type { CommandEvent, PumpSetting, PumpSettingsResponse } from '../src/lib/core/types';

const iso = (ms: number) => new Date(ms).toISOString();

interface Pending {
  id: string;
  from: number | null;
  to: number;
  at: number;
}

export interface PumpState {
  values: Record<string, number>;
  pending: Pending | null;
  last: Record<string, { at: number; from: number | null; to: number }>;
}

export const initialPumpState = (now = Date.now()): PumpState => ({
  values: { heat_delta: 5, pump_flowrate_mode: 0, heating_off_outdoor: 18 },
  pending: null,
  last: { heat_delta: { at: now - 26 * 3_600_000, from: 4, to: 5 } },
});

const WRITABLE: Record<string, { min: number; max: number; command: string; signal: string }> = {
  heat_delta: { min: 3, max: 10, command: 'SetFloorHeatDelta', signal: 'main/Heat_Delta' },
  pump_flowrate_mode: {
    min: 0,
    max: 1,
    command: 'SetPumpFlowrateMode',
    signal: 'main/Pump_Flowrate_Mode',
  },
  heating_off_outdoor: {
    min: 10,
    max: 35,
    command: 'SetHeatingOffOutdoorTemp',
    signal: 'main/Heating_Off_Outdoor_Temp',
  },
};

const FLOW_LABELS = ['delta_t', 'max_flow'];

function progress(state: PumpState, now: number): 'queued' | 'sent' | 'verified' | null {
  const pending = state.pending;
  if (!pending) return null;
  const elapsed = now - pending.at;
  return elapsed < 1500 ? 'queued' : elapsed < 3500 ? 'sent' : 'verified';
}

function settle(state: PumpState, now: number): void {
  if (progress(state, now) !== 'verified' || !state.pending) return;
  const { id, to, from, at } = state.pending;
  state.values[id] = to;
  state.last[id] = { at, from, to };
  state.pending = null;
}

const UNITS: Record<string, string | null> = {
  heat_delta: 'K',
  pump_flowrate_mode: null,
  heating_off_outdoor: '°C',
};

interface ReadSpec {
  id: string;
  signal: string;
  owner: PumpSetting['owner'];
  unit?: string | null;
  value: number | null;
  labels?: string[];
}

const READ: ReadSpec[] = [
  { id: 'max_pump_duty', signal: 'main/Max_Pump_Duty', owner: 'controller', value: 159 },
  {
    id: 'quiet_mode_level',
    signal: 'main/Quiet_Mode_Level',
    owner: 'controller',
    value: 1,
    labels: ['off', 'level_1', 'level_2', 'level_3'],
  },
  {
    id: 'quiet_mode_priority',
    signal: 'main/Quiet_Mode_Priority',
    owner: 'operator',
    value: 0,
    labels: ['sound', 'capacity'],
  },
  {
    id: 'powerful_mode_time',
    signal: 'main/Powerful_Mode_Time',
    owner: 'operator',
    value: 0,
    labels: ['off', '30_min', '60_min', '90_min'],
  },
  {
    id: 'heating_control',
    signal: 'main/Heating_Control',
    owner: 'operator',
    value: 0,
    labels: ['comfort', 'efficiency'],
  },
  {
    id: 'heater_on_outdoor',
    signal: 'main/Heater_On_Outdoor_Temp',
    owner: 'operator',
    unit: '°C',
    value: -5,
  },
  {
    id: 'heater_delay_time',
    signal: 'main/Heater_Delay_Time',
    owner: 'operator',
    unit: 'min',
    value: null,
  },
  {
    id: 'heater_start_delta',
    signal: 'main/Heater_Start_Delta',
    owner: 'operator',
    unit: 'K',
    value: null,
  },
  {
    id: 'heater_stop_delta',
    signal: 'main/Heater_Stop_Delta',
    owner: 'operator',
    unit: 'K',
    value: null,
  },
  {
    id: 'room_heater_state',
    signal: 'main/Room_Heater_State',
    owner: 'operator',
    value: 0,
    labels: ['blocked', 'free'],
  },
  {
    id: 'heating_mode',
    signal: 'main/Heating_Mode',
    owner: 'operator',
    value: 1,
    labels: ['compensation_curve', 'direct'],
  },
  {
    id: 'z1_curve_target_high',
    signal: 'main/Z1_Heat_Curve_Target_High_Temp',
    owner: 'operator',
    unit: '°C',
    value: null,
  },
  {
    id: 'z1_curve_target_low',
    signal: 'main/Z1_Heat_Curve_Target_Low_Temp',
    owner: 'operator',
    unit: '°C',
    value: null,
  },
  {
    id: 'z1_curve_outside_high',
    signal: 'main/Z1_Heat_Curve_Outside_High_Temp',
    owner: 'operator',
    unit: '°C',
    value: null,
  },
  {
    id: 'z1_curve_outside_low',
    signal: 'main/Z1_Heat_Curve_Outside_Low_Temp',
    owner: 'operator',
    unit: '°C',
    value: null,
  },
  {
    id: 'operating_mode_state',
    signal: 'main/Operating_Mode_State',
    owner: 'pump',
    value: 0,
    labels: ['heat'],
  },
  { id: 'zones_state', signal: 'main/Zones_State', owner: 'pump', value: null },
  { id: 'pump_duty', signal: 'main/Pump_Duty', owner: 'pump', value: null },
  { id: 'pump_flow', signal: 'main/Pump_Flow', owner: 'pump', unit: 'l/min', value: null },
  { id: 'internal_heater_state', signal: 'main/Internal_Heater_State', owner: 'pump', value: null },
  { id: 'error', signal: 'main/Error', owner: 'pump', value: null },
];

const KNOWN_MODEL = '32 D4 0B 88 84 73 90 0C 85 84';
const KNOWN_PROFILE = {
  name: 'WH-MXC12J9E8',
  source:
    'Panasonic service manual PAPAMY2110029CE (WH-MXC09J3E8/WH-MXC12J9E8), 14.2.2 Deice Operation',
};

/**
 * `GET pump/settings` as the service answers it: the three writable rows first, then the
 * read-only ones in the service's order. Rows the model does not report are `supported: false`
 * with `value`/`age` null and `fresh` false. `label` is the catalogue meaning, not translated.
 * With `known` the model is the WH-MXC12J9E8 and its profile is named (scenario `deice`).
 */
export function pumpSettings(
  state: PumpState,
  now: number,
  paused: boolean,
  known = false,
): PumpSettingsResponse {
  settle(state, now);
  const phase = progress(state, now);
  const settings: PumpSetting[] = Object.entries(WRITABLE).map(([id, spec]) => {
    const value = state.values[id] ?? null;
    const pending = state.pending?.id === id ? state.pending : null;
    const last = state.last[id];
    return {
      id,
      signal: spec.signal,
      value,
      unit: UNITS[id] ?? null,
      label: id === 'pump_flowrate_mode' && value !== null ? (FLOW_LABELS[value] ?? null) : null,
      fresh: true,
      age: 12.0,
      supported: true,
      access: 'write',
      owner: 'operator',
      command: spec.command,
      min: spec.min,
      max: spec.max,
      last_write: pending
        ? {
            at: iso(pending.at),
            by: 'admin from 127.0.0.1',
            from: pending.from,
            to: pending.to,
            status: phase ?? 'queued',
          }
        : last
          ? {
              at: iso(last.at),
              by: 'admin from 192.168.1.20',
              from: last.from,
              to: last.to,
              status: 'verified',
            }
          : null,
    };
  });
  for (const row of READ) {
    const supported = row.value !== null;
    settings.push({
      id: row.id,
      signal: row.signal,
      value: row.value,
      unit: row.unit ?? null,
      label: row.value !== null ? (row.labels?.[row.value] ?? null) : null,
      fresh: supported,
      age: supported ? 40.0 : null,
      supported,
      access: 'read',
      owner: row.owner,
    });
  }
  const inFlight = state.pending !== null;
  const refusals = paused
    ? ['control is paused']
    : inFlight
      ? [`a write of ${state.pending?.id} is in progress`]
      : [];
  return {
    writable: refusals.length === 0,
    refusals,
    model: known ? KNOWN_MODEL : 'C2 D3 0B 33 65 B2 D3 0B 94 65',
    profile: known ? KNOWN_PROFILE : null,
    settings,
  };
}

/**
 * `POST pump/settings/{id}` as the service answers it: `202 {command}` or a refusal
 * `{"detail": {code, message, params}}`, checked in the service's order.
 */
export function writeSetting(
  state: PumpState,
  id: string,
  body: Record<string, unknown>,
  now: number,
  paused: boolean,
): { status: number; body: unknown } {
  settle(state, now);
  const spec = WRITABLE[id];
  const error = (
    status: number,
    code: string,
    message: string,
    params: Record<string, unknown> = {},
  ) => ({ status, body: { detail: { code, message, params } } });
  if (!spec) return error(404, 'unknown_setting', `'${id}' is not a writable pump setting`);
  const comment = body['comment'];
  if (
    comment !== undefined &&
    comment !== null &&
    (typeof comment !== 'string' || comment.length > 200)
  )
    return error(400, 'bad_comment', 'comment must be a string of at most 200 characters');
  const value = body['value'];
  if (typeof value !== 'number' || !Number.isInteger(value))
    return error(422, 'not_an_integer', 'value must be an integer');
  if (value < spec.min || value > spec.max)
    return error(422, 'out_of_range', `${id} must lie within [${spec.min}, ${spec.max}]`, {
      min: spec.min,
      max: spec.max,
    });
  const expect = body['expect'];
  if (typeof expect !== 'number' || !Number.isInteger(expect))
    return error(422, 'expect_required', 'expect must be the reported value');
  if (paused) return error(409, 'not_publishing', 'control is paused');
  const current = state.values[id] ?? null;
  if (expect !== current)
    return error(409, 'value_changed', `the pump reports ${current}, not ${expect}`, {
      reported: current,
    });
  if (value === current) return error(409, 'unchanged', `the pump already reports ${value}`);
  if (state.pending)
    return error(409, 'in_flight', `a write of ${state.pending.id} is still in progress`);
  state.pending = { id, from: current, to: value, at: now };
  const note = typeof comment === 'string' && comment.trim() ? ` (${comment.trim()})` : '';
  const command: CommandEvent = {
    at: iso(now),
    kind: id,
    value,
    status: 'queued',
    attempt: 0,
    detail: `operator: admin from 127.0.0.1: ${id} ${current} → ${value}${note}`,
    topic: `panasonic_heat_pump/commands/${spec.command}`,
    payload: String(value),
  };
  return { status: 202, body: { command } };
}
