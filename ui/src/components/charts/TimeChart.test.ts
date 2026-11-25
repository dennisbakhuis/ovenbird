// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from '@testing-library/svelte';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { Point } from '$lib/core/chart';
import TimeChart from './TimeChart.svelte';
import type { PanelSpec } from './types';

afterEach(cleanup);

globalThis.ResizeObserver ??= class {
  observe(): void {}
  unobserve(): void {}
  disconnect(): void {}
};

const H = 3_600_000;
const FROM = Date.parse('2026-11-15T00:00:00');
const TO = FROM + 6 * H;
const series = (f: (h: number) => number): Point[] =>
  Array.from({ length: 7 }, (_, h) => [FROM + h * H, f(h)]);

const panels: PanelSpec[] = [
  {
    id: 'room',
    label: 'Room',
    unit: '°C',
    lines: [{ id: 'room', label: 'Room', color: 'green', points: series((h) => 21 + h * 0.1) }],
    bands: [{ id: 'comfort', label: 'Comfort', color: 'green', upper: 21.5, lower: 20.5 }],
  },
  {
    id: 'water',
    label: 'Water',
    unit: '°C',
    lines: [
      { id: 'outlet', label: 'Outlet', color: 'orange', points: series((h) => 30 + h) },
      { id: 'setpoint', label: 'Setpoint', color: 'black', points: series(() => 32), step: true },
    ],
  },
  {
    id: 'pump',
    lanes: [
      {
        id: 'defrost',
        label: 'Defrost',
        color: 'violet',
        segments: [{ from: FROM + H, to: FROM + 1.1 * H, state: 'defrost' }],
      },
    ],
  },
];

