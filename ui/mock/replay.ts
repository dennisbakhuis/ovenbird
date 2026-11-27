import type { ConfigVersion } from '../src/lib/core/types';
import type { Scenario } from './scenario.ts';
import { minuteAt } from './shadow.ts';

const MINUTE = 60_000;
const DAY = 86_400_000;
const TIMEZONE = 'Europe/Amsterdam';
const SIGNAL = 'main/Z1_Water_Target_Temp';
const RETENTION_DAYS = 30;
const MAX_DAYS = 31;
const STEPS = [60, 300, 900, 3600];
const RUN_MS = 2_400;
const KEEP_MS = 3_600_000;
const BUDGET = 150;
const MAX_EPISODES = 500;
const COMFORT_DEFAULT = 21;
const CURVE_GAIN = 2;
const PART_EVERY = 9;

type Kind = 'active' | 'version' | 'draft';

interface ReplayConfig {
  kind: Kind;
  version: number | null;
  changes?: Record<string, unknown>;
}

interface Job {
  id: string;
  key: string;
  from: number;
  to: number;
  step: number;
  threshold: number;
  config: ReplayConfig;
  delta: number;
  now: number;
  modelPlan: boolean;
  versions: { version: number; at: number }[];
  startedMs: number;
  cancelledMs: number | null;
  result: unknown;
}

export interface ReplayContext {
  now: number;
  key: string;
  scenario: Scenario;
  version: number;
  stored: Record<string, unknown>;
  versions: ConfigVersion[];
}

const jobs = new Map<string, Job>();
let sequence = 0;

const dayFormat = new Intl.DateTimeFormat('en-CA', {
  timeZone: TIMEZONE,
  year: 'numeric',
  month: '2-digit',
  day: '2-digit',
});
const hourFormat = new Intl.DateTimeFormat('en-GB', {
  timeZone: TIMEZONE,
  hour: '2-digit',
  hourCycle: 'h23',
});
const iso = (ms: number) => new Date(ms).toISOString();
const round = (value: number, digits = 2) => Math.round(value * 10 ** digits) / 10 ** digits;
const localDate = (ms: number) => dayFormat.format(ms);
const localHour = (ms: number) => Number(hourFormat.format(ms));

const QUARTER = 15 * MINUTE;

function days(from: number, to: number): { date: string; from: number; to: number }[] {
  const out: { date: string; from: number; to: number }[] = [];
  let start = from;
  while (start < to) {
    const date = localDate(start);
    let next = Math.floor(start / QUARTER) * QUARTER + QUARTER;
    while (next < to && localDate(next) === date) next += QUARTER;
    out.push({ date, from: start, to: Math.min(next, to) });
    start = Math.min(next, to);
  }
  return out;
}

const dayIndex = (ms: number) => Math.floor(Date.parse(`${localDate(ms)}T00:00:00Z`) / DAY);
const stored = (ms: number, now: number) => ms >= now - RETENTION_DAYS * DAY && ms < now;
const partDay = (ms: number) => dayIndex(ms) % PART_EVERY === 4;
const partMissing = (ms: number) => partDay(ms) && localHour(ms) >= 9 && localHour(ms) < 18;

function hasDecision(ms: number, now: number): boolean {
  return stored(ms, now) && !partMissing(ms);
}

function versionsOf(context: ReplayContext): { version: number; at: number }[] {
  return context.versions
    .map((item) => ({ version: item.version, at: Date.parse(item.applied_at ?? item.created_at) }))
    .filter((item) => Number.isFinite(item.at))
    .sort((a, b) => a.at - b.at);
}

function versionAt(versions: { version: number; at: number }[], ms: number): number | null {
  let found: number | null = null;
  for (const item of versions) if (item.at <= ms) found = item.version;
  return found;
}

/**
 * `GET replay/coverage`: the stored decisions per local day of the last 31 days (30 days kept,
 * the oldest day empty), with a day every ninth day missing its working hours (a service that was
 * down), and the configuration versions they ran with.
 */
