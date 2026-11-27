import { asCurve, curveWater, type Curve } from '../src/lib/core/curve.ts';
import { checkField } from '../src/lib/core/schema.ts';
import type {
  ConfigDoc,
  ConfigField,
  ConfigSchema,
  ConfigSignals,
  ConfigVersion,
  DecisionRecord,
  PreviewResult,
  ValidateResult,
  ValidationIssue,
  VersionChange,
} from '../src/lib/core/types';
import baseConfig from './fixtures/config.json' with { type: 'json' };
import schemaJson from './fixtures/schema.json' with { type: 'json' };
import { buildRecord, makeSeries, roomFacts } from './decisions.ts';
import { OUTSIDE_SIGNAL, OUTSIDE_STALE_S } from './integrations.ts';

export const schema = schemaJson as unknown as ConfigSchema;

const HOUR = 3_600_000;
const DAY_MS = 24 * HOUR;
const MOCK_VERSION = 12;
const ROOM_KP = 1.2;

export interface ConfigState {
  version: number;
  updatedAt: string;
  updatedBy: string;
  stored: Record<string, unknown>;
  versions: ConfigVersion[];
  ha: { url: string | null; token: string | null };
}

type Values = Record<string, unknown>;

const ENV_LOCKED: Record<string, unknown> = { control_min_setpoint_c: 24 };
const HA_CONNECTION = new Set(['ha_url', 'ha_token']);
/** The broker fields: set with `config/mqtt`, per browser (see `integrations.ts`). */
export const MQTT_CONNECTION = new Set([
  'mqtt_host',
  'mqtt_port',
  'mqtt_username',
  'mqtt_password',
  'mqtt_tls',
  'mqtt_ca_file',
  'mqtt_client_id',
  'heishamon_base',
]);
const CONNECTION = new Set([...HA_CONNECTION, ...MQTT_CONNECTION]);
/** Fields the dev-stack fixture sets from the environment that the mock leaves editable. */
const UNLOCKED = new Set([...MQTT_CONNECTION, 'mqtt_inputs']);

/** The mock's stored Home Assistant connection. */
export const MOCK_HA_URL = 'http://homeassistant.local:8123';
export const MOCK_HA_TOKEN = 'mock-long-lived-token';
/** A token the mock's Home Assistant rejects. */
export const MOCK_BAD_TOKEN = 'wrong-token';
/** A host the mock's Home Assistant cannot be reached at. */
export const MOCK_UNREACHABLE_HOST = 'unreachable.local';

const raw = baseConfig as unknown as ConfigDoc;
const base: ConfigDoc = {
  ...raw,
  fields: Object.fromEntries(
    Object.entries(raw.fields).map(([id, field]) => [
      id,
      id in ENV_LOCKED
        ? { ...field, value: ENV_LOCKED[id], source: 'env', locked: true, stored: field.stored }
        : UNLOCKED.has(id)
          ? { ...field, source: 'default', locked: false, stored: null }
          : field,
    ]),
  ),
};

function storedOf(doc: ConfigDoc): Values {
  const out: Values = {};
  for (const [id, field] of Object.entries(doc.fields)) {
    if (field.stored !== null && field.stored !== undefined && !field.locked && !CONNECTION.has(id))
      out[id] = field.stored;
  }
  return out;
}

function history(stored: Values, now: number): ConfigVersion[] {
  const at = (hoursAgo: number) => new Date(now - hoursAgo * HOUR).toISOString();
  const v = (
    version: number,
    hoursAgo: number,
    comment: string,
    changed: VersionChange[],
    values: Values,
  ): ConfigVersion => ({
    version,
    created_at: at(hoursAgo),
    actor: 'admin from 192.168.1.20',
    origin: 'ui',
    comment,
    applied_at: at(hoursAgo),
    changed,
    values,
  });
  const v9 = { ...stored, control_comfort_c: 21.0 };
  const v10 = { ...stored, control_comfort_c: 21.4 };
  const v11 = { ...stored, control_comfort_c: 21.0, control_dwell_s: 1200 };
  const noDwell = { ...stored };
  return [
    {
      ...v(1, 24 * 14, 'Seed from the dev stack', [], { control_emitter: 'mixed' }),
      origin: 'seed',
      actor: 'system',
    },
    v(9, 24 * 6, 'Comfort 21', [{ field: 'control_comfort_c', from: null, to: 21 }], v9),
    v(10, 24 * 3, 'A bit warmer', [{ field: 'control_comfort_c', from: 21, to: 21.4 }], v10),
    v(
      11,
      30,
      'Longer wait time',
      [
        { field: 'control_comfort_c', from: 20.6, to: 21.0 },
        { field: 'control_dwell_s', from: null, to: 1200 },
      ],
      v11,
    ),
    v(
      12,
      7,
      'Back to the preset wait time',
      [{ field: 'control_dwell_s', from: 1200, to: null }],
      noDwell,
    ),
  ];
}

/**
 * Stored house settings of the `house:facts` scenario: facts, a heat-loss limit and a left-out day.
 */
export function houseFactsStored(now = Date.now()): Values {
  return {
    house_build_period: '1975_1991',
    house_occupants: 3,
    house_ua_min_w_per_k: 200,
    house_ua_max_w_per_k: 300,
    house_learn_excluded_days: [new Date(now - 9 * DAY_MS).toISOString().slice(0, 10)],
  };
}

