import type { Scenario } from './scenario.ts';
import { makeNotifications } from './system.ts';

export interface MockResult {
  status: number;
  body: unknown;
}

const HOUR = 3_600_000;
const DAY = 24 * HOUR;
const SHORT_RUN_MIN = 20;
const BINS = [0, 10, 20, 30, 60, 120, 240];
const TIMEOUT_S = 192;
const SNAPSHOT_AGE_MS = 4 * DAY + 5 * HOUR;

interface MockItem {
  kind: string;
  signal: string;
  snapshot: number;
  before: number;
  sentAfterS: number | null;
  verifiedAfterS: number | null;
}

const ITEMS: MockItem[] = [
  {
    kind: 'water_setpoint',
    signal: 'main/Z1_Water_Target_Temp',
    snapshot: 32,
    before: 29,
    sentAfterS: 2,
    verifiedAfterS: 7,
  },
  {
    kind: 'max_pump_duty',
    signal: 'main/Max_Pump_Duty',
    snapshot: 160,
    before: 159,
    sentAfterS: 4,
    verifiedAfterS: 10,
  },
  {
    kind: 'quiet_mode',
    signal: 'main/Quiet_Mode_Level',
    snapshot: 0,
    before: 0,
    sentAfterS: null,
    verifiedAfterS: null,
  },
];

interface MockRun {
  startedMs: number;
  rehearsal: boolean;
  reason: string | null;
  by: string;
  pausedBefore: boolean;
  snapshotTakenMs: number;
  settled: boolean;
}

interface KeyState {
  run: MockRun | null;
  lastRehearsal: Record<string, unknown> | null;
  lastDry: Record<string, unknown> | null;
  manualMs: number | null;
  releasedMs: number | null;
  snapshotMs: number | null;
  paused: boolean;
}

const states = new Map<string, KeyState>();

function stateOf(key: string): KeyState {
  let state = states.get(key);
  if (!state) {
    state = {
      run: null,
      lastRehearsal: null,
      lastDry: null,
      manualMs: null,
      releasedMs: null,
      snapshotMs: null,
      paused: false,
    };
    states.set(key, state);
  }
  return state;
}

const iso = (ms: number) => new Date(ms).toISOString();

function snapshotTaken(now: number, state?: KeyState): number {
  return state?.snapshotMs ?? Math.floor((now - SNAPSHOT_AGE_MS) / 60_000) * 60_000;
}

/**
 * Whether the scenario has a go-live snapshot: none with `snapshot:none`, and none in a configured
 * Shadow (`mode:shadow`), which never went live.
 */
function hasSnapshot(scenario: Scenario): boolean {
  return scenario.snapshot !== 'none' && scenario.mode !== 'shadow';
}

/**
 * Whether the browser's key has a snapshot to rehearse against: the go-live one, or one an admin
 * captured by hand in Shadow (`POST control/snapshot`).
 */
function hasAnySnapshot(scenario: Scenario, state: KeyState): boolean {
  return (hasSnapshot(scenario) && state.releasedMs === null) || state.manualMs !== null;
}

function runDuration(): number {
  return Math.max(...ITEMS.map((item) => item.verifiedAfterS ?? 0));
}

/**
 * The JSON of a mock release at `now`: items advance with the time since it started (sent after a
 * few seconds, verified a few seconds later; quiet mode is already as recorded).
 */
