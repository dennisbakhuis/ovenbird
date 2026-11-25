import type { Schemas } from '$lib/core/types';
import { getOptional, postJson } from '$lib/core/api';
import { formatDateTime, formatDuration, formatNumber } from '$lib/core/format';
import type { Language } from '$lib/i18n';

export type CheckStatus = Schemas['CheckStatusName'];
export type CriterionStatus = Schemas['CriterionStatusName'];
export type CheckPhase = Schemas['CheckPhaseName'];
export type TrialCheck = Schemas['TrialCheck'];
export type RunHistogramBin = Schemas['RunBin'];
export type RunStats = Schemas['RunStats'];
export type RunDay = Schemas['RunDay'];
export type InsightRuns = Schemas['InsightRuns'];
export type TrialPeriod = Schemas['TrialPeriod'];
export type TrialCriterion = Schemas['TrialCriterion'];
export type TrialState = Schemas['TrialStateName'];
export type TrialSummary = Schemas['TrialSummary'];
export type TrialStatus = Schemas['TrialStatus'];
export type SnapshotItem = Schemas['SnapshotItem'];
export type PumpSnapshot = Schemas['PumpSnapshot'];
export type SnapshotResponse = Schemas['SnapshotState'];
export type ReleaseItemStatus = Schemas['ReleaseItemStatusName'];
export type ReleaseItem = Schemas['ReleaseItem'];
export type ReleaseRun = Schemas['ReleaseRun'];
export type ReleaseState = Schemas['ReleaseState'];
export type ReleaseStarted = Schemas['ReleaseStarted'];
export type EpisodeExplanation = Schemas['EpisodeMark'];

export interface TrialVerdict {
  state: TrialState;
  /** Message key of the line under the criteria. */
  key: string;
  tone: 'good' | 'warn' | 'neutral';
  params: Record<string, string | number>;
}

/**
 * The line under the cut-over criteria, from the summary's `state`: "met" only for a completed
 * trial from go-live; "No trial yet" without a go-live; "Trial running: 0.4 of 7 days" while it
 * runs; "ended early" after a release before the minimum length. An older service without
 * `state` counts as a trial only when the period starts at go-live.
 */
export function trialVerdict(summary: TrialSummary, fmt: TrialFormat): TrialVerdict {
  const state: TrialState =
    summary.state ??
    (summary.source === 'go_live'
      ? 'complete'
      : summary.source === 'default'
        ? 'no_trial'
        : 'not_a_trial');
  const met = summary.criteria_met ?? summary.met;
  const params = {
    days: fmt.num(summary.days ?? summary.trial.days, 1),
    min: fmt.num(summary.min_days ?? 7, 0),
  };
  switch (state) {
    case 'complete':
      return summary.met && met
        ? { state, key: 'trialCriteriaMet', tone: 'good', params }
        : { state, key: 'trialCriteriaNotMet', tone: 'warn', params };
    case 'running':
      return {
        state,
        key: met ? 'trialVerdictRunningOk' : 'trialVerdictRunning',
        tone: 'neutral',
        params,
      };
    case 'ended_early':
      return { state, key: 'trialVerdictEndedEarly', tone: 'warn', params };
    case 'not_a_trial':
      return { state, key: 'trialVerdictNotATrial', tone: 'neutral', params };
    default:
      return { state, key: 'trialVerdictNoTrial', tone: 'neutral', params };
  }
}

export const RELEASE_GOOD_ENDS: readonly ReleaseItemStatus[] = [
  'verified',
  'unchanged',
  'not_managed',
  'planned',
];
export const RELEASE_RUNNING: readonly ReleaseItemStatus[] = ['queued', 'sent', 'retry'];

/** The cut-over target for handing control back, in seconds. */
export const RELEASE_TARGET_S = 300;

/**
 * The go-live checklist and the trial summary; null when the backend does not have it.
 */
export function fetchTrialStatus(signal?: AbortSignal): Promise<TrialStatus | null> {
  return getOptional<TrialStatus>('api/v1/trial/status', signal);
}

/**
 * Compressor run lengths per day; null when the backend does not have it.
 */
export function fetchRuns(days = 7, signal?: AbortSignal): Promise<InsightRuns | null> {
  const n = Math.min(Math.max(Math.round(days), 1), 90);
  return getOptional<InsightRuns>(`api/v1/insight/runs?days=${n}`, signal);
}

/**
 * The pump state recorded at go-live; null when the backend does not have it.
 */
export function fetchSnapshotState(signal?: AbortSignal): Promise<SnapshotResponse | null> {
  return getOptional<SnapshotResponse>('api/v1/control/snapshot', signal);
}

/**
 * The running or last release and the last rehearsal; null when the backend does not have it.
 */