/**
 * Stored house settings of the `house:pin-cost` scenario: the heat loss pinned to one value.
 */
export function housePinStored(): Values {
  return { house_ua_min_w_per_k: 300, house_ua_max_w_per_k: 300 };
}

export function initialConfigState(now = Date.now(), extra: Values = {}): ConfigState {
  const stored = {
    ...storedOf(base),
    weather_enabled: true,
    control_stove_enabled: true,
    control_quiet_windows: [{ start: '22:00', end: '07:00', level: 2 }],
    house_floor_area_m2: 150,
    mqtt_inputs: raw.fields['mqtt_inputs']?.value ?? [],
    ...extra,
  };
  return {
    version: MOCK_VERSION,
    updatedAt: base.updated_at ?? new Date(now).toISOString(),
    updatedBy: base.updated_by ?? 'admin',
    stored,
    versions: history(stored, now),
    ha: { url: MOCK_HA_URL, token: MOCK_HA_TOKEN },
  };
}

function presetFor(emitter: string, id: string): unknown {
  return schema.presets[emitter]?.[id];
}

function effective(state: ConfigState): Record<string, ConfigField> {
  const emitter = String(state.stored['control_emitter'] ?? 'mixed');
  const out: Record<string, ConfigField> = {};
  for (const [id, field] of Object.entries(base.fields)) {
    const def = schema.fields[id];
    const preset = def?.preset_default ? presetFor(emitter, id) : undefined;
    const dflt = preset !== undefined ? preset : field.default;
    if (field.locked) {
      out[id] = { ...field };
      continue;
    }
    if (HA_CONNECTION.has(id)) {
      out[id] = connectionField(state, id);
      continue;
    }
    if (MQTT_CONNECTION.has(id)) {
      out[id] = { ...field };
      continue;
    }
    const stored = state.stored[id];
    const has = stored !== undefined;
    out[id] = {
      value: has ? stored : dflt,
      source: has ? 'store' : preset !== undefined ? 'preset' : 'default',
      locked: false,
      stored: has ? stored : null,
      default: dflt,
    };
  }
  return out;
}

function connectionField(state: ConfigState, id: string): ConfigField {
  const raw = id === 'ha_url' ? state.ha.url : state.ha.token;
  const shown = id === 'ha_token' ? (raw ? 'set' : 'unset') : raw;
  return {
    value: shown,
    source: raw ? 'store' : 'default',
    locked: false,
    stored: raw ? (id === 'ha_token' ? 'set' : raw) : null,
    default: null,
  };
}

/**
 * The `hot_water` part of the config document: the stored setting (`auto` unless `on` or `off`),
 * the pump's report of a tank and whether hot water shows (`on`; `auto` unless the pump reports
 * no tank).
 */
export function hotWaterState(setting: unknown, installed: boolean | null): ConfigDoc['hot_water'] {
  const value = setting === 'on' || setting === 'off' ? setting : 'auto';
  return {
    setting: value,
    installed,
    shown: value === 'on' || (value === 'auto' && installed !== false),
  };
}

export function configDoc(state: ConfigState, paused: boolean): ConfigDoc {
  const fields = effective(state);
  return {
    version: state.version,
    applied_version: state.version,
    updated_at: state.updatedAt,
    updated_by: state.updatedBy,
    mode: {
      configured: 'auto',
      effective: paused ? 'shadow' : 'auto',
      paused,
      reset_pending: false,
    },
    reset_pending: false,
    fields,
    hot_water: hotWaterState(fields['hot_water']?.value, true),
  };
}

function merge(state: ConfigState, changes: Values): Record<string, ConfigField> {
  const next = { ...state.stored };
  for (const [id, value] of Object.entries(changes)) {
    if (value === null) delete next[id];
    else next[id] = value;
  }
  return effective({ ...state, stored: next });
}

const sorted = (days: unknown[]): unknown[] => [...days].sort();

const BOUND_PAIRS = [
  ['house_ua_min_w_per_k', 'house_ua_max_w_per_k'],
  ['house_time_constant_min_h', 'house_time_constant_max_h'],
  ['house_solar_aperture_min_m2', 'house_solar_aperture_max_m2'],
  ['house_internal_gain_min_w', 'house_internal_gain_max_w'],
] as const;

/**
 * The service's date rules of the left-out days: a real `YYYY-MM-DD`, at most a day ahead, once.
 */
function dayProblem(days: unknown[], nowMs: number): string | null {
  const latest = new Date(nowMs + DAY_MS).toISOString().slice(0, 10);
  const seen = new Set<unknown>();
  for (const day of days) {
    if (
      typeof day !== 'string' ||
      !/^\d{4}-\d{2}-\d{2}$/.test(day) ||
      Number.isNaN(Date.parse(`${day}T00:00:00Z`)) ||
      new Date(`${day}T00:00:00Z`).toISOString().slice(0, 10) !== day
    )
      return 'date_format';
    if (day > latest) return 'date_future';
    if (seen.has(day)) return 'date_repeated';
    seen.add(day);
  }
  return null;
}