function runJson(run: MockRun, now: number): Record<string, unknown> {
  const elapsed = Math.max(0, (now - run.startedMs) / 1000);
  const total = runDuration();
  const done = elapsed >= total;
  const items = ITEMS.map((item) => {
    if (item.sentAfterS === null)
      return {
        kind: item.kind,
        signal: item.signal,
        snapshot: item.snapshot,
        before: item.before,
        target: null,
        status: 'unchanged',
        ok: true,
        detail: `the pump already reports ${item.snapshot}`,
        at: iso(run.startedMs),
      };
    const verified = item.verifiedAfterS !== null && elapsed >= item.verifiedAfterS;
    const sent = elapsed >= item.sentAfterS;
    const status = verified ? 'verified' : sent ? 'sent' : 'queued';
    const atS = verified ? (item.verifiedAfterS ?? 0) : sent ? item.sentAfterS : 0;
    return {
      kind: item.kind,
      signal: item.signal,
      snapshot: item.snapshot,
      before: item.before,
      target: item.snapshot,
      status,
      ok: verified,
      detail: verified
        ? `release: ${run.by}: applied in ${Math.round(atS - item.sentAfterS)} s`
        : sent
          ? `release: ${run.by}: sent, waiting for the pump to report ${item.snapshot}`
          : `release: ${run.by}: queued`,
      at: iso(run.startedMs + atS * 1000),
    };
  });
  const duration = Math.round((done ? total : elapsed) * 10) / 10;
  return {
    started_at: iso(run.startedMs),
    finished_at: done ? iso(run.startedMs + total * 1000) : null,
    done,
    outcome: done ? 'ok' : 'running',
    rehearsal: run.rehearsal,
    by: run.by,
    reason: run.reason,
    paused_before: run.pausedBefore,
    duration_s: duration,
    within_limit: duration <= 300,
    snapshot_taken_at: iso(run.snapshotTakenMs),
    items,
  };
}

function settle(state: KeyState, now: number): void {
  const run = state.run;
  if (!run || run.settled || now - run.startedMs < runDuration() * 1000) return;
  run.settled = true;
  if (run.rehearsal) state.lastRehearsal = runJson(run, now);
  state.releasedMs = run.startedMs + runDuration() * 1000;
}

/**
 * The release state of a browser's scenario key, as the control status shows it: `releasing`
 * while a release (or rehearsal) restores the snapshot, `paused` once it is done and until that
 * browser resumes, null otherwise. The shared mock pause is not touched, so parallel browsers keep
 * their own state.
 */
export function releaseHold(key: string, now: number): 'releasing' | 'paused' | null {
  const state = states.get(key);
  if (!state?.paused) return null;
  settle(state, now);
  const run = state.run;
  if (run && now - run.startedMs < runDuration() * 1000) return 'releasing';
  return 'paused';
}

/**
 * `POST control/resume` for a browser's scenario key: ends the pause a release left and, as the
 * service does at the next live tick, records a fresh go-live snapshot when the last one was used.
 * Refused (409) while a release runs.
 */
export function resumeRelease(key: string, now: number): MockResult | null {
  const hold = releaseHold(key, now);
  if (hold === 'releasing')
    return refusal('releasing', 'a release of control is in progress; resume when it is done');
  const state = states.get(key);
  if (hold === 'paused' && state) {
    state.paused = false;
    state.releasedMs = null;
    state.snapshotMs = Math.floor(now / 60_000) * 60_000;
  }
  return null;
}

/** `GET control/release` for a browser's scenario key. */
export function releaseState(key: string, now: number): unknown {
  const state = stateOf(key);
  settle(state, now);
  return {
    release: state.run ? runJson(state.run, now) : null,
    last_rehearsal: state.lastRehearsal,
    last_dry_rehearsal: state.lastDry,
    timeout_s: TIMEOUT_S,
  };
}

function refusal(code: string, message: string): MockResult {
  return { status: 409, body: { detail: { code, message } } };
}

/**
 * `POST control/release` for a browser's scenario key. A release or rehearsal is recorded per key
 * only: it pauses that key (see `releaseHold`) and uses its snapshot, while the shared mock pause
 * stays as it is. A browser with its own `tag` is not refused by a pause another browser made
 * (parallel tests share that state); `mode:*` and a key paused by its own release always refuse.
 */
