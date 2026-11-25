// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from '@testing-library/svelte';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { Point } from '$lib/core/chart';
import BandMeter from './BandMeter.svelte';
import Bars from './Bars.svelte';
import BulletBar from './BulletBar.svelte';
import ChartGallery from './ChartGallery.svelte';
import PowerFlow from './PowerFlow.svelte';
import Sparkline from './Sparkline.svelte';
import StateStrip from './StateStrip.svelte';

afterEach(cleanup);

globalThis.ResizeObserver ??= class {
  observe(): void {}
  unobserve(): void {}
  disconnect(): void {}
};

const H = 3_600_000;
const FROM = Date.parse('2026-11-15T08:00:00');
const label = (el: Element | null) => (el?.getAttribute('aria-label') ?? '').replaceAll(' ', ' ');

describe('Sparkline', () => {
  const points: Point[] = [0, 1, 2, 3].map((h) => [FROM + h * H, 28 + h]);

  it('summarises the trend and is not focusable by default', () => {
    const { container } = render(Sparkline, { points, label: 'Outlet', unit: '°C', minMax: true });
    expect(label(container.querySelector('[role="img"]'))).toBe(
      'Outlet 31 °C, range 28–31 °C, rising 1 K per hour',
    );
    expect(screen.queryByRole('slider')).toBeNull();
    expect(container.querySelector('.caption')?.textContent?.replaceAll(' ', ' ')).toMatch(
      /28–31 °C/,
    );
  });

  it('reads values with the keyboard when interactive', async () => {
    render(Sparkline, { points, label: 'Outlet', unit: '°C', interactive: true });
    const slider = screen.getByRole('slider');
    await fireEvent.keyDown(slider, { key: 'Home' });
    expect(slider.getAttribute('aria-valuetext')?.replaceAll(' ', ' ')).toBe('08:00: Outlet 28 °C');
  });
});

describe('StateStrip', () => {
  const lanes = [
    {
      id: 'compressor',
      label: 'Compressor',
      color: 'orange',
      segments: [
        { from: FROM, to: FROM + 2 * H, state: 'on', level: 0.5 },
        { from: FROM + 3 * H, to: FROM + 4 * H, state: 'on', level: 1 },
      ],
      states: { on: { label: 'on' } },
    },
    { id: 'defrost', label: 'Defrost', color: 'violet', segments: [] },
  ];

  it('lists segments, summarises lanes and shades by level', async () => {
    const { container } = render(StateStrip, {
      from: FROM,
      to: FROM + 6 * H,
      title: 'Pump',
      lanes,
    });
    expect(label(container.querySelector('[role="img"]'))).toBe(
      'Pump, 08:00–14:00. Compressor: on 2 times, 3 h in total. Defrost: none.',
    );
    const items = [...screen.getByTestId('strip-list').querySelectorAll('li')].map((li) =>
      li.textContent?.trim(),
    );
    expect(items).toEqual(['08:00–10:00, on, 2 h', '11:00–12:00, on, 1 h', 'none']);
    const opacities = [...container.querySelectorAll('rect[data-state="on"]')].map((r) =>
      r.getAttribute('fill-opacity'),
    );
    expect(opacities).toEqual(['0.65', '1']);
    expect(screen.getByTestId('strip-list').classList.contains('visually-hidden')).toBe(true);
    await fireEvent.click(screen.getByTestId('strip-list-toggle'));
    expect(screen.getByTestId('strip-list').classList.contains('visually-hidden')).toBe(false);
  });

  it('lists point events as moments with what they were', () => {
    const at = FROM + 4 * H + 19 * 60_000;
    const events = [{ at, text: 'Water setpoint 32 · failed' }];
    const { container } = render(StateStrip, {
      from: FROM,
      to: FROM + 6 * H,
      title: 'Activity',
      lanes: [
        {
          id: 'commands',
          label: 'Commands',
          color: 'orange',
          segments: [{ from: at, to: at + 4 * 60_000, state: 'commands' }],
          events,
        },
      ],
    });
    const items = [...screen.getByTestId('strip-list').querySelectorAll('li')].map((li) =>
      li.textContent?.trim(),
    );
    expect(items).toEqual(['12:19 · Water setpoint 32 · failed']);
    expect(label(container.querySelector('[role="img"]'))).toBe(
      'Activity, 08:00–14:00. Commands: once.',
    );
  });

  it('steps between segment edges with the keyboard', async () => {
    render(StateStrip, { from: FROM, to: FROM + 6 * H, title: 'Pump', lanes });
    const slider = screen.getByRole('slider');
    await fireEvent.keyDown(slider, { key: 'Home' });
    await fireEvent.keyDown(slider, { key: 'ArrowRight' });
    await fireEvent.keyDown(slider, { key: 'ArrowRight' });
    expect(slider.getAttribute('aria-valuetext')).toBe('11:00: Compressor on, Defrost off');
  });
});

