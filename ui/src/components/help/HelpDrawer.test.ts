// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/svelte';
import { flushSync } from 'svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { HelpContent } from '$lib/help/content';
import { fixtureGlossary, fixtureTopic } from '$lib/help/fixtures/fixture';
import { HelpStore } from '$lib/help/store.svelte';
import HelpDrawer from './HelpDrawer.svelte';

const content = new HelpContent({
  './content/en/pump.ts': async () => ({ topic: fixtureTopic }),
  './content/en/glossary-a.ts': async () => ({ glossary: fixtureGlossary }),
});

let store: HelpStore;
let opener: HTMLButtonElement;
let target: HTMLDivElement;

function open(at: string | null = null) {
  opener.focus();
  store.show(at);
  return render(HelpDrawer, { store, content });
}

beforeEach(async () => {
  window.location.hash = '#/pump';
  await new Promise((resolve) => setTimeout(resolve, 0));
  vi.spyOn(Element.prototype, 'getClientRects').mockImplementation(
    () => [{}] as unknown as DOMRectList,
  );
  store = new HelpStore();
  opener = document.createElement('button');
  opener.textContent = 'opener';
  target = document.createElement('div');
  target.dataset['help'] = 'pump.flow';
  document.body.append(opener, target);
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  opener.remove();
  target.remove();
  localStorage.clear();
});

describe('HelpDrawer', () => {
  it('shows the topic of the page, grouped, with sections collapsed', async () => {
    open();
    expect(await screen.findByTestId('help-title')).toHaveProperty('textContent', 'Fixture pump');
    const drawer = screen.getByTestId('help-drawer');
    expect(drawer.getAttribute('role')).toBe('dialog');
    expect(drawer.textContent).toContain('What you see');
    expect(drawer.textContent).toContain('What you can do');
    expect(drawer.textContent).toContain('Good to know');
    const toggles = screen.getAllByTestId('help-section-toggle');
    expect(toggles.map((button) => button.getAttribute('aria-expanded'))).toEqual([
      'false',
      'false',
      'false',
    ]);
    expect(store.seen).toBe(true);
    expect(localStorage.getItem('ovenbird.helpSeen')).toBe('1');
  });

  it('renders markup as nodes, unfolds terms in place and opens the glossary with a way back', async () => {
    open();
    const [flow] = await screen.findAllByTestId('help-section-toggle');
    await fireEvent.click(flow!);
    const section = screen.getAllByTestId('help-section')[0]!;
    expect(section.querySelector('strong')?.textContent).toBe('flow');
    expect(section.querySelectorAll('li')).toHaveLength(2);
    const term = await waitFor(() => {
      const found = section.querySelector<HTMLButtonElement>('[data-term="delta-t"]');
      if (!found) throw new Error('term not rendered');
      return found;
    });
    expect(term.textContent).toBe('difference');
    await fireEvent.click(term);
    expect(term.getAttribute('aria-expanded')).toBe('true');
    expect(section.textContent).toContain('The difference between outlet and inlet water.');
    await fireEvent.click(screen.getByTestId('help-term-more'));
    expect(screen.getByTestId('help-title').textContent).toBe('Delta-T');
    await fireEvent.click(screen.getByTestId('help-back'));
    expect(screen.getByTestId('help-title').textContent).toBe('Fixture pump');
  });

  it('offers Show me only for targets on the page, and rings them', async () => {
    open();
    const toggles = await screen.findAllByTestId('help-section-toggle');
    for (const toggle of toggles) await fireEvent.click(toggle);
    const buttons = await screen.findAllByTestId('help-show-me');
    expect(buttons.map((button) => button.dataset['target'])).toEqual(['pump.flow']);
    await fireEvent.click(buttons[0]!);
    expect(screen.getByTestId('help-spotlight').dataset['target']).toBe('pump.flow');
  });

  it('opens at the section of a data-help target', async () => {
    open('pump.speed');
    const speed = await waitFor(() => {
      const found = screen
        .getAllByTestId('help-section')
        .find((node) => node.dataset['section'] === 'speed');
      expect(found?.querySelector('button')?.getAttribute('aria-expanded')).toBe('true');
      return found!;
    });
    expect(speed.querySelector('ol li strong')?.textContent).toBe('Edit');
    expect(speed.querySelector('a.help-link')?.getAttribute('href')).toBe('#/settings/pump-duty');
  });

  it('searches and jumps to a question', async () => {
    open();
    const search = await screen.findByTestId('help-search');
    await fireEvent.input(search, { target: { value: 'noisy' } });
    const results = await screen.findByTestId('help-results');
    await fireEvent.click(results.querySelector('button')!);
    await waitFor(() => {
      const question = screen.getByTestId('help-question');
      expect(question.querySelector('button')?.getAttribute('aria-expanded')).toBe('true');
    });
  });

  it('closes on Escape and returns focus to the opener', async () => {
    open();
    const drawer = await screen.findByTestId('help-drawer');
    await fireEvent.keyDown(drawer, { key: 'Escape' });
    flushSync();
    expect(store.open).toBe(false);
    expect(screen.queryByTestId('help-drawer')).toBeNull();
    expect(document.activeElement).toBe(opener);
  });

  it('lists all topics and the glossary', async () => {
    open();
    await fireEvent.click(await screen.findByTestId('help-all-topics'));
    expect(screen.getByTestId('help-index').textContent).toContain('Fixture pump');
    await fireEvent.click(screen.getByTestId('help-glossary-link'));
    const list = await screen.findByTestId('help-glossary');
    expect(list.textContent).toContain('Delta-T');
    expect(list.textContent).toContain('Outlet');
  });
});
