import type { Point } from '$lib/core/chart';
import type { OpenLoopRun } from '$lib/core/types';

export interface ReplayLines {
  recorded: Point[];
  candidate: Point[];
  upper: Point[];
  lower: Point[];
  differs: number;
}

/**
 * Step-shaped series of an open-loop run: the recorded and candidate setpoints, the band between them
 * (each value held until the next tick so the band follows the steps) and the share of ticks
 * where they differ.
 */
export function replayLines(openLoop: Pick<OpenLoopRun, 'series' | 'to'>): ReplayLines {
  const { at, recorded, candidate } = openLoop.series;
  const end = Date.parse(openLoop.to);
  const out: ReplayLines = { recorded: [], candidate: [], upper: [], lower: [], differs: 0 };
  let both = 0;
  at.forEach((iso, i) => {
    const t = Date.parse(iso);
    const r = recorded[i];
    const c = candidate[i];
    if (typeof r === 'number') out.recorded.push([t, r]);
    if (typeof c === 'number') out.candidate.push([t, c]);
    if (typeof r !== 'number' || typeof c !== 'number') return;
    both += 1;
    if (r !== c) out.differs += 1;
    const next = at[i + 1];
    const until = next === undefined ? Math.max(end, t) : Date.parse(next);
    const high = Math.max(r, c);
    const low = Math.min(r, c);
    out.upper.push([t, high], [until, high]);
    out.lower.push([t, low], [until, low]);
  });
  out.differs = both > 0 ? out.differs / both : 0;
  return out;
}

export type Limitation = 'room_signal' | 'room_profile' | 'other';

/**
 * Classify a replay limitation sentence from the server so it can be shown in the UI language;
 * unknown sentences are shown as they are.
 */
export function limitationKind(text: string): Limitation {
  if (/room signal/i.test(text)) return 'room_signal';
  if (/freshness|sensor profile/i.test(text)) return 'room_profile';
  return 'other';
}
