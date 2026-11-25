export type Theme = 'light' | 'dark';
export type ThemePreference = 'auto' | Theme;

export const THEME_PREFERENCES: ThemePreference[] = ['auto', 'light', 'dark'];

/**
 * Resolve the theme preference against the device's colour scheme.
 */
export function resolveTheme(preference: ThemePreference, prefersDark: boolean): Theme {
  if (preference === 'auto') return prefersDark ? 'dark' : 'light';
  return preference;
}

/**
 * Put the resolved theme on the root element as `data-theme`, which selects the token set.
 */
export function applyTheme(root: HTMLElement, theme: Theme): void {
  root.dataset['theme'] = theme;
}

/**
 * Parse "#rgb" or "#rrggbb" into 0–255 channels; null for anything else.
 */
export function parseHex(color: string): [number, number, number] | null {
  const hex = color.trim().replace(/^#/, '');
  const full =
    hex.length === 3
      ? hex
          .split('')
          .map((c) => c + c)
          .join('')
      : hex;
  if (!/^[0-9a-f]{6}$/i.test(full)) return null;
  return [0, 2, 4].map((i) => parseInt(full.slice(i, i + 2), 16)) as [number, number, number];
}

/**
 * WCAG relative luminance of a hex colour.
 */
export function relativeLuminance(color: string): number {
  const rgb = parseHex(color);
  if (!rgb) throw new Error(`not a hex colour: ${color}`);
  const [r, g, b] = rgb.map((channel) => {
    const v = channel / 255;
    return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4;
  }) as [number, number, number];
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

/**
 * WCAG contrast ratio between two hex colours (1–21).
 */
export function contrastRatio(a: string, b: string): number {
  const la = relativeLuminance(a);
  const lb = relativeLuminance(b);
  return (Math.max(la, lb) + 0.05) / (Math.min(la, lb) + 0.05);
}

/**
 * Read the custom properties declared in the first CSS rule whose selector matches exactly.
 */
export function cssTokens(css: string, selector: string): Record<string, string> {
  const start = css.indexOf(`${selector} {`);
  if (start < 0) return {};
  const end = css.indexOf('}', start);
  const body = css.slice(css.indexOf('{', start) + 1, end);
  const tokens: Record<string, string> = {};
  for (const match of body.matchAll(/(--[\w-]+)\s*:\s*([^;]+);/g)) {
    tokens[match[1] as string] = (match[2] as string).trim();
  }
  return tokens;
}

/**
 * Follow `var(--x)` aliases inside a token table until a literal value is reached.
 */
export function resolveToken(tokens: Record<string, string>, name: string, depth = 0): string {
  const value = tokens[name];
  if (value === undefined) throw new Error(`unknown token ${name}`);
  const alias = /^var\((--[\w-]+)\)$/.exec(value);
  if (alias && depth < 8) return resolveToken(tokens, alias[1] as string, depth + 1);
  return value;
}
