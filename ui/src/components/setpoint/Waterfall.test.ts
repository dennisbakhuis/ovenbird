// @vitest-environment jsdom
import { cleanup, render, screen, within } from '@testing-library/svelte';
import { afterEach, describe, expect, it } from 'vitest';
import { makeDecision } from '$mock/decisions';
import recorded from '$mock/fixtures/decisions-sim.json';
import type { Decision } from '$lib/core/types';
import Waterfall from './Waterfall.svelte';

afterEach(cleanup);

const atCycleMinute = (minute: number) => makeDecision((minute + 360 * 4000) * 60_000, Date.now());

describe('Waterfall', () => {
  it('renders the pipeline rows of a recorded decision', () => {
    const decision = (recorded.decisions as unknown as Decision[])[0] as Decision;
    const { container } = render(Waterfall, { decision });
    const rows = [...container.querySelectorAll('[data-row]')].map((row) =>
      row.getAttribute('data-row'),
    );
    expect(rows).toEqual([
      'curve',
      'room_feedback',
      'sum',
      'safety',
      'stage',
      'issued',
      'reported',
    ]);
    const issued = container.querySelector('[data-row="issued"]') as HTMLElement;
    expect(within(issued).getByText(`${decision.setpoint} °C`)).toBeTruthy();
    expect(screen.getByTestId('waterfall-collapsed').textContent).toMatch(
      /Plan, Start ramp, Cycling protection/,
    );
  });

  it('shows raw against applied for a limited term and for the safety clamp', () => {
    const decision = atCycleMinute(210);
    const { container } = render(Waterfall, { decision });
    const feedback = container.querySelector('[data-row="room_feedback"]') as HTMLElement;
    expect(feedback.querySelector('[data-detail="room_feedback"]')?.textContent).toBe(
      'raw +7.2 K, applied +6 K',
    );
    const clamp = container.querySelector('[data-row="safety"]') as HTMLElement;
    expect(clamp.querySelector('[data-detail="safety"]')?.textContent).toMatch(
      /raw .* °C, applied .* °C/,
    );
    expect(clamp.querySelector('[data-detail="safety"]')?.textContent).toMatch(/allowed/);
  });

  it('labels the dwell stage with its binding', () => {
    const decision = atCycleMinute(70);
    const { container } = render(Waterfall, { decision });
    expect(container.querySelector('[data-detail="stage"]')?.textContent).toBe('Wait time');
  });

  it('shows the reason instead of bars for a hold', () => {
    const decision = atCycleMinute(301);
    const { container } = render(Waterfall, { decision });
    expect(screen.getByTestId('waterfall-reason').textContent).toMatch(/holding its last values/);
    expect(container.querySelectorAll('[data-row]').length).toBe(0);
  });

  it('shows the refusal reason for a refuse decision', () => {
    render(Waterfall, { decision: atCycleMinute(331) });
    expect(screen.getByTestId('waterfall-reason').textContent).toMatch(/refused to decide/);
  });

  it('drops zero rows and the sum in compact mode', () => {
    const decision = (recorded.decisions as unknown as Decision[])[0] as Decision;
    const { container } = render(Waterfall, { decision, compact: true });
    const rows = [...container.querySelectorAll('[data-row]')].map((row) =>
      row.getAttribute('data-row'),
    );
    expect(rows).toEqual(['curve', 'room_feedback', 'stage', 'issued']);
  });
});
