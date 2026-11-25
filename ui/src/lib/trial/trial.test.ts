import { describe, expect, it } from 'vitest';
import { dictionaries, translateOptional } from '$lib/i18n';
import {
  checkEvidence,
  checkGroups,
  checkLine,
  goLiveCounts,
  openBeforeGoLive,
  checkLink,
  confirmMatches,
  criterionDelta,
  criterionValue,
  elapsedSeconds,
  itemPhase,
  releaseCounts,
  targetShare,
  trialVerdict,
  withNotifyVerdict,
  type TrialSummary,
  type TrialStatus,
  type ReleaseRun,
  type TrialCheck,
  type TrialFormat,
} from './trial';

const fmt: TrialFormat = {
  num: (value, digits = 1) => value.toFixed(digits),
  date: (iso) => `@${iso.slice(0, 10)}`,
  duration: (seconds) => `${Math.round(seconds)}s`,
  percent: (share) => `${Math.round(share * 100)}%`,
};

const check = (
  id: string,
  status: TrialCheck['status'],
  evidence: Record<string, unknown> = {},
): TrialCheck => ({ id, phase: 'go_live', status, message: 'service text', evidence });

const run = (overrides: Partial<ReleaseRun> = {}): ReleaseRun =>
  ({
    started_at: '2026-11-18T10:00:00Z',
    finished_at: null,
    done: false,
    outcome: 'running',
    rehearsal: true,
    by: 'admin',
    reason: null,
    paused_before: false,
    duration_s: 4,
    within_limit: true,
    snapshot_taken_at: '2026-11-14T10:00:00Z',
    items: [
      {
        kind: 'water_setpoint',
        snapshot: 32,
        before: 29,
        target: 32,
        status: 'sent',
        detail: null,
        at: null,
      },
      {
        kind: 'max_pump_duty',
        snapshot: 160,
        before: 160,
        target: null,
        status: 'unchanged',
        detail: null,
        at: null,
      },
      {
        kind: 'quiet_mode',
        snapshot: null,
        before: 0,
        target: null,
        status: 'missing',
        detail: null,
        at: null,
      },
    ],
    ...overrides,
  }) as unknown as ReleaseRun;

