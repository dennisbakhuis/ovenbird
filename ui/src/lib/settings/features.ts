import type { IconName } from '$lib/core/icons';
import type { SectionId } from '$lib/core/schema';
import type { ConfigSchema, FeatureEntry, FeatureId, FeatureState, Tier } from '$lib/core/types';

/**
 * One switchable feature as the Features section lists it. `switch` is the settings field that
 * turns it on or off. Features with a detailed editor elsewhere (`editor`) show only their switch
 * and a link to it; the settings of the others are edited in the card itself (`skip` leaves out
 * the ones the editor still owns). `ack` is the setting with which the owner accepts that an
 * experimental feature may be switched fully on; the card shows it as a checkbox under the switch.
 */
export interface FeatureSpec {
  id: FeatureId;
  switch: string;
  icon: IconName;
  editor?: SectionId;
  inline: boolean;
  skip?: readonly string[];
  threeWay?: boolean;
  ack?: string;
}

export const FEATURES: readonly FeatureSpec[] = [
  {
    id: 'weather_compensation',
    switch: 'control_weather_compensation',
    icon: 'chart',
    editor: 'curve',
    inline: false,
  },
  {
    id: 'room_feedback',
    switch: 'control_feedback_enabled',
    icon: 'thermometer',
    editor: 'room',
    inline: false,
  },
  {
    id: 'slow_start',
    switch: 'control_ramp_enabled',
    icon: 'ramp',
    editor: 'behaviour',
    inline: false,
  },
  {
    id: 'minimum_run',
    switch: 'control_cycling_enabled',
    icon: 'ramp',
    editor: 'behaviour',
    inline: false,
  },
  {
    id: 'pump_duty',
    switch: 'control_pump_duty',
    icon: 'pump',
    editor: 'pump-duty',
    inline: false,
  },
  {
    id: 'quiet',
    switch: 'control_quiet_enabled',
    icon: 'moon',
    editor: 'quiet',
    inline: true,
    skip: ['control_quiet_windows'],
  },
  { id: 'stove', switch: 'control_stove_enabled', icon: 'flame', editor: 'stove', inline: false },
  {
    id: 'dayshift',
    switch: 'control_dayshift_use',
    icon: 'sun',
    inline: true,
    threeWay: true,
    ack: 'control_dayshift_experimental_ok',
  },
  { id: 'summer', switch: 'control_summer_enabled', icon: 'sun', inline: true },
  { id: 'away', switch: 'control_away_enabled', icon: 'home', inline: true },
  { id: 'boost', switch: 'control_boost_enabled', icon: 'flame', inline: true },
  { id: 'starts_alarm', switch: 'safety_starts_alarm_enabled', icon: 'warning', inline: true },
  {
    id: 'house_basics',
    switch: 'house_basics_enabled',
    icon: 'home',
    editor: 'house',
    inline: false,
  },
];

export interface FeatureFields {
  basic: string[];
  advanced: string[];
  expert: string[];
}

/**
 * The fields a feature card lists, by tier, in schema order. The switch and the acknowledgement are
 * left out; the editable
 * ones only when the card edits them itself, the expert ones (fixed by the installation) always.
 */
export function featureFields(schema: ConfigSchema, spec: FeatureSpec): FeatureFields {
  const out: FeatureFields = { basic: [], advanced: [], expert: [] };
  for (const group of schema.groups) {
    for (const id of group.fields) {
      const def = schema.fields[id];
      if (def?.feature !== spec.id || id === spec.switch || id === spec.ack) continue;
      const tier: Tier = def.tier;
      if (tier === 'expert' || def.read_only) out.expert.push(id);
      else if (spec.inline && !spec.skip?.includes(id))
        (tier === 'basic' ? out.basic : out.advanced).push(id);
    }
  }
  return out;
}

/**
 * Whether the schema tags any field with a feature (an older service does not).
 */
export function hasFeatureTags(schema: ConfigSchema): boolean {
  return Object.values(schema.fields).some((def) => def.feature);
}

const STATE_TONE = {
  off: 'neutral',
  shadow: 'info',
  on: 'ok',
  active_now: 'ok',
} as const satisfies Record<FeatureState, string>;

/**
 * Pill tone of a feature state.
 */
export function stateTone(state: FeatureState): (typeof STATE_TONE)[FeatureState] {
  return STATE_TONE[state];
}

/**
 * The service's entry for a feature, or undefined while the states are not loaded.
 */
export function entryOf(
  entries: readonly FeatureEntry[] | null,
  id: FeatureId,
): FeatureEntry | undefined {
  return entries?.find((entry) => entry.id === id);
}

/**
 * Number of changed fields of a feature in a draft: its switch and the fields its card lists.
 */
export function changedIn(
  schema: ConfigSchema,
  spec: FeatureSpec,
  changes: Record<string, unknown>,
): number {
  return Object.keys(changes).filter((id) => schema.fields[id]?.feature === spec.id).length;
}

/**
 * Number of draft changes in any feature's fields, for the section's count in the rail.
 */
export function changedFeatureFields(
  schema: ConfigSchema | null,
  changes: Record<string, unknown>,
): number {
  if (!schema) return 0;
  return Object.keys(changes).filter((id) => schema.fields[id]?.feature).length;
}
