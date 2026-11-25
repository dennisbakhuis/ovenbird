import { describe, expect, it } from 'vitest';
import { parseLocation } from '$lib/core/location';
import {
  HELP_TOPICS,
  hrefFor,
  isAppRoute,
  isHelpTopic,
  isPageTopic,
  pageTopic,
  splitTarget,
  topicFile,
  topicFor,
} from './resolve';

const at = (hash: string, available?: (id: string) => boolean) =>
  topicFor(parseLocation(hash), available);

describe('help topic resolution', () => {
  it('maps pages to their topic', () => {
    for (const page of ['home', 'setpoint', 'weather', 'pump', 'settings', 'more'])
      expect(at(`#/${page}`)).toBe(page);
    expect(at('')).toBe('home');
    expect(at('#/dev-charts')).toBe('home');
    expect(at('#/setpoint?at=2026-11-08T01:00:00Z')).toBe('setpoint');
  });

  it('maps settings sections, activity tabs and system tabs', () => {
    for (const section of [
      'curve',
      'room',
      'pump-duty',
      'behaviour',
      'quiet',
      'stove',
      'emitter',
      'weather',
      'versions',
    ])
      expect(at(`#/settings/${section}`)).toBe(`settings/${section}`);
    expect(at('#/activity')).toBe('activity');
    expect(at('#/activity/alarms')).toBe('activity');
    expect(at('#/activity/holds')).toBe('activity/holds');
    expect(at('#/activity/commands')).toBe('activity/commands');
    expect(at('#/activity/audit')).toBe('activity/audit');
    expect(at('#/system')).toBe('system');
    expect(at('#/system/overview')).toBe('system');
    expect(at('#/system/signals')).toBe('system/signals');
    expect(at('#/signals')).toBe('system/signals');
    expect(at('#/system/data')).toBe('system/data');
    expect(at('#/system/replay')).toBe('system/replay');
  });

  it('falls back to the page for unknown or unavailable sub-topics', () => {
    expect(at('#/settings/unknown')).toBe('settings');
    expect(at('#/pump/whatever')).toBe('pump');
    expect(at('#/settings/curve', () => false)).toBe('settings');
    expect(at('#/activity/holds', (id) => id !== 'activity/holds')).toBe('activity');
  });

  it('lists every topic once and knows their pages, files and links', () => {
    expect(new Set(HELP_TOPICS).size).toBe(HELP_TOPICS.length);
    expect(HELP_TOPICS).toHaveLength(31);
    expect(isHelpTopic('settings/pump-duty')).toBe(true);
    expect(isHelpTopic('toString')).toBe(false);
    expect(pageTopic('settings/pump-duty')).toBe('settings');
    expect(topicFile('settings/pump-duty')).toBe('settings-pump-duty');
    for (const id of HELP_TOPICS.filter(isPageTopic)) {
      const href = hrefFor(id);
      expect(href !== null && isAppRoute(href), id).toBe(true);
      expect(topicFor(parseLocation(href ?? ''))).toBe(id);
    }
  });

  it('keeps the guides first and off the page routes', () => {
    expect(HELP_TOPICS.slice(0, 3)).toEqual(['start', 'switching', 'home']);
    for (const id of ['start', 'switching'] as const) {
      expect(isHelpTopic(id)).toBe(true);
      expect(isPageTopic(id)).toBe(false);
      expect(hrefFor(id)).toBeNull();
      expect(isAppRoute(`#/${id}`)).toBe(false);
      expect(at(`#/${id}`)).toBe('home');
    }
    expect(isPageTopic('settings/stove')).toBe(true);
    expect(isAppRoute('#/settings/stove')).toBe(true);
  });

  it('accepts only in-app routes as links', () => {
    expect(isAppRoute('#/pump')).toBe(true);
    expect(isAppRoute('#/activity/alarms')).toBe(true);
    expect(isAppRoute('#/setpoint?range=7d')).toBe(true);
    expect(isAppRoute('#/nowhere')).toBe(false);
    expect(isAppRoute('#/settings/bogus')).toBe(false);
    expect(isAppRoute('#/dev-charts')).toBe(false);
    expect(isAppRoute('#/pump/a/b')).toBe(false);
    expect(isAppRoute('https://example.com')).toBe(false);
    expect(isAppRoute('javascript:alert(1)')).toBe(false);
  });

  it('splits data-help targets into topic and section', () => {
    expect(splitTarget('settings/pump-duty.max-speed')).toEqual({
      topic: 'settings/pump-duty',
      section: 'max-speed',
    });
    expect(splitTarget('home.rooms')).toEqual({ topic: 'home', section: 'rooms' });
    expect(splitTarget('nope.rooms')).toEqual({ topic: null, section: 'rooms' });
    expect(splitTarget('rooms')).toEqual({ topic: null, section: 'rooms' });
  });
});
