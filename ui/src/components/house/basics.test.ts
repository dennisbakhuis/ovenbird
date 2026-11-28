// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/svelte';
import { afterEach, beforeAll, describe, expect, it, vi } from 'vitest';
import { makeBasics, type BasicsScenario } from '$mock/basics';
import HouseBasics from './HouseBasics.svelte';

beforeAll(() => {
  globalThis.ResizeObserver ??= class {
    observe(): void {}
    unobserve(): void {}
    disconnect(): void {}
  };
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const NOW = Date.parse('2026-11-15T14:00:00');

function serve(scenario?: BasicsScenario, status = 200) {
  const fetchMock = vi.fn(async () =>
    status === 200
      ? new Response(JSON.stringify(makeBasics(NOW, scenario)))
      : new Response('{}', { status }),
  );
  vi.stubGlobal('fetch', fetchMock);
  return fetchMock;
}

describe('HouseBasics', () => {
  it('shows the credible figures without a provisional pill', async () => {
    serve();
    render(HouseBasics);
    const value = await screen.findByTestId('house-loss-value');
    expect(value.textContent).toContain('2.8');
    expect(screen.queryByTestId('house-loss-provisional')).toBeNull();
    expect(screen.getByTestId('house-loss-night').textContent).toContain('extrapolated');
    expect(screen.getByTestId('house-loss-design').textContent).toContain('−10 °C');
    expect(screen.getByTestId('house-loss-basis').textContent).toContain('2 °C outside');
    expect(screen.queryByTestId('house-loss-beyond')).toBeNull();
    expect(screen.getByTestId('house-by-weather-heat').querySelectorAll('[data-bar]')).toHaveLength(
      9,
    );
  });

  it('moves the verdict with the slider', async () => {
    serve();
    render(HouseBasics);
    const slider = await screen.findByTestId('house-supply-slider');
    expect(screen.getByTestId('house-supply-value').textContent).toContain('30');
    expect(screen.getByTestId('house-balance').textContent).toContain('balance at about 29');
    await fireEvent.input(slider, { target: { value: '0' } });
    expect(screen.getByTestId('house-verdict').getAttribute('data-verdict')).toBe('shortfall');
    expect(screen.getByTestId('house-verdict').textContent).toContain('Shortfall');
    await fireEvent.input(slider, { target: { value: '4' } });
    expect(screen.getByTestId('house-verdict').getAttribute('data-verdict')).toBe('surplus');
    expect(screen.getByTestId('house-steady-note').textContent).toContain('steady-state');
  });

  it('marks the provisional state and keeps the band', async () => {
    serve('provisional');
    render(HouseBasics);
    await screen.findByTestId('house-loss-provisional');
    expect(screen.getByTestId('house-loss-reasons').textContent).toContain('Fewer than 30 days');
    expect(screen.getByTestId('house-heat-provisional')).toBeTruthy();
  });

  it('shows no number while collecting, with the days and reasons', async () => {
    serve('collecting');
    render(HouseBasics);
    const card = await screen.findByTestId('house-collecting');
    expect(card.textContent).toContain('6 of 10');
    expect(screen.getByTestId('house-collecting-reasons').textContent).toContain('qualifying');
    expect(screen.queryByTestId('house-loss-now')).toBeNull();
    expect(screen.queryByTestId('house-loss-fit')).toBeNull();
    expect(screen.getByTestId('house-emitter-collecting')).toBeTruthy();
  });

  it('says the feature is off and links to the setting', async () => {
    serve('off');
    render(HouseBasics);
    const link = await screen.findByTestId('house-disabled-link');
    expect(link.getAttribute('href')).toBe('#/settings/house');
    expect(screen.queryByTestId('house-loss-now')).toBeNull();
  });

  it('shows an error that can be retried', async () => {
    const fetchMock = serve(undefined, 500);
    render(HouseBasics);
    await screen.findByTestId('house-basics-error');
    await fireEvent.click(screen.getByTestId('house-basics-retry'));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
  });

  it('draws the fit with its three kinds of marks when opened', async () => {
    serve();
    render(HouseBasics);
    const details = await screen.findByTestId('house-loss-fit');
    await fireEvent.click(details.querySelector('summary') as HTMLElement);
    const points = await screen.findAllByTestId('scatter-point');
    const kinds = new Set(points.map((p) => p.getAttribute('data-mark')));
    expect([...kinds].sort()).toEqual(['near_balance', 'outlier', 'used']);
    expect(screen.getByTestId('scatter-line')).toBeTruthy();
    expect(screen.getByTestId('house-fit-limits').textContent).toContain('sun is not modelled');
  });
});