export function startRelease(
  key: string,
  body: Record<string, unknown>,
  now: number,
  scenario: Scenario,
  publishing: boolean,
): MockResult {
  const state = stateOf(key);
  settle(state, now);
  if (state.run && now - state.run.startedMs < runDuration() * 1000)
    return refusal('in_progress', 'a release is already in progress');
  if (body['dry'] === true) {
    if (!hasAnySnapshot(scenario, state))
      return refusal('no_snapshot', 'no pump-state snapshot: capture one in shadow first');
    const plan = dryPlan(now, state, scenario);
    state.lastDry = plan;
    return { status: 200, body: { release: plan } };
  }
  if (scenario.mode !== undefined || state.paused || (!publishing && scenario.tag === undefined))
    return refusal(
      'not_publishing',
      `publishing is not enabled, so ovenbird has written nothing to restore: ${
        scenario.mode === 'shadow' ? 'control mode is shadow, not auto' : 'control is paused'
      }`,
    );
  if (!hasSnapshot(scenario) || state.releasedMs !== null)
    return refusal(
      'no_snapshot',
      'no pump-state snapshot was recorded (it is taken when ovenbird goes live)',
    );
  const reason = typeof body['reason'] === 'string' ? body['reason'].slice(0, 200) : null;
  const run: MockRun = {
    startedMs: now,
    rehearsal: body['rehearsal'] === true,
    reason: reason || null,
    by: `admin from 127.0.0.1${reason ? `: ${reason}` : ''}`,
    pausedBefore: false,
    snapshotTakenMs: snapshotTaken(now, state),
    settled: false,
  };
  state.run = run;
  state.paused = true;
  return { status: 202, body: { release: runJson(run, now) } };
}

/**
 * A dry rehearsal: the plan against the snapshot, done at once, nothing sent or paused.
 */
function dryPlan(now: number, state: KeyState, scenario: Scenario): Record<string, unknown> {
  const manual = !hasSnapshot(scenario) || state.releasedMs !== null;
  const taken = manual ? (state.manualMs ?? now) : snapshotTaken(now, state);
  return {
    started_at: iso(now),
    finished_at: iso(now),
    done: true,
    outcome: 'ok',
    rehearsal: true,
    dry: true,
    by: 'admin',
    reason: null,
    paused_before: false,
    duration_s: 0,
    within_limit: true,
    snapshot_taken_at: iso(taken),
    snapshot_origin: manual ? 'manual' : 'go_live',
    snapshot_age_s: Math.round((now - taken) / 1000),
    outside_c: 4.5,
    interrupted: false,
    items: ITEMS.map((item) =>
      item.sentAfterS === null
        ? {
            kind: item.kind,
            signal: item.signal,
            snapshot: item.snapshot,
            before: item.before,
            target: null,
            clamped: null,
            waited_for: null,
            status: 'unchanged',
            ok: true,
            detail: `the pump already reports ${item.snapshot}`,
            at: iso(now),
          }
        : {
            kind: item.kind,
            signal: item.signal,
            snapshot: item.snapshot,
            before: item.before,
            target: item.snapshot,
            clamped: null,
            waited_for: null,
            status: 'planned',
            ok: true,
            detail: `would restore ${item.before} → ${item.snapshot}`,
            at: iso(now),
          },
    ),
  };
}

function snapshotJson(now: number, state: KeyState, manual = false): Record<string, unknown> {
  const releasedMs = manual ? null : state.releasedMs;
  const taken = manual ? (state.manualMs ?? now) : snapshotTaken(now, state);
  const staleAfter = manual ? (7 * DAY) / 1000 : (30 * DAY) / 1000;
  const age = Math.round((now - taken) / 1000);
  return {
    taken_at: iso(taken),
    origin: manual ? 'manual' : 'go_live',
    by: manual ? 'admin' : null,
    outside_c: 4.5,
    age_s: age,
    stale: age > staleAfter,
    stale_after_s: staleAfter,
    previous_mode: 'shadow',
    own_values_possible: false,
    register: 'setcurves_target_high',
    complete: true,
    released_at: releasedMs === null ? null : iso(releasedMs),
    items: ITEMS.map((item) => ({ kind: item.kind, signal: item.signal, value: item.snapshot })),
    facts: {
      'main/Heating_Mode': 1,
      'main/Operating_Mode_State': 0,
      'main/Z1_Heat_Request_Temp': 32,
      'main/Z1_Curve_Target_High_Temp': 40,
      'main/Z1_Curve_Target_Low_Temp': 26,
      'main/Z1_Curve_Outside_High_Temp': 15,
      'main/Z1_Curve_Outside_Low_Temp': -10,
    },
  };
}

