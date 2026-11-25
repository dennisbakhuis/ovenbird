import { timeLocale } from '$lib/core/format';
import type { ArchiveGroup, ArchiveMonth } from '$lib/core/types';

export type GroupKind = ArchiveGroup['kind'];

/**
 * Path of a month's download (`YYYY-MM`).
 */
export function monthPath(period: string): string {
  return `api/v1/archive/months/${period}`;
}

/**
 * Path of a calendar year's (`2026`) or heating season's (`2026-27`) download.
 */
export function groupPath(group: Pick<ArchiveGroup, 'kind' | 'id'>): string {
  return `api/v1/archive/${group.kind === 'year' ? 'years' : 'seasons'}/${group.id}`;
}

function monthDate(period: string, language: string | undefined, month: 'long' | 'short'): string {
  const [year, number] = period.split('-').map(Number);
  if (!year || !number) return period;
  return new Intl.DateTimeFormat(timeLocale(language), {
    month,
    year: 'numeric',
    timeZone: 'UTC',
  }).format(Date.UTC(year, number - 1, 1));
}

/**
 * A month (`2026-10`) as "October 2026" in the UI language.
 */
export function monthName(period: string, language?: string): string {
  return monthDate(period, language, 'long');
}

/**
 * A month (`2026-10`) as "Oct 2026" in the UI language.
 */
export function monthShort(period: string, language?: string): string {
  return monthDate(period, language, 'short');
}

/**
 * Whether a year or season download holds fewer than all its months.
 */
export function isPartial(group: Pick<ArchiveGroup, 'months' | 'of'>): boolean {
  return group.months.length < group.of;
}

/**
 * The frozen months of a calendar year: what deleting the year removes.
 */
export function frozenOfYear(months: readonly ArchiveMonth[], year: string): ArchiveMonth[] {
  return months.filter((month) => month.state === 'frozen' && month.period.startsWith(`${year}-`));
}
