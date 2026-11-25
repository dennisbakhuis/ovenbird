import type { SocketLike } from './live.svelte';

/**
 * A live connection that first fetches a single-use pass and opens the WebSocket with it.
 *
 * Safari never sends the login on a WebSocket, so the service would refuse the connection; the
 * pass comes from a normal request, which does carry the login. Without a pass (an older
 * service, or the request failed) the socket opens without one, which works where the browser
 * sends the login itself.
 */
export class TicketSocket implements SocketLike {
  onopen: ((event: unknown) => void) | null = null;
  onmessage: ((event: { data: unknown }) => void) | null = null;
  onclose: ((event: unknown) => void) | null = null;

  #socket: SocketLike | null = null;
  #closed = false;

  constructor(
    url: string,
    getTicket: () => Promise<string | null>,
    open: (url: string) => SocketLike,
  ) {
    void getTicket()
      .catch(() => null)
      .then((ticket) => {
        if (this.#closed) return;
        const target = ticket ? `${url}?ticket=${encodeURIComponent(ticket)}` : url;
        const socket = open(target);
        this.#socket = socket;
        socket.onopen = (event) => this.onopen?.(event);
        socket.onmessage = (event) => this.onmessage?.(event);
        socket.onclose = (event) => this.onclose?.(event);
      });
  }

  close(): void {
    this.#closed = true;
    this.#socket?.close();
  }
}