const CLIENT_TO_SERVER: Record<string, string> = {
  not_a_number: 'type',
  not_integer: 'type',
  not_an_option: 'not_allowed',
  not_a_curve: 'type',
  not_windows: 'type',
  too_many_windows: 'too_many',
  curve_too_few_points: 'curve_points',
  curve_too_many_points: 'curve_points',
  curve_not_finite: 'curve_points',
  curve_outside_not_increasing: 'curve_order',
  curve_water_increases: 'curve_order',
  curve_outside_out_of_range: 'curve_outside_range',
  curve_water_out_of_range: 'curve_range',
  not_mqtt_inputs: 'type',
  mqtt_inputs_invalid: 'invalid',
};

function curveShift(state: ConfigState, value: unknown): { shift_k: number; at: number } {
  const before = asCurve(effective(state)['control_curve']?.value) ?? [];
  const after = asCurve(value) ?? [];
  let worst = { shift_k: 0, at: -15 };
  for (let at = -15; at <= 20; at += 1) {
    const shift = curveWater(after, at) - curveWater(before, at);
    if (Math.abs(shift) > Math.abs(worst.shift_k))
      worst = { shift_k: Math.round(shift * 100) / 100, at };
  }
  return worst;
}

export function validate(state: ConfigState, changes: Values): ValidateResult {
  const errors: ValidationIssue[] = [];
  const warnings: ValidationIssue[] = [];
  const active = configDoc(state, false);
  const issue = (
    field: string | null,
    code: string,
    message: string,
    params: Record<string, unknown> = {},
  ): ValidationIssue => ({ field, code, message, params });
  for (const [id, value] of Object.entries(changes)) {
    const known = active.fields[id];
    const def = schema.fields[id];
    if (!known || !def) {
      errors.push(issue(id, 'unknown_field', `${id} is not a settings field`));
      continue;
    }
    if (CONNECTION.has(id)) {
      const where = HA_CONNECTION.has(id) ? 'config/ha' : 'config/mqtt';
      errors.push(issue(id, 'connection_field', `${id} is set with PUT api/v1/${where}`));
      continue;
    }
    if (def.editable === false) {
      errors.push(issue(id, 'not_editable', `${id} cannot be changed here`));
      continue;
    }
    if (known.locked) {
      errors.push(
        issue(id, 'locked', `${id} is set by ${def.env}`, { source: known.source, env: def.env }),
      );
      continue;
    }
    if (value === null) continue;
    const result = checkField(schema, id, value, active);
    if (result.error) {
      const code = CLIENT_TO_SERVER[result.error] ?? result.error;
      const params =
        code === 'outside_envelope' ? { at: [5], by_k: [1] } : { min: def.min, max: def.max };
      errors.push(issue(id, code, `${id}: ${code}`, params));
    }
    if (result.warning === 'below_soft_min' || result.warning === 'above_soft_max') {
      warnings.push(
        issue(id, result.warning, `${id} ${String(value)} is outside the usual range`, {
          value,
          soft_min: def.soft_min,
          soft_max: def.soft_max,
        }),
      );
    } else if (result.warning === 'curve_shift_large') {
      warnings.push(
        issue(id, 'curve_shift_large', 'the curve moves by more than 3 K', {
          ...curveShift(state, value),
          limit_k: 3,
        }),
      );
    }
  }
  const after = merge(state, changes);
  if (
    changes['control_cycling_enabled'] === false &&
    active.fields['control_cycling_enabled']?.value === true &&
    !errors.length
  )
    warnings.push(
      issue('control_cycling_enabled', 'cycling_disabled', 'the pump may stop early in a run'),
    );
  if (changes['control_model_use'] === 'on' && !errors.some((e) => e.field === 'control_model_use'))
    errors.push(
      issue('control_model_use', 'model_use_on_locked', 'control_model_use on is locked for now'),
    );
  const emitter = changes['control_emitter'];
  if (
    emitter !== undefined &&
    emitter !== active.fields['control_emitter']?.value &&
    !errors.length
  )
    warnings.push(
      issue('control_emitter', 'emitter_changed', 'changing the emitter changes every preset', {
        from: active.fields['control_emitter']?.value,
        to: emitter,
      }),
    );
  const numberOf = (id: string) => {
    const v = after[id]?.value;
    return typeof v === 'number' ? v : null;
  };
  const enterK = numberOf('control_stove_enter_above_k');
  const exitK = numberOf('control_stove_exit_hysteresis_k');
  if (enterK !== null && exitK !== null && exitK > enterK)
    errors.push(
      issue(
        'control_stove_exit_hysteresis_k',
        'stove_hysteresis',
        'wood-stove exit hysteresis above the entry threshold',
        { max: enterK },
      ),
    );
  const minActive = numberOf('control_stove_min_active_s');
  const maxActive = numberOf('control_stove_max_active_s');
  if (minActive !== null && maxActive !== null && minActive > maxActive)
    errors.push(
      issue(
        'control_stove_min_active_s',
        'stove_min_above_max',
        'wood-stove minimum episode longer than the maximum',
        { max: maxActive },
      ),
    );
  if (
    after['control_stove_reference_signal']?.value != null &&
    after['control_stove_reference_signal']?.value === after['control_room_signal']?.value
  )
    errors.push(
      issue(
        'control_stove_reference_signal',
        'stove_reference_is_room',
        'the room signal as the wood-stove reference room',
      ),
    );
  for (const [low, high] of BOUND_PAIRS) {
    const lowValue = numberOf(low);
    const highValue = numberOf(high);
    if (lowValue !== null && highValue !== null && lowValue > highValue)
      errors.push(
        issue(high, 'house_bounds_order', `${low} must not exceed ${high}`, {
          min_field: low,
          max_field: high,
          min: lowValue,
          max: highValue,
        }),
      );
  }
  const fitDays = numberOf('house_learn_fit_days');
  const testDays = numberOf('house_learn_test_days');
  if (fitDays !== null && testDays !== null && fitDays < testDays + 8)
    errors.push(
      issue(
        'house_learn_fit_days',
        'house_fit_days_short',
        'house_learn_fit_days must be at least house_learn_test_days + 8',
        { fit_days: fitDays, test_days: testDays, min: testDays + 8 },
      ),
    );
  const left = changes['house_learn_excluded_days'];
  if (Array.isArray(left) && !errors.some((e) => e.field === 'house_learn_excluded_days')) {
    const problem = dayProblem(left, Date.now());
    if (problem) errors.push(issue('house_learn_excluded_days', problem, problem, {}));
  }
  const room = after['control_room_signal']?.value;
  const liveness = after['control_room_liveness_signals']?.value;
  if ((room === null || room === undefined) && Array.isArray(liveness) && liveness.length > 0)
    errors.push(
      issue(
        'control_room_liveness_signals',
        'room_signal_required',
        'liveness needs a room signal',
      ),
    );
  return {
    valid: errors.length === 0,
    errors,
    warnings,
    effective: Object.fromEntries(Object.entries(changes).map(([id]) => [id, after[id]?.value])),
  };
}