export function fetchRelease(signal?: AbortSignal): Promise<ReleaseState | null> {
  return getOptional<ReleaseState>('api/v1/control/release', signal);
}

/**
 * Start a release of control (admin), a rehearsal of it, or a dry rehearsal (plans against the
 * snapshot without sending; also in Shadow).
 */
export function startRelease(
  rehearsal: boolean,
  reason: string,
  dry = false,
): Promise<ReleaseStarted> {
  const body: Record<string, unknown> = {};
  if (rehearsal || dry) body['rehearsal'] = true;
  if (dry) body['dry'] = true;
  if (reason) body['reason'] = reason;
  return postJson<ReleaseStarted>('api/v1/control/release', body);
}

/**
 * Capture the pump state now (admin), to rehearse against before go-live.
 */
export function captureSnapshot(): Promise<SnapshotResponse> {
  return postJson<SnapshotResponse>('api/v1/control/snapshot', {});
}

/**
 * Mark a divergence episode as explained with a note (admin), or remove the mark (`note` null).
 */
export function explainEpisode(
  start: string,
  note: string | null,
): Promise<{ explained: EpisodeExplanation | null }> {
  return postJson(
    'api/v1/shadow/episodes/explain',
    note === null ? { start, explained: false } : { start, note },
  );
}

/**
 * Formatters the pure helpers below use, so they stay independent of the UI language.
 */
export interface TrialFormat {
  num: (value: number, digits?: number) => string;
  date: (iso: string) => string;
  duration: (seconds: number) => string;
  percent: (share: number) => string;
}

export interface TextRef {
  key: string;
  params: Record<string, string | number>;
}

const num = (value: unknown): number | null =>
  typeof value === 'number' && Number.isFinite(value) ? value : null;
const text = (value: unknown): string | null =>
  typeof value === 'string' && value !== '' ? value : null;
const record = (value: unknown): Record<string, unknown> | null =>
  value && typeof value === 'object' && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
const list = (value: unknown): unknown[] => (Array.isArray(value) ? value : []);

/**
 * The one-line message of a checklist item as a message key (`trialMsg_<id>_<variant>`) with its
 * parameters, built from the status and the evidence rather than the service's English text.
 */
export function checkLine(check: TrialCheck, fmt: TrialFormat): TextRef {
  const e = check.evidence ?? {};
  const ref = (variant: string, params: Record<string, string | number> = {}): TextRef => ({
    key: `trialMsg_${check.id}_${variant}`,
    params,
  });
  switch (check.id) {
    case 'shadow_days': {
      const days = num(e['days']) ?? 0;
      const required = num(e['required_days']) ?? 14;
      if (check.status === 'ok') return ref('ok', { days: fmt.num(days, 1) });
      if (check.status === 'warn')
        return ref('warn', { days: fmt.num(days, 1), required: fmt.num(required, 0) });
      return ref('fail');
    }
    case 'divergence': {
      const coverage = num(e['coverage']);
      const long = num(e['long_episodes']) ?? 0;
      const days = num(e['days']) ?? 14;
      const min = num(e['long_episode_min']) ?? 120;
      const explained = num(e['explained_episodes']) ?? 0;
      if (check.status === 'ok' && explained > 0) return ref('explained', { n: explained });
      if (check.status === 'ok') return ref('ok', { days: fmt.num(days, 0) });
      if (check.status === 'fail') return ref('fail');
      if (long > 0) return ref('long', { n: long, min: fmt.num(min, 0) });
      return ref('coverage', {
        percent: coverage === null ? '–' : fmt.percent(coverage),
        days: fmt.num(days, 0),
      });
    }
    case 'envelope_rule':
      if (check.status === 'ok' && e['last'] === null) return ref('declared');
      return ref(check.status);
    case 'release_plan':
    case 'envelope_proof':
      return ref(check.status);
    case 'notifications': {
      if (check.status === 'ok') return ref('ok');
      const test = record(e['last_test']);
      const live = text(e['live_verdict']);
      if (live) return { key: live, params: {} };
      const health = record(e['health']);
      if (health) {
        const state = text(health['state']);
        if (state === 'not_configured') return ref('off');
        if (state === 'failing')
          return ref((num(health['failures_in_row']) ?? 0) > 0 ? 'delivery_failed' : 'test_failed');
        if (state === 'untested') return ref('no_test');
        if (text(health['deadman_state']) === 'not_configured') return ref('no_deadman');
        return ref('deadman_pending');
      }
      if (e['configured'] === false) return ref('off');
      if (test && test['ok'] === false) return ref('test_failed');
      if (record(e['last_error']) || text(e['last_error'])) return ref('delivery_failed');
      if (check.status === 'fail') return ref(test ? 'test_failed' : 'off');
      if (!test) return ref('no_test');
      if (e['deadman_configured'] === false) return ref('no_deadman');
      return ref('deadman_pending');
    }
    case 'rollback_rehearsal': {
      const last = record(e['last']);
      const duration = num(last?.['duration_s']);
      if (check.status === 'fail' || !last) return ref('fail');
      if (check.status === 'ok') return ref('ok', { duration: fmt.duration(duration ?? 0) });
      if (last['outcome'] !== 'ok') return ref('incomplete');
      return ref('slow', {
        duration: duration === null ? '–' : fmt.duration(duration),
        limit: fmt.duration(num(e['limit_s']) ?? RELEASE_TARGET_S),
      });
    }
    case 'alarms': {
      if (check.status === 'ok') return ref('ok');
      if (check.status === 'fail') return ref('fail', { n: list(e['critical']).length });
      return ref('warn', { n: list(e['warning']).length });
    }
    case 'room': {
      if (check.status === 'ok') return ref('ok');
      if (Object.keys(e).length === 0) return ref('none');
      if (check.status === 'fail') return ref('stale');
      if (e['plausible'] === false) return ref('implausible');
      const authority = num(e['authority']);
      return ref('authority', { percent: authority === null ? '–' : fmt.percent(authority) });
    }
    case 'pump_snapshot': {
      const snapshot = record(e['snapshot']);
      const time = fmt.date(text(snapshot?.['taken_at']) ?? '');
      if (check.status === 'ok')
        return ref(snapshot?.['origin'] === 'manual' ? 'manual' : 'ok', { time });
      if (!('snapshot' in e)) return ref('no_loop');
      if (!snapshot) return ref('none');
      if (text(snapshot['released_at'])) return ref('released');
      if (snapshot['stale'] === true)
        return ref('stale', { days: fmt.num((num(snapshot['age_s']) ?? 0) / 86_400, 0) });
      return ref('incomplete');
    }
    default:
      return { key: '', params: {} };
  }
}

