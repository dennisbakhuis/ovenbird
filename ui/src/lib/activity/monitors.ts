import { clockNow } from '$lib/core/format';
import type { Monitor } from '$lib/core/types';

export type MonitorWithLimit = Monitor & {
  limit?: number | null;
  unit?: string | null;
  direction?: 'above' | 'below' | null;
};

export interface MonitorBar {
  value: number;
  limit: number;
  unit: string;
  direction: 'above' | 'below';
}

function defrostBar(monitor: MonitorWithLimit, nowMs: number): MonitorBar | null {
  if (typeof monitor.limit !== 'number' || !Number.isFinite(monitor.limit)) return null;
  const since = monitor.since ? Date.parse(monitor.since) : NaN;
  const elapsed = Number.isFinite(since) ? Math.max(0, (nowMs - since) / 1000) : 0;
  return { value: elapsed, limit: monitor.limit, unit: monitor.unit ?? 's', direction: 'above' };
}

/**
 * Bullet-bar data of a monitor, or null when the backend gives no numeric value and limit.
 */
export function monitorBar(monitor: MonitorWithLimit, nowMs = clockNow()): MonitorBar | null {
  if (monitor.code === 'defrost_stuck') return defrostBar(monitor, nowMs);
  if (typeof monitor.value !== 'number' || !Number.isFinite(monitor.value)) return null;
  if (typeof monitor.limit !== 'number' || !Number.isFinite(monitor.limit)) return null;
  return {
    value: monitor.value,
    limit: monitor.limit,
    unit: monitor.unit ?? '',
    direction: monitor.direction === 'below' ? 'below' : 'above',
  };
}

const ACTIONS: [RegExp, string][] = [
  [/^(command_hold|foreign_writer|verification_failed|hold_latched|correction_failed)$/, 'holds'],
  [/^(write_budget)$/, 'commands'],
  [/^(room_|ha_link_down)/, 'room'],
  [/^(config_reset)$/, 'versions'],
  [
    /^(mode_mismatch|heishamon_restarted|notify_failing|mqtt_connection_reverted|mqtt_revert_failed)$/,
    'system',
  ],
  [/^(archive_failing|archive_rebuilt)$/, 'system'],
  [/^(release_interrupted)$/, 'trial'],
  [/^(stove_reference_missing)$/, 'stove'],
  [/^(outside_sensor_stale|outside_sensor_implausible)$/, 'curve'],
  [
    /^(pump_setting_changed|low_flow|pump_error|backup_heater|defrost_stuck|outlet_overshoot)/,
    'pump',
  ],
];

export type AlarmAction =
  'holds' | 'commands' | 'room' | 'versions' | 'system' | 'pump' | 'trial' | 'stove' | 'curve';

/**
 * Where an alarm is best looked into, by alarm code.
 */
export function alarmAction(code: string): AlarmAction | null {
  for (const [pattern, action] of ACTIONS) if (pattern.test(code)) return action as AlarmAction;
  return null;
}

export const ACTION_HREF: Record<AlarmAction, string> = {
  holds: '#/activity/holds',
  commands: '#/activity/commands',
  room: '#/settings/room',
  versions: '#/settings/versions',
  system: '#/system',
  pump: '#/pump',
  trial: '#/system/trial',
  stove: '#/settings/stove',
  curve: '#/settings/curve',
};
