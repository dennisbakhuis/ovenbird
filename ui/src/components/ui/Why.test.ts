// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from '@testing-library/svelte';
import { afterEach, describe, expect, it } from 'vitest';
import WhyHarness from './WhyHarness.test.svelte';

afterEach(cleanup);

describe('Why', () => {
  it('opens a labelled panel, closes on Escape and returns focus', async () => {
    render(WhyHarness, { title: 'Wait time' });
    const button = screen.getByTestId('why-button');
    expect(button.getAttribute('aria-expanded')).toBe('false');
    await fireEvent.click(button);
    expect(button.getAttribute('aria-expanded')).toBe('true');
    const panel = screen.getByTestId('why');
    expect(panel.getAttribute('role')).toBe('dialog');
    expect(panel.textContent).toContain('Explanation text');
    expect(panel.parentElement?.parentElement).toBe(document.body);
    await fireEvent.keyDown(panel, { key: 'Escape' });
    expect(screen.queryByTestId('why')).toBeNull();
    expect(document.activeElement).toBe(button);
  });

  it('moves focus into the panel without taking it from a control inside', async () => {
    render(WhyHarness, { title: 'Wait time' });
    await fireEvent.click(screen.getByTestId('why-button'));
    const close = screen.getByLabelText('Close');
    close.focus();
    await new Promise((resolve) => requestAnimationFrame(() => setTimeout(resolve, 0)));
    expect(document.activeElement).toBe(close);
  });

  it('closes on a click outside', async () => {
    render(WhyHarness, { title: 'Wait time' });
    await fireEvent.click(screen.getByTestId('why-button'));
    expect(screen.getByTestId('why')).toBeTruthy();
    await fireEvent.pointerDown(document.body);
    expect(screen.queryByTestId('why')).toBeNull();
  });

  it('locks page scroll while shown as a sheet', async () => {
    render(WhyHarness, { title: 'Wait time', sheet: 'always' });
    await fireEvent.click(screen.getByTestId('why-button'));
    expect(screen.getByTestId('why').getAttribute('aria-modal')).toBe('true');
    expect(document.documentElement.style.overflow).toBe('hidden');
    await fireEvent.click(screen.getByLabelText('Close'));
    expect(document.documentElement.style.overflow).toBe('');
  });
});
