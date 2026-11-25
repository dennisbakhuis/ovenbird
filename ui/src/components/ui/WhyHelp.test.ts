// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from '@testing-library/svelte';
import { afterEach, describe, expect, it } from 'vitest';
import { help } from '$lib/help/store.svelte';
import WhyHelpHarness from './WhyHelpHarness.test.svelte';

afterEach(() => {
  cleanup();
  help.close();
});

describe('Why → help', () => {
  it('links to the help section of the closest data-help element', async () => {
    render(WhyHelpHarness, { helpId: 'pump.flow' });
    const button = screen.getByTestId('why-button');
    await fireEvent.click(button);
    await fireEvent.click(screen.getByTestId('why-more-help'));
    expect(screen.queryByTestId('why')).toBeNull();
    expect(help.open).toBe(true);
    expect(help.request.target).toBe('pump.flow');
    help.close();
    expect(document.activeElement).toBe(button);
  });

  it('has no help link outside a data-help element', async () => {
    render(WhyHelpHarness, {});
    await fireEvent.click(screen.getByTestId('why-button'));
    expect(screen.queryByTestId('why-more-help')).toBeNull();
  });
});
