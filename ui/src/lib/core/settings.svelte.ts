import {
  detectLanguage,
  translate,
  translateOptional,
  type Language,
  type LanguagePreference,
  type MessageKey,
  type Params,
} from '$lib/i18n';
import { STORAGE_PREFIX } from './brand';
import { setFormatLanguage } from './format';
import { hasBusyVariant, hotWater, textKey } from './hotWater.svelte';
import { isFramed } from './location';
import { applyTheme, resolveTheme, type Theme, type ThemePreference } from './theme';

const LANGUAGE_KEY = `${STORAGE_PREFIX}language`;
const THEME_KEY = `${STORAGE_PREFIX}theme`;
const DARK_QUERY = '(prefers-color-scheme: dark)';

function load<T extends string>(key: string, allowed: readonly T[], fallback: T): T {
  try {
    const stored = localStorage.getItem(key);
    return allowed.find((value) => value === stored) ?? fallback;
  } catch {
    return fallback;
  }
}

function store(key: string, value: string): void {
  try {
    localStorage.setItem(key, value);
  } catch {
    return;
  }
}

function darkQuery(): MediaQueryList | null {
  return typeof window === 'undefined' || typeof window.matchMedia !== 'function'
    ? null
    : window.matchMedia(DARK_QUERY);
}

class Settings {
  preference = $state<LanguagePreference>(load(LANGUAGE_KEY, ['auto', 'en', 'nl'], 'auto'));
  theme = $state<ThemePreference>(load(THEME_KEY, ['auto', 'light', 'dark'], 'auto'));
  prefersDark = $state(darkQuery()?.matches ?? false);
  readonly framed: boolean = isFramed();

  constructor() {
    darkQuery()?.addEventListener('change', (event) => {
      this.prefersDark = event.matches;
      this.#apply();
    });
    this.#apply();
  }

  get language(): Language {
    if (this.preference !== 'auto') return this.preference;
    return this.browserLanguage;
  }

  get browserLanguage(): Language {
    return detectLanguage(typeof navigator === 'undefined' ? [] : navigator.languages);
  }

  get resolvedTheme(): Theme {
    return resolveTheme(this.theme, this.prefersDark);
  }

  setPreference(value: LanguagePreference): void {
    this.preference = value;
    store(LANGUAGE_KEY, value);
  }

  setTheme(value: ThemePreference): void {
    this.theme = value;
    store(THEME_KEY, value);
    this.#apply();
  }

  #apply(): void {
    if (typeof document === 'undefined') return;
    applyTheme(document.documentElement, this.resolvedTheme);
    if (this.framed) document.documentElement.dataset['framed'] = '';
  }
}

export const settings = new Settings();
setFormatLanguage(() => settings.language);

/**
 * The key to translate: its neutral `busy_` variant while hot water is hidden. Only keys that
 * have such a variant depend on whether hot water shows.
 */
function shownKey<K extends string>(key: K): K | MessageKey {
  return hasBusyVariant(key) ? textKey(key, hotWater.shown) : key;
}

/**
 * Reactive translation using the current language.
 */
export function t(key: MessageKey, params: Record<string, string | number> = {}): string {
  return translate(settings.language, shownKey(key), params);
}

/**
 * Reactive translation of a server code (`prefix + code`), with the raw code as fallback.
 */
export function tc(prefix: string, code: string, params: Params = {}): string {
  return translateOptional(settings.language, shownKey(`${prefix}${code}`), params) ?? code;
}

/**
 * Reactive translation of a dynamic key; undefined when unknown.
 */
export function tOpt(key: string, params: Params = {}): string | undefined {
  return translateOptional(settings.language, shownKey(key), params);
}
