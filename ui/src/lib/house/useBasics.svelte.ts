import { Poller } from '$lib/core/poll.svelte';
import { fetchBasics, type InsightBasics } from '$lib/house/basics';

export type BasicsPhase = 'loading' | 'ok' | 'missing' | 'failed';

export interface BasicsState {
  phase: BasicsPhase;
  data: InsightBasics | null;
}

export const BASICS_REFRESH_MS = 60_000;

/**
 * Reactive house basics, refreshed every minute (the service caches the fits and reads the live
 * values on each request). Call `start()` inside an `$effect` and return its stop function. A 404
 * gives phase `missing` and stops retrying; a failure keeps the last data and tries again.
 */
export function createBasics() {
  const state = $state<BasicsState>({ phase: 'loading', data: null });
  const poller = new Poller(
    async (signal) => {
      try {
        const result = await fetchBasics(signal);
        if (result.kind === 'missing') {
          state.phase = 'missing';
          state.data = null;
          return 'stop';
        }
        state.data = result.data;
        state.phase = 'ok';
      } catch {
        if (signal.aborted) return;
        state.phase = state.data ? 'ok' : 'failed';
      }
    },
    { intervalMs: BASICS_REFRESH_MS },
  );

  return {
    state,
    start: () => poller.start(),
    retry: () => poller.refresh(),
  };
}
