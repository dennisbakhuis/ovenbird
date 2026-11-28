import type { ConfigDoc } from '$lib/core/types';

export const FACTS_GROUP = 'house';

/** The house facts the owner can answer; the heat-loss estimate starts from them. */
export const FACT_FIELDS = [
  'house_build_period',
  'house_floor_area_m2',
  'house_occupants',
  'house_volume_m3',
  'house_window_area_m2',
  'house_window_orientation',
] as const;

/**
 * Whether at least one fact about the house is set.
 */
export function anyFactSet(config: ConfigDoc | null): boolean {
  return FACT_FIELDS.some((id) => {
    const value = config?.fields[id]?.value;
    return value !== null && value !== undefined;
  });
}