/**
 * A second, quieter line with the evidence behind a checklist item, or null.
 */
export function checkEvidence(check: TrialCheck, fmt: TrialFormat): TextRef | null {
  const e = check.evidence ?? {};
  const ref = (variant: string, params: Record<string, string | number>): TextRef => ({
    key: `trialEv_${check.id}_${variant}`,
    params,
  });
  switch (check.id) {
    case 'shadow_days': {
      const first = text(e['first']);
      return first ? ref('since', { time: fmt.date(first) }) : null;
    }
    case 'divergence': {
      const coverage = num(e['coverage']);
      const max = num(e['max_abs_k']);
      if (coverage === null && max === null) return null;
      return ref('figures', {
        percent: coverage === null ? '–' : fmt.percent(coverage),
        max: max === null ? '–' : fmt.num(max, 1),
        hours: fmt.num(num(e['hours_over']) ?? 0, 1),
      });
    }
    case 'envelope_rule': {
      const last = record(e['last']);
      const at = text(last?.['at']);
      return at ? ref('seen', { n: num(e['count']) ?? 1, time: fmt.date(at) }) : null;
    }
    case 'notifications': {
      const test = record(e['last_test']);
      const at = text(test?.['at']);
      return at ? ref('tested', { time: fmt.date(at) }) : null;
    }
    case 'rollback_rehearsal': {
      const last = record(e['last']);
      const at = text(last?.['finished_at']) ?? text(last?.['started_at']);
      return at
        ? ref('when', {
            time: fmt.date(at),
            limit: fmt.duration(num(e['limit_s']) ?? RELEASE_TARGET_S),
          })
        : null;
    }
    case 'room': {
      const value = num(e['value']);
      return value === null ? null : ref('value', { value: fmt.num(value, 1) });
    }
    default:
      return null;
  }
}

/**
 * The page that holds the facts behind a checklist item, or null.
 */
export function checkLink(id: string): string | null {
  const links: Record<string, string> = {
    divergence: '#/system/shadow',
    notifications: '#/system',
    alarms: '#/activity',
    room: '#/settings/room',
    envelope_rule: '#/system',
    envelope_proof: '#/system',
  };
  return links[id] ?? null;
}

export type ItemPhase = 'running' | 'good' | 'bad';

/**
 * Whether a release item is still moving, ended well, or ended badly.
 */
export function itemPhase(status: ReleaseItemStatus): ItemPhase {
  if (RELEASE_RUNNING.includes(status)) return 'running';
  return RELEASE_GOOD_ENDS.includes(status) ? 'good' : 'bad';
}

/**
 * How many items of a release are running, ended well and ended badly.
 */
export function releaseCounts(run: ReleaseRun): Record<ItemPhase, number> {
  const counts: Record<ItemPhase, number> = { running: 0, good: 0, bad: 0 };
  for (const item of run.items) counts[itemPhase(item.status)] += 1;
  return counts;
}

