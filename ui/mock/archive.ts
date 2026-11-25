import type {
  ArchiveDeleteResult,
  ArchiveGroup,
  ArchiveMonth,
  ArchiveStatus,
  ConfigDoc,
} from '../src/lib/core/types';
import type { Download } from './data.ts';
import type { Scenario } from './scenario.ts';

const MONTHS_KEPT = 15;
const FIRST_DAY = 12;
const FULL_MONTH_BYTES = 30_400_000;
const OPEN_DAY_BYTES = 2_700_000;
const GAP_MONTH_AGO = 5;
const GAP_DAYS = 3;
const NOTICE =
  "This archive holds the full measurement history of the installation: room and water temperatures, heat-pump activity and the controller's decisions. Over weeks they reveal when the house is occupied, heated or empty. Share it with care.";

const deletions = new Map<string, Set<string>>();

interface Period {
  year: number;
  month: number;
}

const label = ({ year, month }: Period) => `${year}-${String(month).padStart(2, '0')}`;
const iso = (ms: number) => new Date(ms).toISOString().replace('.000Z', 'Z');
const startOf = ({ year, month }: Period) => Date.UTC(year, month - 1, 1);
const daysIn = ({ year, month }: Period) => new Date(Date.UTC(year, month, 0)).getUTCDate();

function shift(period: Period, by: number): Period {
  const index = period.year * 12 + period.month - 1 + by;
  return { year: Math.floor(index / 12), month: (index % 12) + 1 };
}

function deleted(key: string): Set<string> {
  let found = deletions.get(key);
  if (!found) {
    found = new Set();
    deletions.set(key, found);
  }
  return found;
}

/**
 * The months the mock archive holds for a scenario at `now`: fifteen months, the first one from
 * its twelfth day, one with three days missing, the current one open, deleted ones left out.
 */
function months(now: number, key: string, scenario: Scenario): ArchiveMonth[] {
  if (scenario.archive === 'empty') return [];
  const today = new Date(now);
  const current = { year: today.getUTCFullYear(), month: today.getUTCMonth() + 1 };
  const gone = deleted(key);
  const out: ArchiveMonth[] = [];
  for (let back = MONTHS_KEPT - 1; back >= 0; back -= 1) {
    const period = shift(current, -back);
    const name = label(period);
    if (gone.has(name)) continue;
    const total = daysIn(period);
    const start = startOf(period);
    const end = startOf(shift(period, 1));
    if (back === 0) {
      out.push({
        period: name,
        state: 'open',
        bytes: today.getUTCDate() * OPEN_DAY_BYTES,
        days_total: total,
        from: iso(start),
        to: iso(end),
        complete: null,
        days: null,
        decision_days: null,
        missing_days: null,
        created_at: null,
        archived_to: iso(Math.floor(now / 900_000) * 900_000 - 600_000),
      });
      continue;
    }
    const first = back === MONTHS_KEPT - 1;
    const missing = first ? FIRST_DAY - 1 : back === GAP_MONTH_AGO ? GAP_DAYS : 0;
    const days = total - missing;
    out.push({
      period: name,
      state: 'frozen',
      bytes: Math.round((FULL_MONTH_BYTES * days) / total) + ((period.month * 7919) % 400_000),
      days_total: total,
      from: iso(start),
      to: iso(end),
      complete: missing === 0,
      days,
      decision_days: days,
      missing_days: missing,
      created_at: iso(end + 6 * 3_600_000),
      archived_to: iso(end),
    });
  }
  return out;
}

function group(
  kind: 'year' | 'season',
  id: string,
  period: string,
  periods: string[],
  stored: ArchiveMonth[],
): ArchiveGroup {
  const inside = stored.filter((month) => periods.includes(month.period));
  const frozen = inside.filter((month) => month.state === 'frozen');
  const names = frozen.map((month) => month.period).sort();
  return {
    id,
    kind,
    period,
    months: names,
    open_months: inside.filter((month) => month.state === 'open').map((month) => month.period),
    of: periods.length,
    bytes: frozen.reduce((sum, month) => sum + month.bytes, 0),
    complete: frozen.length === periods.length && frozen.every((month) => month.complete),
    first: names[0] ?? null,
    last: names.at(-1) ?? null,
  };
}

function groups(stored: ArchiveMonth[]): { years: ArchiveGroup[]; seasons: ArchiveGroup[] } {
  const years = [...new Set(stored.map((month) => Number(month.period.slice(0, 4))))];
  const seasonStarts = [
    ...new Set(
      stored.map((month) => {
        const [year, number] = month.period.split('-').map(Number) as [number, number];
        return number >= 8 ? year : year - 1;
      }),
    ),
  ];
  const yearGroups = years
    .sort((a, b) => b - a)
    .map((year) =>
      group(
        'year',
        String(year),
        String(year),
        Array.from({ length: 12 }, (_, index) => label({ year, month: index + 1 })),
        stored,
      ),
    );
  const seasonGroups = seasonStarts
    .sort((a, b) => b - a)
    .map((start) =>
      group(
        'season',
        `${start}-${String((start + 1) % 100).padStart(2, '0')}`,
        `${start}/${String((start + 1) % 100).padStart(2, '0')}`,
        Array.from({ length: 12 }, (_, index) => label(shift({ year: start, month: 8 }, index))),
        stored,
      ),
    );
  return { years: yearGroups, seasons: seasonGroups };
}