/** `GET control/snapshot`. */
export function makeSnapshotState(
  now: number,
  scenario: Scenario,
  publishing: boolean,
  key = '',
): unknown {
  const state = stateOf(key);
  settle(state, now);
  const running = state.run !== null && now - state.run.startedMs < runDuration() * 1000;
  const goLive = hasSnapshot(scenario) && state.releasedMs === null;
  const refusal = running
    ? 'in_progress'
    : publishing && scenario.tag === undefined
      ? 'controlling'
      : goLive
        ? 'in_use'
        : null;
  const capture = { can_capture: refusal === null, capture_refusal: refusal };
  if (state.manualMs !== null && !goLive)
    return { snapshot: snapshotJson(now, state, true), armed: true, publishing, ...capture };
  if (!hasSnapshot(scenario)) return { snapshot: null, armed: false, publishing, ...capture };
  return {
    snapshot: snapshotJson(now, state),
    armed: state.releasedMs === null,
    publishing,
    ...capture,
  };
}

/**
 * `POST control/snapshot` for a browser's scenario key: captures the pump state by hand while
 * ovenbird does not control; refused like the service (`controlling`, `in_use`, `in_progress`).
 */
export function captureSnapshot(
  key: string,
  now: number,
  scenario: Scenario,
  publishing: boolean,
): MockResult {
  const before = makeSnapshotState(now, scenario, publishing, key) as {
    capture_refusal: string | null;
  };
  if (before.capture_refusal !== null)
    return refusal(
      before.capture_refusal,
      `the snapshot cannot be captured now: ${before.capture_refusal}`,
    );
  const state = stateOf(key);
  state.manualMs = Math.floor(now / 60_000) * 60_000;
  return { status: 200, body: makeSnapshotState(now, scenario, publishing, key) };
}

function seeded(seed: number): () => number {
  let value = seed;
  return () => {
    value = (value * 1103515245 + 12345) % 2147483648;
    return value / 2147483648;
  };
}

/**
 * Run lengths in minutes for one day: longer runs on colder days, a few short ones.
 */
function dayRuns(dayIndex: number): number[] {
  const random = seeded(dayIndex * 7919 + 17);
  const count = 5 + Math.floor(random() * 5);
  const runs: number[] = [];
  for (let i = 0; i < count; i += 1) {
    const r = random();
    runs.push(
      r < 0.15 ? 6 + Math.round(random() * 12) : Math.round(25 + random() * random() * 260),
    );
  }
  return runs;
}

function stats(lengths: number[], censored: number, offs: number[]): Record<string, unknown> {
  const sorted = [...lengths].sort((a, b) => a - b);
  const n = sorted.length;
  const median =
    n === 0
      ? null
      : n % 2
        ? sorted[(n - 1) / 2]
        : ((sorted[n / 2 - 1] as number) + (sorted[n / 2] as number)) / 2;
  const short = sorted.filter((length) => length < SHORT_RUN_MIN).length;
  return {
    runs: n,
    censored,
    short_runs: short,
    short_share: n ? Math.round((short / n) * 1000) / 1000 : null,
    median_min: median,
    mean_min: n ? Math.round((sorted.reduce((a, b) => a + b, 0) / n) * 10) / 10 : null,
    longest_min: n ? sorted[n - 1] : null,
    min_off_min: offs.length ? Math.min(...offs) : null,
    histogram: BINS.map((low, index) => {
      const high = index + 1 < BINS.length ? (BINS[index + 1] as number) : null;
      return {
        from_min: low,
        to_min: high,
        runs: sorted.filter((length) => length >= low && (high === null || length < high)).length,
      };
    }),
  };
}