function clampTo(value: number, low: number, high: number): number {
  return Math.min(Math.max(value, low), high);
}

function shiftRecord(
  record: DecisionRecord,
  curveShift: number,
  roomShift: number,
): DecisionRecord {
  const next: DecisionRecord = structuredClone(record);
  if (next.terms.length === 0) return next;
  const move = (name: string, by: number) => {
    const term = next.terms.find((item) => item.name === name);
    if (term) {
      term.raw += by;
      term.value += by;
    }
  };
  move('curve', curveShift);
  move('room_feedback', roomShift);
  const safety = next.terms.find((item) => item.name === 'safety');
  if (safety && next.pre_round !== null) {
    const low = Number(next.controller_state['safety_low_c'] ?? -Infinity);
    const high = Number(next.controller_state['safety_high_c'] ?? Infinity);
    safety.raw += curveShift + roomShift;
    safety.value = clampTo(safety.raw, low, high);
    next.pre_round = safety.value;
    next.setpoint = Math.floor(safety.value + 0.5);
  }
  return next;
}

function shifts(state: ConfigState, changes: Values, outside: number) {
  const active = effective(state);
  const after = merge(state, changes);
  const curveOld = active['control_curve']?.value as Curve;
  const curveNew = after['control_curve']?.value as Curve;
  const comfortOld = Number(active['control_comfort_c']?.value);
  const comfortNew = Number(after['control_comfort_c']?.value);
  return {
    curve: curveWater(curveNew, outside) - curveWater(curveOld, outside),
    room: (comfortNew - comfortOld) * ROOM_KP,
  };
}

const ROOM_PROFILE_FIELDS = [
  'control_room_profile',
  'control_room_step_k',
  'control_room_report_interval_s',
  'control_room_silence_limit_s',
  'control_room_liveness_signals',
  'control_room_crosscheck_signal',
  'control_room_decay_start_s',
  'control_room_alive_decay_start_s',
  'control_room_alive_decay_end_s',
];

/**
 * What the replay cannot show for a candidate, with the service's texts: another room signal
 * was not recorded; room freshness stays as recorded under the active sensor profile.
 */
export function previewLimitations(state: ConfigState, changes: Values): string[] {
  const before = effective(state);
  const after = merge(state, changes);
  const differs = (id: string) =>
    JSON.stringify(before[id]?.value ?? null) !== JSON.stringify(after[id]?.value ?? null);
  const out: string[] = [];
  if (differs('control_room_signal'))
    out.push(
      "the candidate's room signal was not recorded with the decisions; it runs without that room input",
    );
  if (ROOM_PROFILE_FIELDS.some(differs))
    out.push("the room value's freshness is as recorded under the active sensor profile");
  return out;
}