export function makeCoverage(context: ReplayContext, from: number | null, to: number | null) {
  const end = to ?? context.now;
  const start = from ?? end - MAX_DAYS * DAY;
  const versions = versionsOf(context);
  const perVersion = new Map<
    string,
    { version: number | null; from: number; to: number; n: number }
  >();
  const list = days(start, end).map((day) => {
    let decisions = 0;
    let first: number | null = null;
    let last: number | null = null;
    for (let ms = Math.ceil(day.from / MINUTE) * MINUTE; ms < day.to; ms += MINUTE) {
      if (!hasDecision(ms, context.now)) continue;
      decisions += 1;
      first ??= ms;
      last = ms;
      const version = versionAt(versions, ms);
      const id = String(version);
      const entry = perVersion.get(id) ?? { version, from: ms, to: ms, n: 0 };
      entry.to = ms + MINUTE;
      entry.n += 1;
      perVersion.set(id, entry);
    }
    return {
      date: day.date,
      from: iso(day.from),
      to: iso(day.to),
      decisions,
      expected: Math.round((day.to - day.from) / MINUTE),
      first: first === null ? null : iso(first),
      last: last === null ? null : iso(last),
    };
  });
  const firstStored = list.find((day) => day.first)?.first ?? null;
  const lastStored = [...list].reverse().find((day) => day.last)?.last ?? null;
  return {
    from: iso(start),
    to: iso(end),
    timezone: TIMEZONE,
    interval_s: 60,
    retention_days: RETENTION_DAYS,
    max_days: MAX_DAYS,
    oldest: firstStored,
    newest: lastStored,
    days: list,
    versions: [...perVersion.values()]
      .sort((a, b) => a.from - b.from)
      .map((item) => ({
        version: item.version,
        from: iso(item.from),
        to: iso(item.to),
        decisions: item.n,
      })),
  };
}

function comfortOf(values: Record<string, unknown> | undefined): number {
  const value = values?.['control_comfort_c'];
  return typeof value === 'number' ? value : COMFORT_DEFAULT;
}

/** The replayed setpoint's offset from the recorded one: the curve shift of a comfort change. */
function offsetOf(context: ReplayContext, config: ReplayConfig): number {
  const active = comfortOf(context.stored);
  if (config.kind === 'version') {
    const found = context.versions.find((item) => item.version === config.version);
    return CURVE_GAIN * (comfortOf(found?.values as Record<string, unknown>) - active);
  }
  if (config.kind === 'draft' && config.changes && 'control_comfort_c' in config.changes)
    return CURVE_GAIN * (comfortOf(config.changes) - active);
  return 0;
}

type Refusal = { status: number; body: { detail: string } };

/**
 * `POST replay`: checks the body as the service does and starts a job that runs for 2.4 s of
 * real time (`replay` then `compare`); a new job cancels the one still running. 403 for a
 * `role:viewer` scenario.
 */