function localMidnight(ms: number): number {
  const date = new Date(ms);
  date.setHours(0, 0, 0, 0);
  return date.getTime();
}

/** `GET insight/runs?days=`. */
export function makeRuns(days: number, now: number): unknown {
  const today = localMidnight(now);
  const all: number[] = [];
  const allOffs: number[] = [];
  const list = [];
  for (let back = days - 1; back >= 0; back -= 1) {
    const start = localMidnight(today - back * DAY + HOUR * 2);
    const dayIndex = Math.floor(start / DAY);
    let lengths = dayRuns(dayIndex);
    const partial = back === 0;
    if (partial) {
      const share = Math.max(0.1, (now - start) / DAY);
      lengths = lengths.slice(0, Math.max(1, Math.round(lengths.length * share)));
    }
    const offs = lengths.slice(1).map((_, i) => 12 + ((dayIndex + i * 13) % 50));
    all.push(...lengths);
    allOffs.push(...offs);
    list.push({
      date: new Date(start).toISOString().slice(0, 10),
      from: iso(start),
      to: iso(partial ? now : start + DAY),
      partial,
      ...stats(lengths, partial ? 1 : 0, offs),
    });
  }
  return {
    timezone: 'Europe/Amsterdam',
    short_run_min: SHORT_RUN_MIN,
    signal: 'main/Compressor_Freq',
    total: stats(all, 1, allOffs),
    days: list,
  };
}

function period(
  from: number,
  to: number,
  room: number,
  roomMin: number,
  shortShare: number,
  writesPerDay: number,
): Record<string, unknown> {
  const days = Math.round(((to - from) / DAY) * 100) / 100;
  const runs = Math.round(days * 7);
  const short = Math.round(runs * shortShare);
  return {
    from: iso(from),
    to: iso(to),
    days,
    room_mean_c: room,
    room_min_c: roomMin,
    room_hours: Math.round(days * 24 * 10) / 10,
    outside_mean_c: 4.1,
    runs: {
      runs,
      censored: 1,
      short_runs: short,
      short_share: runs ? Math.round((short / runs) * 1000) / 1000 : null,
      median_min: 52,
      mean_min: 63.4,
      longest_min: 238,
      min_off_min: 14,
      histogram: [],
    },
    pump_errors: 0,
    writes: Math.round(writesPerDay * days),
    writes_per_day: writesPerDay,
    setpoint_changes_per_day: Math.round((writesPerDay + 1.1) * 10) / 10,
  };
}

const MIN_TRIAL_DAYS = 7;
const PHASE_OF: Record<string, string> = { envelope_proof: 'trial', rollback_rehearsal: 'trial' };

interface CheckEntry {
  id: string;
  status: string;
  message: string;
  evidence: Record<string, unknown>;
}

function check(
  id: string,
  status: string,
  message: string,
  evidence: Record<string, unknown> = {},
): CheckEntry {
  return { id, status, message, evidence };
}

function counts(entries: CheckEntry[]): Record<string, number> {
  return {
    ok: entries.filter((entry) => entry.status === 'ok').length,
    warn: entries.filter((entry) => entry.status === 'warn').length,
    fail: entries.filter((entry) => entry.status === 'fail').length,
  };
}

function group(entries: CheckEntry[]): {
  ready: boolean;
  counts: Record<string, number>;
  ids: string[];
} {
  return {
    ready: entries.every((entry) => entry.status === 'ok'),
    counts: counts(entries),
    ids: entries.map((entry) => entry.id),
  };
}