describe('checkLine', () => {
  it('builds the shadow-days line from the evidence', () => {
    expect(checkLine(check('shadow_days', 'warn', { days: 9.2, required_days: 14 }), fmt)).toEqual({
      key: 'trialMsg_shadow_days_warn',
      params: { days: '9.2', required: '14' },
    });
    expect(checkLine(check('shadow_days', 'fail', { days: 0 }), fmt).key).toBe(
      'trialMsg_shadow_days_fail',
    );
  });

  it('tells long divergence from low coverage', () => {
    expect(
      checkLine(
        check('divergence', 'warn', { long_episodes: 2, long_episode_min: 120, days: 14 }),
        fmt,
      ),
    ).toEqual({ key: 'trialMsg_divergence_long', params: { n: 2, min: '120' } });
    expect(
      checkLine(check('divergence', 'warn', { long_episodes: 0, coverage: 0.5, days: 14 }), fmt),
    ).toEqual({ key: 'trialMsg_divergence_coverage', params: { percent: '50%', days: '14' } });
  });

  it('picks the notification variant from the evidence', () => {
    expect(checkLine(check('notifications', 'fail'), fmt).key).toBe('trialMsg_notifications_off');
    expect(checkLine(check('notifications', 'fail', { last_test: { ok: false } }), fmt).key).toBe(
      'trialMsg_notifications_test_failed',
    );
    expect(checkLine(check('notifications', 'warn', { last_test: null }), fmt).key).toBe(
      'trialMsg_notifications_no_test',
    );
    expect(
      checkLine(
        check('notifications', 'warn', { last_test: { ok: true }, deadman_configured: false }),
        fmt,
      ).key,
    ).toBe('trialMsg_notifications_no_deadman');
    expect(
      checkLine(
        check('notifications', 'warn', { last_test: { ok: true }, deadman_configured: true }),
        fmt,
      ).key,
    ).toBe('trialMsg_notifications_deadman_pending');
    expect(
      checkLine(
        check('notifications', 'warn', {
          last_test: { ok: true },
          last_error: { at: '2026-11-18T10:00:00Z', error: 'timeout' },
        }),
        fmt,
      ).key,
    ).toBe('trialMsg_notifications_delivery_failed');
    expect(
      checkLine(check('notifications', 'fail', { configured: false, last_test: null }), fmt).key,
    ).toBe('trialMsg_notifications_off');
  });

  it('never shows Notifications as done while the live verdict says failing', () => {
    const status = {
      at: '',
      mode: 'shadow',
      configured_mode: 'shadow',
      ready: true,
      counts: { ok: 2, warn: 0, fail: 0 },
      checklist: [check('notifications', 'ok'), check('room', 'ok')],
      summary: null,
    } as unknown as TrialStatus;
    expect(withNotifyVerdict(status, false, 'notifyVerdictTestFailed')).toBe(status);
    const live = withNotifyVerdict(status, true, 'notifyVerdictTestFailed');
    expect(live.ready).toBe(false);
    expect(live.counts).toEqual({ ok: 1, warn: 1, fail: 0 });
    expect(live.checklist[0]?.status).toBe('warn');
    expect(checkLine(live.checklist[0] as TrialCheck, fmt).key).toBe('notifyVerdictTestFailed');
  });

  it('reads the rehearsal and the snapshot', () => {
    expect(
      checkLine(
        check('rollback_rehearsal', 'ok', { last: { duration_s: 42, outcome: 'ok' } }),
        fmt,
      ),
    ).toEqual({ key: 'trialMsg_rollback_rehearsal_ok', params: { duration: '42s' } });
    expect(
      checkLine(
        check('rollback_rehearsal', 'warn', {
          last: { duration_s: 400, outcome: 'ok' },
          limit_s: 300,
        }),
        fmt,
      ),
    ).toEqual({
      key: 'trialMsg_rollback_rehearsal_slow',
      params: { duration: '400s', limit: '300s' },
    });
    expect(checkLine(check('pump_snapshot', 'warn', { snapshot: null }), fmt).key).toBe(
      'trialMsg_pump_snapshot_none',
    );
    expect(checkLine(check('pump_snapshot', 'warn'), fmt).key).toBe(
      'trialMsg_pump_snapshot_no_loop',
    );
    expect(
      checkLine(
        check('pump_snapshot', 'warn', { snapshot: { released_at: '2026-11-18T10:00:00Z' } }),
        fmt,
      ).key,
    ).toBe('trialMsg_pump_snapshot_released');
  });

  it('counts alarms and reads the room', () => {
    expect(checkLine(check('alarms', 'fail', { critical: ['low_flow'] }), fmt).params).toEqual({
      n: 1,
    });
    expect(checkLine(check('room', 'warn', { plausible: false }), fmt).key).toBe(
      'trialMsg_room_implausible',
    );
    expect(checkLine(check('room', 'warn', { plausible: true, authority: 0.45 }), fmt)).toEqual({
      key: 'trialMsg_room_authority',
      params: { percent: '45%' },
    });
    expect(checkLine(check('room', 'fail'), fmt).key).toBe('trialMsg_room_none');
  });

  it('has a text in both languages for every variant it can return', () => {
    const variants: TrialCheck[] = [
      check('shadow_days', 'ok', { days: 15 }),
      check('shadow_days', 'warn', { days: 3 }),
      check('shadow_days', 'fail'),
      check('divergence', 'ok'),
      check('divergence', 'warn', { long_episodes: 1 }),
      check('divergence', 'warn', { coverage: 0.4 }),
      check('divergence', 'fail'),
      check('envelope_rule', 'ok'),
      check('envelope_rule', 'warn'),
      check('envelope_rule', 'fail'),
      check('notifications', 'ok'),
      check('notifications', 'warn', { last_error: 'x' }),
      check('rollback_rehearsal', 'fail'),
      check('rollback_rehearsal', 'warn', { last: { outcome: 'incomplete' } }),
      check('alarms', 'ok'),
      check('alarms', 'warn', { warning: ['x'] }),
      check('room', 'ok'),
      check('room', 'fail', { fresh: false }),
      check('pump_snapshot', 'ok', { snapshot: { taken_at: '2026-11-14T10:00:00Z' } }),
      check('pump_snapshot', 'warn', { snapshot: { complete: false } }),
    ];
    for (const language of ['en', 'nl'] as const)
      for (const item of variants) {
        const line = checkLine(item, fmt);
        expect(translateOptional(language, line.key, line.params), line.key).toBeTruthy();
      }
    for (const key of Object.keys(dictionaries.en).filter((k) => k.startsWith('trialMsg_')))
      expect(Object.hasOwn(dictionaries.nl, key), key).toBe(true);
  });
});

