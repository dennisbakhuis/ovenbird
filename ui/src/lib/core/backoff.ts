/**
 * Reconnect delay in milliseconds for the given attempt (0-based): exponential, capped, with
 * optional jitter in [0.5, 1) of the delay.
 */
export function backoffDelay(
  attempt: number,
  random: () => number = Math.random,
  baseMs = 1000,
  maxMs = 30000,
): number {
  const exp = Math.min(maxMs, baseMs * 2 ** Math.max(0, attempt));
  return Math.round(exp * (0.5 + random() * 0.5));
}

/**
 * Derive the WebSocket URL for `api/v1/ws` relative to a page location, keeping any path prefix.
 */
export function wsUrl(loc: Pick<Location, 'protocol' | 'host' | 'pathname'>): string {
  const scheme = loc.protocol === 'https:' ? 'wss:' : 'ws:';
  const dir = loc.pathname.endsWith('/')
    ? loc.pathname
    : loc.pathname.slice(0, loc.pathname.lastIndexOf('/') + 1);
  return `${scheme}//${loc.host}${dir}api/v1/ws`;
}
