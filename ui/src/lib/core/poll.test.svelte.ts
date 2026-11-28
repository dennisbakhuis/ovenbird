import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { poll, pollDelay, Poller } from './poll.svelte';

beforeEach(() => vi.useFakeTimers());
afterEach(() => vi.useRealTimers());

describe('pollDelay', () => {
  it('keeps the interval without a back-off bound and doubles up to it', () => {
    expect(pollDelay(1000, 3)).toBe(1000);
    expect(pollDelay(1000, 0, 8000)).toBe(1000);
    expect(pollDelay(1000, 2, 8000)).toBe(4000);
    expect(pollDelay(1000, 6, 8000)).toBe(8000);
  });
});

describe('Poller', () => {
  it('runs at once, then after every interval', async () => {
    const task = vi.fn(() => Promise.resolve());
    const stop = poll(task, { intervalMs: 1000 });
    expect(task).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(2500);
    expect(task).toHaveBeenCalledTimes(3);
    stop();
  });

  it('waits one interval first when not immediate', async () => {
    const task = vi.fn(() => Promise.resolve());
    const stop = poll(task, { intervalMs: 1000, immediate: false });
    expect(task).not.toHaveBeenCalled();
    await vi.advanceTimersByTimeAsync(1000);
    expect(task).toHaveBeenCalledTimes(1);
    stop();
  });

  it('reads a function interval for each run', async () => {
    let interval = 100;
    const task = vi.fn(() => Promise.resolve());
    const stop = poll(task, { intervalMs: () => interval });
    await vi.advanceTimersByTimeAsync(250);
    expect(task).toHaveBeenCalledTimes(3);
    interval = 10_000;
    await vi.advanceTimersByTimeAsync(100);
    await vi.advanceTimersByTimeAsync(5000);
    expect(task).toHaveBeenCalledTimes(4);
    stop();
  });

  it('aborts the running task and stops scheduling when stopped', async () => {
    let signal: AbortSignal | undefined;
    const task = vi.fn((s: AbortSignal) => {
      signal = s;
      return new Promise<void>(() => undefined);
    });
    const stop = poll(task, { intervalMs: 1000 });
    stop();
    expect(signal?.aborted).toBe(true);
    await vi.advanceTimersByTimeAsync(5000);
    expect(task).toHaveBeenCalledTimes(1);
  });

  it('does not schedule another run when stopped during a run', async () => {
    let finish: () => void = () => undefined;
    const task = vi.fn(() => new Promise<void>((resolve) => (finish = resolve)));
    const stop = poll(task, { intervalMs: 1000 });
    stop();
    finish();
    await vi.advanceTimersByTimeAsync(5000);
    expect(task).toHaveBeenCalledTimes(1);
  });

  it('ends the loop when the task resolves to stop', async () => {
    const task = vi.fn(() => Promise.resolve('stop'));
    const stop = poll(task, { intervalMs: 1000 });
    await vi.advanceTimersByTimeAsync(5000);
    expect(task).toHaveBeenCalledTimes(1);
    stop();
  });

  it('backs off after failures and recovers on success', async () => {
    let fail = true;
    const task = vi.fn(() => (fail ? Promise.reject(new Error('down')) : Promise.resolve()));
    const poller = new Poller(task, { intervalMs: 1000, maxBackoffMs: 4000 });
    const stop = poller.start();
    await vi.advanceTimersByTimeAsync(0);
    expect(poller.failures).toBe(1);
    await vi.advanceTimersByTimeAsync(1999);
    expect(task).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(1);
    expect(task).toHaveBeenCalledTimes(2);
    expect(poller.failures).toBe(2);
    await vi.advanceTimersByTimeAsync(3999);
    expect(task).toHaveBeenCalledTimes(2);
    fail = false;
    await vi.advanceTimersByTimeAsync(1);
    expect(task).toHaveBeenCalledTimes(3);
    expect(poller.failures).toBe(0);
    stop();
  });

  it('refreshes on demand but not while a run is in flight', async () => {
    let finish: () => void = () => undefined;
    const task = vi.fn(() => new Promise<void>((resolve) => (finish = resolve)));
    const poller = new Poller(task, { intervalMs: 60_000 });
    const stop = poller.start();
    poller.refresh();
    expect(task).toHaveBeenCalledTimes(1);
    finish();
    await vi.advanceTimersByTimeAsync(0);
    poller.refresh();
    expect(task).toHaveBeenCalledTimes(2);
    stop();
  });
});
