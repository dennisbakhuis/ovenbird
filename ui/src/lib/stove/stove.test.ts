import { describe, expect, it } from 'vitest';
import {
  canStartStove,
  stoveHeadlineKey,
  stoveOrigin,
  stoveReference,
  stoveWaiting,
} from './stove';
import type { StoveStatus } from '$lib/core/types';

const status = (over: Partial<StoveStatus> = {}): StoveStatus => ({
  enabled: true,
  auto: true,
  active: false,
  source: null,
  trigger: null,
  since: null,
  entry_c: null,
  integral_k: null,
  blocked: false,
  level_blocked: false,
  reentry_wait: false,
  backoff_k: 3,
  enter_c: 22.5,
  exit_c: 21.5,
  reference_c: 21.0,
  request: null,
  ...over,
});

describe('stove', () => {
  it('can start only when enabled and not already running', () => {
    expect(canStartStove(status())).toBe(true);
    expect(canStartStove(status({ active: true }))).toBe(false);
    expect(canStartStove(status({ enabled: false }))).toBe(false);
    expect(canStartStove(null)).toBe(false);
  });

  it('tells automatic, manual and handover episodes apart', () => {
    expect(stoveOrigin(status())).toBeNull();
    expect(stoveOrigin(status({ active: true, source: 'auto', trigger: 'level' }))).toBe('auto');
    expect(stoveOrigin(status({ active: true, source: 'manual', trigger: 'manual' }))).toBe(
      'manual',
    );
    expect(stoveOrigin(status({ active: true, source: 'auto', trigger: 'handover' }))).toBe(
      'handover',
    );
  });

  it('names why the detection waits, a stop first', () => {
    expect(stoveWaiting(status())).toBeNull();
    expect(stoveWaiting(status({ level_blocked: true }))).toBe('level_blocked');
    expect(stoveWaiting(status({ reentry_wait: true, level_blocked: true }))).toBe('reentry_wait');
    expect(stoveWaiting(status({ blocked: true, reentry_wait: true }))).toBe('blocked');
    expect(stoveWaiting(status({ active: true, blocked: true }))).toBeNull();
  });

  it('tells whether the rest of the house is watched', () => {
    const active = status({ active: true, reference_c: 19.6 });
    expect(stoveReference(active, null)).toBe('none');
    expect(stoveReference(active, 'ha/sensor.hall')).toBe('watched');
    expect(stoveReference({ ...active, reference_c: null }, 'ha/sensor.hall')).toBe('stale');
  });

  it('says "backed off" only while ovenbird sends', () => {
    expect(stoveHeadlineKey('controlling', true)).toBe('stoveBanner');
    expect(stoveHeadlineKey('unknown', false)).toBe('stoveBanner');
    expect(stoveHeadlineKey('watching', false)).toBe('stoveBannerIdle_watching');
    expect(stoveHeadlineKey('paused', false)).toBe('stoveBannerIdle_paused');
    expect(stoveHeadlineKey('held', false)).toBe('stoveBannerIdle_held');
    expect(stoveHeadlineKey('simulated', false)).toBe('stoveBannerIdle');
  });
});