describe('checkEvidence and checkLink', () => {
  it('gives a quiet second line when the evidence has one', () => {
    expect(
      checkEvidence(check('shadow_days', 'warn', { first: '2026-11-05T10:00:00Z' }), fmt),
    ).toEqual({ key: 'trialEv_shadow_days_since', params: { time: '@2026-11-05' } });
    expect(checkEvidence(check('alarms', 'ok'), fmt)).toBeNull();
    expect(
      checkEvidence(
        check('divergence', 'warn', { coverage: 0.96, max_abs_k: 3.4, hours_over: 11.5 }),
        fmt,
      ),
    ).toEqual({
      key: 'trialEv_divergence_figures',
      params: { percent: '96%', max: '3.4', hours: '11.5' },
    });
  });

  it('links the facts behind an item', () => {
    expect(checkLink('divergence')).toBe('#/system/shadow');
    expect(checkLink('shadow_days')).toBeNull();
  });
});

describe('release progress', () => {
  it('sorts items into running, good and bad', () => {
    expect(itemPhase('queued')).toBe('running');
    expect(itemPhase('retry')).toBe('running');
    expect(itemPhase('verified')).toBe('good');
    expect(itemPhase('not_managed')).toBe('good');
    expect(itemPhase('timeout')).toBe('bad');
    expect(releaseCounts(run())).toEqual({ running: 1, good: 1, bad: 1 });
  });

  it('adds the time since the fetch while running, not after', () => {
    expect(elapsedSeconds(run(), 1_000, 3_500)).toBeCloseTo(6.5);
    expect(elapsedSeconds(run({ done: true, duration_s: 9 }), 1_000, 60_000)).toBe(9);
    expect(elapsedSeconds(run(), 5_000, 1_000)).toBe(4);
  });

  it('measures against the 5-minute target', () => {
    expect(targetShare(150)).toBe(0.5);
    expect(targetShare(900)).toBe(1);
    expect(targetShare(-5)).toBe(0);
  });

  it('needs the confirmation word typed', () => {
    expect(confirmMatches(' release ', 'RELEASE')).toBe(true);
    expect(confirmMatches('teruggeven', 'TERUGGEVEN')).toBe(true);
    expect(confirmMatches('RELEAS', 'RELEASE')).toBe(false);
    expect(confirmMatches('', '')).toBe(false);
  });
});

describe('criteria values', () => {
  it('formats per criterion', () => {
    expect(criterionValue('room_mean', 21.7, fmt)).toBe('21.7 °C');
    expect(criterionValue('short_runs', 0.122, fmt)).toBe('12%');
    expect(criterionValue('pump_errors', 0, fmt)).toBe('0');
    expect(criterionValue('writes_per_day', null, fmt)).toBe('–');
  });

  it('signs the difference', () => {
    expect(criterionDelta('room_mean', -0.1, fmt)).toBe('−0.10 K');
    expect(criterionDelta('short_runs', 0.024, fmt)).toBe('+2.4 pp');
    expect(criterionDelta('pump_errors', null, fmt)).toBeNull();
    expect(criterionDelta('room_min', 0, fmt)).toBe('±0.00 K');
  });
});

