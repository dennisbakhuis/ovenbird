// @vitest-environment jsdom
import { cleanup, render, screen } from '@testing-library/svelte';
import { afterEach, describe, expect, it } from 'vitest';
import FormRowHarness from './FormRowHarness.test.svelte';

afterEach(cleanup);

describe('FormRow', () => {
  it('ties the label to the control and describes it with the hint', () => {
    render(FormRowHarness, { hint: 'Up to 200 characters' });
    const input = screen.getByLabelText('Comment');
    const hint = screen.getByText('Up to 200 characters');
    expect(input.getAttribute('aria-describedby')).toBe(hint.id);
    expect(input.getAttribute('aria-invalid')).toBeNull();
  });

  it('marks the control invalid and announces the error', () => {
    render(FormRowHarness, { hint: 'Hint', error: 'Too long' });
    const input = screen.getByLabelText('Comment');
    const error = screen.getByRole('alert');
    expect(error.textContent).toBe('Too long');
    expect(input.getAttribute('aria-invalid')).toBe('true');
    expect(input.getAttribute('aria-describedby')?.split(' ')).toContain(error.id);
  });
});
