import type { QuietWindow } from '$lib/core/fieldFormat';

export interface Segment {
  from: number;
  to: number;
  level: number;
  index: number;
}

export const MAX_WINDOWS = 4;
export const DAY_MINUTES = 1440;

/**
 * Minutes since midnight of an "HH:MM" time, or null when malformed.
 */
export function toMinutes(time: string): number | null {
  const match = /^(\d{1,2}):(\d{2})$/.exec(time);
  if (!match) return null;
  const hours = Number(match[1]);
  const minutes = Number(match[2]);
  return hours < 24 && minutes < 60 ? hours * 60 + minutes : null;
}

/**
 * Split windows into segments within one day; a window that ends before it starts wraps past
 * midnight and becomes two segments.
 */
export function windowSegments(windows: QuietWindow[]): Segment[] {
  const out: Segment[] = [];
  windows.forEach((w, index) => {
    const from = toMinutes(w.start);
    const to = toMinutes(w.end);
    if (from === null || to === null || from === to) return;
    if (from < to) out.push({ from, to, level: w.level, index });
    else {
      out.push({ from, to: DAY_MINUTES, level: w.level, index });
      if (to > 0) out.push({ from: 0, to, level: w.level, index });
    }
  });
  return out;
}

/**
 * Indexes of windows that overlap another window.
 */
export function overlapping(windows: QuietWindow[]): number[] {
  const segments = windowSegments(windows);
  const hit = new Set<number>();
  for (const a of segments)
    for (const b of segments)
      if (a.index < b.index && a.from < b.to && b.from < a.to) {
        hit.add(a.index);
        hit.add(b.index);
      }
  return [...hit].sort();
}