export function startReplay(
  context: ReplayContext,
  body: Record<string, unknown>,
): { status: number; body: unknown } {
  if (context.scenario.role === 'viewer')
    return { status: 403, body: { detail: 'this action needs the operate role' } };
  const from = typeof body['from'] === 'string' ? Date.parse(body['from']) : NaN;
  const to = typeof body['to'] === 'string' ? Date.parse(body['to']) : NaN;
  const bad = (detail: string): Refusal => ({ status: 400, body: { detail } });
  if (!Number.isFinite(from) || !Number.isFinite(to)) return bad('from and to are required');
  if (to <= from) return bad('from must lie before to');
  if (to - from > MAX_DAYS * DAY) return bad(`the period must be at most ${MAX_DAYS} days`);
  const kind = body['config'] ?? 'active';
  if (kind !== 'active' && kind !== 'version' && kind !== 'draft')
    return bad('config must be active, version or draft');
  const step = body['step'] ?? STEPS.find((s) => (to - from) / 1000 / s <= 1500) ?? 3600;
  if (typeof step !== 'number' || !STEPS.includes(step))
    return bad('step must be one of 60, 300, 900, 3600');
  const threshold = body['threshold_k'] ?? 1;
  if (typeof threshold !== 'number' || !(threshold > 0) || threshold > 20)
    return bad('threshold_k must be above 0 and at most 20');
  const config: ReplayConfig = { kind, version: context.version };
  if (kind === 'version') {
    const version = body['version'];
    if (typeof version !== 'number' || !context.versions.some((v) => v.version === version))
      return { status: 404, body: { detail: `version ${String(version)} not found` } };
    config.version = version;
  }
  if (kind === 'draft') {
    const changes = body['changes'] ?? {};
    if (typeof changes !== 'object' || changes === null || Array.isArray(changes))
      return bad('changes must be an object');
    config.changes = changes as Record<string, unknown>;
  }
  for (const job of jobs.values())
    if (job.key === context.key && state(job) === 'running') job.cancelledMs = Date.now();
  expire();
  sequence += 1;
  const job: Job = {
    id: `mock${sequence.toString(16).padStart(6, '0')}`,
    key: context.key,
    from,
    to,
    step,
    threshold,
    config,
    delta: offsetOf(context, config),
    now: context.now,
    modelPlan: context.scenario.modelplan === 'on',
    versions: versionsOf(context),
    startedMs: Date.now(),
    cancelledMs: null,
    result: null,
  };
  jobs.set(job.id, job);
  return { status: 202, body: jobJson(job) };
}

/** `GET replay/{id}`: the job as it stands now; 404 for an unknown or expired one. */
export function replayJob(id: string): { status: number; body: unknown } {
  expire();
  const job = jobs.get(id);
  return job ? { status: 200, body: jobJson(job) } : { status: 404, body: { detail: 'not found' } };
}

/** `POST replay/{id}/cancel`: stops a running job; 403 for a `role:viewer` scenario. */
export function cancelReplay(id: string, scenario: Scenario): { status: number; body: unknown } {
  if (scenario.role === 'viewer')
    return { status: 403, body: { detail: 'this action needs the operate role' } };
  const job = jobs.get(id);
  if (!job) return { status: 404, body: { detail: 'not found' } };
  if (state(job) === 'running') job.cancelledMs = Date.now();
  return { status: 200, body: jobJson(job) };
}

function expire(): void {
  const now = Date.now();
  for (const [id, job] of jobs) if (now - job.startedMs > KEEP_MS) jobs.delete(id);
}

function state(job: Job): 'running' | 'done' | 'cancelled' {
  if (job.cancelledMs !== null) return 'cancelled';
  return Date.now() - job.startedMs >= RUN_MS ? 'done' : 'running';
}

function jobJson(job: Job) {
  const current = state(job);
  const elapsed = (job.cancelledMs ?? Date.now()) - job.startedMs;
  const progress = current === 'done' ? 1 : round(Math.min(0.99, elapsed / RUN_MS), 3);
  if (current === 'done') job.result ??= makeResult(job);
  return {
    id: job.id,
    state: current,
    phase: current === 'done' ? 'done' : progress < 0.75 ? 'replay' : 'compare',
    progress,
    from: iso(job.from),
    to: iso(job.to),
    config: job.config,
    started_at: iso(job.startedMs),
    finished_at: current === 'running' ? null : iso(job.cancelledMs ?? job.startedMs + RUN_MS),
    error: null,
    result: current === 'done' ? job.result : null,
  };
}

interface Row {
  ts: number;
  recorded: number | null;
  replayed: number | null;
  pump: number | null;
  reason: string | null;
}

function changes(values: (number | null)[]): number {
  let count = 0;
  let last: number | null = null;
  for (const value of values) {
    if (value === null) continue;
    if (last !== null && value !== last) count += 1;
    last = value;
  }
  return count;
}

function shares(counts: Map<string, number>, total: number): Record<string, number> {
  const out: Record<string, number> = {};
  for (const [code, n] of [...counts].sort((a, b) => b[1] - a[1]))
    out[code] = total ? round(n / total, 3) : 0;
  return out;
}

