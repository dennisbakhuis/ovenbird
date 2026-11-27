// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from '@testing-library/svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { HouseRun } from '$lib/house/run';
import RunCard from './RunCard.svelte';

afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

const idle: HouseRun = {
  state: 'idle',
  enabled: true,
  started_at: null,
  next_due_at: '2099-01-01T10:00:00Z',
  interval_h: 168,
  last: {
    at: '2026-11-27T10:00:00Z',
    outcome: 'promoted',
    message: 'promoted: better',
    runtime_s: 275,
    model: 'house-1',
  },
  failure: null,
};

function answer(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

function service(queue: (() => Response)[]): ReturnType<typeof vi.fn> {
  const fetcher = vi.fn(async () => (queue.length > 1 ? queue.shift()! : queue[0]!)());
  vi.stubGlobal('fetch', fetcher);
  return fetcher;
}

async function settle(): Promise<void> {
  await vi.advanceTimersByTimeAsync(0);
}

beforeEach(() => {
  vi.useFakeTimers({ toFake: ['setInterval', 'clearInterval', 'setTimeout', 'clearTimeout'] });
});

describe('RunCard', () => {
  it('shows an idle learner with its next run and last outcome', async () => {
    service([() => answer(200, idle)]);
    render(RunCard);
    await settle();
    expect(screen.getByTestId('run-state').getAttribute('data-kind')).toBe('scheduled');
    expect(screen.getByTestId('run-outcome').textContent).toContain('New model in use');
    expect((screen.getByTestId('run-now') as HTMLButtonElement).disabled).toBe(false);
  });

  it('renders nothing on an older service without the endpoint', async () => {
    service([() => answer(404, { detail: 'Not Found' })]);
    render(RunCard);
    await settle();
    expect(screen.queryByTestId('house-run')).toBeNull();
  });

  it('explains a learner that is not built in and cannot be started', async () => {
    service([() => answer(200, { ...idle, state: 'unavailable', last: null, next_due_at: null })]);
    render(RunCard);
    await settle();
    expect(screen.getByTestId('run-state').textContent).toContain('no built-in learner');
    expect((screen.getByTestId('run-now') as HTMLButtonElement).disabled).toBe(true);
  });

  it('says automatic learning is off', async () => {
    service([() => answer(200, { ...idle, enabled: false, next_due_at: null })]);
    render(RunCard);
    await settle();
    expect(screen.getByTestId('run-state').getAttribute('data-kind')).toBe('disabled');
    expect(screen.getByTestId('run-settings-link').getAttribute('href')).toBe('#/settings/house');
  });

  it('puts a failure in plain words next to the last run', async () => {
    service([
      () =>
        answer(200, {
          ...idle,
          failure: { at: '2026-11-27T09:00:00Z', reason: 'memory', detail: 'killed' },
        }),
    ]);
    render(RunCard);
    await settle();
    const failure = screen.getByTestId('run-failure');
    expect(failure.textContent).toContain('ran out of memory');
    expect(failure.textContent).toContain('killed');
  });

  it('lists what is still missing when the last run found too little data', async () => {
    service([
      () =>
        answer(200, {
          ...idle,
          last: { ...idle.last, outcome: 'learning', message: 'not enough' },
        }),
    ]);
    render(RunCard, {
      credibility: {
        credible: false,
        days: 38,
        heating_days: 37,
        cold_days: 6,
        outside_span_k: 12,
        rules: {
          heating_days: 30,
          heating_day_w: 300,
          cold_days: 10,
          cold_day_below_c: 5,
          outside_span_k: 10,
        },
        needed: { heating_days: 0, cold_days: 4, outside_span_k: 0 },
        reasons: [],
        low_confidence: false,
        message: null,
      },
    });
    await settle();
    expect(screen.getByTestId('run-learning').textContent).toContain('4 more cold days');
  });

  it('starts a run, polls every 5 s until idle and then tells the page', async () => {
    const running: HouseRun = { ...idle, state: 'running', started_at: '2026-11-27T12:00:00Z' };
    const fetcher = service([
      () => answer(200, idle),
      () => answer(202, running),
      () => answer(200, running),
      () => answer(200, idle),
    ]);
    const onsettled = vi.fn();
    render(RunCard, { onsettled });
    await settle();
    await fireEvent.click(screen.getByTestId('run-now'));
    await settle();
    expect(screen.getByTestId('run-state').getAttribute('data-kind')).toBe('running');
    expect((screen.getByTestId('run-now') as HTMLButtonElement).disabled).toBe(true);
    expect(onsettled).not.toHaveBeenCalled();
    await vi.advanceTimersByTimeAsync(5000);
    expect(screen.getByTestId('run-state').getAttribute('data-kind')).toBe('running');
    await vi.advanceTimersByTimeAsync(5000);
    expect(screen.getByTestId('run-state').getAttribute('data-kind')).toBe('scheduled');
    expect(onsettled).toHaveBeenCalledTimes(1);
    const calls = fetcher.mock.calls.length;
    await vi.advanceTimersByTimeAsync(20_000);
    expect(fetcher.mock.calls.length).toBe(calls);
  });

  it('explains a refusal for a read-only login', async () => {
    let call = 0;
    service([
      () => (call++ === 0 ? answer(200, idle) : answer(403, { detail: 'needs the operate role' })),
    ]);
    render(RunCard);
    await settle();
    await fireEvent.click(screen.getByTestId('run-now'));
    await settle();
    expect(screen.getByTestId('run-error').textContent).toContain('operate or admin role');
  });
});
