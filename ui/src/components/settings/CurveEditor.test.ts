// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from '@testing-library/svelte';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { Curve } from '$lib/core/curve';
import CurveEditor from './CurveEditor.svelte';

const base: Curve = [
  [-10, 39],
  [0, 34],
  [15, 25],
];
const envelope = { curve: base, below_k: 6, above_k: 5 };

function mount(points: Curve = base) {
  const onchange = vi.fn();
  render(CurveEditor, {
    points,
    active: base,
    envelope,
    limits: { min: 20, max: 40 },
    onchange,
  });
  return onchange;
}

globalThis.ResizeObserver = class {
  observe() {}
  unobserve() {}
  disconnect() {}
};

afterEach(cleanup);

describe('CurveEditor', () => {
  it('edits a point with the arrow keys', async () => {
    const onchange = mount();
    const handle = screen.getByTestId('curve-handle-1');
    await fireEvent.keyDown(handle, { key: 'ArrowUp' });
    expect(onchange).toHaveBeenLastCalledWith([base[0], [0, 35], base[2]]);
    await fireEvent.keyDown(handle, { key: 'ArrowUp', shiftKey: true });
    expect(onchange).toHaveBeenLastCalledWith([base[0], [0, 34.5], base[2]]);
    await fireEvent.keyDown(handle, { key: 'ArrowRight' });
    expect(onchange).toHaveBeenLastCalledWith([base[0], [1, 34], base[2]]);
  });

  it('keeps the curve monotone on keyboard edits', async () => {
    const flat: Curve = [
      [-10, 39],
      [0, 39],
      [15, 25],
    ];
    const onchange = mount(flat);
    await fireEvent.keyDown(screen.getByTestId('curve-handle-1'), { key: 'ArrowUp' });
    expect(onchange).not.toHaveBeenCalled();
  });

  it('edits with the steppers', async () => {
    const onchange = mount();
    await fireEvent.click(screen.getByTestId('point-water-1-dec'));
    expect(onchange).toHaveBeenLastCalledWith([base[0], [0, 33], base[2]]);
    await fireEvent.click(screen.getByTestId('point-water-1-dec'), { shiftKey: true });
    expect(onchange).toHaveBeenLastCalledWith([base[0], [0, 33.5], base[2]]);
    await fireEvent.click(screen.getByTestId('point-outside-2-inc'));
    expect(onchange).toHaveBeenLastCalledWith([base[0], base[1], [16, 25]]);
  });

  it('adds a point and respects the limits', async () => {
    const onchange = mount();
    await fireEvent.click(screen.getByTestId('add-point'));
    const added = onchange.mock.calls[0]?.[0] as Curve;
    expect(added).toHaveLength(4);
    cleanup();
    const six = Array.from({ length: 6 }, (_, i) => [i * 5 - 10, 40 - i * 2] as [number, number]);
    mount(six);
    expect((screen.getByTestId('add-point') as HTMLButtonElement).disabled).toBe(true);
  });

  it('cannot remove below two points', async () => {
    const two: Curve = [base[0]!, base[2]!];
    const onchange = mount(two);
    const remove = screen.getByTestId('remove-point-0') as HTMLButtonElement;
    expect(remove.disabled).toBe(true);
    await fireEvent.click(remove);
    expect(onchange).not.toHaveBeenCalled();
  });

  it("shows the draft value at today's outside temperature and the shaded difference", () => {
    const onchange = vi.fn();
    render(CurveEditor, {
      points: [base[0]!, [0, 36], base[2]!],
      active: base,
      envelope,
      limits: { min: 20, max: 40 },
      operating: { outside: 0, curve: 34, issued: 34 },
      dots: [
        [0, 33],
        [0, 34],
        [1, 33],
      ],
      onchange,
    });
    expect(screen.getByTestId('curve-draft-now').textContent).toContain('36');
    expect(screen.getByTestId('curve-diff')).toBeTruthy();
    expect(screen.getByTestId('curve-dots').querySelectorAll('rect')).toHaveLength(2);
    expect(screen.getByTestId('curve-svg').getAttribute('aria-describedby')).toBeTruthy();
  });

  it('removes a point from three', async () => {
    const onchange = mount();
    await fireEvent.click(screen.getByTestId('remove-point-1'));
    expect(onchange).toHaveBeenLastCalledWith([base[0], base[2]]);
  });
});