/**
 * `GET archive` for a scenario: `archive:empty` holds nothing, `archive:error` reports a failed
 * step; the switch follows `history_archive_enabled` in `doc`.
 */
export function makeArchive(
  now: number,
  doc: ConfigDoc,
  key: string,
  scenario: Scenario,
): ArchiveStatus {
  const stored = months(now, key, scenario);
  const frozen = stored.filter((month) => month.state === 'frozen');
  const days = frozen.reduce((sum, month) => sum + (month.days ?? 0), 0);
  const bytes = frozen.reduce((sum, month) => sum + month.bytes, 0);
  const open = stored.find((month) => month.state === 'open');
  return {
    enabled: doc.fields['history_archive_enabled']?.value !== false,
    timezone: String(doc.fields['control_timezone']?.value ?? 'Europe/Amsterdam'),
    state: {
      last_run_at: iso(Math.floor(now / 900_000) * 900_000),
      error: scenario.archive === 'error' ? 'disk I/O error' : null,
      behind: false,
      archived_to: open?.archived_to ?? null,
    },
    months: [...stored].reverse(),
    ...groups(stored),
    total_bytes: stored.reduce((sum, month) => sum + month.bytes, 0),
    bytes_per_year: days > 0 ? Math.round((bytes / days) * 365) : null,
    notice: NOTICE,
  };
}

const refusal = (status: number, detail: string): Download => ({
  status,
  type: 'application/json',
  filename: null,
  body: JSON.stringify({ detail }),
});

function emptyZip(filename: string): Download {
  const body = new Uint8Array(22);
  body.set([0x50, 0x4b, 0x05, 0x06]);
  return { status: 200, type: 'application/zip', filename, body };
}

/**
 * `GET archive/months/{month}`, `archive/years/{year}` and `archive/seasons/{season}`: an empty
 * zip under the service's file name; 403 for a viewer, 400 for a malformed period, 404 for one
 * without a stored (frozen, for a bundle) month.
 */
export function archiveDownload(
  kind: string,
  ident: string,
  now: number,
  key: string,
  scenario: Scenario,
): Download {
  if (scenario.role === 'viewer') return refusal(403, 'this action needs the admin role');
  const stored = months(now, key, scenario);
  if (kind === 'months') {
    if (!/^\d{4}-(0[1-9]|1[0-2])$/.test(ident)) return refusal(400, 'month must be YYYY-MM');
    const month = stored.find((item) => item.period === ident);
    if (!month) return refusal(404, `${ident} is not in the archive`);
    return emptyZip(`ovenbird-archive-${ident}${month.state === 'open' ? '-partial' : ''}.zip`);
  }
  const { years, seasons } = groups(stored);
  const valid = kind === 'years' ? /^\d{4}$/.test(ident) : /^\d{4}-\d{2}$/.test(ident);
  if (!valid) return refusal(400, `malformed ${kind === 'years' ? 'year' : 'season'}`);
  const found = (kind === 'years' ? years : seasons).find((item) => item.id === ident);
  if (!found || found.months.length === 0)
    return refusal(404, `no frozen month of ${ident} in the archive`);
  return emptyZip(
    kind === 'years' ? `ovenbird-archive-${ident}.zip` : `ovenbird-archive-season-${ident}.zip`,
  );
}

/**
 * `POST archive/delete`: forget a frozen month or every frozen month of a year for this
 * browser's scenario.
 */
export function archiveDelete(
  body: Record<string, unknown>,
  now: number,
  doc: ConfigDoc,
  key: string,
  scenario: Scenario,
): { status: number; body: ArchiveDeleteResult | { detail: string } } {
  if (scenario.role === 'viewer')
    return { status: 403, body: { detail: 'this action needs the admin role' } };
  const period = body['period'];
  if (typeof period !== 'string' || !/^\d{4}(-(0[1-9]|1[0-2]))?$/.test(period))
    return { status: 400, body: { detail: 'period must be a month (YYYY-MM) or a year (YYYY)' } };
  const stored = months(now, key, scenario);
  const chosen = stored.filter((month) =>
    period.length === 4 ? month.period.startsWith(`${period}-`) : month.period === period,
  );
  if (period.length === 7 && chosen[0]?.state === 'open')
    return {
      status: 409,
      body: { detail: `${period} is still being archived; delete it once it is frozen` },
    };
  const frozen = chosen.filter((month) => month.state === 'frozen').map((month) => month.period);
  if (frozen.length === 0)
    return { status: 404, body: { detail: `no frozen month of ${period} in the archive` } };
  for (const name of frozen) deleted(key).add(name);
  return {
    status: 200,
    body: { deleted: frozen.sort(), archive: makeArchive(now, doc, key, scenario) },
  };
}

/**
 * Forget the deletions (tests).
 */
export function resetArchive(): void {
  deletions.clear();
}
