// @vitest-environment jsdom
import { cleanup, render, screen } from '@testing-library/svelte';
import { afterEach, describe, expect, it } from 'vitest';
import ForecastErrorCard from './ForecastErrorCard.svelte';
import DayCards from './DayCards.svelte';
import WeatherStates from './WeatherStates.svelte';

afterEach(cleanup);

globalThis.ResizeObserver ??= class {
  observe(): void {}
  unobserve(): void {}
  disconnect(): void {}
};

describe('weather components', () => {
  it('shows the opt-in explanation and a link to Settings → Weather when disabled', () => {
    render(WeatherStates, {
      props: { kind: 'disabled', reason: 'weather_enabled is off', provider: 'open-meteo' },
    });
    expect(screen.getByTestId('weather-disabled')).toBeTruthy();
    expect(screen.getByTestId('weather-enable-link').getAttribute('href')).toBe(
      '#/settings/weather',
    );
  });

  it('announces a stale forecast with its age', () => {
    render(WeatherStates, { props: { kind: 'stale', age: 11_000 } });
    const box = screen.getByTestId('weather-stale');
    expect(box.getAttribute('role')).toBe('status');
    expect(box.textContent).toMatch(/out of date/i);
    expect(screen.getByTestId('weather-stale-why-button')).toBeTruthy();
  });

  it('renders one card per day', () => {
    render(DayCards, {
      props: {
        now: Date.parse('2026-11-16T12:00:00'),
        days: [
          {
            start: Date.parse('2026-11-16T00:00:00'),
            min: 1,
            max: 6,
            meanCloud: 20,
            sunHours: 5,
            peakRadiation: 300,
            maxWind: 6,
            curveMin: 30,
            curveMax: 33,
            sky: 'sunny',
            hours: 24,
          },
        ],
      },
    });
    expect(screen.getAllByTestId('weather-day')).toHaveLength(1);
    expect(screen.getByTestId('weather-day').textContent).toMatch(/5 h of sun/);
  });

  it('lists error per lead time and handles missing statistics', () => {
    const { container } = render(ForecastErrorCard, {
      props: { error: { lead_h: [6, 24], bias_k: [0.3, null], mae_k: [0.9, 1.4], n: [10, 4] } },
    });
    expect(container.textContent).toMatch(/Bias: \+0\.3 K/);
    cleanup();
    render(ForecastErrorCard, { props: { error: { lead_h: [], bias_k: [], mae_k: [], n: [] } } });
    expect(screen.getByTestId('forecast-error').textContent).toMatch(/Not enough/);
  });
});
