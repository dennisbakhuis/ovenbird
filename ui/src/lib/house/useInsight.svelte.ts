import { poll } from '$lib/core/poll.svelte';
import { fetchInsightDaily, type InsightDaily } from '$lib/house/insight';

export type InsightPhase = 'loading' | 'ok' | 'missing' | 'failed';

export interface InsightState {
  phase: InsightPhase;
  data: InsightDaily | null;
}

const REFRESH_MS = 600_000;

/**
 * Reactive daily insight for `days` days, refreshed every 10 minutes. Call `start()` inside an
 * `$effect` and return its stop function. A 404 gives phase `missing` and stops retrying.
 */
export function createInsight(days: number) {
  const state = $state<InsightState>({ phase: 'loading', data: null });

  function start(): () => void {
    return poll(
      async (signal) => {
        try {
          const result = await fetchInsightDaily(days, signal);
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
      { intervalMs: REFRESH_MS },
    );
  }

  return {
    state,
    start,
  };
}
