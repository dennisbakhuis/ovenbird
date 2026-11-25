// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from '@testing-library/svelte';
import { afterEach, describe, expect, it, vi } from 'vitest';
import Segmented from './Segmented.svelte';

afterEach(cleanup);

const options = [
  { value: 6, label: '6 h', testid: 'r-6' },
  { value: 24, label: '24 h', testid: 'r-24' },
];

describe('Segmented', () => {
  it('marks the current option pressed and reports a pick', async () => {
    const onchange = vi.fn();
    render(Segmented<number>, { options, value: 24, onchange, label: 'Range' });
    expect(screen.getByRole('group', { name: 'Range' })).toBeTruthy();
    expect(screen.getByTestId('r-24').getAttribute('aria-pressed')).toBe('true');
    expect(screen.getByTestId('r-6').getAttribute('aria-pressed')).toBe('false');
    await fireEvent.click(screen.getByTestId('r-6'));
    expect(onchange).toHaveBeenCalledWith(6);
  });

  it('can be a radio group instead', async () => {
    const onchange = vi.fn();
    render(Segmented<number>, {
      options,
      value: 24,
      onchange,
      label: 'Range',
      semantics: 'radio',
    });
    expect(screen.getByRole('radiogroup', { name: 'Range' })).toBeTruthy();
    expect((screen.getByTestId('r-24') as HTMLInputElement).checked).toBe(true);
    await fireEvent.click(screen.getByTestId('r-6'));
    expect(onchange).toHaveBeenCalledWith(6);
  });
});