export function preview(
  state: ConfigState,
  changes: Values,
  hours: number,
  now: number,
): PreviewResult {
  const checked = validate(state, changes);
  if (!checked.valid) return checked;
  const { record: current } = buildRecord(now);
  const outsideNow = Number(current.controller_state['outside_filtered_c'] ?? 3);
  const nowShift = shifts(state, changes, outsideNow);
  const candidate = shiftRecord(current, nowShift.curve, nowShift.room);
  const from = now - hours * HOUR;
  const recorded = makeSeries(from, now, 900, now);
  const candidateSetpoints: (number | null)[] = [];
  const candidatePre: (number | null)[] = [];
  const diffs: number[] = [];
  recorded.at.forEach((at, i) => {
    const pre = recorded.pre_round[i];
    const base = recorded.setpoint[i];
    if (pre === null || pre === undefined || base === null || base === undefined) {
      candidateSetpoints.push(base ?? null);
      candidatePre.push(null);
      return;
    }
    const filtered = Number(
      buildRecord(Date.parse(at)).record.controller_state['outside_filtered_c'] ?? 3,
    );
    const shift = shifts(state, changes, filtered);
    const low = recorded.safety_low[i] ?? -Infinity;
    const high = recorded.safety_high[i] ?? Infinity;
    const nextPre = clampTo(pre + shift.curve + shift.room, low, high);
    candidatePre.push(Math.round(nextPre * 100) / 100);
    const nextSetpoint = Math.floor(nextPre + 0.5);
    candidateSetpoints.push(nextSetpoint);
    diffs.push(nextSetpoint - base);
  });
  const changesOf = (list: (number | null)[]) =>
    list.filter((v, i) => i > 0 && v !== null && v !== list[i - 1]).length;
  const perDay = (n: number) => Math.round((n * 240) / hours) / 10;
  const mean = diffs.length ? diffs.reduce((a, b) => a + b, 0) / diffs.length : 0;
  return {
    ...checked,
    now: {
      current,
      candidate,
      delta_setpoint:
        candidate.setpoint !== null && current.setpoint !== null
          ? candidate.setpoint - current.setpoint
          : null,
    },
    open_loop_run: {
      from: new Date(from).toISOString(),
      to: new Date(now).toISOString(),
      ticks: Math.round(hours * 60),
      skipped: 3,
      identity_ok: true,
      identity_ticks: Math.round(hours * 60) - 3,
      identity_mismatches: 0,
      identity_first_mismatch: null,
      open_loop: true,
      series: {
        at: recorded.at,
        recorded: recorded.setpoint,
        candidate: candidateSetpoints,
        candidate_pre_round: candidatePre,
      },
      summary: {
        mean_diff_k: Math.round(mean * 100) / 100,
        min_diff_k: diffs.length ? Math.min(...diffs) : 0,
        max_diff_k: diffs.length ? Math.max(...diffs) : 0,
        changes_recorded: changesOf(recorded.setpoint),
        changes_candidate: changesOf(candidateSetpoints),
        writes_per_day: perDay(changesOf(candidateSetpoints)),
        budget: 150,
        share_safety_clamped: 0.02,
        share_feedback_limited: 0,
        ladder: { schedule_curve_feedback: 0.99, curve_only: 0.01 },
        binding: { deadband: 0.61, dwell: 0.07 },
      },
      limitations: previewLimitations(state, changes),
    },
  };
}

export interface ApplyBody {
  base_version?: number;
  changes?: Values;
  comment?: string;
  acknowledge?: string[];
  version?: number;
}

const COMMENT_MAX = 200;

function refused(errors: ValidationIssue[], warnings: ValidationIssue[] = []) {
  return { status: 422, body: { errors, warnings } };
}

function commit(
  state: ConfigState,
  changes: Values,
  body: ApplyBody,
  now: number,
  paused: boolean,
  origin: 'ui' | 'rollback',
): { status: number; body: unknown } {
  const stored = { ...state.stored };
  for (const [id, value] of Object.entries(changes)) {
    if (value === null) delete stored[id];
    else
      stored[id] =
        Array.isArray(value) && schema.fields[id]?.type === 'dates' ? sorted(value) : value;
  }
  const changed: VersionChange[] = Object.keys(changes).map((field) => ({
    field,
    from: state.stored[field] ?? null,
    to: changes[field] ?? null,
  }));
  state.stored = stored;
  state.version += 1;
  state.updatedAt = new Date(now).toISOString();
  state.updatedBy = 'admin from 127.0.0.1';
  state.versions.push({
    version: state.version,
    created_at: state.updatedAt,
    actor: state.updatedBy,
    origin,
    comment: body.comment ?? null,
    applied_at: state.updatedAt,
    changed,
    values: { ...stored },
  });
  return {
    status: 200,
    body: { version: state.version, applies: 'next_tick', config: configDoc(state, paused) },
  };
}

export function apply(
  state: ConfigState,
  body: ApplyBody,
  now: number,
  paused: boolean,
  origin: 'ui' | 'rollback' = 'ui',
): { status: number; body: unknown } {
  if (body.base_version !== state.version)
    return {
      status: 409,
      body: { detail: 'the configuration changed meanwhile', version: state.version },
    };
  if ((body.comment ?? '').length > COMMENT_MAX)
    return refused([
      { field: null, code: 'comment_too_long', message: 'at most 200 characters', params: {} },
    ]);
  const changes = body.changes ?? {};
  const checked = validate(state, changes);
  const errors = [...checked.errors];
  const acknowledged = body.acknowledge ?? [];
  for (const warning of checked.warnings) {
    if (!acknowledged.includes(warning.code))
      errors.push({
        field: warning.field,
        code: 'warning_not_acknowledged',
        message: `warning ${warning.code} was not acknowledged`,
        params: { warning: warning.code },
      });
  }
  const before = effective(state);
  const after = merge(state, changes);
  const unchanged = Object.keys(changes).every(
    (id) =>
      JSON.stringify(before[id]?.stored ?? null) === JSON.stringify(after[id]?.stored ?? null),
  );
  if (errors.length === 0 && unchanged)
    errors.push({ field: null, code: 'no_change', message: 'nothing changed', params: {} });
  if (errors.length > 0) return refused(errors, checked.warnings);
  return commit(state, changes, body, now, paused, origin);
}

