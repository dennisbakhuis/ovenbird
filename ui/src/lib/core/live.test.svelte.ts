import { describe, expect, it, vi } from 'vitest';
import { health, makeSnapshot } from '$mock/fixtures';
import { LiveStore, type LiveDeps, type SocketLike } from './live.svelte';

class FakeSocket implements SocketLike {
  onopen: ((event: unknown) => void) | null = null;
  onmessage: ((event: { data: unknown }) => void) | null = null;
  onclose: ((event: unknown) => void) | null = null;
  closed = false;
  close(): void {
    this.closed = true;
  }
}

function setup() {
  const sockets: FakeSocket[] = [];
  const timers: { fn: () => void; ms: number; id: number }[] = [];
  let nextId = 1;
  const deps: LiveDeps = {
    createSocket: () => {
      const socket = new FakeSocket();
      sockets.push(socket);
      return socket;
    },
    loadHealth: () => Promise.resolve(health),
    loadSnapshot: () => Promise.resolve(makeSnapshot(0)),
    setTimer: (fn, ms) => {
      const id = nextId++;
      timers.push({ fn, ms, id });
      return id;
    },
    clearTimer: (id) => {
      const index = timers.findIndex((t) => t.id === id);
      if (index >= 0) timers.splice(index, 1);
    },
    random: () => 0.5,
    now: () => 1000,
  };
  return { store: new LiveStore(deps), sockets, timers };
}

describe('LiveStore', () => {
  it('tracks connection state and applies messages', () => {
    const { store, sockets } = setup();
    store.start();
    expect(store.connected).toBe(false);
    sockets[0]!.onopen?.({});
    expect(store.connected).toBe(true);
    sockets[0]!.onmessage?.({ data: JSON.stringify({ type: 'snapshot', data: makeSnapshot(0) }) });
    expect(store.snapshot?.heishamon.alive).toBe(true);
    sockets[0]!.onmessage?.({
      data: JSON.stringify({ type: 'health', data: { ...health, ready: false } }),
    });
    expect(store.health?.ready).toBe(false);
    store.stop();
  });

  it('reconnects with growing backoff and resets after open', () => {
    const { store, sockets, timers } = setup();
    store.start();
    sockets[0]!.onclose?.({});
    const retry1 = timers.find((t) => t.ms !== 1000)!;
    expect(retry1.ms).toBe(750);
    timers.splice(timers.indexOf(retry1), 1);
    retry1.fn();
    expect(sockets).toHaveLength(2);
    sockets[1]!.onclose?.({});
    expect(timers.find((t) => t.ms !== 1000)!.ms).toBe(1500);
    store.stop();
  });

  it('reports a lost stream only after a connection ended, not while the first one opens', () => {
    const { store, sockets, timers } = setup();
    store.start();
    expect(store.connected).toBe(false);
    expect(store.lost).toBe(false);
    sockets[0]!.onopen?.({});
    expect(store.lost).toBe(false);
    sockets[0]!.onclose?.({});
    expect(store.lost).toBe(true);
    timers.find((t) => t.ms !== 1000)!.fn();
    expect(store.lost).toBe(true);
    sockets[1]!.onopen?.({});
    expect(store.lost).toBe(false);
    store.stop();
  });

  it('does not reconnect after stop', () => {
    const { store, sockets } = setup();
    const spy = vi.fn();
    store.start();
    const first = sockets[0]!;
    first.onclose = spy;
    store.stop();
    expect(first.closed).toBe(true);
    expect(sockets).toHaveLength(1);
  });

  it('derives the service clock from the snapshot time and the observed rate', () => {
    let real = 10_000;
    const store = new LiveStore({
      createSocket: () => new FakeSocket(),
      loadHealth: () => Promise.resolve(health),
      loadSnapshot: () => Promise.resolve(makeSnapshot(0)),
      setTimer: () => 1,
      clearTimer: () => {},
      random: () => 0.5,
      now: () => real,
    });
    expect(store.serviceNow()).toBe(10_000);
    const base = Date.parse('2026-11-07T12:00:00Z');
    const at = (offsetMs: number) => ({
      ...makeSnapshot(0),
      at: new Date(base + offsetMs).toISOString(),
    });
    store.applySnapshot(at(0));
    real += 10_000;
    store.applySnapshot(at(600_000));
    real += 1_000;
    expect(store.serviceNow()).toBe(base + 600_000 + 60_000);
  });
});