interface NotifyHealth {
  state: string;
  reason: string | null;
  deadman_state: string;
}

/**
 * The `notifications` checklist item from the same facts as `GET notifications/status`, by the
 * service's rule: its `health` verdict (failing: fail, untested: warn), then the dead-man ping.
 */
function notificationsCheck(now: number, scenario: Scenario, key: string): CheckEntry {
  const status = makeNotifications(now, scenario, key) as {
    ntfy: { configured: boolean; last_test: unknown; last_sent: unknown; last_error: unknown };
    deadman: { configured: boolean; last_ok: string | null; last_skip: string | null };
    health: NotifyHealth;
  };
  const health = status.health;
  if (!status.ntfy.configured)
    return check(
      'notifications',
      'fail',
      'ntfy is not configured (OVENBIRD_NOTIFY_NTFY_URL and _TOPIC)',
      {
        health,
      },
    );
  const evidence = {
    health,
    last_test: status.ntfy.last_test,
    last_sent: status.ntfy.last_sent,
    last_error: status.ntfy.last_error,
    deadman_configured: status.deadman.configured,
    deadman_last_ok: status.deadman.last_ok,
  };
  const item = (state: string, message: string) => check('notifications', state, message, evidence);
  if (health.state === 'failing') return item('fail', `alerts do not arrive: ${health.reason}`);
  if (health.state === 'untested') return item('warn', 'no test notification sent yet; send one');
  if (health.deadman_state === 'not_configured')
    return item('warn', 'no dead-man ping configured (OVENBIRD_NOTIFY_DEADMAN_URL)');
  if (health.deadman_state === 'waiting')
    return item('warn', 'the dead-man ping has not succeeded yet');
  if (health.deadman_state === 'failing') return item('warn', 'the last dead-man ping failed');
  if (health.deadman_state === 'skipped')
    return item('warn', `the dead-man ping is held back: ${status.deadman.last_skip}`);
  return item('ok', 'alerts arrive; dead-man ping alive');
}

/**
 * The envelope rule as `GET system/about` reports it: whether it is declared installed, how often
 * it was seen acting and the last proof.
 */
export interface EnvelopeFacts {
  installed: boolean;
  state: string;
  count: number;
  last: unknown;
}

/**
 * `GET trial/status`: the checklist in two phases and the summary against the baseline. `paused`
 * is the browser's effective pause (by hand or after its own release); `envelope` the envelope
 * rule as `system/about` reports it. Before go-live (`phase: go_live`, all ok = `ready`) and in
 * the first trial (`envelope_proof`, `rollback_rehearsal`; everything ok = `ready_for_cutover`).
 * The summary covers the go-live snapshot until now or its release (`source: go_live`), else the
 * last 7 days (`default`, `state: no_trial`); `met` only for a `complete` trial of at least
 * `min_days` whose criteria are met.
 */
