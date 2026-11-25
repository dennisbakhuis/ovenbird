// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from '@testing-library/svelte';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { ReplayCoverage, ReplayEpisode } from '$lib/replay/replay';
import CoverageStrip from './CoverageStrip.svelte';
import ReplayEpisodes from './ReplayEpisodes.svelte';

const DAY = 86_400_000;
const START = Date.parse('2026-11-17T23:00:00Z');
const NOW = Date.parse('2026-11-20T12:00:00Z');

afterEach(cleanup);

const coverage = (counts: number[], retention = 30): ReplayCoverage => ({
  from: new Date(START).toISOString(),
  to: new Date(NOW).toISOString(),
  timezone: 'Europe/Amsterdam',
  interval_s: 60,
  retention_days: retention,
  max_days: 31,
  oldest: null,
  newest: null,
  versions: [],
  days: counts.map((decisions, index) => ({
    date: `2026-11-${18 + index}`,
    from: new Date(START + index * DAY).toISOString(),
    to: new Date(START + (index + 1) * DAY).toISOString(),
    decisions,
    expected: 1440,
    first: null,
    last: null,
  })),
});

function episode(start: string, extra: Partial<ReplayEpisode> = {}): ReplayEpisode {
  return {
    start,
    end: new Date(Date.parse(start) + 30 * 60_000).toISOString(),
    minutes: 30,
    max_abs_k: 2.5,
    max_diff_k: 2.5,
    ovenbird_c: 35,
    pump_c: 32,
    recorded_c: 33,
    reason: 'start_ramp',
    reason_at_max: 'start_ramp',
    mode: 'shadow',
    writer: 'other',
    ended_by: 'converged',
    ...extra,
  };
}

describe('CoverageStrip', () => {
  it('grades the days, outlines the period and picks a day', async () => {
    const onpick = vi.fn();
    render(CoverageStrip, {
      coverage: coverage([0, 700, 1440]),
      period: { from: START + 2 * DAY + 3_600_000, to: NOW },
      now: NOW,
      onpick,
    });
    const days = screen.getAllByTestId('replay-day');
    expect(days.map((day) => day.dataset['level'])).toEqual(['none', 'part', 'full']);
    expect((days[0] as HTMLButtonElement).disabled).toBe(true);
    expect(days[2]?.getAttribute('aria-pressed')).toBe('true');
    expect(days[1]?.getAttribute('aria-pressed')).toBe('false');
    await fireEvent.click(days[1] as HTMLElement);
    expect(onpick).toHaveBeenCalledWith(expect.objectContaining({ decisions: 700 }));
    expect(screen.getByTestId('replay-coverage').textContent).toContain('kept 30 days');
  });

  it('says so when nothing is stored', () => {
    render(CoverageStrip, { coverage: coverage([0, 0]), period: null, now: NOW, onpick: () => {} });
    expect(screen.getByTestId('replay-coverage').textContent).toContain('No decisions stored');
  });
});

describe('ReplayEpisodes', () => {
  it('lists the newest first with the values and the reason', () => {
    render(ReplayEpisodes, {
      episodes: [
        episode('2026-11-19T06:00:00Z'),
        episode('2026-11-20T06:00:00Z', { max_diff_k: -1.5, max_abs_k: 1.5, ended_by: 'gap' }),
      ],
      total: 2,
      thresholdK: 1,
      now: NOW,
    });
    const items = screen.getAllByTestId('replay-episode');
    expect(items[0]?.dataset['end']).toBe('gap');
    expect(items[0]?.textContent).toContain('1.5 K below the pump');
    expect(items[1]?.textContent).toContain('2.5 K above the pump');
    expect(items[1]?.textContent).toContain('replayed 35 °C, recorded 33 °C, pump 32 °C');
    expect(items[1]?.textContent).toContain('Reason:');
  });

  it('hides older episodes and notes a capped list', () => {
    const episodes = Array.from({ length: 6 }, (_, index) =>
      episode(new Date(START + index * 3_600_000).toISOString()),
    );
    render(ReplayEpisodes, { episodes, total: 640, thresholdK: 1, now: NOW });
    expect(screen.getByTestId('replay-episodes-more').textContent).toContain('2 older');
    expect(screen.getByTestId('replay-episodes').textContent).toContain('newest 6 of 640');
  });

  it('says when the replay stayed with the pump', () => {
    render(ReplayEpisodes, { episodes: [], total: 0, thresholdK: 1, now: NOW });
    expect(screen.getByTestId('replay-episodes-none').textContent).toContain('1 K');
  });
});