export function rollback(
  state: ConfigState,
  body: ApplyBody,
  now: number,
  paused: boolean,
): { status: number; body: unknown } {
  const target = state.versions.find((v) => v.version === body.version);
  if (!target) return { status: 404, body: { detail: `no configuration version ${body.version}` } };
  const values = target.values ?? {};
  const locked = new Set(
    Object.entries(base.fields)
      .filter(([, field]) => field.locked)
      .map(([id]) => id),
  );
  const changes: Values = {};
  for (const id of Object.keys(state.stored)) if (!(id in values)) changes[id] = null;
  for (const [id, value] of Object.entries(values)) if (!locked.has(id)) changes[id] = value;
  return apply(state, { ...body, changes }, now, paused, 'rollback');
}

type Candidate = ConfigSignals['room'][number];

const PUMP_DEVICE = 'dev-panasonic-heat-pump';

/**
 * A Home Assistant entity of the heat pump's own device, as Home Assistant's HeishaMon
 * integration creates it: the service marks it `pump_mirror` because its values equal the
 * HeishaMon values ovenbird already reads over MQTT.
 */
function pumpMirror(entity: string, name: string, unit: string, value: number): Candidate {
  const climate = entity.startsWith('climate.');
  return {
    signal: climate ? `ha/${entity}#current_temperature` : `ha/${entity}`,
    name: `Panasonic Heat Pump ${name}`,
    unit,
    value,
    held_s: 40,
    source: 'ha',
    pump_mirror: true,
    entity_id: entity,
    area: 'Utility room',
    device_id: PUMP_DEVICE,
  };
}

const PUMP_TEMPERATURES: Candidate[] = [
  pumpMirror('climate.panasonic_heat_pump_main_z1_temp', 'Zone 1', '°C', 32.5),
  pumpMirror('sensor.panasonic_heat_pump_main_dhw_temp', 'DHW Temp', '°C', 47.5),
  pumpMirror('sensor.panasonic_heat_pump_main_main_inlet_temp', 'Inlet Temp', '°C', 28),
  pumpMirror('sensor.panasonic_heat_pump_main_main_outlet_temp', 'Outlet Temp', '°C', 32.5),
  pumpMirror('sensor.panasonic_heat_pump_main_outside_temp', 'Outside Temp', '°C', 5),
  pumpMirror('sensor.panasonic_heat_pump_main_room_thermostat_temp', 'Room Temp', '°C', 21.5),
];

const PUMP_SENSORS: Candidate[] = [
  ...PUMP_TEMPERATURES.filter((c) => c.entity_id?.startsWith('sensor.')),
  pumpMirror('sensor.panasonic_heat_pump_main_pump_flow', 'Pump Flow', 'L/min', 17.4),
  pumpMirror('sensor.panasonic_heat_pump_main_compressor_freq', 'Compressor Freq', 'Hz', 38),
];

export const signals: ConfigSignals = {
  ha: { enabled: true, link_up: true, temperature_unit: '°C' },
  room: [
    {
      signal: 'ha/sensor.living_room_temperature',
      name: 'Living room climate',
      unit: '°C',
      value: 21.9,
      held_s: 7800,
      source: 'ha',
      pump_mirror: false,
      entity_id: 'sensor.living_room_temperature',
      area: 'Living room',
      device_id: 'dev-living-room-climate',
    },
    {
      signal: 'ha/sensor.bedroom_temperature',
      name: 'Bedroom',
      unit: '°C',
      value: 19.4,
      held_s: 120,
      source: 'ha',
      pump_mirror: false,
      entity_id: 'sensor.bedroom_temperature',
      area: 'Bedroom',
    },
    ...PUMP_TEMPERATURES,
    {
      signal: 'ha/climate.living_room#current_temperature',
      name: 'Living room thermostat',
      unit: '°C',
      value: 21.6,
      held_s: 300,
      source: 'ha',
      pump_mirror: false,
      entity_id: 'climate.living_room',
      area: 'Living room',
    },
    {
      signal: 'room_temperature',
      name: 'Room temperature (MQTT)',
      unit: '°C',
      value: 21.7,
      held_s: 40,
      source: 'mqtt',
      pump_mirror: false,
    },
    {
      signal: 'ha/sensor.garden_temperature',
      name: 'Garden temperature',
      unit: '°C',
      value: 5.8,
      held_s: 120,
      source: 'ha',
      pump_mirror: false,
      entity_id: 'sensor.garden_temperature',
      area: 'Garden',
    },
  ],
  liveness: [
    {
      signal: 'ha/sensor.hallway_motion_battery',
      name: 'Gang beweging battery',
      unit: '%',
      value: 64,
      held_s: 900,
      source: 'ha',
      pump_mirror: false,
      entity_id: 'sensor.hallway_motion_battery',
      area: 'Gang',
      device_id: 'dev-gang-beweging',
    },
    ...PUMP_SENSORS,
    {
      signal: 'ha/sensor.living_room_humidity',
      name: 'Living room climate humidity',
      unit: '%',
      value: 54,
      held_s: 120,
      source: 'ha',
      pump_mirror: false,
      entity_id: 'sensor.living_room_humidity',
      area: 'Living room',
      device_id: 'dev-living-room-climate',
    },
    {
      signal: 'ha/sensor.living_room_battery',
      name: 'Living room climate battery',
      unit: '%',
      value: 87,
      held_s: null,
      source: 'ha',
      pump_mirror: false,
      entity_id: 'sensor.living_room_battery',
      area: 'Living room',
      device_id: 'dev-living-room-climate',
    },
    {
      signal: 'ha/sensor.living_room_temperature',
      name: 'Living room climate',
      unit: '°C',
      value: 21.9,
      held_s: 7800,
      source: 'ha',
      pump_mirror: false,
      entity_id: 'sensor.living_room_temperature',
      area: 'Living room',
      device_id: 'dev-living-room-climate',
    },
  ],
  crosscheck: [
    {
      signal: 'ha/sensor.living_room_temperature',
      name: 'Living room climate',
      unit: '°C',
      value: 21.9,
      held_s: 7800,
      source: 'ha',
      pump_mirror: false,
      entity_id: 'sensor.living_room_temperature',
      area: 'Living room',
      device_id: 'dev-living-room-climate',
    },
    {
      signal: 'ha/climate.living_room#current_temperature',
      name: 'Living room thermostat',
      unit: '°C',
      value: 21.6,
      held_s: 300,
      source: 'ha',
      pump_mirror: false,
      entity_id: 'climate.living_room',
      area: 'Living room',
    },
    ...PUMP_TEMPERATURES,
    {
      signal: 'main/Room_Thermostat_Temp',
      name: null,
      unit: null,
      value: 22,
      held_s: 0,
      source: 'heishamon',
      pump_mirror: false,
    },
  ],
};

