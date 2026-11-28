import { untrack } from 'svelte';
import { fetchHealth, fetchLiveTicket, fetchSnapshot } from './api';
import { backoffDelay, wsUrl } from './backoff';
import { TicketSocket } from './ticketSocket';
import type { Health, ServerMessage, Snapshot } from './types';

export interface SocketLike {
  onopen: ((event: unknown) => void) | null;
  onmessage: ((event: { data: unknown }) => void) | null;
  onclose: ((event: unknown) => void) | null;
  close(): void;
}

export interface LiveDeps {
  createSocket: () => SocketLike;
  loadHealth: () => Promise<Health>;
  loadSnapshot: () => Promise<Snapshot>;
  setTimer: (fn: () => void, ms: number) => number;
  clearTimer: (id: number) => void;
  random: () => number;
  now: () => number;
}

/**
 * Parse a WebSocket payload into a server message, or null when it is not understood.
 */
export function parseMessage(raw: unknown): ServerMessage | null {
  if (typeof raw !== 'string') return null;
  try {
    const parsed = JSON.parse(raw) as { type?: unknown; data?: unknown };
    const known = ['snapshot', 'health', 'decision', 'config'];
    if (typeof parsed.type === 'string' && known.includes(parsed.type) && parsed.data) {
      return parsed as ServerMessage;
    }
  } catch {
    return null;
  }
  return null;
}

/**
 * Reactive live state: latest snapshot and health, WebSocket connectivity and a 1 s clock.
 * `connected` is false until the first open; `lost` is true only once a connection attempt has
 * ended without a stream, so a page still opening its first socket shows no outage.
 */
export class LiveStore {
  snapshot = $state<Snapshot | null>(null);
  health = $state<Health | null>(null);
  connected = $state(false);
  lost = $state(false);
  receivedAt = $state(0);
  decisionSeq = $state(0);
  configVersion = $state<number | null>(null);
  now = $state(0);
  attempt = 0;

  #deps: LiveDeps;
  #socket: SocketLike | null = null;
  #retryTimer: number | null = null;
  #clockTimer: number | null = null;
  #running = false;
  #anchorAt = 0;
  #anchorReceived = 0;
  #rate = 1;

  constructor(deps: LiveDeps) {
    this.#deps = deps;
    this.now = deps.now();
  }

  start(): void {
    if (this.#running) return;
    this.#running = true;
    this.#tickClock();
    this.#connect();
  }

  stop(): void {
    this.#running = false;
    if (this.#retryTimer !== null) this.#deps.clearTimer(this.#retryTimer);
    if (this.#clockTimer !== null) this.#deps.clearTimer(this.#clockTimer);
    this.#retryTimer = null;
    this.#clockTimer = null;
    const socket = this.#socket;
    this.#socket = null;
    if (socket) {
      socket.onclose = null;
      socket.close();
    }
    this.connected = false;
    this.lost = false;
  }

  applySnapshot(snapshot: Snapshot): void {
    this.snapshot = snapshot;
    this.receivedAt = this.#deps.now();
    this.now = this.receivedAt;
    this.#observeRate(Date.parse(snapshot.at), this.receivedAt);
  }

  #observeRate(at: number, received: number): void {
    if (Number.isNaN(at)) return;
    const elapsed = received - this.#anchorReceived;
    if (this.#anchorReceived === 0 || elapsed > 120_000 || at < this.#anchorAt) {
      this.#anchorAt = at;
      this.#anchorReceived = received;
      return;
    }
    if (elapsed < 3_000) return;
    const ratio = (at - this.#anchorAt) / elapsed;
    this.#rate = ratio > 0.8 && ratio < 1.25 ? 1 : Math.min(Math.max(ratio, 0.1), 3_600);
  }

  /**
   * The service's current time in epoch ms: the latest snapshot time plus the real time elapsed
   * since it arrived, scaled by the observed clock rate. Falls back to the browser clock.
   * Not reactive; read `now` alongside it where the value must refresh.
   */
  serviceNow(): number {
    return untrack(() => {
      const at = this.snapshot ? Date.parse(this.snapshot.at) : NaN;
      const real = this.#deps.now();
      if (Number.isNaN(at)) return real;
      const elapsed = Math.max(0, real - this.receivedAt);
      return at + elapsed * this.#rate;
    });
  }

  /**
   * The service clock as a reactive read: `serviceNow()`, refreshed by the 1 s tick.
   */
  get clock(): number {
    void this.now;
    return this.serviceNow();
  }

  #tickClock(): void {
    this.now = this.#deps.now();
    this.#clockTimer = this.#deps.setTimer(() => this.#tickClock(), 1000);
  }

  async #refresh(): Promise<void> {
    const [health, snapshot] = await Promise.allSettled([
      this.#deps.loadHealth(),
      this.#deps.loadSnapshot(),
    ]);
    if (health.status === 'fulfilled') this.health = health.value;
    if (snapshot.status === 'fulfilled' && this.snapshot === null)
      this.applySnapshot(snapshot.value);
  }

  #connect(): void {
    if (!this.#running) return;
    void this.#refresh();
    const socket = this.#deps.createSocket();
    this.#socket = socket;
    socket.onopen = () => {
      this.attempt = 0;
      this.connected = true;
      this.lost = false;
      void this.#refresh();
    };
    socket.onmessage = (event) => {
      const message = parseMessage(event.data);
      if (!message) return;
      if (message.type === 'snapshot') this.applySnapshot(message.data);
      else if (message.type === 'health') this.health = message.data;
      else if (message.type === 'decision') this.decisionSeq += 1;
      else this.configVersion = message.data.version;
    };
    socket.onclose = () => {
      this.connected = false;
      this.#socket = null;
      if (!this.#running) return;
      this.lost = true;
      const delay = backoffDelay(this.attempt, this.#deps.random);
      this.attempt += 1;
      this.#retryTimer = this.#deps.setTimer(() => this.#connect(), delay);
    };
  }
}

/**
 * Build the browser dependencies: the WebSocket opened with a live pass (or the mock stream in
 * mock mode) and fetch.
 */
export async function browserDeps(): Promise<LiveDeps> {
  let createSocket: () => SocketLike;
  if (import.meta.env.MODE === 'mock') {
    const { MockSocket } = await import('$mock/socket');
    createSocket = () => new MockSocket();
  } else {
    createSocket = () =>
      new TicketSocket(
        wsUrl(location),
        fetchLiveTicket,
        (url) => new WebSocket(url) as unknown as SocketLike,
      );
  }
  return {
    createSocket,
    loadHealth: () => fetchHealth(),
    loadSnapshot: () => fetchSnapshot(),
    setTimer: (fn, ms) => window.setTimeout(fn, ms),
    clearTimer: (id) => window.clearTimeout(id),
    random: Math.random,
    now: () => Date.now(),
  };
}