/**
 * Seconds a release has taken: the service's `duration_s`, plus the time since it was fetched
 * while the release still runs.
 */
export function elapsedSeconds(run: ReleaseRun, fetchedAtMs: number, nowMs: number): number {
  const base = num(run.duration_s) ?? 0;
  if (run.done) return base;
  return base + Math.max(0, (nowMs - fetchedAtMs) / 1000);
}

/**
 * Share (0–1) of the 5-minute target used by `elapsed` seconds.
 */
export function targetShare(elapsed: number, target = RELEASE_TARGET_S): number {
  return Math.min(1, Math.max(0, elapsed / target));
}

/**
 * Whether the typed confirmation matches the word to type (case and outer spaces ignored).
 */
export function confirmMatches(typed: string, word: string): boolean {
  return typed.trim().toLocaleUpperCase() === word.trim().toLocaleUpperCase() && word.trim() !== '';
}

/**
 * A criterion's value in its unit: °C for the room, a percentage for the short-run share, a
 * count or a rate otherwise; "–" when missing.
 */
export function criterionValue(id: string, value: number | null, fmt: TrialFormat): string {
  if (value === null || value === undefined) return '–';
  switch (id) {
    case 'room_mean':
    case 'room_min':
      return `${fmt.num(value, 1)} °C`;
    case 'short_runs':
      return fmt.percent(value);
    case 'pump_errors':
      return fmt.num(value, 0);
    default:
      return fmt.num(value, 1);
  }
}

/**
 * A criterion's difference (trial − baseline) with its sign and unit, or null without one.
 */
export function criterionDelta(id: string, delta: number | null, fmt: TrialFormat): string | null {
  if (delta === null || delta === undefined) return null;
  const sign = delta > 0 ? '+' : delta < 0 ? '−' : '±';
  const size = Math.abs(delta);
  if (id === 'short_runs') return `${sign}${fmt.num(size * 100, 1)} pp`;
  if (id === 'room_mean' || id === 'room_min') return `${sign}${fmt.num(size, 2)} K`;
  return `${sign}${fmt.num(size, 1)}`;
}

/**
 * The formatters of the trial page for a language, dates relative to the service clock.
 */
export function trialFormat(language: Language, nowMs: number): TrialFormat {
  return {
    num: (value, digits = 1) => formatNumber(value, digits, language),
    date: (iso) => formatDateTime(iso, language, nowMs),
    duration: (seconds) => formatDuration(seconds, language),
    percent: (share) =>
      `${formatNumber(share * 100, Math.abs(share) < 0.1 && share !== 0 ? 1 : 0, language)} %`,
  };
}

/**
 * The checklist with its Notifications item brought in line with the live notification verdict
 * (the System tile and the strip use the same): a channel that is failing now is never "Done",
 * even when the service's checklist was computed before the failure or only looked at the last
 * test. Counts and readiness follow.
 */
/**
 * The checklist in its groups: "before go-live" (what `ready` means) and "in the first trial"
 * (only possible once ovenbird controls). An older service without `phase` gives one group.
 */
export function checkGroups(
  checklist: TrialCheck[],
): { phase: CheckPhase | null; checks: TrialCheck[] }[] {
  if (!checklist.some((check) => check.phase === 'trial'))
    return [{ phase: null, checks: checklist }];
  return (['go_live', 'trial'] as const)
    .map((phase) => ({
      phase,
      checks: checklist.filter((check) => (check.phase ?? 'go_live') === phase),
    }))
    .filter((group) => group.checks.length > 0);
}

/**
 * How many items before go-live are not done yet (all items for an older service).
 */
export function openBeforeGoLive(checklist: TrialCheck[]): number {
  return checklist.filter((check) => check.phase !== 'trial' && check.status !== 'ok').length;
}

/**
 * Done, to-check and missing counts of the items before go-live (all items for an older service).
 */
export function goLiveCounts(checklist: TrialCheck[]): Record<CheckStatus, number> {
  const counts: Record<CheckStatus, number> = { ok: 0, warn: 0, fail: 0 };
  for (const check of checklist) if (check.phase !== 'trial') counts[check.status] += 1;
  return counts;
}

export function withNotifyVerdict(status: TrialStatus, failing: boolean, key: string): TrialStatus {
  if (!failing) return status;
  const index = status.checklist.findIndex((c) => c.id === 'notifications' && c.status === 'ok');
  if (index < 0) return status;
  const checklist = status.checklist.map((check, i) =>
    i === index
      ? { ...check, status: 'warn' as const, evidence: { ...check.evidence, live_verdict: key } }
      : check,
  );
  const counts = { ...status.counts };
  counts.ok = Math.max(0, (counts.ok ?? 0) - 1);
  counts.warn = (counts.warn ?? 0) + 1;
  return { ...status, checklist, counts, ready: false };
}
