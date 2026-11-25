// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from '@testing-library/svelte';
import { afterEach, describe, expect, it, vi } from 'vitest';
import ButtonHarness from './ButtonHarness.test.svelte';

afterEach(cleanup);

describe('Button', () => {
  it('is a type=button button that passes attributes and clicks through', async () => {
    const onclick = vi.fn();
    render(ButtonHarness, { onclick, extra: { 'data-testid': 'go', 'aria-label': 'Go now' } });
    const button = screen.getByTestId('go');
    expect(button.tagName).toBe('BUTTON');
    expect(button.getAttribute('type')).toBe('button');
    expect(button.getAttribute('aria-label')).toBe('Go now');
    await fireEvent.click(button);
    expect(onclick).toHaveBeenCalledOnce();
  });

  it('submits when asked to', () => {
    render(ButtonHarness, { type: 'submit' });
    expect(screen.getByRole('button').getAttribute('type')).toBe('submit');
  });

  it('busy disables the button and says so', async () => {
    render(ButtonHarness, { busy: true });
    const button = screen.getByRole('button') as HTMLButtonElement;
    expect(button.disabled).toBe(true);
    expect(button.getAttribute('aria-busy')).toBe('true');
    expect(button.querySelector('.spin')).not.toBeNull();
  });

  it('renders an anchor with the same look when given an href', () => {
    render(ButtonHarness, { href: '#/pump' });
    const link = screen.getByRole('link');
    expect(link.getAttribute('href')).toBe('#/pump');
    expect(link.classList.contains('btn')).toBe(true);
  });

  it('an anchor that is disabled loses its href and says aria-disabled', () => {
    render(ButtonHarness, { href: '#/pump', disabled: true });
    const link = screen.getByText('Label');
    expect(link.getAttribute('href')).toBeNull();
    expect(link.getAttribute('aria-disabled')).toBe('true');
  });
});
