// @vitest-environment jsdom
import { cleanup, render, screen } from '@testing-library/svelte';
import { afterEach, beforeAll, describe, expect, it } from 'vitest';
import CommandProgress from './CommandProgress.svelte';
import CopScatter from './CopScatter.svelte';
import LoopDiagram from './LoopDiagram.svelte';

beforeAll(() => {
  globalThis.ResizeObserver ??= class {
    observe(): void {}
    unobserve(): void {}
    disconnect(): void {}
  };
});

afterEach(cleanup);

const loop = {
  kind: 'running' as const,
  outletC: 32.5,
  inletC: 28,
  flowLpm: 17.4,
  duty: 120,
  maxDuty: 159,
  hz: 38,
  electricW: 1900,
  heatW: 7600,
  setDeltaK: 5,
};

describe('LoopDiagram', () => {
  it('describes the loop with its live values', () => {
    render(LoopDiagram, { props: loop });
    const label = screen.getByTestId('loop-diagram').getAttribute('aria-label') ?? '';
    expect(label).toContain('Heating');
    expect(label).toContain('32.5');
    expect(label).toContain('4.5');
    expect(label).toContain('120 of 159');
    expect(screen.queryByTestId('loop-duty-note')).toBeNull();
  });

  it('says honestly that the pump drives its own duty during a defrost', () => {
    render(LoopDiagram, { props: { ...loop, kind: 'defrost', duty: 220 } });
    expect(screen.getByTestId('loop-duty-note').textContent).toMatch(/own duty.*159/);
    expect(screen.getByTestId('loop-diagram').getAttribute('aria-label')).toContain('220 of 159');
  });

  it('renders with every value missing', () => {
    render(LoopDiagram, {
      props: {
        kind: 'unknown',
        outletC: null,
        inletC: null,
        flowLpm: null,
        duty: null,
        maxDuty: null,
        hz: null,
        electricW: null,
        heatW: null,
        setDeltaK: null,
      },
    });
    expect(screen.getByTestId('loop-diagram').getAttribute('aria-label')).toContain('–');
  });
});

describe('CopScatter', () => {
  it('summarises the dots and the trend', () => {
    const dots = [0, 2, 4, 6, 8].map((outside, i) => ({
      t: Date.UTC(2026, 10, 14, i),
      outside,
      cop: 3 + outside * 0.1,
    }));
    render(CopScatter, {
      props: { dots, fit: { slope: 0.1, intercept: 3 }, loading: false, failed: false },
    });
    const plot = screen.getByTestId('cop-plot');
    expect(plot.getAttribute('data-dots')).toBe('5');
    expect(plot.getAttribute('aria-label')).toMatch(/5 hours.*Trend 0\.1/);
  });

  it('says when there is not enough data', () => {
    render(CopScatter, { props: { dots: [], fit: null, loading: false, failed: false } });
    expect(screen.getByTestId('cop-none')).toBeTruthy();
  });
});

describe('CommandProgress', () => {
  it('marks the current step', () => {
    render(CommandProgress, { props: { status: 'sent' } });
    expect(screen.getByText('sent').closest('li')?.getAttribute('aria-current')).toBe('step');
  });

  it('shows a neutral step for a null or unknown status', () => {
    const view = render(CommandProgress, { props: { status: null } });
    expect(screen.getByTestId('progress-unknown').textContent).toMatch(/status unknown/);
    view.rerender({ status: 'something_new' });
    expect(screen.getByTestId('command-progress').getAttribute('data-status')).toBe(
      'something_new',
    );
  });

  it.each(['failed', 'refused', 'dropped'])('shows %s as a failed end', (status) => {
    render(CommandProgress, { props: { status } });
    expect(screen.getByTestId('progress-failed').textContent).toContain(status);
  });
});
