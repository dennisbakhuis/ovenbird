import type { NotificationStatus } from '$lib/system/about';
import { ApiError, type FailureKind } from '$lib/core/api';
import type { Alarm } from '$lib/core/types';

/** Alarm codes of the service for failing notification channels (newer services raise one). */
export const NOTIFY_ALARM_CODES: readonly string[] = ['notify_failing'];

/**
 * Whether the service already raises an alarm for failing notifications: then that alarm is what
 * Home and the strip show, not a second warning of the UI's own.
 */
export function hasNotifyAlarm(alarms: Alarm[]): boolean {
  return alarms.some((alarm) => NOTIFY_ALARM_CODES.includes(alarm.code));
}

export type NotifyTone = 'good' | 'warn' | 'bad';

export type NotifyVerdictKey =
  | 'notifyVerdictOk'
  | 'notifyVerdictOff'
  | 'notifyVerdictTestFailed'
  | 'notifyVerdictDelivery'
  | 'notifyVerdictDeadman'
  | 'notifyVerdictUntested'
  | 'notifyVerdictNoDeadman';

export interface NotifyVerdict {
  tone: NotifyTone;
  key: NotifyVerdictKey;
  /** Alerts are set up but do not reach anyone: shown on Home and in the strip too. */
  failing: boolean;
}

function errorAt(value: { at: string; error: string } | string | null | undefined): number | null {
  if (!value || typeof value === 'string') return null;
  const at = Date.parse(value.at);
  return Number.isFinite(at) ? at : null;
}

/**
 * Whether the last deliveries of ntfy failed: the service's own health when it reports one
 * (`health.state` failing with sends that failed in a row), otherwise a `last_error` newer than
 * the last message that went out.
 */
export function deliveryFailing(status: NotificationStatus): boolean {
  const health = status.health;
  if (health) return health.state === 'failing' && (health.failures_in_row ?? 0) > 0;
  const failed = errorAt(status.ntfy.last_error);
  if (failed === null) return false;
  const sent = status.ntfy.last_sent ? Date.parse(status.ntfy.last_sent.at) : NaN;
  return !Number.isFinite(sent) || failed > sent;
}

function testFailed(status: NotificationStatus): boolean {
  const test = status.ntfy.last_test;
  if (!test || test.ok) return false;
  if (status.health) return status.health.state === 'failing';
  return true;
}

/**
 * One verdict on the notification channels, shared by the System tile, the trial checklist and
 * the Home/strip warning so they never disagree: no channel (bad, not "failing": nothing was set
 * up), the last test failed or the last message did not go out (bad), the dead-man ping is
 * unhealthy (warn), never tested, no dead-man, or all good. `failing` marks the states in which
 * alerts are set up but do not reach anyone.
 */
export function notifyVerdict(status: NotificationStatus | null | undefined): NotifyVerdict | null {
  if (!status) return null;
  const { ntfy, deadman, health } = status;
  if (!ntfy.configured || health?.state === 'not_configured')
    return { tone: 'bad', key: 'notifyVerdictOff', failing: false };
  if (deliveryFailing(status)) return { tone: 'bad', key: 'notifyVerdictDelivery', failing: true };
  if (testFailed(status)) return { tone: 'bad', key: 'notifyVerdictTestFailed', failing: true };
  if (health?.state === 'failing')
    return { tone: 'bad', key: 'notifyVerdictDelivery', failing: true };
  if (deadman.configured && !deadman.healthy)
    return { tone: 'warn', key: 'notifyVerdictDeadman', failing: true };
  if (health ? health.state === 'untested' : !ntfy.last_test)
    return { tone: 'warn', key: 'notifyVerdictUntested', failing: false };
  if (!deadman.configured) return { tone: 'warn', key: 'notifyVerdictNoDeadman', failing: false };
  return { tone: 'good', key: 'notifyVerdictOk', failing: false };
}

/** Why "Send test" did not send: the failure kind and, when rate-limited, the seconds to wait. */
export interface TestFailure {
  kind: FailureKind;
  retryS: number | null;
}

/**
 * The seconds to wait from a `429` of the service (`detail.retry_after_s`), or null.
 */
export function retryAfter(error: unknown): number | null {
  if (!(error instanceof ApiError) || error.status !== 429) return null;
  const detail = (error.body as { detail?: { retry_after_s?: unknown } } | null)?.detail;
  const seconds = Number(detail?.retry_after_s);
  return Number.isFinite(seconds) && seconds >= 0 ? Math.ceil(seconds) : null;
}