describe('BandMeter', () => {
  it('shows position, target, flip and trend in words and shape', () => {
    const { container } = render(BandMeter, {
      props: {
        label: 'Room',
        value: 20.4,
        target: 21.0,
        low: 20.5,
        high: 21.5,
        trend: -0.2,
        flip: { at: 20.7 },
      },
    });
    expect(screen.getByTestId('band-meter').dataset['state']).toBe('below');
    expect(label(container.querySelector('svg[role="img"]'))).toBe(
      'Room 20.4 °C, 0.6 K below target 21 °C, below the comfort band 20.5–21.5 °C, falling 0.2 K per hour, changes at 20.7 °C',
    );
    expect(container.querySelector('path.marker')).toBeTruthy();
    expect(container.querySelector('.trend')?.getAttribute('data-direction')).toBe('falling');
  });

  it('uses a round marker inside the band and copes with no value', () => {
    const { container } = render(BandMeter, { label: 'Room', value: 21.0, low: 20.5, high: 21.5 });
    expect(container.querySelector('circle.marker')).toBeTruthy();
    cleanup();
    render(BandMeter, { label: 'Room', value: null, low: 20.5, high: 21.5 });
    expect(screen.getByTestId('band-meter').dataset['state']).toBeUndefined();
  });
});

describe('BulletBar', () => {
  it('reports ok, warning and breached with distinct icons', () => {
    render(BulletBar, { label: 'Outlet', value: 30.8, limit: 45, unit: '°C' });
    expect(screen.getByTestId('bullet-bar').dataset['status']).toBe('ok');
    cleanup();
    render(BulletBar, { label: 'Flow', value: 8, limit: 7, warn: 9, direction: 'below' });
    expect(screen.getByTestId('bullet-bar').dataset['status']).toBe('warning');
    cleanup();
    const { container } = render(BulletBar, { label: 'Outlet', value: 47, limit: 45, unit: '°C' });
    expect(screen.getByTestId('bullet-bar').dataset['status']).toBe('critical');
    expect(label(container.querySelector('svg[role="img"]'))).toBe(
      'Outlet 47 °C, above the alarm limit 45 °C by 2 K',
    );
  });
});

describe('Bars', () => {
  const items = [
    { label: 'Mon', value: 9.6 },
    { label: 'Tue', value: 10.4 },
    { label: 'Wed', value: null },
  ];

  it('draws one bar per known value and reads them with the keyboard', async () => {
    const onselect = vi.fn();
    const { container } = render(Bars, { title: 'Energy', items, unit: 'kWh', onselect });
    expect(container.querySelectorAll('rect[data-bar]')).toHaveLength(2);
    expect(label(container.querySelector('[role="img"]'))).toBe(
      'Energy: Mon 9.6 kWh, Tue 10.4 kWh, Wed –',
    );
    const slider = screen.getByRole('slider');
    await fireEvent.keyDown(slider, { key: 'Home' });
    await fireEvent.keyDown(slider, { key: 'ArrowRight' });
    expect(slider.getAttribute('aria-valuetext')?.replaceAll(' ', ' ')).toBe('Tue: 10.4 kWh');
    await fireEvent.keyDown(slider, { key: 'Enter' });
    expect(onselect).toHaveBeenCalledWith(1);
  });

  it('grows horizontal bars from zero in both directions', () => {
    const { container } = render(Bars, {
      title: 'Bias',
      items: [
        { label: '6 h', value: 0.5 },
        { label: '24 h', value: -0.5 },
      ],
      orientation: 'horizontal',
      min: -1,
      max: 1,
    });
    const fills = [...container.querySelectorAll<HTMLElement>('.fill')].map((f) => f.style.left);
    expect(fills).toEqual(['50%', '25%']);
    const slider = screen.getByRole('slider');
    expect(slider.getAttribute('aria-orientation')).toBe('vertical');
  });
});

describe('PowerFlow', () => {
  it('splits heat into electric and ambient with COP', () => {
    const { container } = render(PowerFlow, { electricW: 1900, heatW: 8400 });
    const flow = screen.getByTestId('power-flow');
    expect(flow.dataset['state']).toBe('running');
    expect(label(flow)).toBe(
      'Electric 1.9 kW in, heat 8.4 kW out, of which 6.5 kW from the outside air, COP 4.4',
    );
    expect(container.querySelectorAll('.seg')).toHaveLength(2);
  });

  it('names idle, unknown and no-heat states', () => {
    render(PowerFlow, { electricW: 18, heatW: 0 });
    expect(screen.getByTestId('power-flow').dataset['state']).toBe('idle');
    cleanup();
    render(PowerFlow, { electricW: null, heatW: null });
    expect(screen.getByTestId('power-flow').dataset['state']).toBe('unknown');
    cleanup();
    render(PowerFlow, { electricW: 1400, heatW: 0 });
    expect(screen.getByTestId('power-flow').dataset['state']).toBe('no-heat');
  });
});

describe('ChartGallery', () => {
  it('renders every component with an accessible summary', () => {
    const { container } = render(ChartGallery);
    for (const id of [
      'dev-timechart-panels',
      'dev-timechart-weather',
      'dev-timechart-legacy',
      'dev-statestrip',
      'dev-sparklines',
      'dev-bandmeter',
      'dev-bulletbar',
      'dev-bars',
      'dev-powerflow',
    ]) {
      expect(screen.getByTestId(id)).toBeTruthy();
    }
    const images = [...container.querySelectorAll('[role="img"]')];
    expect(images.length).toBeGreaterThan(20);
    expect(images.every((img) => (img.getAttribute('aria-label') ?? '').length > 5)).toBe(true);
    expect(screen.getAllByTestId('chart-night').length).toBeGreaterThan(0);
  });
});
