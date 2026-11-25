import { describe, expect, it, vi } from 'vitest';
import type { SocketLike } from './live.svelte';
import { TicketSocket } from './ticketSocket';

class FakeSocket implements SocketLike {
  onopen: ((event: unknown) => void) | null = null;
  onmessage: ((event: { data: unknown }) => void) | null = null;
  onclose: ((event: unknown) => void) | null = null;
  closed = false;
  constructor(readonly url: string) {}
  close(): void {
    this.closed = true;
  }
}

function opener() {
  const sockets: FakeSocket[] = [];
  const open = (url: string) => {
    const socket = new FakeSocket(url);
    sockets.push(socket);
    return socket;
  };
  return { sockets, open };
}

const settle = () => new Promise((resolve) => setTimeout(resolve, 0));

function only(sockets: FakeSocket[]): FakeSocket {
  expect(sockets).toHaveLength(1);
  const [socket] = sockets;
  if (!socket) throw new Error('no socket was opened');
  return socket;
}

describe('TicketSocket', () => {
  it('opens the live connection with the pass and forwards its events', async () => {
    const { sockets, open } = opener();
    const socket = new TicketSocket('ws://h/api/v1/ws', () => Promise.resolve('a+b/c'), open);
    const onopen = vi.fn();
    const onmessage = vi.fn();
    const onclose = vi.fn();
    socket.onopen = onopen;
    socket.onmessage = onmessage;
    socket.onclose = onclose;
    await settle();
    expect(sockets.map((s) => s.url)).toEqual(['ws://h/api/v1/ws?ticket=a%2Bb%2Fc']);
    const inner = only(sockets);
    inner.onopen?.('open');
    inner.onmessage?.({ data: 'x' });
    inner.onclose?.('close');
    expect(onopen).toHaveBeenCalledWith('open');
    expect(onmessage).toHaveBeenCalledWith({ data: 'x' });
    expect(onclose).toHaveBeenCalledWith('close');
  });

  it('opens without a pass when none can be had', async () => {
    const { sockets, open } = opener();
    new TicketSocket('ws://h/api/v1/ws', () => Promise.reject(new Error('404')), open);
    await settle();
    expect(sockets.map((s) => s.url)).toEqual(['ws://h/api/v1/ws']);
  });

  it('never opens after it was closed while the pass was on its way', async () => {
    const { sockets, open } = opener();
    const socket = new TicketSocket('ws://h/api/v1/ws', () => Promise.resolve('t'), open);
    socket.close();
    await settle();
    expect(sockets).toEqual([]);
  });

  it('closes the open connection and stays quiet once its handler is removed', async () => {
    const { sockets, open } = opener();
    const socket = new TicketSocket('ws://h/api/v1/ws', () => Promise.resolve('t'), open);
    const onclose = vi.fn();
    socket.onclose = onclose;
    await settle();
    socket.onclose = null;
    socket.close();
    const inner = only(sockets);
    inner.onclose?.('close');
    expect(inner.closed).toBe(true);
    expect(onclose).not.toHaveBeenCalled();
  });
});