/** The replay of a job's period: the mock's recorded decisions shifted by the config offset. */
function makeResult(job: Job) {
  const started = performance.now();
  const end = Math.min(job.to, job.now);
  const rows: Row[] = [];
  const scenario: Scenario = {};
  for (let ts = Math.ceil(job.from / MINUTE) * MINUTE; ts < end; ts += MINUTE) {
    const minute = minuteAt(ts, job.now, scenario);
    const has = hasDecision(ts, job.now) && minute.ovenbird !== null;
    const recorded = has ? minute.ovenbird : null;
    const night = localHour(ts) >= 23 || localHour(ts) < 6;
    const offset = job.config.kind === 'draft' && night ? 0 : job.delta;
    rows.push({
      ts,
      recorded,
      replayed: recorded === null ? null : Math.round(recorded + offset),
      pump: minute.pump,
      reason: has ? minute.reason : null,
    });
  }
  const ticks = rows.filter((row) => row.replayed !== null).length;
  const compared = rows.filter((row) => row.replayed !== null && row.pump !== null);
  const diffs = compared.map((row) => (row.replayed as number) - (row.pump as number));
  const above = diffs.filter((d) => d > job.threshold).length;
  const below = diffs.filter((d) => d < -job.threshold).length;
  const vsRecorded = rows
    .filter((row) => row.replayed !== null)
    .map((row) => (row.replayed as number) - (row.recorded as number));
  const reasons = new Map<string, number>();
  for (const row of rows)
    if (row.reason) reasons.set(row.reason, (reasons.get(row.reason) ?? 0) + 1);
  const dayRows = days(job.from, end).map((day) => {
    const inside = rows.filter((row) => row.ts >= day.from && row.ts < day.to);
    return {
      date: day.date,
      from: iso(day.from),
      to: iso(day.to),
      writes: changes(inside.map((row) => row.replayed)),
      changes_recorded: changes(inside.map((row) => row.recorded)),
      sent_recorded: 0,
    };
  });
  const writes = changes(rows.map((row) => row.replayed));
  const maxDay = Math.max(0, ...dayRows.map((day) => day.writes));
  const spanDays = Math.max((end - job.from) / DAY, 1 / 1440);
  const episodes = findEpisodes(rows, job.threshold);
  const versionTicks = new Map<number | null, number>();
  for (const row of rows)
    if (row.recorded !== null) {
      const version = versionAt(job.versions, row.ts);
      versionTicks.set(version, (versionTicks.get(version) ?? 0) + 1);
    }
  return {
    from: iso(job.from),
    to: iso(job.to),
    config: job.config,
    ticks,
    skipped: 0,
    open_loop: true,
    threshold_k: job.threshold,
    step: job.step,
    timezone: TIMEZONE,
    signal: SIGNAL,
    identity: {
      ok: ticks > 0 ? true : null,
      ticks,
      mismatches: 0,
      first_mismatch: null,
      unknown: 0,
      versions: [...versionTicks].map(([version, n]) => ({
        version,
        ticks: n,
        mismatches: 0,
        first_mismatch: null,
      })),
    },
    summary: {
      minutes: rows.length,
      compared_minutes: compared.length,
      gap_minutes: rows.length - compared.length,
      coverage: rows.length ? round(compared.length / rows.length, 3) : 0,
      mean_abs_k: diffs.length
        ? round(diffs.reduce((s, d) => s + Math.abs(d), 0) / diffs.length)
        : null,
      max_abs_k: diffs.length ? round(Math.max(...diffs.map(Math.abs))) : null,
      bias_k: diffs.length ? round(diffs.reduce((s, d) => s + d, 0) / diffs.length) : null,
      hours_over: round((above + below) / 60),
      above_pump_min: above,
      below_pump_min: below,
      differs_recorded_min: vsRecorded.filter((d) => d !== 0).length,
      above_recorded_min: vsRecorded.filter((d) => d > 0).length,
      below_recorded_min: vsRecorded.filter((d) => d < 0).length,
      mean_diff_recorded_k: vsRecorded.length
        ? round(vsRecorded.reduce((s, d) => s + d, 0) / vsRecorded.length)
        : 0,
      changes_recorded: changes(rows.map((row) => row.recorded)),
      changes_replayed: writes,
      changes_pump: changes(rows.map((row) => row.pump)),
      writes,
      writes_per_day: round(writes / spanDays, 1),
      max_writes_day: maxDay,
      days_over_budget: dayRows.filter((day) => day.writes > BUDGET).length,
      budget: BUDGET,
      budget_use: round(maxDay / BUDGET, 3),
      sent_recorded: 0,
      share_safety_clamped: ticks ? 0.03 : 0,
      share_feedback_limited: 0,
      ladder: !ticks
        ? {}
        : job.modelPlan
          ? { model_plan: 0.58, schedule_curve_feedback: 0.36, curve_only: 0.06 }
          : { schedule_curve_feedback: 0.94, curve_only: 0.06 },
      reason: shares(reasons, ticks),
      binding: ticks ? { deadband: 0.41, dwell: 0.12, safety_min: 0.03 } : {},
      episodes: episodes.length,
      longest_episode_min: Math.max(0, ...episodes.map((ep) => ep.minutes)),
    },
    days: dayRows,
    episodes_total: episodes.length,
    episodes: episodes.slice(-MAX_EPISODES),
    series: series(rows, job.step),
    limitations:
      job.config.kind === 'draft' && Object.keys(job.config.changes ?? {}).length
        ? ['The room responds to the recorded control, not to the draft (open loop).']
        : [],
    run_s: round((performance.now() - started) / 1000 + RUN_MS / 1000, 1),
  };
}

