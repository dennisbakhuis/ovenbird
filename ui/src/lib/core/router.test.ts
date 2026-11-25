import { describe, expect, it } from 'vitest';
import { buildHash, parseLocation } from './location';

describe('router', () => {
  it('parses top-level routes, sub-paths and queries', () => {
    expect(parseLocation('#/home')).toEqual({ route: 'home', sub: [], query: {} });
    expect(parseLocation('#/activity/holds')).toEqual({
      route: 'activity',
      sub: ['holds'],
      query: {},
    });
    expect(parseLocation('#/setpoint?at=2026-11-08T01%3A00%3A00Z&range=6')).toEqual({
      route: 'setpoint',
      sub: [],
      query: { at: '2026-11-08T01:00:00Z', range: '6' },
    });
    expect(parseLocation('#/system/signals/')).toEqual({
      route: 'system',
      sub: ['signals'],
      query: {},
    });
  });

  it('keeps the old routes working', () => {
    expect(parseLocation('#/signals').route).toBe('system');
    expect(parseLocation('#/signals').sub).toEqual(['signals']);
    expect(parseLocation('#/health')).toEqual({ route: 'system', sub: [], query: {} });
  });

  it('falls back to home for unknown or empty hashes', () => {
    expect(parseLocation('').route).toBe('home');
    expect(parseLocation('#/').route).toBe('home');
    expect(parseLocation('#/nope/x?y=1')).toEqual({ route: 'home', sub: [], query: {} });
  });

  it('round-trips through buildHash', () => {
    const hash = buildHash('setpoint', [], { at: '2026-11-08T01:00:00Z', range: '24' });
    expect(parseLocation(hash)).toEqual({
      route: 'setpoint',
      sub: [],
      query: { at: '2026-11-08T01:00:00Z', range: '24' },
    });
    expect(buildHash('activity', ['audit'])).toBe('#/activity/audit');
    expect(buildHash('home', [], { at: undefined, x: '' })).toBe('#/home');
  });
});

describe('page changes and framing', () => {
  it('treats route and sub-path changes as a new page, not query changes', async () => {
    const { isNewPage, parseLocation: parse } = await import('./location');
    expect(isNewPage(parse('#/home'), parse('#/setpoint'))).toBe(true);
    expect(isNewPage(parse('#/activity'), parse('#/activity/holds'))).toBe(true);
    expect(isNewPage(parse('#/setpoint?range=6'), parse('#/setpoint?range=24'))).toBe(false);
  });

  it('detects a frame, also across origins', async () => {
    const { isFramed } = await import('./location');
    const self = {};
    expect(isFramed({ self, top: self })).toBe(false);
    expect(isFramed({ self, top: {} })).toBe(true);
    const crossOrigin = {
      self,
      get top(): unknown {
        throw new Error('blocked');
      },
    };
    expect(isFramed(crossOrigin)).toBe(true);
    expect(isFramed(undefined)).toBe(false);
  });
});
