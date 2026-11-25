import { effectiveAge } from './format';
import type { Signal } from './types';

export type SignalGroup = 'room' | 'temperatures' | 'pump' | 'power' | 'settings' | 'other';
export const SIGNAL_GROUPS: SignalGroup[] = [
  'room',
  'temperatures',
  'pump',
  'power',
  'settings',
  'other',
];

export type Freshness = 'fresh' | 'held' | 'stale';

const INTERNAL = new Set(['stats']);
const ON_CHANGE_MIN_MAX_AGE_S = 3600;

/**
 * Signal id without its topic prefix (`main/Outside_Temp` becomes `Outside_Temp`).
 */
export function shortId(id: string): string {
  return id.includes('/') ? id.slice(id.lastIndexOf('/') + 1) : id;
}

/**
 * Signals that are bookkeeping of the bridge, not measurements.
 */
export function isInternalSignal(id: string): boolean {
  return INTERNAL.has(shortId(id).toLowerCase());
}

/**
 * Signals about the hot-water tank and its runs (`DHW_Temp`, `Force_DHW_State`,
 * `DHW_Power_Production`, the tank's sterilization), left out while hot water is hidden.
 */
export function isHotWaterSignal(id: string): boolean {
  return /dhw|^sterilization/i.test(shortId(id));
}

/**
 * Readable fallback name for an id without a translation.
 */
export function humanizeId(id: string): string {
  const base = shortId(id).replace(/^sensor\./, '');
  const text = base.replace(/_+/g, ' ').trim();
  return text.charAt(0).toUpperCase() + text.slice(1);
}

/**
 * Name of a signal for people: its translated label, else the service's name unless that is a
 * topic path, else the configured id humanised (`room_temperature` becomes "Room temperature").
 */
export function signalName(
  id: string,
  name: string | null | undefined,
  translate: (key: string) => string | undefined,
): string {
  return translate(`sig_${shortId(id)}`) ?? (name && !name.includes('/') ? name : humanizeId(id));
}

/**
 * Group of a signal, by id and source.
 */
export function signalGroup(id: string, signal: Pick<Signal, 'source'>): SignalGroup {
  const name = shortId(id).toLowerCase();
  if (signal.source !== 'heishamon') return 'room';
  if (
    /^room_heater|heater_on_outdoor|heating_off_outdoor|heat_delta|flowrate_mode|quiet_mode_priority|powerful_mode|heating_control|heater_(delay|start|stop)|buffer_installed|dhw_installed/.test(
      name,
    )
  )
    return 'settings';
  if (name.startsWith('room')) return 'room';
  if (/^heat_power|power/.test(name)) return 'power';
  if (
    /^z1_heat_curve|installed|^heating_(off|mode)|sensor_settings|^zones_state|holiday/.test(name)
  )
    return 'settings';
  if (/temp$|^z1_|^main_/.test(name)) return 'temperatures';
  if (
    /compressor|pump|defrost|threeway|quiet|operating|operations|heatpump_state|error|heater|force_dhw/.test(
      name,
    )
  )
    return 'pump';
  return 'other';
}

/**
 * Freshness of a signal. A fresh signal with a generous limit (an on-change sensor that only
 * reports when its value moves) is `held`, not stale.
 */
export function freshness(signal: Signal): Freshness {
  if (!signal.fresh) return 'stale';
  const onChange = signal.alive_by || (signal.max_age ?? 0) >= ON_CHANGE_MIN_MAX_AGE_S;
  return onChange ? 'held' : 'fresh';
}

/**
 * Age in seconds of the last proof of life of a signal: its alive_by signal when known, else
 * its own last report.
 */
export function proofAge(
  signal: Signal,
  all: Record<string, Signal>,
  receivedAt: number,
  now: number,
): number {
  const by = signal.alive_by ? all[signal.alive_by] : undefined;
  return effectiveAge((by ?? signal).age, receivedAt, now);
}

/**
 * Dictionary key of a pump-reported value label (`max_flow`, `No error`).
 */
export function valueLabelKey(label: string): string {
  return `sigval_${label.trim().toLowerCase().replace(/\s+/g, '_')}`;
}
