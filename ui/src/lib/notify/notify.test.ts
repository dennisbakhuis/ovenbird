import { describe, expect, it } from 'vitest';
import type { NotificationStatus } from '$lib/system/about';
import { ApiError } from '$lib/core/api';
import { deliveryFailing, hasNotifyAlarm, notifyVerdict, retryAfter } from './notify';

const HEALTH = {
  state: 'ok' as const,
  reason: null,
  failing_since: null,
  failures_in_row: 0,
  pending: [],
  deadman_state: 'ok',
};

const status = (
  ntfy: Partial<NotificationStatus['ntfy']> = {},
  deadman: Partial<NotificationStatus['deadman']> = {},
): NotificationStatus => ({
  ntfy: {
    configured: true,
    server: 'ntfy.sh',
    token: true,
    min_severity: 'warning',
    events: true,
    sent: 3,
    suppressed: 0,
    dropped: 0,
    queued: 0,
    last_sent: { at: '2026-11-18T10:00:00Z', title: 'Test' },
    last_error: null,
    last_test: { at: '2026-11-18T10:00:00Z', ok: true, error: null, by: null },
    rate_limit_per_hour: 20,
    ...ntfy,
  },
  deadman: {
    configured: true,
    server: 'hc-ping.com',
    interval_s: 300,
    pings: 12,
    last_ok: '2026-11-18T10:05:00Z',
    last_error: null,
    last_skip: null,
    healthy: true,
    unhealthy_reason: null,
    ...deadman,
  },
});

describe('notifyVerdict', () => {
  it('is good when tested and the watchdog is alive', () => {
    expect(notifyVerdict(status())).toEqual({
      tone: 'good',
      key: 'notifyVerdictOk',
      failing: false,
    });
    expect(notifyVerdict(null)).toBeNull();
  });

  it('marks a failed test, a failed delivery and a dead watchdog as failing', () => {
    const failedTest = status({
      last_test: { at: '2026-11-18T10:00:00Z', ok: false, error: '403', by: null },
    });
    expect(notifyVerdict(failedTest)).toMatchObject({ tone: 'bad', failing: true });
    const lost = status({ last_error: { at: '2026-11-18T11:00:00Z', error: 'timeout' } });
    expect(notifyVerdict(lost)).toMatchObject({ key: 'notifyVerdictDelivery', failing: true });
    const dead = status({}, { healthy: false, unhealthy_reason: 'no ping for 3 h' });
    expect(notifyVerdict(dead)).toMatchObject({ tone: 'warn', failing: true });
  });

  it('does not call a channel that was never set up failing', () => {
    expect(notifyVerdict(status({ configured: false }))).toMatchObject({
      key: 'notifyVerdictOff',
      failing: false,
    });
    expect(notifyVerdict(status({ last_test: null }))).toMatchObject({ failing: false });
  });
});

describe('deliveryFailing', () => {
  it('follows the service health when given, else the newest of error and send', () => {
    const health = (over: object) => ({
      ...status(),
      health: { ...HEALTH, ...over },
    });
    expect(deliveryFailing(health({ state: 'failing', failures_in_row: 3 }))).toBe(true);
    expect(
      deliveryFailing({
        ...health({}),
        ntfy: { ...status().ntfy, last_error: { at: '2026-11-18T11:00:00Z', error: 'x' } },
      }),
    ).toBe(false);
    expect(
      deliveryFailing(status({ last_error: { at: '2026-11-18T09:00:00Z', error: 'x' } })),
    ).toBe(false);
    expect(
      deliveryFailing(status({ last_error: { at: '2026-11-18T11:00:00Z', error: 'x' } })),
    ).toBe(true);
    expect(deliveryFailing(status({ last_error: 'boom' as never }))).toBe(false);
  });

  it('reads the service verdict: a failed test that a later send outran is not failing', () => {
    const failedTest = {
      ...status({ last_test: { at: '2026-11-18T09:00:00Z', ok: false, error: '403', by: null } }),
      health: HEALTH,
    };
    expect(notifyVerdict(failedTest)?.failing).toBe(false);
    const untested = {
      ...status({ last_test: null }),
      health: { ...HEALTH, state: 'untested' as const },
    };
    expect(notifyVerdict(untested)?.key).toBe('notifyVerdictUntested');
  });

  it('defers to an alarm of the service', () => {
    const alarm = {
      code: 'notify_failing',
      severity: 'warning' as const,
      message: '',
      since: '',
      detail: {},
    };
    expect(hasNotifyAlarm([alarm])).toBe(true);
    expect(hasNotifyAlarm([])).toBe(false);
  });
});

describe('retryAfter', () => {
  it('reads the seconds of a 429 and nothing else', () => {
    const limited = new ApiError('x', 429, { detail: { code: 'test_rate', retry_after_s: 11.2 } });
    expect(retryAfter(limited)).toBe(12);
    expect(retryAfter(new ApiError('x', 409, { detail: { retry_after_s: 3 } }))).toBeNull();
    expect(retryAfter(new Error('x'))).toBeNull();
  });
});
