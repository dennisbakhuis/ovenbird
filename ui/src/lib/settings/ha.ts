import type { ConfigDoc, HaTestResult, SignalCandidate } from '$lib/core/types';

export const HA_PREFIX = 'ha/';

const SIGNAL_FIELDS = [
  'control_room_signal',
  'control_room_liveness_signals',
  'control_room_crosscheck_signal',
  'control_stove_reference_signal',
  'control_outside_signal',
] as const;

const SCHEMES = new Set(['http:', 'https:', 'ws:', 'wss:']);

export type HaUrlProblem = 'scheme' | 'host' | 'credentials' | 'query';

/**
 * The `ha/` signals the effective configuration reads, in field order without repeats.
 */
export function haSignals(config: ConfigDoc | null): string[] {
  const out: string[] = [];
  for (const id of SIGNAL_FIELDS) {
    const value = config?.fields[id]?.value;
    const list = Array.isArray(value) ? value : [value];
    for (const item of list) {
      if (typeof item === 'string' && item.startsWith(HA_PREFIX) && !out.includes(item))
        out.push(item);
    }
  }
  return out;
}

/**
 * What is wrong with a Home Assistant URL, mirroring the service's check (null when it passes or
 * is empty). The service has the final word.
 */
export function haUrlProblem(text: string): HaUrlProblem | null {
  const value = text.trim();
  if (!value) return null;
  let url: URL;
  try {
    url = new URL(value);
  } catch {
    return /^[a-z][a-z0-9+.-]*:\/\//i.test(value) ? 'host' : 'scheme';
  }
  if (!SCHEMES.has(url.protocol)) return 'scheme';
  if (!url.hostname) return 'host';
  if (url.username || url.password) return 'credentials';
  if (url.search || url.hash || value.includes('?') || value.includes('#')) return 'query';
  return null;
}

/**
 * Liveness candidates with the room sensor's own device first (same `device_id`), then the
 * rest in their order. Without device facts the order stays as it is.
 */
export function sameDeviceFirst(
  liveness: SignalCandidate[],
  room: SignalCandidate[],
  roomSignal: string | null,
): SignalCandidate[] {
  const device = room.find((c) => c.signal === roomSignal)?.device_id;
  if (!device) return liveness;
  const own = liveness.filter((c) => c.device_id === device && c.signal !== roomSignal);
  return [...own, ...liveness.filter((c) => !own.includes(c))];
}

/**
 * Whether a candidate is on the room sensor's own device.
 */
export function onDevice(candidate: SignalCandidate, device: string | null | undefined): boolean {
  return Boolean(device) && candidate.device_id === device;
}

export type HaVerdict = 'ok' | 'entities' | 'failed';

/**
 * The headline of a connection test: everything fine, connected but an entity has a problem, or
 * no working connection.
 */
export function haVerdict(result: HaTestResult): HaVerdict {
  if (result.ok) return 'ok';
  if (result.error_code === null && result.reachable && result.auth_ok) return 'entities';
  return 'failed';
}

/**
 * The host (and port) of a URL for a compact summary; the text itself when it does not parse.
 */
export function haHost(text: string | null | undefined): string | null {
  if (!text) return null;
  try {
    return new URL(text).host || text;
  } catch {
    return text;
  }
}