const ROOM_SIGNALS = ['ha/sensor.living_room_temperature', 'room_temperature'];
const TEMPERATURE_UNITS = new Set(['°C', 'C', 'celsius']);

/**
 * Candidates for the stored MQTT inputs that the fixed lists do not have yet: temperatures (°C)
 * for room and cross-check, every input for liveness, as the service lists them.
 */
function inputCandidates(inputs: unknown): { temperature: Candidate[]; all: Candidate[] } {
  const all = (Array.isArray(inputs) ? inputs : []).flatMap((item): Candidate[] => {
    const row = (item ?? {}) as Record<string, unknown>;
    const topic = typeof row['topic'] === 'string' ? row['topic'].trim() : '';
    if (!topic) return [];
    const own = typeof row['signal'] === 'string' ? row['signal'].trim() : '';
    const unit = typeof row['unit'] === 'string' && row['unit'] ? row['unit'] : null;
    return [
      {
        signal: own || `mqtt/${topic}`,
        name: topic,
        unit,
        value: unit && TEMPERATURE_UNITS.has(unit) ? 6.2 : null,
        held_s: unit && TEMPERATURE_UNITS.has(unit) ? 30 : null,
        source: 'mqtt',
        pump_mirror: false,
      },
    ];
  });
  return { temperature: all.filter((c) => c.unit && TEMPERATURE_UNITS.has(c.unit)), all };
}

/**
 * Signal candidates at `now`: the active room sensor reports the same value and held time as
 * the snapshot and the control status. Stored MQTT inputs the lists do not have yet are added.
 * With `outsideStale` the chosen outside sensor is as old as the decision says (42 min).
 */
export function makeSignals(
  now: number,
  roomStale = false,
  inputs: unknown = [],
  outsideStale = false,
): ConfigSignals {
  const room = roomFacts(now, roomStale);
  const live = (candidate: Candidate) => {
    if (ROOM_SIGNALS.includes(candidate.signal))
      return { ...candidate, value: room.value, held_s: room.heldS };
    if (outsideStale && candidate.signal === OUTSIDE_SIGNAL)
      return { ...candidate, held_s: OUTSIDE_STALE_S };
    return candidate;
  };
  const extra = inputCandidates(inputs);
  const add = (list: Candidate[], more: Candidate[]) => [
    ...list,
    ...more.filter((c) => !list.some((known) => known.signal === c.signal)),
  ];
  return {
    ...signals,
    room: add(signals.room, extra.temperature).map(live),
    liveness: add(signals.liveness, extra.all).map(live),
    crosscheck: add(signals.crosscheck, extra.temperature).map(live),
  };
}

const URL_SCHEMES = new Set(['http:', 'https:', 'ws:', 'wss:']);

function urlProblem(text: string): string | null {
  let url: URL;
  try {
    url = new URL(text);
  } catch {
    return 'not a URL';
  }
  if (!URL_SCHEMES.has(url.protocol)) return 'must be http, https, ws or wss';
  if (!url.hostname) return 'needs a host';
  if (url.username || url.password) return 'must not contain a user name or password';
  if (url.search || url.hash) return 'must not have a query or fragment';
  return null;
}

/**
 * `PUT api/v1/config/ha`: store the connection (the token stays write-only), refusing what the
 * service refuses: unknown keys, an invalid URL or token, a URL without token or the reverse.
 */