describe('trialVerdict', () => {
  const period = { from: '', to: '', days: 0.4 } as TrialSummary['trial'];
  const summary = (over: Partial<TrialSummary>): TrialSummary =>
    ({
      source: 'go_live',
      trial: period,
      baseline: period,
      criteria: [],
      met: false,
      ...over,
    }) as TrialSummary;

  it('says met only for a completed trial', () => {
    expect(trialVerdict(summary({ state: 'complete', met: true }), fmt).key).toBe(
      'trialCriteriaMet',
    );
    expect(
      trialVerdict(summary({ state: 'running', met: false, criteria_met: true, days: 0.4 }), fmt),
    ).toMatchObject({ key: 'trialVerdictRunningOk', params: { days: '0.4', min: '7' } });
    expect(trialVerdict(summary({ state: 'no_trial', source: 'default' }), fmt).key).toBe(
      'trialVerdictNoTrial',
    );
    expect(trialVerdict(summary({ state: 'ended_early' }), fmt).tone).toBe('warn');
  });

  it('never calls the default comparison of an older service a met trial', () => {
    expect(trialVerdict(summary({ source: 'default', met: true }), fmt).key).toBe(
      'trialVerdictNoTrial',
    );
    expect(trialVerdict(summary({ source: 'query', met: true }), fmt).key).toBe(
      'trialVerdictNotATrial',
    );
  });
});

describe('the notifications item with the service health', () => {
  const item = (status: 'ok' | 'warn' | 'fail', health: object) =>
    checkLine(
      { id: 'notifications', phase: 'go_live', status, message: '', evidence: { health } },
      fmt,
    ).key;

  it('names the same failure as the System tile', () => {
    expect(item('fail', { state: 'failing', failures_in_row: 4 })).toBe(
      'trialMsg_notifications_delivery_failed',
    );
    expect(item('fail', { state: 'failing', failures_in_row: 0 })).toBe(
      'trialMsg_notifications_test_failed',
    );
    expect(item('warn', { state: 'untested' })).toBe('trialMsg_notifications_no_test');
    expect(item('warn', { state: 'ok', deadman_state: 'not_configured' })).toBe(
      'trialMsg_notifications_no_deadman',
    );
  });
});

describe('the checks added for the two groups', () => {
  const line = (
    id: string,
    status: 'ok' | 'warn' | 'fail',
    evidence: Record<string, unknown> = {},
  ) => checkLine({ id, phase: 'go_live', status, message: '', evidence }, fmt).key;

  it('has a text for every status of the new checks', () => {
    for (const id of ['release_plan', 'envelope_proof'])
      for (const status of ['ok', 'warn', 'fail'] as const)
        expect(translateOptional('en', line(id, status)), `${id} ${status}`).toBeDefined();
  });

  it('says declared, not seen, for a rule that is only declared', () => {
    expect(line('envelope_rule', 'ok', { installed: true, count: 0, last: null })).toBe(
      'trialMsg_envelope_rule_declared',
    );
    expect(line('envelope_rule', 'ok', { installed: true, count: 2, last: { at: 'x' } })).toBe(
      'trialMsg_envelope_rule_ok',
    );
  });
});

describe('checkGroups', () => {
  const check = (id: string, status: 'ok' | 'warn' | 'fail', phase?: 'go_live' | 'trial') =>
    ({
      id,
      status,
      message: '',
      evidence: {},
      ...(phase ? { phase } : {}),
    }) as TrialCheck;

  it('splits before go-live from the first trial and counts only the first as to do', () => {
    const list = [
      check('alarms', 'ok', 'go_live'),
      check('release_plan', 'fail', 'go_live'),
      check('rollback_rehearsal', 'fail', 'trial'),
    ];
    expect(checkGroups(list).map((g) => [g.phase, g.checks.length])).toEqual([
      ['go_live', 2],
      ['trial', 1],
    ]);
    expect(openBeforeGoLive(list)).toBe(1);
    expect(goLiveCounts(list)).toEqual({ ok: 1, warn: 0, fail: 1 });
  });

  it('keeps one group for an older service', () => {
    const list = [check('alarms', 'ok'), check('rollback_rehearsal', 'fail')];
    expect(checkGroups(list)).toEqual([{ phase: null, checks: list }]);
    expect(openBeforeGoLive(list)).toBe(1);
  });
});
