// @vitest-environment jsdom
import { cleanup, render, screen } from '@testing-library/svelte';
import { afterEach, describe, expect, it } from 'vitest';
import type { Alarm, ForecastPoint } from '$lib/core/types';
import VerdictCard from './VerdictCard.svelte';
import HomeTiles from './HomeTiles.svelte';
import RoomCard from './RoomCard.svelte';

globalThis.ResizeObserver ??= class {
  observe(): void {}
  unobserve(): void {}
  disconnect(): void {}
};

afterEach(cleanup);

const NOW = Date.parse('2026-11-15T12:00:00Z');
const alarm = (severity: Alarm['severity']): Alarm => ({
  code: 'flow_low',
  severity,
  message: 'flow',
  since: '2026-11-15T11:00:00Z',
  detail: {},
});

describe('VerdictCard', () => {
  it('says the house is at temperature, with tonight under it and no link', () => {
    render(VerdictCard, {
      verdict: { kind: 'ok', tone: 'good', attention: null },
      tonight: 'Tonight: down to −1 °C outside. Heating continues.',
      clock: NOW,
    });
    expect(screen.getByTestId('verdict-text').textContent).toBe('The house is at temperature');
    expect(screen.getByTestId('tonight').textContent).toContain('−1 °C');
    expect(screen.queryByTestId('verdict-link')).toBeNull();
    expect(screen.getByRole('status')).toBeTruthy();
  });

  it('is an alert for a critical alarm and names it, linking to Activity', () => {
    render(VerdictCard, {
      verdict: {
        kind: 'attention',
        tone: 'bad',
        attention: { kind: 'alarm', code: alarm('critical').code, more: 1, critical: true },
      },
      clock: NOW,
    });
    expect(screen.getByRole('alert')).toBeTruthy();
    expect(screen.getByTestId('verdict-text').textContent).toMatch(
      /^Needs attention: .+ and 1 more$/,
    );
    expect(screen.getByTestId('verdict-link').getAttribute('href')).toBe('#/activity');
  });

  it('points a hold to the holds tab', () => {
    render(VerdictCard, {
      verdict: {
        kind: 'attention',
        tone: 'warn',
        attention: { kind: 'held', reason: null, until: null, latched: true },
      },
      clock: NOW,
    });
    expect(screen.getByTestId('verdict-text').textContent).toBe(
      'Needs attention: ovenbird waits for a release',
    );
    expect(screen.getByTestId('verdict-link').getAttribute('href')).toBe('#/activity/holds');
  });
});

describe('HomeTiles', () => {
  const stats = {
    energy: { electricKwh: 9.6, heatKwh: 39, cop: 4.06, coverage: 1 },
    starts: 4,
    defrosts: 3,
    meanRunS: 3600,
    longestRunS: 5400,
  };
  const forecast: ForecastPoint[] = [
    [new Date(NOW + 3_600_000).toISOString(), 2, null, null, null],
  ];

  it('shows energy, COP and starts without a forecast tile when weather is unavailable', () => {
    render(HomeTiles, { stats, forecast: null, forecastOff: false, nowMs: NOW });
    expect(screen.getByTestId('tile-energy').textContent).toContain('9.6');
    expect(screen.getByTestId('tile-cop').textContent).toContain('4.1');
    expect(screen.getByTestId('tile-starts').textContent).toContain('4');
    expect(screen.queryByTestId('forecast-strip')).toBeNull();
    expect(screen.queryByTestId('forecast-off')).toBeNull();
  });

  it('points to the weather settings when the forecast is off', () => {
    render(HomeTiles, { stats, forecast: null, forecastOff: true, nowMs: NOW });
    expect(screen.getByTestId('forecast-off')).toBeTruthy();
  });

  it('shows the forecast range when weather is on', () => {
    render(HomeTiles, { stats, forecast, forecastOff: false, nowMs: NOW });
    expect(screen.getByTestId('forecast-strip').textContent).toContain('2');
  });

  it('shows dashes without data', () => {
    render(HomeTiles, { stats: null, forecast: null, forecastOff: false, nowMs: NOW });
    expect(screen.getByTestId('tile-energy').textContent).toContain('–');
  });
});

describe('RoomCard', () => {
  it('shows value, target and sensor freshness', () => {
    render(RoomCard, {
      props: {
        value: 20.4,
        target: 21.0,
        halfBand: 0.5,
        trend: -0.2,
        fresh: true,
        changedAgoS: 7200,
        configured: true,
      },
    });
    expect(screen.getByTestId('room-value').textContent).toContain('20.4');
    expect(screen.getByText(/Sensor ok/)).toBeTruthy();
  });

  const props = {
    value: 21.3,
    target: 21.0,
    halfBand: 0.5,
    trend: 0,
    fresh: true,
    changedAgoS: 166 * 86400,
    configured: true,
  };

  it('says the value is trusted less below full authority', () => {
    render(RoomCard, { props: { ...props, trust: 'reduced', authority: 0.4 } });
    const line = screen.getByTestId('room-trust');
    expect(line.textContent).toContain('ovenbird trusts it less (40 %)');
    expect(line.textContent).not.toContain('Sensor ok');
    expect(line.querySelector('a')?.getAttribute('href')).toBe('#/setpoint');
  });

  it('warns that the room value is not trusted at zero authority', () => {
    render(RoomCard, { props: { ...props, trust: 'untrusted', authority: 0 } });
    const line = screen.getByTestId('room-trust');
    expect(line.textContent).toContain('Room value not trusted');
    expect(line.classList.contains('warn')).toBe(true);
  });

  it('explains a missing room sensor', () => {
    render(RoomCard, {
      props: {
        value: null,
        target: null,
        halfBand: 0.5,
        trend: null,
        fresh: false,
        changedAgoS: null,
        configured: false,
      },
    });
    expect(screen.getByText('No room sensor is configured')).toBeTruthy();
  });
});
