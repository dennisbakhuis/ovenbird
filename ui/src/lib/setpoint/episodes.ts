import type { Point } from '$lib/core/chart';
import { reasonCategory, type ReasonCategory } from './series';
import type { AlarmEvent, DecisionSeries } from '$lib/core/types';

export type EpisodeKind = 'decisions' | 'hold' | 'gap';

export interface Episode {
  kind: EpisodeKind;
  group: string;
  from: number;
  to: number;
  last: number;
  reason: string;
  reasons: string[];
  bindings: string[];
  ladder: string | null;
  category: ReasonCategory;
  ticks: number;
  setpointFirst: number | null;
  setpointLast: number | null;
  setpointMin: number | null;
  setpointMax: number | null;
  changes: number;
  steps: Point[];
  configVersion: number | null;
  versionFrom: number | null;
  ongoing: boolean;
  holdReason: string | null;
}

export interface HoldInterval {
  from: number;
  to: number;
  reason: string;
  ongoing: boolean;
}

export interface EpisodeOptions {
  endT?: number;
  gapMs?: number;
  holds?: HoldInterval[];
}

const MINUTE = 60_000;
const START_GROUP = new Set(['start_ramp', 'cycling_protect']);
const KEEP_GROUP = new Set(['deadband_hold', 'dwell_hold']);
const STEADY_GROUPS = new Set([
  'room_feedback',
  'curve',
  'room_stale',
  'room_implausible',
  'plan_preheat',
  'plan_setback',
  'stove',
]);

/**
 * Merge group of a reason: a compressor start (start ramp and cycling protection alternate while
 * the water warms up) is one group, dead band and wait time ("the setpoint stays") are one group;
 * every other reason is its own group.
 */
export function episodeGroup(reason: string): string {
  if (START_GROUP.has(reason)) return 'start';
  if (KEEP_GROUP.has(reason)) return 'keep';
  return reason;
}

function ladderClass(ladder: string | null): string {
  return ladder === 'hold' || ladder === 'refuse' ? ladder : 'control';
}

function emptyEpisode(t: number, reason: string, ladder: string | null): Episode {
  return {
    kind: 'decisions',
    group: episodeGroup(reason),
    from: t,
    to: t,
    last: t,
    reason: START_GROUP.has(reason) ? 'start_ramp' : reason,
    reasons: [],
    bindings: [],
    ladder,
    category: reasonCategory(START_GROUP.has(reason) ? 'start_ramp' : reason),
    ticks: 0,
    setpointFirst: null,
    setpointLast: null,
    setpointMin: null,
    setpointMax: null,
    changes: 0,
    steps: [],
    configVersion: null,
    versionFrom: null,
    ongoing: false,
    holdReason: null,
  };
}

function addTick(
  episode: Episode,
  t: number,
  reason: string,
  binding: string | null,
  setpoint: number | null,
  version: number | null,
): void {
  episode.ticks += 1;
  episode.last = t;
  if (!episode.reasons.includes(reason)) episode.reasons.push(reason);
  if (binding !== null && !episode.bindings.includes(binding)) episode.bindings.push(binding);
  if (version !== null) episode.configVersion = version;
  if (setpoint === null) return;
  if (episode.setpointFirst === null) episode.setpointFirst = setpoint;
  if (episode.setpointLast !== null && episode.setpointLast !== setpoint) episode.changes += 1;
  if (episode.setpointLast !== setpoint) episode.steps.push([t, setpoint]);
  episode.setpointLast = setpoint;
  episode.setpointMin = Math.min(episode.setpointMin ?? setpoint, setpoint);
  episode.setpointMax = Math.max(episode.setpointMax ?? setpoint, setpoint);
}

function absorb(into: Episode, other: Episode): void {
  into.to = other.to;
  into.last = other.last;
  into.ticks += other.ticks;
  into.ongoing = other.ongoing;
  for (const reason of other.reasons) if (!into.reasons.includes(reason)) into.reasons.push(reason);
  for (const binding of other.bindings)
    if (!into.bindings.includes(binding)) into.bindings.push(binding);
  if (other.configVersion !== null) into.configVersion = other.configVersion;
  for (const step of other.steps) {
    if (into.setpointLast !== null && into.setpointLast === step[1]) continue;
    if (into.setpointLast !== null) into.changes += 1;
    into.steps.push(step);
    into.setpointFirst ??= step[1];
    into.setpointLast = step[1];
    into.setpointMin = Math.min(into.setpointMin ?? step[1], step[1]);
    into.setpointMax = Math.max(into.setpointMax ?? step[1], step[1]);
  }
}

/**
 * Stitch a compressor start back together: the ramp releases in steps with dead-band ticks in
 * between, so start, keep, start … runs (without a version change) become one start episode.
 */
