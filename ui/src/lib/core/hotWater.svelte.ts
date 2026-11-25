import { GLYPHS } from '$components/charts/glyphs';
import { en, type MessageKey } from '$lib/i18n';
import type { IconName } from './icons';
import type { ConfigDoc, Snapshot } from './types';

export type HotWaterSetting = ConfigDoc['hot_water']['setting'];

/** The pump's own report of a hot-water tank: 1 installed, 0 none. */
export const INSTALLED_SIGNAL = 'main/DHW_Installed';

/** Icon of a hot-water run while hot water is hidden: the pump is busy with something else. */
export const BUSY_ICON: IconName = 'gear';

const BUSY_PREFIX = 'busy_';

/**
 * Whether the pump's report says a tank is installed: true for 1, false for 0, null when the
 * value is missing or not understood.
 */
export function reportedInstalled(value: unknown): boolean | null {
  if (typeof value === 'boolean') return value;
  if (typeof value === 'number' && Number.isFinite(value)) return value > 0;
  if (typeof value === 'string' && /^[01]$/.test(value.trim())) return value.trim() === '1';
  return null;
}

/**
 * Whether hot water shows in the app. `on` always, `off` never; `auto` (also with no setting
 * known yet) follows the pump's live report of a tank, else what the service decided, else
 * shows it.
 */
export function hotWaterShown(
  setting: HotWaterSetting | null,
  installed: unknown,
  decided: boolean | null,
): boolean {
  if (setting === 'on') return true;
  if (setting === 'off') return false;
  return reportedInstalled(installed) ?? decided ?? true;
}

export interface HotWaterSources {
  snapshot: Snapshot | null;
  config: ConfigDoc | null;
}

/**
 * Whether hot water shows, from the stored setting in the config document and the live
 * snapshot. `connect` points it at the app's live and control stores once at start-up; until
 * then it shows hot water.
 */
export class HotWaterStore {
  #source = $state.raw<() => HotWaterSources>(() => ({ snapshot: null, config: null }));

  readonly shown = $derived.by(() => {
    const { snapshot, config } = this.#source();
    const state = config?.hot_water;
    return hotWaterShown(
      state?.setting ?? null,
      snapshot?.signals[INSTALLED_SIGNAL]?.value,
      state?.shown ?? null,
    );
  });

  connect(source: () => HotWaterSources): void {
    this.#source = source;
  }
}

export const hotWater = new HotWaterStore();

/**
 * Whether a message key has a neutral `busy_` variant for while hot water is hidden.
 */
export function hasBusyVariant(key: string): boolean {
  return `${BUSY_PREFIX}${key}` in en;
}

/**
 * The message key to show: while hot water is hidden, a text about a hot-water run gives way to
 * its `busy_<key>` variant ("Pump busy elsewhere"), so a run still shows without naming hot
 * water. Every other key is returned as is.
 */
export function textKey<K extends string>(key: K, shown: boolean): K | MessageKey {
  return !shown && hasBusyVariant(key) ? (`${BUSY_PREFIX}${key}` as MessageKey) : key;
}

/**
 * Day-strip lanes as shown: the hot-water lane (`dhw`) stays while hot water shows; hidden, it
 * stays only when it has runs to show, under the neutral gear glyph.
 */
export function hotWaterLanes<
  L extends { id: string; segments: readonly unknown[]; icon?: string },
>(lanes: L[], shown: boolean): L[] {
  if (shown) return lanes;
  return lanes.flatMap((lane) =>
    lane.id !== 'dhw' ? [lane] : lane.segments.length > 0 ? [{ ...lane, icon: GLYPHS.gear }] : [],
  );
}
