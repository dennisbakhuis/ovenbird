import { describe, expect, it } from 'vitest';
import config from '$mock/fixtures/config.json';
import schema from '$mock/fixtures/schema.json';
import { dictionaries, translateOptional } from '$lib/i18n';
import { DraftStore, parseExport, type StorageLike } from './draft.svelte';
import { checkChanges, checkNumber, fromDisplay, toDisplay } from './schema';
import type { ConfigDoc, ConfigSchema } from './types';

const doc = config as unknown as ConfigDoc;
const sch = schema as unknown as ConfigSchema;

function memory(): StorageLike & { data: Record<string, string> } {
  const data: Record<string, string> = {};
  return {
    data,
    getItem: (k) => data[k] ?? null,
    setItem: (k, v) => void (data[k] = v),
    removeItem: (k) => void delete data[k],
  };
}

describe('draft', () => {
  it('keeps only changes that differ from the active value', () => {
    const draft = new DraftStore(memory());
    draft.set('control_comfort_c', 22, doc);
    expect(draft.count).toBe(1);
    expect(draft.base).toBe(1);
    draft.set('control_comfort_c', 21.5, doc);
    expect(draft.count).toBe(0);
    expect(draft.base).toBeNull();
  });

  it('null resets a stored value and is a no-op for a preset value', () => {
    const draft = new DraftStore(memory());
    draft.reset('control_comfort_c', doc);
    expect(draft.changes['control_comfort_c']).toBeNull();
    expect(draft.value('control_comfort_c', doc)).toBe(21);
    expect(draft.diff(doc)[0]).toMatchObject({ from: 21.5, to: 21, reset: true });
    draft.reset('control_dwell_s', doc);
    expect(draft.has('control_dwell_s')).toBe(false);
  });

  it('never drafts a locked field', () => {
    const draft = new DraftStore(memory());
    draft.set('control_interval_s', 30, doc);
    expect(draft.count).toBe(0);
  });

  it('persists and reloads, and detects a moved config', () => {
    const store = memory();
    new DraftStore(store).set('control_comfort_c', 22, doc);
    const again = new DraftStore(store);
    expect(again.changes).toEqual({ control_comfort_c: 22 });
    expect(again.isStale({ ...doc, version: 2 })).toBe(true);
    expect(again.isStale(doc)).toBe(false);
  });

  it('keeps the origin of a loaded suggestion until the draft is edited or cleared', () => {
    const store = memory();
    const draft = new DraftStore(store);
    const origin = {
      label: 'Suggested by the house model',
      comment: 'house-1',
      kind: 'house' as const,
    };
    const curve = [
      [-10, 40],
      [0, 35],
      [15, 26],
    ];
    expect(draft.loadChanges({ control_curve: curve }, origin, doc)).toBe(1);
    expect(draft.origin).toEqual(origin);
    expect(new DraftStore(store).origin).toEqual(origin);
    draft.set('control_comfort_c', 22, doc);
    expect(draft.origin).toBeNull();
    draft.loadChanges({ control_curve: curve }, origin, doc);
    expect(draft.changes).toEqual({ control_curve: curve });
    draft.clear();
    expect(draft.origin).toBeNull();
    expect(new DraftStore(store).origin).toBeNull();
  });

  it('keeps no origin when the suggestion equals the active config', () => {
    const draft = new DraftStore(memory());
    const same = doc.fields['control_curve']?.value;
    expect(draft.loadChanges({ control_curve: same }, { label: 'x', comment: 'y' }, doc)).toBe(0);
    expect(draft.origin).toBeNull();
    expect(draft.count).toBe(0);
  });

  it('turns an import into a draft with resets for absent fields', () => {
    const parsed = parseExport(
      JSON.stringify({
        ovenbird_config: 1,
        values: { control_dwell_s: 1500, control_interval_s: 30, nonsense: 1 },
      }),
    );
    if ('error' in parsed) throw new Error('parse');
    const draft = new DraftStore(memory());
    const outcome = draft.loadDocument(parsed.values, doc, sch);
    expect(draft.changes['control_dwell_s']).toBe(1500);
    expect(draft.changes['control_comfort_c']).toBeNull();
    expect(draft.has('control_interval_s')).toBe(false);
    expect(outcome.locked).toEqual(['control_interval_s']);
    expect(outcome.unknown).toEqual(['nonsense']);
  });

  it('rejects files that are not exports', () => {
    expect(parseExport('nope')).toEqual({ error: 'not_json' });
    expect(parseExport('{"values":{}}')).toEqual({ error: 'not_an_export' });
  });
});

describe('schema checks and units', () => {
  it('flags hard bounds and soft ranges from the schema', () => {
    const def = sch.fields['control_comfort_c']!;
    expect(checkNumber(def, 4).error).toBe('below_min');
    expect(checkNumber(def, 31).error).toBe('above_max');
    expect(checkNumber(def, 25)).toEqual({ error: null, warning: 'above_soft_max' });
    expect(checkNumber(def, 21)).toEqual({ error: null, warning: null });
    expect(checkNumber(sch.fields['control_pump_duty_heat']!, 100.5).error).toBe('not_integer');
  });

  it('checks the curve envelope and shift', () => {
    const out = checkChanges(
      sch,
      {
        control_curve: [
          [-10, 39],
          [0, 25],
          [15, 25],
        ],
      },
      doc,
    );
    expect(out.errors['control_curve']).toBe('outside_envelope');
    const shifted = checkChanges(
      sch,
      {
        control_curve: [
          [-10, 39],
          [0, 38],
          [15, 25],
        ],
      },
      doc,
    );
    expect(shifted.warnings['control_curve']).toBe('curve_shift_large');
  });

  it('round-trips display units', () => {
    for (const id of [
      'control_dwell_s',
      'control_room_silence_limit_s',
      'control_outside_filter_s',
    ]) {
      const def = sch.fields[id]!;
      for (const value of [300, 900, 1800, 5400, 86400])
        expect(fromDisplay(def, toDisplay(def, value))).toBe(value);
    }
  });
});

describe('field texts', () => {
  it.each(['en', 'nl'] as const)(
    'every schema field and option has label and help in %s',
    (lang) => {
      for (const [id, def] of Object.entries(sch.fields)) {
        if (def.editable === false) continue;
        expect(translateOptional(lang, `cfg.${id}.label`), id).toBeTruthy();
        expect(translateOptional(lang, `cfg.${id}.help`), id).toBeTruthy();
        for (const option of def.options ?? [])
          expect(
            translateOptional(lang, `cfg.${id}.opt.${option}`),
            `${id}.${option}`,
          ).toBeTruthy();
      }
      expect(Object.keys(dictionaries[lang]).length).toBeGreaterThan(0);
    },
  );

  it.each(['en', 'nl'] as const)('has group and section texts in %s', (lang) => {
    for (const g of sch.groups) expect(translateOptional(lang, `group_${g.id}`), g.id).toBeTruthy();
  });
});
