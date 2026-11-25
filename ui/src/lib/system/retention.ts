import type { ConfigDoc, RetentionPreset } from '$lib/core/types';

export type PresetId = RetentionPreset['id'];
export type PresetChoice = PresetId | 'custom';

export const RETENTION_FIELDS = [
  'history_raw_days',
  'history_1m_days',
  'history_15m_days',
  'history_1h_days',
  'history_decision_days',
] as const;

export type RetentionField = (typeof RETENTION_FIELDS)[number];
export type RetentionValues = Record<RetentionField, number>;

/**
 * The simple choices of Settings → Data, as the service defines them (`0` keeps forever). The
 * storage report repeats them with their projected size; these serve when it is not loaded.
 */
export const RETENTION_PRESETS: Record<PresetId, RetentionValues> = {
  short: {
    history_raw_days: 7,
    history_1m_days: 31,
    history_15m_days: 366,
    history_1h_days: 0,
    history_decision_days: 31,
  },
  standard: {
    history_raw_days: 14,
    history_1m_days: 90,
    history_15m_days: 0,
    history_1h_days: 0,
    history_decision_days: 30,
  },
  long: {
    history_raw_days: 31,
    history_1m_days: 366,
    history_15m_days: 0,
    history_1h_days: 0,
    history_decision_days: 366,
  },
  unlimited: {
    history_raw_days: 0,
    history_1m_days: 0,
    history_15m_days: 0,
    history_1h_days: 0,
    history_decision_days: 0,
  },
};

export const PRESET_IDS = Object.keys(RETENTION_PRESETS) as PresetId[];

/**
 * A retention value in days, with "keep forever" (`null`, missing or 0) as 0.
 */
export function keptDays(value: unknown): number {
  return typeof value === 'number' && value > 0 ? value : 0;
}

/**
 * The preset the five retention values match, or `custom`.
 */
export function matchPreset(
  values: Partial<Record<RetentionField, unknown>>,
  presets: Record<PresetId, RetentionValues> = RETENTION_PRESETS,
): PresetChoice {
  const found = PRESET_IDS.find((id) =>
    RETENTION_FIELDS.every((field) => keptDays(values[field]) === presets[id][field]),
  );
  return found ?? 'custom';
}

/**
 * The draft changes that pick a preset: a field already kept forever stays as it is stored
 * (`null` and 0 both mean forever), so choosing a preset changes only what differs.
 */
export function presetChanges(
  id: PresetId,
  config: ConfigDoc | null,
  presets: Record<PresetId, RetentionValues> = RETENTION_PRESETS,
): Record<RetentionField, number | null> {
  const out = {} as Record<RetentionField, number | null>;
  for (const field of RETENTION_FIELDS) {
    const days = presets[id][field];
    const active = config?.fields[field]?.value;
    out[field] = days === 0 && keptDays(active) === 0 ? ((active as number | null) ?? null) : days;
  }
  return out;
}

/**
 * The presets of a storage report as a value table, falling back to the built-in one.
 */
export function presetTable(
  presets: readonly RetentionPreset[] | null | undefined,
): Record<PresetId, RetentionValues> {
  const out = { ...RETENTION_PRESETS };
  for (const item of presets ?? []) {
    if (!(item.id in out)) continue;
    const values = {} as RetentionValues;
    for (const field of RETENTION_FIELDS) values[field] = keptDays(item.values[field]);
    out[item.id] = values;
  }
  return out;
}
