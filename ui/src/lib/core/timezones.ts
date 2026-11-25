/**
 * IANA time zones the browser knows, sorted, with `current` included even when the browser does
 * not list it (an older or a custom value stays selectable).
 */
export function timeZones(current: string | null): string[] {
  const intl = Intl as unknown as { supportedValuesOf?: (key: string) => string[] };
  let zones: string[];
  try {
    zones = intl.supportedValuesOf?.('timeZone') ?? [];
  } catch {
    zones = [];
  }
  const all = new Set(zones);
  const browser = browserZone();
  if (browser) all.add(browser);
  if (current) all.add(current);
  all.add('UTC');
  return [...all].sort((a, b) => a.localeCompare(b));
}

/** The browser's own time zone, or null when it cannot be told. */
export function browserZone(): string | null {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || null;
  } catch {
    return null;
  }
}

/** "18:27" at `ms` in `zone`, or null when the zone is not valid. */
export function clockIn(ms: number, zone: string, locale: string): string | null {
  try {
    return new Intl.DateTimeFormat(locale === 'nl' ? 'nl-NL' : 'en-GB', {
      timeZone: zone,
      hour: '2-digit',
      minute: '2-digit',
    }).format(ms);
  } catch {
    return null;
  }
}
