// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from '@testing-library/svelte';
import { afterEach, describe, expect, it, vi } from 'vitest';
import DateInput from './DateInput.svelte';
import TimeInput from './TimeInput.svelte';

afterEach(cleanup);

describe('TimeInput', () => {
  it('is a time field that shows the HH:MM value', () => {
    render(TimeInput, { value: '07:30', onchange: vi.fn(), 'data-testid': 't' });
    const input = screen.getByTestId('t') as HTMLInputElement;
    expect(input.type).toBe('time');
    expect(input.value).toBe('07:30');
  });

  it('reports a complete time and ignores an empty one', async () => {
    const onchange = vi.fn();
    render(TimeInput, { value: '07:30', onchange, 'data-testid': 't' });
    const input = screen.getByTestId('t') as HTMLInputElement;
    await fireEvent.input(input, { target: { value: '' } });
    expect(onchange).not.toHaveBeenCalled();
    await fireEvent.input(input, { target: { value: '21:05' } });
    expect(onchange).toHaveBeenCalledWith('21:05');
  });
});

describe('DateInput', () => {
  it('reports a complete date only', async () => {
    const onchange = vi.fn();
    render(DateInput, { value: '2026-12-01', onchange, 'data-testid': 'd' });
    const input = screen.getByTestId('d') as HTMLInputElement;
    expect(input.type).toBe('date');
    await fireEvent.input(input, { target: { value: '2026-12-24' } });
    expect(onchange).toHaveBeenLastCalledWith('2026-12-24');
  });
});
