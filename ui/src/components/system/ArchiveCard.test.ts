// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/svelte';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { makeArchive } from '$mock/archive';
import config from '$mock/fixtures/config.json';
import type { ArchiveStatus, ConfigDoc } from '$lib/core/types';
import ArchiveCard from './ArchiveCard.svelte';

const NOW = Date.parse('2026-11-20T12:00:00Z');
const doc = config as unknown as ConfigDoc;

function archive(): ArchiveStatus {
  return makeArchive(NOW, doc, 'card', {});
}

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe('ArchiveCard', () => {
  it('lists the months newest first, the years and on demand the heating seasons', async () => {
    render(ArchiveCard, {
      archive: archive(),
      phase: 'ok',
      now: NOW,
      onchange: () => undefined,
      onrefresh: () => undefined,
      showMonths: true,
    });
    const months = screen.getAllByTestId('archive-month');
    expect(months[0]?.dataset['state']).toBe('open');
    expect(months[0]?.textContent).toContain('November 2026');
    expect(months[0]?.querySelector('[data-testid="archive-month-delete"]')).toBeNull();
    expect(months.at(-1)?.textContent).toContain('11 days missing');
    expect(screen.getByTestId('archive-privacy').textContent).toContain('Share it with care');
    const years = screen.getAllByTestId('archive-group').map((row) => row.dataset['period']);
    expect(years).toEqual(['2026', '2025']);
    expect(screen.getAllByTestId('archive-group')[1]?.textContent).toContain('Partial: 4 of 12');
    await fireEvent.click(screen.getByTestId('archive-by-season'));
    const seasons = screen.getAllByTestId('archive-group').map((row) => row.dataset['period']);
    expect(seasons).toEqual(['2026-27', '2025-26']);
    expect(screen.queryAllByTestId('archive-group-delete')).toHaveLength(0);
  });

  it('deletes a month after confirmation and hands the new list up', async () => {
    const after = archive();
    after.months = after.months.filter((month) => month.period !== '2026-09');
    const fetch = vi.fn(async () => json({ deleted: ['2026-09'], archive: after }));
    vi.stubGlobal('fetch', fetch);
    const onchange = vi.fn();
    render(ArchiveCard, {
      archive: archive(),
      phase: 'ok',
      now: NOW,
      onchange,
      onrefresh: () => undefined,
      showMonths: true,
    });
    const row = screen
      .getAllByTestId('archive-month')
      .find((item) => item.dataset['period'] === '2026-09')!;
    await fireEvent.click(row.querySelector('[data-testid="archive-month-delete"]')!);
    expect(screen.getByTestId('archive-delete-dialog').textContent).toContain('September 2026');
    await fireEvent.click(screen.getByTestId('archive-delete-confirm'));
    await waitFor(() => expect(onchange).toHaveBeenCalledWith(after));
    const [path, init] = fetch.mock.calls[0] as unknown as [string, RequestInit];
    expect(path).toBe('api/v1/archive/delete');
    expect(JSON.parse(String(init.body))).toEqual({ period: '2026-09' });
    expect(screen.getByTestId('archive-message').textContent).toContain('September 2026 deleted');
  });

  it('names a refusal and puts the switch back', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async (_path: string, init?: RequestInit) =>
        init?.method === 'PUT' ? json({ detail: 'admin' }, 403) : json(doc),
      ),
    );
    render(ArchiveCard, {
      archive: archive(),
      phase: 'ok',
      now: NOW,
      onchange: () => undefined,
      onrefresh: () => undefined,
      showMonths: true,
    });
    const toggle = screen.getByTestId('archive-switch') as HTMLInputElement;
    expect(toggle.checked).toBe(true);
    await fireEvent.click(toggle);
    await waitFor(() =>
      expect(screen.getByTestId('archive-message').textContent).toContain('admin login'),
    );
    expect(toggle.checked).toBe(true);
  });

  it('says so for an older service and for an empty archive', () => {
    render(ArchiveCard, {
      archive: null,
      phase: 'ok',
      now: NOW,
      onchange: () => undefined,
      onrefresh: () => undefined,
      showMonths: true,
    });
    expect(screen.getByTestId('archive-missing')).toBeTruthy();
    cleanup();
    render(ArchiveCard, {
      archive: makeArchive(NOW, doc, 'card', { archive: 'empty' }),
      phase: 'ok',
      now: NOW,
      onchange: () => undefined,
      onrefresh: () => undefined,
      showMonths: true,
    });
    expect(screen.getByTestId('archive-empty')).toBeTruthy();
  });
});
