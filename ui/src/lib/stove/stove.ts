import type { StoveStatus } from '$lib/core/types';

/** Durations offered for a manual wood-stove episode, in hours. */
export const STOVE_HOURS = [2, 4, 8] as const;

export type StoveWaiting = 'blocked' | 'level_blocked' | 'reentry_wait';

/**
 * Why the automatic detection waits while no episode runs: after a manual stop, after an
 * untrusted room value or after an episode reached its longest time; null otherwise.
 */
export function stoveWaiting(stove: StoveStatus | null | undefined): StoveWaiting | null {
  if (!stove || !stove.enabled || stove.active) return null;
  if (stove.blocked) return 'blocked';
  if (stove.reentry_wait) return 'reentry_wait';
  if (stove.level_blocked) return 'level_blocked';
  return null;
}

/**
 * How the current episode started, for its detail line: detected automatically, by hand, or by
 * hand and taken over by the detection; null without an episode.
 */
export function stoveOrigin(
  stove: StoveStatus | null | undefined,
): 'auto' | 'manual' | 'handover' | null {
  if (!stove?.active) return null;
  if (stove.trigger === 'handover') return 'handover';
  return stove.source === 'manual' ? 'manual' : 'auto';
}

/**
 * Whether a manual start can be offered: wood-stove mode is enabled and no episode runs.
 */
export function canStartStove(stove: StoveStatus | null | undefined): boolean {
  return Boolean(stove?.enabled) && !stove?.active;
}

export type StoveReference = 'none' | 'watched' | 'stale';

/**
 * What the reference-room guard can do during an episode: no reference room is set (nothing
 * else in the house is watched), the reference room is watched (it has a fresh reading), or a
 * reference room is set but has no fresh reading (the service reports `reference_c` null), so
 * the guard cannot work.
 */
export function stoveReference(
  stove: StoveStatus | null | undefined,
  signal: string | null | undefined,
): StoveReference {
  if (!signal) return 'none';
  return stove?.reference_c === null || stove?.reference_c === undefined ? 'stale' : 'watched';
}

/**
 * The headline key of the wood-stove banner, following the control fact: "heating backed off"
 * only while ovenbird sends; otherwise what it would do and why nothing is sent (only watches,
 * paused, waiting out a hold, may not send, off).
 */
export function stoveHeadlineKey(kind: string, sending: boolean): string {
  if (sending || kind === 'unknown') return 'stoveBanner';
  if (['watching', 'paused', 'held', 'refused', 'off'].includes(kind))
    return `stoveBannerIdle_${kind}`;
  return 'stoveBannerIdle';
}
