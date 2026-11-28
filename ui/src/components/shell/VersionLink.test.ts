// @vitest-environment jsdom
import { cleanup, render, screen } from '@testing-library/svelte';
import { afterEach, describe, expect, it } from 'vitest';
import VersionLink from './VersionLink.svelte';

afterEach(cleanup);

describe('VersionLink', () => {
  it('shows nothing while the version is unknown but keeps its slot', () => {
    render(VersionLink, { version: null, testid: 'app-version' });
    expect(screen.queryByTestId('app-version')).toBeNull();
    const slot = screen.getByTestId('app-version-slot');
    expect(slot.textContent?.trim()).toBe('');
    expect(slot.classList.contains('slot')).toBe(true);
  });

  it('links the version to the page with the About card', () => {
    render(VersionLink, { version: '0.6.0', testid: 'app-version' });
    const link = screen.getByTestId('app-version');
    expect(link.textContent).toBe('v0.6.0');
    expect(link.getAttribute('href')).toBe('#/system');
    expect(link.getAttribute('aria-label')).toBe('ovenbird v0.6.0');
  });

  it('names the app before the number when asked', () => {
    render(VersionLink, { version: '0.6.0', testid: 'more-version', prefix: true });
    expect(screen.getByTestId('more-version').textContent).toBe('ovenbirdv0.6.0');
    expect(screen.getByTestId('more-version-slot').classList.contains('prefix')).toBe(true);
  });
});