export function setConnection(
  state: ConfigState,
  body: Record<string, unknown>,
  paused: boolean,
): { status: number; body: unknown } {
  const unknown = Object.keys(body).filter((key) => key !== 'url' && key !== 'token');
  if (unknown.length > 0 || Object.keys(body).length === 0)
    return { status: 400, body: { detail: 'body must have url and/or token' } };
  const issue = (field: string, code: string, message: string): ValidationIssue => ({
    field,
    code,
    message,
    params: {},
  });
  const errors: ValidationIssue[] = [];
  const next = { ...state.ha };
  for (const [key, field] of [
    ['url', 'ha_url'],
    ['token', 'ha_token'],
  ] as const) {
    if (!(key in body)) continue;
    const value = body[key];
    if (value !== null && typeof value !== 'string') {
      errors.push(issue(field, 'type', `${field} must be a string`));
      continue;
    }
    const text = value === null ? null : value.trim() || null;
    if (key === 'url' && text) {
      const problem = urlProblem(text);
      if (problem) errors.push(issue(field, 'invalid', `ha_url ${problem}`));
    }
    if (key === 'token' && text && /\s/.test(text))
      errors.push(issue(field, 'invalid', 'ha_token must not contain whitespace'));
    next[key] = text;
  }
  if (errors.length === 0 && next.url && !next.token)
    errors.push(issue('ha_token', 'missing', 'ha_url is set but ha_token is missing'));
  if (errors.length === 0 && next.token && !next.url)
    errors.push(issue('ha_url', 'missing', 'ha_token is set but ha_url is missing'));
  if (errors.length === 0 && next.url === state.ha.url && next.token === state.ha.token)
    errors.push({ field: null, code: 'no_change', message: 'nothing changed', params: {} });
  if (errors.length > 0) return refused(errors);
  state.ha = next;
  return { status: 200, body: { config: configDoc(state, paused) } };
}

/**
 * `POST api/v1/config/ha/test`: a deterministic answer. The host `unreachable.local` cannot be
 * reached, the token `wrong-token` is rejected; anything else connects, and every requested
 * signal that the mock's candidates list is found.
 */
export function testConnection(
  state: ConfigState,
  body: Record<string, unknown>,
  activeSignals: string[],
): { status: number; body: unknown } {
  const url = typeof body['url'] === 'string' ? body['url'].trim() : (state.ha.url ?? '');
  const typed = typeof body['token'] === 'string' ? body['token'].trim() : '';
  const token = typed || (url === state.ha.url ? (state.ha.token ?? '') : '');
  const requested = Array.isArray(body['signals'])
    ? (body['signals'] as unknown[]).filter((s): s is string => typeof s === 'string')
    : activeSignals;
  const wanted = requested.filter((s) => s.startsWith('ha/'));
  const base = {
    ok: false,
    url: url || null,
    reachable: false,
    auth_ok: null as boolean | null,
    ha_version: null as string | null,
    latency_ms: null as number | null,
    temperature_unit: null as string | null,
    metric: null as boolean | null,
    entities: [] as unknown[],
    error: null as string | null,
    error_code: null as string | null,
  };
  const fail = (code: string, error: string) => ({
    status: 200,
    body: { ...base, error_code: code, error },
  });
  if (!url) return fail('not_configured', 'no Home Assistant URL');
  if (urlProblem(url)) return fail('invalid_url', `ha_url ${urlProblem(url)}`);
  if (!token) return fail('token_required', 'no access token to test with');
  if (new URL(url).hostname === MOCK_UNREACHABLE_HOST)
    return fail('unreachable', `cannot reach ${url}/api/: OSError: Name or service not known`);
  base.reachable = true;
  base.latency_ms = 23.4;
  if (token === MOCK_BAD_TOKEN) {
    base.auth_ok = false;
    return fail('auth_failed', 'Home Assistant rejected the token');
  }
  base.auth_ok = true;
  base.ha_version = '2026.11.2';
  base.temperature_unit = '°C';
  base.metric = true;
  const known = new Map(
    [...signals.room, ...signals.liveness, ...signals.crosscheck].map((c) => [c.signal, c]),
  );
  base.entities = wanted.map((signal) => {
    const candidate = known.get(signal);
    const entity = signal.slice(3).split('#')[0] ?? signal;
    return {
      signal,
      entity_id: entity,
      found: candidate !== undefined,
      state: candidate ? String(candidate.value ?? '') : null,
      value: candidate?.value ?? null,
      unit: candidate?.unit ?? null,
      problem: candidate ? null : 'not found in Home Assistant',
    };
  });
  base.ok = base.entities.every((e) => (e as { problem: unknown }).problem === null);
  return { status: 200, body: base };
}

export function versionsList(state: ConfigState, limit: number): { versions: ConfigVersion[] } {
  const list = [...state.versions].reverse().slice(0, limit);
  return { versions: list.map(({ values, ...rest }) => (void values, rest)) };
}

export function exportDoc(state: ConfigState, now: number, paused: boolean) {
  const doc = configDoc(state, paused);
  return {
    ovenbird_config: 1,
    app_version: '0.4.1',
    exported_at: new Date(now).toISOString(),
    version: state.version,
    values: { ...state.stored },
    effective: Object.fromEntries(Object.entries(doc.fields).map(([id, f]) => [id, f.value])),
  };
}
