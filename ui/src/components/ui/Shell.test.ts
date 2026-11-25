// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from '@testing-library/svelte';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { clearTransient, currentNotices, notify, SUCCESS_TIMEOUT_MS } from './Banner.svelte';
import Details from './DetailsHarness.test.svelte';

afterEach(cleanup);

describe('notices', () => {
  it('dismisses success notices after 8 s and keeps warnings', () => {
    vi.useFakeTimers();
    notify('Version 13 saved.');
    const warning = notify('Check the sensor', { tone: 'warn' });
    expect(currentNotices().map((n) => n.text)).toEqual(['Version 13 saved.', 'Check the sensor']);
    vi.advanceTimersByTime(SUCCESS_TIMEOUT_MS + 1);
    expect(currentNotices().map((n) => n.id)).toEqual([warning]);
    notify('Loaded');
    clearTransient();
    expect(currentNotices().map((n) => n.id)).toEqual([warning]);
    vi.useRealTimers();
  });
});

describe('Details', () => {
  it('stays collapsed by default and remembers the open state per id', async () => {
    const store = new Map<string, string>();
    vi.stubGlobal('localStorage', {
      getItem: (key: string) => store.get(key) ?? null,
      setItem: (key: string, value: string) => store.set(key, value),
    });
    render(Details, { id: 'inputs' });
    expect(screen.queryByText('Hidden body')).toBeNull();
    const details = screen.getByTestId('details') as HTMLDetailsElement;
    details.open = true;
    await fireEvent(details, new Event('toggle'));
    expect(screen.getByText('Hidden body')).toBeTruthy();
    expect(store.get('ovenbird.details.inputs')).toBe('1');
    cleanup();
    render(Details, { id: 'inputs' });
    expect(screen.getByText('Hidden body')).toBeTruthy();
    vi.unstubAllGlobals();
  });
});
