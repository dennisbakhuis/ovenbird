import { asCurve, curveProblems, curveWater } from './curve.ts';
import { asMqttInputs, mqttInputProblems } from './mqttInputs.ts';
import type { IconName } from './icons';
import type { ConfigDoc, ConfigSchema, FieldDef, Tier } from './types';

export const SECTIONS = [
  { id: 'curve', groups: ['curve'], icon: 'chart' },
  { id: 'room', groups: ['room', 'feedback', 'monitors'], icon: 'thermometer' },
  { id: 'pump-duty', groups: ['pump', 'pump_duty'], icon: 'pump' },
  { id: 'stove', groups: ['stove'], icon: 'flame' },
  { id: 'behaviour', groups: ['limits', 'behaviour', 'ramp', 'cycling'], icon: 'ramp' },
  { id: 'quiet', groups: ['quiet'], icon: 'moon' },
  { id: 'emitter', groups: ['emitter'], icon: 'flame' },
  { id: 'weather', groups: ['weather'], icon: 'weather' },
  { id: 'house', groups: ['house', 'house_bounds', 'house_learning'], icon: 'home' },
  { id: 'ha', groups: ['ha'], icon: 'link' },
  { id: 'mqtt', groups: ['mqtt'], icon: 'globe' },
  { id: 'data', groups: ['history'], icon: 'download' },
  { id: 'versions', groups: [], icon: 'clock' },
] as const satisfies readonly { id: string; groups: readonly string[]; icon: IconName }[];

export type SectionId = (typeof SECTIONS)[number]['id'];

/**
 * Connection fields: set with `PUT config/ha` or `config/mqtt`, never through a configuration
 * change (the service answers `connection_field`).
 */
export const CONNECTION_FIELDS: ReadonlySet<string> = new Set([
  'ha_url',
  'ha_token',
  'mqtt_host',
  'mqtt_port',
  'mqtt_username',
  'mqtt_password',
  'mqtt_tls',
  'mqtt_ca_file',
  'mqtt_client_id',
  'heishamon_base',
]);

/**
 * Section with the given id, or undefined for the overview and unknown ids.
 */
export function sectionOf(id: string | undefined): (typeof SECTIONS)[number] | undefined {
  return SECTIONS.find((section) => section.id === id);
}

/**
 * Number of draft changes that fall in the given schema groups.
 */
export function changesIn(
  schema: ConfigSchema | null,
  changes: Record<string, unknown>,
  groups: readonly string[],
): number {
  if (!schema || groups.length === 0) return 0;
  const ids = new Set(fieldsOf(schema, [...groups], ['basic', 'advanced', 'expert']));
  return Object.keys(changes).filter((field) => ids.has(field)).length;
}

export interface FieldCheck {
  error: string | null;
  warning: string | null;
}

const FACTORS: Record<string, number> = { s: 1, min: 60, h: 3600 };
const OK: FieldCheck = { error: null, warning: null };
const SHIFT_LIMIT_K = 3;
/** A retention is 0 (keep forever) or at least this many days, as the service requires. */
export const RETENTION_MIN_DAYS = 1;

/**
 * Factor from the stored unit to the display unit (seconds to minutes or hours, a share to
 * percent), 1 otherwise.
 */
export function displayFactor(def: FieldDef): number {
  if (def.unit === 'ratio' && def.display === '%') return 0.01;
  return def.display && def.unit === 's' ? (FACTORS[def.display] ?? 1) : 1;
}

/**
 * Display unit of a field: the `display` conversion target when set, else its stored unit.
 */
export function displayUnit(def: FieldDef): string {
  if (def.unit === 'ratio') return def.display ?? '';
  return def.display && def.unit === 's' ? def.display : (def.unit ?? '');
}

/**
 * Convert a stored value to its display unit.
 */
export function toDisplay(def: FieldDef, value: number): number {
  return Math.round((value / displayFactor(def)) * 1e9) / 1e9;
}

/**
 * Convert a value typed in the display unit back to the stored unit.
 */
export function fromDisplay(def: FieldDef, value: number): number {
  return Math.round(value * displayFactor(def) * 1000) / 1000;
}

/**
 * Check a number against the schema's hard bounds (error) and soft range (warning).
 */
export function checkNumber(def: FieldDef, value: unknown): FieldCheck {
  if (value === null || value === undefined) return OK;
  if (typeof value !== 'number' || !Number.isFinite(value))
    return { error: 'not_a_number', warning: null };
  if (def.type === 'integer' && !Number.isInteger(value))
    return { error: 'not_integer', warning: null };
  if (def.min !== null && def.min !== undefined) {
    if (value < def.min || (def.exclusive_min && value <= def.min))
      return { error: 'below_min', warning: null };
  }
  if (def.max !== null && def.max !== undefined) {
    if (value > def.max || (def.exclusive_max && value >= def.max))
      return { error: 'above_max', warning: null };
  }
  if (def.soft_min !== null && def.soft_min !== undefined && value < def.soft_min)
    return { error: null, warning: 'below_soft_min' };
  if (def.soft_max !== null && def.soft_max !== undefined && value > def.soft_max)
    return { error: null, warning: 'above_soft_max' };
  return OK;
}

