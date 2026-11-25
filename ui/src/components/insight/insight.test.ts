// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/svelte';
import { afterEach, beforeAll, describe, expect, it, vi } from 'vitest';
import { makeInsightDaily } from '$mock/insight';
import InsightCharts from './InsightCharts.svelte';
import WeekCard from './WeekCard.svelte';

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

function serve(status = 200) {
  const fetchMock = vi.fn(async (input: unknown) => {
    const days = Number(new URL(String(input), 'http://x/').searchParams.get('days') ?? 7);
    return status === 200
      ? new Response(JSON.stringify(makeInsightDaily(days, NOW)))
      : new Response('{}', { status });
  });
  vi.stubGlobal('fetch', fetchMock);
  return fetchMock;
}

describe('InsightCharts', () => {
  it('shows 7 days, switches to 30, marks today and the gaps', async () => {
    serve();
    render(InsightCharts);
    const blocks = await screen.findByTestId('insight-blocks');
    expect(blocks.getAttribute('data-days')).toBe('7');
    expect(screen.getByTestId('insight-electric').querySelectorAll('[data-bar]')).toHaveLength(7);
    await fireEvent.click(screen.getByTestId('insight-span-30'));
    expect(screen.getByTestId('insight-blocks').getAttribute('data-days')).toBe('30');
    const electric = screen.getByTestId('insight-electric');
    expect(electric.querySelectorAll('[data-bar]').length).toBe(29);
    expect(electric.querySelectorAll('line.missing')).toHaveLength(1);
    expect(electric.querySelector('svg')?.getAttribute('aria-label')).toContain('Electricity');
    expect(screen.getByTestId('insight-note').textContent).toContain('coverage: 1');
  });

  it('renders nothing on a 404', async () => {
    const fetchMock = serve(404);
    const { container } = render(InsightCharts);
    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    await new Promise((r) => setTimeout(r, 20));
    expect(screen.queryByTestId('insight-card')).toBeNull();
    expect(container.textContent?.trim()).toBe('');
  });

  it('says so when the load fails', async () => {
    serve(500);
    render(InsightCharts);
    expect(await screen.findByTestId('insight-failed')).toBeTruthy();
  });
});

describe('WeekCard', () => {
  it('shows the week figures and links to Pump and House', async () => {
    serve();
    render(WeekCard);
    const card = await screen.findByTestId('insight-week');
    expect(card.querySelector('a[href="#/pump"]')).not.toBeNull();
    expect(screen.getByTestId('week-house-link').getAttribute('href')).toBe('#/house');
    expect(screen.getByTestId('week-energy').textContent).toMatch(/\d/);
    expect(card.querySelectorAll('[data-bar]').length).toBe(7);
  });

  it('is hidden on a 404', async () => {
    const fetchMock = serve(404);
    render(WeekCard);
    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    await new Promise((r) => setTimeout(r, 20));
    expect(screen.queryByTestId('insight-week')).toBeNull();
  });
});
