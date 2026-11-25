export type Route =
  | 'home'
  | 'setpoint'
  | 'weather'
  | 'settings'
  | 'pump'
  | 'activity'
  | 'system'
  | 'more'
  | 'house'
  | 'dev-charts';

export const ROUTES: Route[] = [
  'home',
  'setpoint',
  'weather',
  'settings',
  'pump',
  'activity',
  'system',
  'more',
  'house',
  'dev-charts',
];

export interface Location {
  route: Route;
  sub: string[];
  query: Record<string, string>;
}

const ALIASES: Record<string, { route: Route; sub: string[] }> = {
  signals: { route: 'system', sub: ['signals'] },
  health: { route: 'system', sub: [] },
  shadow: { route: 'system', sub: ['shadow'] },
  trial: { route: 'system', sub: ['trial'] },
};

/**
 * Parse a location hash such as "#/setpoint?at=2026-11-08T01:00:00Z" or "#/activity/holds"
 * into a route, sub-path segments and query parameters, defaulting to home.
 */
export function parseLocation(hash: string): Location {
  const body = hash.replace(/^#\/?/, '');
  const [pathPart = '', queryPart = ''] = body.split('?', 2);
  const segments = pathPart.split('/').filter(Boolean);
  const first = segments[0] ?? '';
  const query: Record<string, string> = {};
  for (const [key, value] of new URLSearchParams(queryPart)) query[key] = value;
  const alias = ALIASES[first];
  if (alias) return { route: alias.route, sub: alias.sub, query };
  const route = ROUTES.find((candidate) => candidate === first);
  if (!route) return { route: 'home', sub: [], query: {} };
  return { route, sub: segments.slice(1), query };
}

/**
 * Parse a location hash into just its top-level route.
 */
export function parseRoute(hash: string): Route {
  return parseLocation(hash).route;
}

/**
 * Build the hash for a route with optional sub-path and query parameters.
 */
export function buildHash(
  route: Route,
  sub: string[] = [],
  query: Record<string, string | undefined> = {},
): string {
  const path = [route, ...sub].join('/');
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(query)) {
    if (value !== undefined && value !== '') params.set(key, value);
  }
  const text = params.toString();
  return `#/${path}${text ? `?${text}` : ''}`;
}

/**
 * Whether a change of location opens another page (route or sub-path), as opposed to a
 * query change on the same page such as a new time range.
 */
export function isNewPage(previous: Location, next: Location): boolean {
  return previous.route !== next.route || previous.sub.join('/') !== next.sub.join('/');
}

/**
 * Whether the app runs inside a frame, such as the Home Assistant ingress panel. A frame on
 * another origin throws on access to `top`, which also means framed.
 */
export function isFramed(
  win: { readonly self: unknown; readonly top: unknown } | undefined = globalThis.window,
): boolean {
  if (!win) return false;
  try {
    return win.self !== win.top;
  } catch {
    return true;
  }
}