describe('TimeChart', () => {
  it('renders v1 props unchanged: one panel, legend values, summary', () => {
    render(TimeChart, {
      from: FROM,
      to: TO,
      title: 'Last 6 hours',
      lines: [
        { id: 'outside', label: 'Outside', color: 'blue', points: series((h) => h) },
        {
          id: 'room',
          label: 'Room',
          color: 'green',
          points: series(() => 20.7),
          axis: 'right',
        },
      ],
    });
    const svg = screen.getByTestId('time-chart');
    expect(svg.getAttribute('role')).toBe('img');
    expect(svg.getAttribute('aria-label')).toMatch(/^Last 6 hours, 00:00–06:00\. Outside 6/);
    expect(svg.querySelectorAll('path[data-line]')).toHaveLength(2);
    expect(screen.getByRole('button', { name: /Outside/ }).textContent).toMatch(/6\s°C/);
  });

  it('stacks one panel per unit with lanes on a shared axis', () => {
    const { container } = render(TimeChart, { from: FROM, to: TO, title: 'Today', panels });
    expect([...container.querySelectorAll('.panel-label')].map((t) => t.textContent)).toEqual([
      'Room · °C',
      'Water · °C',
    ]);
    expect(
      container.querySelector('[data-lane="defrost"] rect[data-state="defrost"]'),
    ).toBeTruthy();
    const label = screen.getByTestId('time-chart').getAttribute('aria-label') ?? '';
    expect(label).toContain('Defrost: once, 6 min in total');
  });

  it('labels a rule at the left end, drawn over the lines', () => {
    const ruled: PanelSpec[] = [
      {
        id: 'room',
        label: 'Room',
        unit: '°C',
        lines: [{ id: 'room', label: 'Room', color: 'green', points: series(() => 21.0) }],
        rules: [{ value: 21.0, label: 'target 21.0' }],
      },
    ];
    const { container } = render(TimeChart, { from: FROM, to: TO, title: 'Room', panels: ruled });
    const label = screen.getByTestId('rule-label');
    expect(label.getAttribute('x')).toBe('4');
    expect(label.getAttribute('text-anchor')).toBeNull();
    const path = container.querySelector('path[data-line="room"]');
    expect(path?.compareDocumentPosition(label)).toBe(Node.DOCUMENT_POSITION_FOLLOWING);
  });

  it('writes negative values with a true minus sign', async () => {
    const delta: PanelSpec[] = [
      {
        id: 'dt',
        label: 'ΔT',
        unit: 'K',
        lines: [{ id: 'dt', label: 'ΔT', color: 'red', points: series(() => -5.5) }],
      },
    ];
    render(TimeChart, { from: FROM, to: TO, title: 'Delta', panels: delta });
    expect(screen.getByTestId('time-chart').textContent).toContain('\u22125.5');
    expect(screen.getByTestId('time-chart').textContent).not.toMatch(/-5[.,]5/);
    await fireEvent.click(screen.getByTestId('chart-table-toggle'));
    expect(screen.getByTestId('chart-table').textContent).toContain('\u22125.5');
  });

  it('hides a series with its legend chip', async () => {
    const ontoggle = vi.fn();
    const { container } = render(TimeChart, {
      from: FROM,
      to: TO,
      title: 'Today',
      panels,
      ontoggle,
    });
    const chip = screen.getByRole('button', { name: /Outlet/ });
    expect(chip.getAttribute('aria-pressed')).toBe('true');
    await fireEvent.click(chip);
    expect(chip.getAttribute('aria-pressed')).toBe('false');
    expect(container.querySelector('path[data-line="outlet"]')).toBeNull();
    expect(ontoggle).toHaveBeenCalledWith('outlet', false);
    expect(screen.getByTestId('time-chart').getAttribute('aria-label')).not.toContain('Outlet');
  });

  it('moves a keyboard crosshair and reads every series', async () => {
    const onselect = vi.fn();
    render(TimeChart, { from: FROM, to: TO, title: 'Today', panels, onselect });
    const slider = screen.getByRole('slider', { name: 'Today: time cursor' });
    await fireEvent.keyDown(slider, { key: 'End' });
    await fireEvent.keyDown(slider, { key: 'ArrowLeft' });
    const text = slider.getAttribute('aria-valuetext') ?? '';
    expect(text).toMatch(/^05:00: Room 21\.5\s°C, Outlet 35\s°C, Setpoint 32\s°C, Defrost off$/);
    expect(screen.getByTestId('chart-when').textContent).toBe('05:00');
    await fireEvent.keyDown(slider, { key: 'Home' });
    await fireEvent.keyDown(slider, { key: 'ArrowRight' });
    await fireEvent.keyDown(slider, { key: 'Enter' });
    expect(onselect).toHaveBeenCalledWith(FROM + H);
    expect(slider.getAttribute('aria-valuetext')).toContain('Defrost Defrost');
    await fireEvent.keyDown(slider, { key: 'Escape' });
    expect(screen.getByTestId('chart-when').textContent).toBe('Latest');
  });

  it('shows the data as a table on request', async () => {
    render(TimeChart, { from: FROM, to: TO, title: 'Today', panels });
    const toggle = screen.getByTestId('chart-table-toggle');
    expect(screen.queryByTestId('chart-table')).toBeNull();
    await fireEvent.click(toggle);
    expect(toggle.getAttribute('aria-expanded')).toBe('true');
    const table = screen.getByTestId('chart-table');
    expect(table.querySelectorAll('thead th')).toHaveLength(4);
    expect(table.querySelectorAll('tbody tr').length).toBeGreaterThan(3);
    expect(table.textContent).toContain('Defrost');
  });

  it('draws icons on markers and drops labels that would overlap', () => {
    const { container } = render(TimeChart, {
      from: FROM,
      to: TO,
      title: 'Today',
      panels,
      markers: [
        { t: FROM + 2 * H, label: 'config v12', icon: 'M0 0h1' },
        { t: FROM + 2 * H + 60_000, label: 'hold', icon: 'M0 0h1' },
        { t: FROM + 2 * H + 120_000, label: 'third' },
      ],
    });
    const markers = container.querySelectorAll('[data-testid="chart-marker"]');
    expect(markers).toHaveLength(3);
    const labels = container.querySelectorAll('.marker-label');
    expect([...labels].map((label) => label.textContent)).toEqual(['config v12']);
    expect(container.querySelectorAll('.marker-icon')).toHaveLength(2);
  });

  it('right-aligns a marker label near the right edge', () => {
    const { container } = render(TimeChart, {
      from: FROM,
      to: TO,
      title: 'Today',
      panels,
      markers: [{ t: TO - 60_000, label: 'hold', icon: 'M0 0h1' }],
    });
    const label = container.querySelector('.marker-label');
    expect(label?.getAttribute('text-anchor')).toBe('end');
  });
});