export function makeTrialStatus(
  now: number,
  scenario: Scenario,
  key: string,
  paused = false,
  envelope: EnvelopeFacts = { installed: true, state: 'declared', count: 0, last: null },
): unknown {
  const state = stateOf(key);
  settle(state, now);
  const shadow = scenario.mode === 'shadow';
  const inShadow = paused || scenario.mode !== undefined;
  const taken = snapshotTaken(now, state);
  const manual = state.manualMs !== null && !(hasSnapshot(scenario) && state.releasedMs === null);
  const snapshot = manual
    ? snapshotJson(now, state, true)
    : hasSnapshot(scenario)
      ? snapshotJson(now, state)
      : null;
  const rehearsal = state.lastRehearsal;
  const plan = [state.lastDry, rehearsal].find((run) => run !== null && run['outcome'] === 'ok');
  const envelopeEvidence = {
    installed: envelope.installed,
    count: envelope.count,
    last: envelope.last,
  };
  const notifyFailing = scenario.notify === 'failing';
  const entries: CheckEntry[] = [
    {
      id: 'shadow_days',
      status: 'warn',
      message: '9.2 of 14 days in shadow',
      evidence: {
        days: 9.2,
        required_days: 14.0,
        first: iso(now - 13 * DAY),
        last: iso(now - 4 * DAY),
        journal_days: 90,
      },
    },
    {
      id: 'divergence',
      status: 'warn',
      message: '2 episodes of 120 min or longer to review',
      evidence: {
        days: 14,
        coverage: 0.962,
        mean_abs_k: 0.62,
        max_abs_k: 3.4,
        hours_over: 11.5,
        episodes: 9,
        long_episodes: 2,
        long_episode_min: 120,
        longest: null,
      },
    },
    envelope.state === 'proven'
      ? check('envelope_rule', 'ok', 'installed and seen acting', envelopeEvidence)
      : envelope.installed
        ? check(
            'envelope_rule',
            'ok',
            'declared installed; prove it in the first trial by stopping the service',
            envelopeEvidence,
          )
        : check(
            'envelope_rule',
            'fail',
            'not declared installed (OVENBIRD_ENVELOPE_RULE_INSTALLED)',
            envelopeEvidence,
          ),
    notificationsCheck(now, scenario, key),
    plan !== undefined && plan !== null
      ? check(
          'release_plan',
          'ok',
          `a ${plan['dry'] === true ? 'dry rehearsal' : 'rehearsal'} planned every setting`,
          { last: plan },
        )
      : check(
          'release_plan',
          'fail',
          'no rehearsal yet: capture a snapshot, then run a dry rehearsal',
          { last: rehearsal },
        ),
    scenario.alarms === 'none'
      ? {
          id: 'alarms',
          status: 'ok',
          message: 'no open alarms',
          evidence: { critical: [], warning: [] },
        }
      : scenario.alarms === 'critical'
        ? {
            id: 'alarms',
            status: 'fail',
            message: 'critical alarms are active',
            evidence: {
              critical: ['outlet_overshoot'],
              warning: ['foreign_writer', ...(notifyFailing ? ['notify_failing'] : [])],
            },
          }
        : {
            id: 'alarms',
            status: 'warn',
            message: 'warnings are active',
            evidence: {
              critical: [],
              warning: [
                shadow ? 'heishamon_restarted' : 'foreign_writer',
                ...(notifyFailing ? ['notify_failing'] : []),
              ],
            },
          },
    scenario.room === 'stale'
      ? {
          id: 'room',
          status: 'fail',
          message: 'the room value is not fresh',
          evidence: {
            signal: 'ha/sensor.living_room_temperature',
            value: 21.3,
            fresh: false,
          },
        }
      : scenario.room === 'old' || scenario.room === 'untrusted'
        ? {
            id: 'room',
            status: 'warn',
            message: 'the room value is held long; reduced authority',
            evidence: {
              signal: 'ha/sensor.living_room_temperature',
              value: 22.1,
              fresh: true,
              plausible: true,
              authority: scenario.room === 'old' ? 0.45 : 0,
            },
          }
        : {
            id: 'room',
            status: 'ok',
            message: 'the room value is fresh and trusted',
            evidence: {
              signal: 'ha/sensor.living_room_temperature',
              value: 21.6,
              fresh: true,
              plausible: true,
              authority: 1,
            },
          },
    snapshot === null
      ? {
          id: 'pump_snapshot',
          status: 'warn',
          message: 'no snapshot yet: capture one in shadow; the go-live records its own',
          evidence: { snapshot: null },
        }
      : manual
        ? {
            id: 'pump_snapshot',
            status: 'ok',
            message: 'captured in shadow; the go-live records the values of that moment',
            evidence: { snapshot },
          }
        : state.releasedMs !== null
          ? {
              id: 'pump_snapshot',
              status: 'warn',
              message: 'used by a release; capture a new one, or the next go-live records it',
              evidence: { snapshot },
            }
          : {
              id: 'pump_snapshot',
              status: 'ok',
              message: 'recorded at go-live',
              evidence: { snapshot },
            },
    envelope.state === 'proven'
      ? check('envelope_proof', 'ok', 'seen correcting the pump', {
          count: envelope.count,
          last: envelope.last,
        })
      : check(
          'envelope_proof',
          'warn',
          'not seen acting yet: while ovenbird controls, stop the service at night-time load and let the rule correct the setpoint',
          { count: envelope.count, last: envelope.last },
        ),
    rehearsal === null
      ? check(
          'rollback_rehearsal',
          'fail',
          'no rehearsal yet: possible once ovenbird controls (release, then resume)',
          { last: null },
        )
      : check(
          'rollback_rehearsal',
          rehearsal['outcome'] === 'ok' && rehearsal['within_limit'] ? 'ok' : 'warn',
          `rehearsed in ${Math.round(Number(rehearsal['duration_s']))} s`,
          { last: rehearsal, limit_s: 300 },
        ),
  ];
  const checklist = entries.map((entry) => ({ ...entry, phase: PHASE_OF[entry.id] ?? 'go_live' }));
  const groups = {
    go_live: group(checklist.filter((entry) => entry.phase === 'go_live')),
    trial: group(checklist.filter((entry) => entry.phase === 'trial')),
  };
  const source = snapshot === null || manual ? 'default' : 'go_live';
  const trialFrom = source === 'default' ? now - 7 * DAY : taken;
  const trialTo = source === 'default' ? now : Math.max(trialFrom, state.releasedMs ?? now);
  const length = trialTo - trialFrom;
  const days = Math.round((length / DAY) * 100) / 100;
  const trialState =
    source === 'default'
      ? 'no_trial'
      : days >= MIN_TRIAL_DAYS
        ? 'complete'
        : state.releasedMs !== null
          ? 'ended_early'
          : 'running';
  const trial = period(trialFrom, trialTo, 20.9, 20.1, 0.122, 12.0);
  const baseline = period(trialFrom - length, trialFrom, 21.0, 20.2, 0.146, 0);
  const criteria = [
    { id: 'room_mean', trial: 20.9, baseline: 21.0, delta: -0.1, limit: 0.5, status: 'ok' },
    { id: 'room_min', trial: 20.1, baseline: 20.2, delta: -0.1, limit: null, status: 'info' },
    {
      id: 'short_runs',
      trial: 0.122,
      baseline: 0.146,
      delta: -0.024,
      limit: SHORT_RUN_MIN,
      status: 'ok',
    },
    { id: 'pump_errors', trial: 0, baseline: 0, delta: null, limit: 0, status: 'ok' },
    { id: 'writes_per_day', trial: 12.0, baseline: 0, delta: null, limit: 150, status: 'ok' },
    {
      id: 'setpoint_changes_per_day',
      trial: 13.1,
      baseline: 18.4,
      delta: null,
      limit: null,
      status: 'info',
    },
  ];
  const criteriaMet = criteria.every((c) => c.status === 'ok' || c.status === 'info');
  return {
    at: iso(now),
    mode: inShadow ? 'shadow' : 'auto',
    configured_mode: shadow ? 'shadow' : 'auto',
    ready: groups.go_live.ready,
    ready_for_cutover: checklist.every((entry) => entry.status === 'ok'),
    not_ready: checklist
      .filter((entry) => entry.phase === 'go_live' && entry.status !== 'ok')
      .map((entry) => ({ id: entry.id, message: entry.message })),
    counts: counts(checklist),
    groups,
    checklist,
    summary: {
      source,
      state: trialState,
      days,
      min_days: MIN_TRIAL_DAYS,
      trial,
      baseline,
      criteria,
      criteria_met: criteriaMet,
      met: criteriaMet && trialState === 'complete',
    },
  };
}