/**
 * Check a heating curve: structure, the envelope band around the preset curve, and the shift
 * against the active curve (warning).
 */
export function checkCurve(
  schema: ConfigSchema,
  def: FieldDef,
  value: unknown,
  active: unknown,
  limits: { waterMin: number; waterMax: number },
): FieldCheck {
  const points = asCurve(value);
  if (!points) return { error: 'not_a_curve', warning: null };
  const problem = curveProblems(points, {
    ...limits,
    outsideMin: def.outside_min,
    outsideMax: def.outside_max,
    minPoints: def.min_points,
    maxPoints: def.max_points,
  })[0];
  if (problem) return { error: `curve_${problem}`, warning: null };
  const { curve, below_k: below, above_k: above } = schema.envelope;
  for (let outside = -30; outside <= 30; outside += 1) {
    const water = curveWater(points, outside);
    const anchor = curveWater(curve, outside);
    if (water < anchor - below - 1e-9 || water > anchor + above + 1e-9)
      return { error: 'outside_envelope', warning: null };
  }
  const before = asCurve(active);
  if (before) {
    for (let outside = -15; outside <= 20; outside += 1) {
      if (Math.abs(curveWater(points, outside) - curveWater(before, outside)) > SHIFT_LIMIT_K)
        return { error: null, warning: 'curve_shift_large' };
    }
  }
  return OK;
}

/**
 * Check one field value the way the schema allows; the server stays the authority.
 */
export function checkField(
  schema: ConfigSchema,
  id: string,
  value: unknown,
  config: ConfigDoc | null,
  limits?: { waterMin: number; waterMax: number },
): FieldCheck {
  const def = schema.fields[id];
  if (!def || value === null || value === undefined) return OK;
  if (def.type === 'number' || def.type === 'integer') return checkNumber(def, value);
  if (def.type === 'retention') {
    if (value === 0) return OK;
    if (typeof value === 'number' && value > 0 && value < RETENTION_MIN_DAYS)
      return { error: 'retention_min', warning: null };
    return checkNumber(def, value);
  }
  if (def.type === 'curve')
    return checkCurve(
      schema,
      def,
      value,
      config?.fields[id]?.value,
      limits ?? { waterMin: def.min ?? 10, waterMax: def.max ?? 60 },
    );
  if (def.type === 'enum' && def.options && !def.options.includes(String(value)))
    return { error: 'not_an_option', warning: null };
  if (def.type === 'mqtt_inputs') {
    if (!Array.isArray(value)) return { error: 'not_mqtt_inputs', warning: null };
    if (def.max_items !== undefined && value.length > def.max_items)
      return { error: 'too_many', warning: null };
    const base = config?.fields['heishamon_base']?.value;
    const problems = mqttInputProblems(
      asMqttInputs(value),
      typeof base === 'string' ? base : undefined,
    );
    if (problems.some((p) => p !== null)) return { error: 'mqtt_inputs_invalid', warning: null };
  }
  if (def.type === 'dates') {
    if (!Array.isArray(value) || value.some((day) => typeof day !== 'string'))
      return { error: 'not_dates', warning: null };
    if (def.max_items !== undefined && value.length > def.max_items)
      return { error: 'too_many', warning: null };
  }
  if (def.type === 'windows') {
    const items = Array.isArray(value) ? value : null;
    if (!items) return { error: 'not_windows', warning: null };
    if (def.max_items !== undefined && items.length > def.max_items)
      return { error: 'too_many_windows', warning: null };
  }
  return OK;
}

/**
 * Check every changed field; returns per-field client-side errors and warnings.
 */
export function checkChanges(
  schema: ConfigSchema,
  changes: Record<string, unknown>,
  config: ConfigDoc | null,
  limits?: { waterMin: number; waterMax: number },
): { errors: Record<string, string>; warnings: Record<string, string> } {
  const errors: Record<string, string> = {};
  const warnings: Record<string, string> = {};
  for (const [id, value] of Object.entries(changes)) {
    const result = checkField(schema, id, value, config, limits);
    if (result.error) errors[id] = result.error;
    if (result.warning) warnings[id] = result.warning;
  }
  return { errors, warnings };
}

/**
 * Fields of a group in schema order, optionally limited to the tiers shown.
 */
export function fieldsOf(
  schema: ConfigSchema,
  groupIds: readonly string[],
  tiers: readonly Tier[],
): string[] {
  return schema.groups
    .filter((group) => groupIds.includes(group.id))
    .flatMap((group) => group.fields)
    .filter((id) => {
      const def = schema.fields[id];
      return def !== undefined && tiers.includes(def.tier);
    });
}
