import { readdirSync, readFileSync } from 'node:fs';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';
import { NARROW_QUERY, WIDE_QUERY } from './breakpoints';
import { contrastRatio, cssTokens, resolveTheme, resolveToken } from './theme';

const css = readFileSync(fileURLToPath(new URL('../../app.css', import.meta.url)), 'utf8');
const light = cssTokens(css, ':root');
const dark = { ...light, ...cssTokens(css, ":root[data-theme='dark']") };
const THEMES = { light, dark } as const;

const STATUS = ['ok', 'limited', 'frozen', 'stopped', 'manual', 'unknown'];

const TEXT: [string, string][] = [
  ['--text', '--bg'],
  ['--text', '--surface'],
  ['--text', '--surface-2'],
  ['--muted', '--bg'],
  ['--muted', '--surface'],
  ['--muted', '--surface-2'],
  ['--accent', '--surface'],
  ['--accent', '--bg'],
  ['--on-accent', '--accent'],
  ['--ok', '--surface'],
  ['--warn-text', '--warn-bg'],
  ['--err-text', '--err-bg'],
  ['--chart-axis', '--surface'],
  ...STATUS.flatMap((s): [string, string][] => [
    [`--status-${s}`, '--surface'],
    [`--status-${s}`, `--status-${s}-bg`],
  ]),
  ['--status-manual', '--status-manual-bg'],
];

const GRAPHIC = Object.keys(light).filter(
  (name) =>
    (name.startsWith('--cat-') ||
      name.startsWith('--series-') ||
      name.startsWith('--wf-') ||
      name.startsWith('--band-')) &&
    !['--series-comfort-band', '--series-ambient'].includes(name),
);

const LABELS = ['a', 'b', 'c', 'd', 'e', 'f', 'g'].map((letter) => `--label-${letter}`);
const LABEL_TEXT_MIN = { light: 3, dark: 4.5 } as const;

describe('theme', () => {
  it('resolves the preference against the device scheme', () => {
    expect(resolveTheme('auto', true)).toBe('dark');
    expect(resolveTheme('auto', false)).toBe('light');
    expect(resolveTheme('light', true)).toBe('light');
    expect(resolveTheme('dark', false)).toBe('dark');
  });

  it('computes WCAG contrast', () => {
    expect(contrastRatio('#000000', '#ffffff')).toBeCloseTo(21, 5);
    expect(contrastRatio('#777777', '#ffffff')).toBeCloseTo(4.48, 2);
  });

  it('defines every token in both themes', () => {
    const darkOnly = cssTokens(css, ":root[data-theme='dark']");
    expect(Object.keys(darkOnly).filter((name) => !(name in light))).toEqual([]);
    expect(GRAPHIC.length).toBeGreaterThan(30);
  });

  it.each(Object.keys(THEMES) as (keyof typeof THEMES)[])(
    'meets WCAG AA for text in %s',
    (name) => {
      const tokens = THEMES[name];
      const failures = TEXT.map(([fg, bg]) => ({
        pair: `${fg} on ${bg}`,
        ratio: contrastRatio(resolveToken(tokens, fg), resolveToken(tokens, bg)),
      })).filter((entry) => entry.ratio < 4.5);
      expect(failures).toEqual([]);
    },
  );

  it.each(Object.keys(THEMES) as (keyof typeof THEMES)[])(
    'keeps the energy label colours legible with their text and on the surface in %s',
    (name) => {
      const tokens = THEMES[name];
      const failures: string[] = [];
      for (const label of LABELS) {
        const fill = resolveToken(tokens, label);
        const onLabel = contrastRatio(resolveToken(tokens, '--on-label'), fill);
        if (onLabel < LABEL_TEXT_MIN[name]) failures.push(`--on-label on ${label}: ${onLabel}`);
        const onSurface = contrastRatio(fill, resolveToken(tokens, '--surface'));
        if (onSurface < 3) failures.push(`${label} on --surface: ${onSurface}`);
      }
      expect(failures).toEqual([]);
    },
  );

  it.each(Object.keys(THEMES) as (keyof typeof THEMES)[])(
    'gives chart and status inks 3:1 against the surfaces in %s',
    (name) => {
      const tokens = THEMES[name];
      const failures: string[] = [];
      for (const ink of GRAPHIC) {
        for (const surface of ['--surface', '--bg']) {
          const ratio = contrastRatio(resolveToken(tokens, ink), resolveToken(tokens, surface));
          if (ratio < 3) failures.push(`${ink} on ${surface}: ${ratio.toFixed(2)}`);
        }
      }
      expect(failures).toEqual([]);
    },
  );
});

