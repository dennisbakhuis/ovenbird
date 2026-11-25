// @vitest-environment jsdom
import { cleanup, render, screen } from '@testing-library/svelte';
import { afterEach, describe, expect, it } from 'vitest';
import EmptyState from '$ui/EmptyState.svelte';
import { ART_NAMES, loadArt } from './index';

afterEach(cleanup);

const pascal = (name: string) => name[0]!.toUpperCase() + name.slice(1);
const SOURCES = import.meta.glob<string>('./*.svelte', {
  query: '?raw',
  import: 'default',
  eager: true,
});

describe('art', () => {
  it('covers every ArtName', () => {
    expect([...ART_NAMES].sort()).toEqual(
      [
        'activity',
        'allQuiet',
        'shadow',
        'home',
        'noData',
        'pump',
        'settings',
        'setpoint',
        'system',
        'weather',
        'weatherOff',
        'welcome',
      ].sort(),
    );
  });

  it.each(ART_NAMES)('loads and renders %s as one decorative svg', async (name) => {
    const Art = await loadArt(name);
    const { container } = render(Art);
    const svgs = container.querySelectorAll('svg');
    expect(svgs).toHaveLength(1);
    expect(svgs[0]!.getAttribute('aria-hidden')).toBe('true');
    expect(svgs[0]!.getAttribute('viewBox')).toBe('0 0 300 180');
  });

  it.each(ART_NAMES)('%s uses brand tokens only and exactly one ember', (name) => {
    const source = SOURCES[`./${pascal(name)}.svelte`] ?? '';
    expect(source).not.toMatch(/#[0-9a-f]{3,6}\b/i);
    const nest = SOURCES['./Nest.svelte'] ?? '';
    const embers =
      (source.match(/var\(--brand-ember\)/g) ?? []).length +
      (source.match(/<Nest [^>]*\bember\b/g) ?? []).length;
    expect(nest).toContain('var(--brand-ember)');
    expect(embers).toBe(1);
    expect(source.length).toBeLessThan(6500);
  });

  it('renders an empty state with its text and drawing', async () => {
    render(EmptyState, {
      props: { art: 'noData', title: 'Nothing yet', text: 'Come back later.', testid: 'empty' },
    });
    expect(screen.getByTestId('empty').textContent).toContain('Nothing yet');
    expect(screen.getByText('Come back later.')).toBeTruthy();
    await expect.poll(() => screen.getByTestId('empty').querySelector('svg')).toBeTruthy();
  });
});
