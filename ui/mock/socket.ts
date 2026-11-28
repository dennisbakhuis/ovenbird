import type { SocketLike } from '../src/lib/core/live.svelte';
import { makeDecision } from './decisions';
import { health, makeSnapshot } from './fixtures';
import { parseScenario, scenarioNow } from './scenario';

interface MockSocketWindow {
  __mockSockets?: MockSocket[];
}

/**
 * Fake WebSocket emitting a snapshot and decision on open and every 5 s afterwards. The snapshot
 * comes from the mock server when it answers, so server-side state (a manual wood-stove request,
 * the room value it implies) reaches the live view too; otherwise it is built here.
 */
export class MockSocket implements SocketLike {
  onopen: ((event: unknown) => void) | null = null;
  onmessage: ((event: { data: unknown }) => void) | null = null;
  onclose: ((event: unknown) => void) | null = null;
  #timer: number | undefined;

  constructor() {
    const registry = ((window as unknown as MockSocketWindow).__mockSockets ??= []);
    registry.push(this);
    window.setTimeout(() => {
      this.onopen?.({});
      void this.#emit();
      this.#timer = window.setInterval(() => void this.#emit(), 5000);
    }, 300);
  }

  async #snapshot(now: number, scenario: ReturnType<typeof parseScenario>): Promise<unknown> {
    try {
      const response = await fetch('api/v1/snapshot');
      if (response.ok) return await response.json();
    } catch {
      /* fall back to a locally built snapshot */
    }
    return makeSnapshot(now, scenario);
  }

  async #emit(): Promise<void> {
    const scenario = parseScenario(document.cookie);
    const now = scenarioNow(scenario, Date.now());
    const snapshot = await this.#snapshot(now, scenario);
    this.onmessage?.({ data: JSON.stringify({ type: 'snapshot', data: snapshot }) });
    this.onmessage?.({ data: JSON.stringify({ type: 'health', data: health }) });
    this.onmessage?.({
      data: JSON.stringify({ type: 'decision', data: makeDecision(now, now, 'auto') }),
    });
  }

  /**
   * Simulate the server ending the stream: stop emitting and report the close.
   */
  drop(): void {
    this.close();
  }

  close(): void {
    window.clearInterval(this.#timer);
    this.onclose?.({});
  }
}