const SRC = fileURLToPath(new URL('../..', import.meta.url));

function sourceFiles(dir: string, extensions: string[]): string[] {
  return readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const path = join(dir, entry.name);
    if (entry.isDirectory()) return sourceFiles(path, extensions);
    const wanted = extensions.some((ext) => entry.name.endsWith(ext));
    return wanted && !entry.name.endsWith('.test.ts') ? [path] : [];
  });
}

function relative(path: string): string {
  return path.slice(SRC.length);
}

describe('css tokens in use', () => {
  it('defines every var(--name) used in .svelte and .ts files', () => {
    const defined = new Set(Object.keys(light));
    const used = new Map<string, Set<string>>();
    for (const file of sourceFiles(SRC, ['.svelte', '.ts'])) {
      const text = readFileSync(file, 'utf8').replace(/\/\*[\s\S]*?\*\//g, '');
      for (const match of text.matchAll(/style:(--[a-z0-9-]+)=/gi)) defined.add(match[1] as string);
      for (const match of text.matchAll(/var\(\s*(--[a-z0-9-]*[a-z0-9])(?![a-z0-9-]|\$)/gi)) {
        const name = match[1] as string;
        if (!used.has(name)) used.set(name, new Set());
        used.get(name)?.add(relative(file));
      }
    }
    const undefinedNames = [...used.keys()].filter((name) => !defined.has(name)).sort();
    expect(undefinedNames).toEqual([]);
  });

  it('uses no colour literal inside a <style> block', () => {
    const colour = /#[0-9a-f]{3,8}\b|\b(?:rgb|rgba|hsl|hsla)\(/gi;
    const offenders: string[] = [];
    for (const file of sourceFiles(SRC, ['.svelte'])) {
      const text = readFileSync(file, 'utf8');
      const blocks = [...text.matchAll(/<style[^>]*>([\s\S]*?)<\/style>/g)].map((m) => m[1] ?? '');
      const count = blocks.reduce((sum, block) => sum + (block.match(colour)?.length ?? 0), 0);
      if (count > 0) offenders.push(`${relative(file)}: ${count}`);
    }
    expect(offenders.sort()).toEqual([]);
  });

  const DECLARATION =
    /(?<![\w-])(font-size|font-weight|border[a-z-]*-radius|padding[a-z-]*|margin[a-z-]*|(?:row-|column-)?gap)\s*:\s*([^;{}]+)/g;
  const LENGTH = /(?<![\w.#-])-?\d*\.?\d+(?:px|rem|em)\b/g;
  const ALLOWED_FONT_SIZE_EM = new Set(['home/RoomCard.svelte:0.4em']);
  const ALLOWED_PIXEL = new Set(['1px']);
  const SPACING_LITERAL_CAP_OUTSIDE_CHARTS = 307;

  function styleDeclarations(file: string): { property: string; value: string }[] {
    const text = readFileSync(file, 'utf8');
    const blocks = [...text.matchAll(/<style[^>]*>([\s\S]*?)<\/style>/g)].map((m) => m[1] ?? '');
    return blocks.flatMap((block) =>
      [...block.matchAll(DECLARATION)].map((m) => ({
        property: m[1] as string,
        value: (m[2] as string).replace(/var\([^)]*\)/g, ''),
      })),
    );
  }

  function literals(file: string, kind: 'font-size' | 'weight' | 'radius' | 'spacing'): string[] {
    const found: string[] = [];
    for (const { property, value } of styleDeclarations(file)) {
      if (kind === 'weight') {
        if (property === 'font-weight' && /\b\d{3}\b/.test(value)) found.push(value.trim());
        continue;
      }
      const wanted =
        kind === 'font-size'
          ? property === 'font-size'
          : kind === 'radius'
            ? property.endsWith('radius')
            : /^(padding|margin|gap|row-gap|column-gap)/.test(property);
      if (!wanted) continue;
      for (const length of value.match(LENGTH) ?? []) {
        if (ALLOWED_PIXEL.has(length) && kind === 'spacing') continue;
        if (/^-?0+(?:\.0+)?(?:px|rem|em)$/.test(length)) continue;
        found.push(length);
      }
    }
    return found;
  }

  it.each(['font-size', 'weight', 'radius'] as const)(
    'uses no literal %s in a <style> block, only tokens',
    (kind) => {
      const offenders: string[] = [];
      for (const file of sourceFiles(SRC, ['.svelte'])) {
        for (const literal of literals(file, kind)) {
          const key = `${relative(file).replace(/^components\//, '')}:${literal}`;
          if (kind === 'font-size' && ALLOWED_FONT_SIZE_EM.has(key)) continue;
          offenders.push(key);
        }
      }
      expect(offenders.sort()).toEqual([]);
    },
  );

  it('uses no literal padding, margin or gap in the chart components, only tokens', () => {
    const offenders: string[] = [];
    for (const file of sourceFiles(SRC, ['.svelte'])) {
      if (!relative(file).startsWith('components/charts/')) continue;
      for (const literal of literals(file, 'spacing'))
        offenders.push(`${relative(file)}:${literal}`);
    }
    expect(offenders.sort()).toEqual([]);
  });

  it('does not add literal padding, margin or gap outside the chart components', () => {
    let count = 0;
    for (const file of sourceFiles(SRC, ['.svelte'])) {
      if (relative(file).startsWith('components/charts/')) continue;
      count += literals(file, 'spacing').length;
    }
    expect(count).toBeLessThanOrEqual(SPACING_LITERAL_CAP_OUTSIDE_CHARTS);
  });
});

describe('breakpoints', () => {
  const mediaCss = readFileSync(
    fileURLToPath(new URL('../../styles/media.css', import.meta.url)),
    'utf8',
  );
  const definitions = Object.fromEntries(
    [...mediaCss.matchAll(/@custom-media\s+(--[a-z]+)\s+(\([^;]+\));/g)].map((m) => [m[1], m[2]]),
  );

  it('defines exactly the narrow and wide breakpoints, equal to the TypeScript constants', () => {
    expect(definitions).toEqual({ '--narrow': NARROW_QUERY, '--wide': WIDE_QUERY });
  });

  it('uses only --narrow and --wide as viewport width conditions in @media rules', () => {
    const offenders: string[] = [];
    for (const file of sourceFiles(SRC, ['.svelte', '.css'])) {
      if (file.endsWith('media.css')) continue;
      const text = readFileSync(file, 'utf8').replace(/\/\*[\s\S]*?\*\//g, '');
      for (const match of text.matchAll(/@media([^{]*)\{/g)) {
        const query = match[1] ?? '';
        if (/width|height/.test(query)) offenders.push(`${relative(file)}:${query.trim()}`);
      }
    }
    expect(offenders).toEqual([]);
  });

  it('calls matchMedia with a breakpoint constant, never a width literal', () => {
    const offenders: string[] = [];
    for (const file of sourceFiles(SRC, ['.svelte', '.ts'])) {
      if (file.endsWith('breakpoints.ts')) continue;
      const text = readFileSync(file, 'utf8');
      if (/matchMedia\??\.?\(\s*['"`][^'"`]*width/.test(text)) offenders.push(relative(file));
      if (/['"`]\((?:min|max)-width/.test(text)) offenders.push(relative(file));
    }
    expect(offenders).toEqual([]);
  });
});
