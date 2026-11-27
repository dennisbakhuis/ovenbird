import { describe, expect, it } from 'vitest';
import { ApiError } from '$lib/core/api';
import { outcomeKind, presentation, refusalOf, type HouseRun } from './run';

const NOW = Date.parse('2026-11-27T12:00:00Z');

const run = (overrides: Partial<HouseRun> = {}): HouseRun => ({
  state: 'idle',
  enabled: true,
  started_at: null,
  next_due_at: '2026-12-04T10:00:00Z',
  interval_h: 168,
  last: null,
  failure: null,
  ...overrides,
});

describe('presentation', () => {
  it('puts running and unavailable first, whatever else is set', () => {
    expect(presentation(run({ state: 'running', enabled: false }), NOW)).toBe('running');
    expect(presentation(run({ state: 'unavailable', enabled: false }), NOW)).toBe('unavailable');
  });

  it('says disabled when automatic learning is off', () => {
    expect(presentation(run({ enabled: false, next_due_at: null }), NOW)).toBe('disabled');
  });

  it('tells scheduled, due and never apart', () => {
    expect(presentation(run(), NOW)).toBe('scheduled');
    expect(presentation(run({ next_due_at: '2026-11-27T11:00:00Z' }), NOW)).toBe('due_soon');
    expect(presentation(run({ next_due_at: null }), NOW)).toBe('never');
  });
});

describe('outcomeKind', () => {
  it('knows the learner outcomes and falls back for anything else', () => {
    expect(outcomeKind('promoted')).toBe('promoted');
    expect(outcomeKind('kept_champion')).toBe('kept');
    expect(outcomeKind('kept')).toBe('kept');
    expect(outcomeKind('learning')).toBe('learning');
    expect(outcomeKind('failed')).toBe('failed');
    expect(outcomeKind('whatever')).toBe('other');
    expect(outcomeKind(null)).toBe('other');
  });
});

describe('refusalOf', () => {
  const conflict = (code: string) =>
    new ApiError('run', 409, { detail: { code, message: '', params: {} } });

  it('reads the 409 codes', () => {
    expect(refusalOf(conflict('learner_running'))).toBe('learner_running');
    expect(refusalOf(conflict('learner_unavailable'))).toBe('learner_unavailable');
    expect(refusalOf(conflict('other'))).toBe('failed');
  });

  it('reads the authorisation refusals', () => {
    expect(refusalOf(new ApiError('run', 403))).toBe('forbidden');
    expect(refusalOf(new ApiError('run', 401))).toBe('forbidden');
  });

  it('calls everything else failed', () => {
    expect(refusalOf(new ApiError('run', 500))).toBe('failed');
    expect(refusalOf(new TypeError('network'))).toBe('failed');
  });
});
