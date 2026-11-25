import { ROUTES, type Location, type Route } from '$lib/core/location';
import type { HelpTopicId } from './types';

const SUB_TOPICS = {
  settings: [
    'curve',
    'room',
    'pump-duty',
    'behaviour',
    'quiet',
    'stove',
    'house',
    'ha',
    'mqtt',
    'emitter',
    'weather',
    'versions',
  ],
  activity: ['holds', 'commands', 'audit'],
  system: ['signals', 'shadow', 'trial', 'replay', 'data'],
} as const satisfies Partial<Record<Route, readonly string[]>>;

const PAGE_TOPICS = [
  'home',
  'setpoint',
  'weather',
  'pump',
  'settings',
  'activity',
  'system',
  'more',
  'house',
] as const;

const GUIDE_TOPICS: readonly HelpTopicId[] = ['start', 'switching'];

const ALL: Record<HelpTopicId, true> = {
  start: true,
  switching: true,
  home: true,
  setpoint: true,
  weather: true,
  pump: true,
  settings: true,
  'settings/curve': true,
  'settings/room': true,
  'settings/pump-duty': true,
  'settings/behaviour': true,
  'settings/quiet': true,
  'settings/stove': true,
  'settings/house': true,
  'settings/ha': true,
  'settings/mqtt': true,
  'settings/emitter': true,
  'settings/weather': true,
  'settings/versions': true,
  activity: true,
  'activity/holds': true,
  'activity/commands': true,
  'activity/audit': true,
  system: true,
  'system/signals': true,
  'system/shadow': true,
  'system/trial': true,
  'system/replay': true,
  'system/data': true,
  more: true,
  house: true,
};

/** Every help topic id: the guides first, then the app's pages and tabs in their order. */
export const HELP_TOPICS = Object.keys(ALL) as HelpTopicId[];

/** Sub-paths that the activity and system tabs accept besides their default tab. */
const DEFAULT_TABS: Partial<Record<Route, string>> = { activity: 'alarms', system: 'overview' };

/**
 * Whether a string is a known help topic id.
 */
export function isHelpTopic(id: string): id is HelpTopicId {
  return Object.hasOwn(ALL, id);
}

/**
 * Whether a topic describes a page or tab of the app; the guides (`start`, `switching`) do not.
 */
export function isPageTopic(id: HelpTopicId): boolean {
  return !GUIDE_TOPICS.includes(id);
}

/**
 * The topic of the page a topic belongs to: `settings/curve` → `settings`.
 */
export function pageTopic(id: HelpTopicId): HelpTopicId {
  return id.split('/')[0] as HelpTopicId;
}

/**
 * The help topic for a router location: the tab or settings section when it has a topic,
 * otherwise the page. `available` lets the caller fall back to the page when a sub-topic has
 * no content.
 */
export function topicFor(
  location: Pick<Location, 'route' | 'sub'>,
  available: (id: HelpTopicId) => boolean = () => true,
): HelpTopicId {
  const route = location.route;
  const page: HelpTopicId = (PAGE_TOPICS as readonly string[]).includes(route)
    ? (route as HelpTopicId)
    : 'home';
  const sub = location.sub[0];
  if (!sub || page !== route) return page;
  const subs: readonly string[] = SUB_TOPICS[route as keyof typeof SUB_TOPICS] ?? [];
  if (!subs.includes(sub)) return page;
  const candidate = `${route}/${sub}` as HelpTopicId;
  return available(candidate) ? candidate : page;
}

/**
 * The hash of the page a topic describes, or null for a guide that is not a page.
 */
export function hrefFor(id: HelpTopicId): string | null {
  return isPageTopic(id) ? `#/${id}` : null;
}

/**
 * The file name of a topic in `content/<language>/`: the id with `/` replaced by `-`.
 */
export function topicFile(id: HelpTopicId): string {
  return id.replace('/', '-');
}

/**
 * Whether an in-app link (`#/route/sub`) points at a page or tab that exists.
 */
export function isAppRoute(href: string): boolean {
  if (!href.startsWith('#/')) return false;
  const [path = '', query] = href.slice(2).split('?', 2);
  if (query !== undefined && !/^[\w.%=&:-]*$/.test(query)) return false;
  const segments = path.split('/').filter(Boolean);
  const [first, second, ...rest] = segments;
  if (!first || rest.length > 0) return false;
  if (first === 'dev-charts' || !ROUTES.includes(first as Route)) return false;
  if (second === undefined) return true;
  if (DEFAULT_TABS[first as Route] === second) return true;
  const subs: readonly string[] = SUB_TOPICS[first as keyof typeof SUB_TOPICS] ?? [];
  return subs.includes(second);
}

/**
 * Split a `data-help` target `<topic>.<section>` into its topic and section; the topic is
 * null when the prefix is not a known topic id.
 */
export function splitTarget(target: string): { topic: HelpTopicId | null; section: string } {
  const dot = target.lastIndexOf('.');
  if (dot < 0) return { topic: null, section: target };
  const prefix = target.slice(0, dot);
  return { topic: isHelpTopic(prefix) ? prefix : null, section: target.slice(dot + 1) };
}
