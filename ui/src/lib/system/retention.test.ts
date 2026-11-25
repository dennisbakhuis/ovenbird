import { describe, expect, it } from 'vitest';
import { makeArchive } from '$mock/archive';
import { makeStorage } from '$mock/data';
import config from '$mock/fixtures/config.json';
import schema from '$mock/fixtures/schema.json';
import { checkField } from '$lib/core/schema';
import type { ConfigDoc, ConfigSchema } from '$lib/core/types';
import { frozenOfYear, groupPath, isPartial, monthName, monthPath } from './archive';
import { RETENTION_PRESETS, keptDays, matchPreset, presetChanges, presetTable } from './retention';

const doc = config as unknown as ConfigDoc;
const sch = schema as unknown as ConfigSchema;
const NOW = Date.parse('2026-11-20T12:00:00Z');

function withValues(values: Record<string, number | null>): ConfigDoc {
  const fields = { ...doc.fields };
  for (const [id, value] of Object.entries(values))
    fields[id] = { ...fields[id]!, value, stored: value };
  return { ...doc, fields };
}

describe('retention presets', () => {
  it('reads forever as 0 and matches the defaults as standard', () => {
    expect([null, undefined, 0, 14].map(keptDays)).toEqual([0, 0, 0, 14]);
    const values = Object.fromEntries(
      Object.keys(RETENTION_PRESETS.standard).map((id) => [id, doc.fields[id]?.value]),
    );
    expect(matchPreset(values)).toBe('standard');
    expect(matchPreset({ ...values, history_raw_days: 21 })).toBe('custom');
    expect(matchPreset(RETENTION_PRESETS.unlimited)).toBe('unlimited');
  });

  it('changes only what differs and keeps an unset forever unset', () => {
    const short = presetChanges('short', doc);
    expect(short.history_15m_days).toBe(366);
    expect(short.history_1h_days).toBeNull();
    const unlimited = presetChanges('unlimited', withValues({ history_1h_days: 0 }));
    expect(unlimited.history_1h_days).toBe(0);
    expect(unlimited.history_raw_days).toBe(0);
  });

  it('takes the values the service reports over the built-in ones', () => {
    const table = presetTable([
      {
        id: 'short',
        values: { ...RETENTION_PRESETS.short, history_raw_days: 5 },
        projected_bytes: 1,
        growth_bytes_per_year: 0,
      },
    ]);
    expect(table.short.history_raw_days).toBe(5);
    expect(table.long).toEqual(RETENTION_PRESETS.long);
    expect(presetTable(null)).toEqual(RETENTION_PRESETS);
  });

  it('refuses a retention between 0 and one day', () => {
    expect(checkField(sch, 'history_1m_days', 0.5, doc).error).toBe('retention_min');
    expect(checkField(sch, 'history_1m_days', 1, doc).error).toBeNull();
    expect(checkField(sch, 'history_1m_days', 0, doc).error).toBeNull();
  });

  it('projects every preset in the mock storage report and names the one in effect', () => {
    const storage = makeStorage(NOW, doc, 'presets');
    expect(storage.preset).toBe('standard');
    const sizes = Object.fromEntries(storage.presets.map((p) => [p.id, p.projected_bytes ?? 0]));
    expect(sizes['short']!).toBeLessThan(sizes['long']!);
    expect(storage.presets.find((p) => p.id === 'standard')?.projected_bytes).toBe(
      storage.projected_bytes,
    );
    const custom = makeStorage(NOW, withValues({ history_raw_days: 21 }), 'presets');
    expect(custom.preset).toBeNull();
  });
});

describe('yearly archive helpers', () => {
  it('builds the download paths and names the months', () => {
    expect(monthPath('2026-10')).toBe('api/v1/archive/months/2026-10');
    expect(groupPath({ kind: 'year', id: '2026' })).toBe('api/v1/archive/years/2026');
    expect(groupPath({ kind: 'season', id: '2026-27' })).toBe('api/v1/archive/seasons/2026-27');
    expect(monthName('2026-10', 'en-GB')).toBe('October 2026');
    expect(monthName('2026-10', 'nl')).toBe('oktober 2026');
    expect(monthName('nonsense', 'en')).toBe('nonsense');
  });

  it('tells partial years and what deleting a year removes', () => {
    const archive = makeArchive(NOW, doc, 'helpers', {});
    expect(archive.months[0]?.state).toBe('open');
    const year = archive.years.find((group) => group.id === '2025')!;
    expect(isPartial(year)).toBe(true);
    expect(frozenOfYear(archive.months, '2025').map((m) => m.period)).toEqual(
      [...year.months].reverse(),
    );
    const current = archive.years.find((group) => group.id === '2026')!;
    expect(current.open_months).toEqual(['2026-11']);
    expect(frozenOfYear(archive.months, '2026')).toHaveLength(10);
  });

  it('follows the switch and the scenarios', () => {
    const off = makeArchive(NOW, withValues({ history_archive_enabled: null }), 'k', {});
    expect(off.enabled).toBe(true);
    const fields = { ...doc.fields };
    fields['history_archive_enabled'] = { ...fields['history_archive_enabled']!, value: false };
    expect(makeArchive(NOW, { ...doc, fields }, 'k', {}).enabled).toBe(false);
    expect(makeArchive(NOW, doc, 'k', { archive: 'empty' }).months).toEqual([]);
    expect(makeArchive(NOW, doc, 'k', { archive: 'error' }).state?.error).toBeTruthy();
  });
});