function findEpisodes(rows: Row[], threshold: number) {
  const found: { minutes: number; [key: string]: unknown }[] = [];
  let open: { start: number; end: number; atMax: Row; first: Row; maxDiff: number } | null = null;
  const close = (endedBy: 'converged' | 'gap' | 'open') => {
    if (!open) return;
    found.push({
      start: iso(open.start),
      end: iso(open.end),
      minutes: Math.round((open.end - open.start) / MINUTE),
      max_abs_k: round(Math.abs(open.maxDiff)),
      max_diff_k: round(open.maxDiff),
      ovenbird_c: open.atMax.replayed,
      pump_c: open.atMax.pump,
      recorded_c: open.atMax.recorded,
      reason: open.first.reason,
      reason_at_max: open.atMax.reason,
      mode: 'shadow',
      writer: 'other',
      ended_by: endedBy,
    });
    open = null;
  };
  for (const row of rows) {
    const diff = row.replayed === null || row.pump === null ? null : row.replayed - row.pump;
    if (diff !== null && Math.abs(diff) > threshold) {
      if (!open)
        open = { start: row.ts, end: row.ts + MINUTE, atMax: row, first: row, maxDiff: diff };
      else {
        open.end = row.ts + MINUTE;
        if (Math.abs(diff) > Math.abs(open.maxDiff)) {
          open.maxDiff = diff;
          open.atMax = row;
        }
      }
      continue;
    }
    close(diff === null ? 'gap' : 'converged');
  }
  close('open');
  return found;
}

function series(rows: Row[], step: number) {
  const stepMs = step * 1000;
  const out = {
    at: [] as string[],
    recorded: [] as (number | null)[],
    replayed: [] as (number | null)[],
    pump: [] as (number | null)[],
  };
  let index = 0;
  while (index < rows.length) {
    const bucket = Math.floor((rows[index] as Row).ts / stepMs) * stepMs;
    const last = {
      recorded: null as number | null,
      replayed: null as number | null,
      pump: null as number | null,
    };
    while (index < rows.length && (rows[index] as Row).ts < bucket + stepMs) {
      const row = rows[index] as Row;
      last.recorded = row.recorded ?? last.recorded;
      last.replayed = row.replayed ?? last.replayed;
      last.pump = row.pump ?? last.pump;
      index += 1;
    }
    out.at.push(iso(bucket));
    out.recorded.push(last.recorded);
    out.replayed.push(last.replayed);
    out.pump.push(last.pump);
  }
  return out;
}

/** Forget every replay job (between tests). */
export function resetReplays(): void {
  jobs.clear();
}
