import { ApiError, getOptional, postJson } from '$lib/core/api';
import type { Schemas } from '$lib/core/types';
import type { MessageKey } from '$lib/i18n';

export const RUN_POLL_MS = 5_000;

export type HouseRun = Schemas['HouseRun'];
export type LearnerState = HouseRun['state'];
export type RunLast = NonNullable<HouseRun['last']>;
export type RunFailure = NonNullable<HouseRun['failure']>;
export type FailureReason = RunFailure['reason'];

export type StartRefusal = 'learner_running' | 'learner_unavailable' | 'forbidden' | 'failed';

/**
 * The learner's run state; null when the backend does not have the endpoint (an older service).
 */
export function fetchRun(signal?: AbortSignal): Promise<HouseRun | null> {
  return getOptional<HouseRun>('api/v1/insight/house/run', signal);
}

/**
 * Ask the learner for a run now; answers with the run state (`running`).
 */
export function startRun(): Promise<HouseRun> {
  return postJson<HouseRun>('api/v1/insight/house/run', {});
}

/**
 * Why a run request was refused: the learner already runs, this install has none, the login may
 * not operate, or anything else.
 */
export function refusalOf(error: unknown): StartRefusal {
  if (!(error instanceof ApiError)) return 'failed';
  if (error.status === 401 || error.status === 403) return 'forbidden';
  if (error.status === 409) {
    if (error.code === 'learner_running' || error.code === 'learner_unavailable') return error.code;
  }
  return 'failed';
}

export type Presentation =
  'running' | 'unavailable' | 'disabled' | 'due_soon' | 'scheduled' | 'never';

/**
 * How the learner is presented: running, not built in, switched off, or idle with the next run
 * (`due_soon` once it is due).
 */
export function presentation(run: HouseRun, nowMs: number): Presentation {
  if (run.state === 'running') return 'running';
  if (run.state === 'unavailable') return 'unavailable';
  if (!run.enabled) return 'disabled';
  if (run.next_due_at === null) return 'never';
  return Date.parse(run.next_due_at) <= nowMs ? 'due_soon' : 'scheduled';
}

export type OutcomeKind = 'promoted' | 'kept' | 'learning' | 'failed' | 'other';

/**
 * The learner's outcome word as one of the known kinds.
 */
export function outcomeKind(outcome: string | null | undefined): OutcomeKind {
  if (outcome === 'kept_champion' || outcome === 'kept') return 'kept';
  return outcome === 'promoted' || outcome === 'learning' || outcome === 'failed'
    ? outcome
    : 'other';
}

export const OUTCOME_KEYS: Record<OutcomeKind, MessageKey> = {
  promoted: 'houseRunOutcome_promoted',
  kept: 'houseRunOutcome_kept',
  learning: 'houseRunOutcome_learning',
  failed: 'houseRunOutcome_failed',
  other: 'houseRunOutcome_other',
};

export const FAILURE_KEYS: Record<FailureReason, MessageKey> = {
  timeout: 'houseRunFailure_timeout',
  memory: 'houseRunFailure_memory',
  exit: 'houseRunFailure_exit',
  spawn: 'houseRunFailure_spawn',
};