function stitchStarts(runs: Episode[]): Episode[] {
  const out: Episode[] = [];
  let i = 0;
  while (i < runs.length) {
    const run = runs[i] as Episode;
    out.push(run);
    i += 1;
    if (run.group !== 'start') continue;
    while (
      runs[i]?.group === 'keep' &&
      runs[i + 1]?.group === 'start' &&
      runs[i]?.versionFrom === null &&
      runs[i + 1]?.versionFrom === null
    ) {
      absorb(run, runs[i] as Episode);
      absorb(run, runs[i + 1] as Episode);
      i += 2;
    }
  }
  return out;
}

function gapEpisode(from: number, to: number): Episode {
  return {
    ...emptyEpisode(from, 'gap', null),
    kind: 'gap',
    group: 'gap',
    reason: 'gap',
    to,
    last: from,
  };
}

/**
 * Merge decision ticks into episodes, oldest first. A new episode starts when the reason group,
 * the ladder class (control, hold, refuse) or the config version changes, or after a gap in the
 * ticks. Dead-band and wait-time ticks keep the setpoint by definition and join the running
 * episode instead of splitting it. Gaps longer than `gapMs` become their own entries; command
 * holds are added as entries of their own, sorted by start.
 */
export function buildEpisodes(series: DecisionSeries, options: EpisodeOptions = {}): Episode[] {
  const interval = series.step > 0 ? series.step * 1000 : MINUTE;
  const gapMs = options.gapMs ?? Math.max(3 * interval, 5 * MINUTE);
  const endT = options.endT ?? Date.parse(series.to);
  const out: Episode[] = [];
  let current: Episode | null = null;
  let group: string | null = null;
  let previousT: number | null = null;
  let previousVersion: number | null = null;

  for (let i = 0; i < series.at.length; i += 1) {
    const t = Date.parse(series.at[i] ?? '');
    const reason = series.reason[i] ?? null;
    if (!Number.isFinite(t) || reason === null) continue;
    const ladder = series.ladder[i] ?? null;
    const version = series.config_version[i] ?? null;

    if (current !== null && previousT !== null && t - previousT > gapMs) {
      current.to = previousT + interval;
      current = null;
      out.push(gapEpisode(previousT + interval, t));
    }
    const versionChanged =
      version !== null && previousVersion !== null && version !== previousVersion;
    const tickGroup = episodeGroup(reason);
    const joins =
      current !== null &&
      !versionChanged &&
      ladderClass(current.ladder) === ladderClass(ladder) &&
      (tickGroup === group || (tickGroup === 'keep' && STEADY_GROUPS.has(group ?? '')));
    if (!joins) {
      if (current !== null) current.to = t;
      current = emptyEpisode(t, reason, ladder);
      if (versionChanged) current.versionFrom = previousVersion;
      out.push(current);
      group = tickGroup;
    }
    if (current !== null) {
      addTick(current, t, reason, series.binding[i] ?? null, series.setpoint[i] ?? null, version);
    }
    previousT = t;
    if (version !== null) previousVersion = version;
  }

  if (current !== null) {
    const live = Number.isFinite(endT) && endT - current.last <= gapMs;
    current.to = live ? Math.max(endT, current.last) : current.last + interval;
    current.ongoing = live;
  }

  const merged = stitchStarts(out);
  for (const hold of options.holds ?? []) {
    merged.push({
      ...emptyEpisode(hold.from, 'hold', null),
      kind: 'hold',
      group: 'hold',
      reason: 'hold',
      category: 'manual',
      to: hold.to,
      last: hold.from,
      ongoing: hold.ongoing,
      holdReason: hold.reason,
    });
  }
  return merged.sort((a, b) => a.from - b.from || kindOrder(a) - kindOrder(b));
}

function kindOrder(episode: Episode): number {
  return episode.kind === 'hold' ? 0 : episode.kind === 'gap' ? 1 : 2;
}

/**
 * Command-hold intervals from the alarm journal: a `started` event opens a hold, the next
 * `expired` or `released` closes it; a hold still open runs until `endT`.
 */
export function holdIntervals(events: AlarmEvent[], endT: number): HoldInterval[] {
  const sorted = events
    .filter((event) => event.code === 'command_hold')
    .map((event) => ({ event, t: Date.parse(event.at) }))
    .filter((item) => Number.isFinite(item.t))
    .sort((a, b) => a.t - b.t);
  const out: HoldInterval[] = [];
  let open: HoldInterval | null = null;
  for (const { event, t } of sorted) {
    const reason = typeof event.detail['reason'] === 'string' ? event.detail['reason'] : '';
    if (event.event === 'started') {
      if (open) out.push({ ...open, to: t, ongoing: false });
      open = { from: t, to: endT, reason, ongoing: true };
    } else if ((event.event === 'expired' || event.event === 'released') && open) {
      out.push({ ...open, to: t, ongoing: false });
      open = null;
    }
  }
  if (open) out.push(open);
  return out;
}

/**
 * The decision episode that covers `t`, or null.
 */
export function episodeAt(episodes: Episode[], t: number): Episode | null {
  return (
    episodes.find(
      (episode) =>
        episode.kind === 'decisions' &&
        t >= episode.from &&
        t < Math.max(episode.to, episode.last + 1),
    ) ?? null
  );
}
