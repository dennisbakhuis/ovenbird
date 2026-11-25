import { afterEach, describe, expect, it } from 'vitest';
import { makeSnapshot } from '$mock/fixtures';
import { GLYPHS } from '$components/charts/glyphs';
import { dictionaries } from '$lib/i18n';
import {
  hasBusyVariant,
  hotWater,
  hotWaterLanes,
  hotWaterShown,
  reportedInstalled,
  textKey,
  type HotWaterSetting,
} from './hotWater.svelte';
import { settings, t, tc, tOpt } from './settings.svelte';
import type { ConfigDoc, Snapshot } from './types';

describe('hotWaterShown', () => {
  it('shows for on and hides for off, whatever the pump reports', () => {
    for (const installed of [1, 0, null]) {
      expect(hotWaterShown('on', installed, false)).toBe(true);
      expect(hotWaterShown('off', installed, true)).toBe(false);
    }
  });

  it('follows the live report of a tank for auto, then the service, then shows', () => {
    expect(hotWaterShown('auto', 1, false)).toBe(true);
    expect(hotWaterShown('auto', 0, true)).toBe(false);
    expect(hotWaterShown('auto', undefined, false)).toBe(false);
    expect(hotWaterShown('auto', null, true)).toBe(true);
    expect(hotWaterShown('auto', null, null)).toBe(true);
    expect(hotWaterShown(null, 0, null)).toBe(false);
  });

  it('reads the tank report as 1 or 0', () => {
    expect([1, 0, true, false, '1', '0', 'x', null, Number.NaN].map(reportedInstalled)).toEqual([
      true,
      false,
      true,
      false,
      true,
      false,
      null,
      null,
      null,
    ]);
  });
});

describe('hot-water texts', () => {
  it('swaps a text for its busy variant only while hot water is hidden', () => {
    expect(textKey('pumpStateDhw', true)).toBe('pumpStateDhw');
    expect(textKey('pumpStateDhw', false)).toBe('busy_pumpStateDhw');
    expect(textKey('pumpStateRunning', false)).toBe('pumpStateRunning');
    expect(hasBusyVariant('reason_dhw_freeze')).toBe(true);
  });

  it('has a base text for every busy variant, and no busy text names hot water', () => {
    for (const language of ['en', 'nl'] as const) {
      const dictionary: Record<string, string> = dictionaries[language];
      for (const [key, text] of Object.entries(dictionary)) {
        if (!key.startsWith('busy_')) continue;
        expect(dictionary[key.slice('busy_'.length)], key).toBeDefined();
        expect(text, key).not.toMatch(/hot.?water|dhw|tapwater|warm ?water|boiler|\btank/i);
      }
    }
  });

  it('covers every text that names hot water, except those shown only with hot water', () => {
    const own = /^(cfg\.hot_water\.|hotWaterTank_|sig_(DHW_|Force_DHW)|sigval_.+_dhw$)/;
    const operatingModes = ['inputEnum_operating_mode_3', 'inputEnum_operating_mode_4'];
    const uncovered = Object.entries(dictionaries.en)
      .filter(([key, text]) => /hot.?water|\bDHW\b/i.test(text) && !key.startsWith('busy_'))
      .map(([key]) => key)
      .filter((key) => !own.test(key) && !operatingModes.includes(key) && !hasBusyVariant(key));
    expect(uncovered).toEqual([]);
  });
});

describe('hotWaterLanes', () => {
  const lanes = [
    { id: 'compressor', segments: [1], icon: 'fan' },
    { id: 'dhw', segments: [] as number[], icon: 'tap' },
  ];

  it('keeps every lane while hot water shows', () => {
    expect(hotWaterLanes(lanes, true)).toBe(lanes);
  });

  it('drops an empty hot-water lane and keeps one with runs under the gear', () => {
    expect(hotWaterLanes(lanes, false).map((lane) => lane.id)).toEqual(['compressor']);
    const run = [lanes[0]!, { ...lanes[1]!, segments: [1] }];
    expect(hotWaterLanes(run, false)[1]).toEqual({ id: 'dhw', segments: [1], icon: GLYPHS.gear });
  });
});

function doc(setting: HotWaterSetting, installed: boolean | null): ConfigDoc {
  return {
    hot_water: { setting, installed, shown: setting === 'on' || installed !== false },
  } as ConfigDoc;
}

describe('the hot-water store', () => {
  const NOW = new Date(2026, 10, 15, 12).getTime();
  const withTank = makeSnapshot(NOW, {});
  const noTank = makeSnapshot(NOW, { dhw: 'none' });
  const unreported: Snapshot = {
    ...withTank,
    signals: Object.fromEntries(
      Object.entries(withTank.signals).filter(([id]) => id !== 'main/DHW_Installed'),
    ),
  };

  afterEach(() => {
    hotWater.connect(() => ({ snapshot: null, config: null }));
    settings.setPreference('auto');
  });

  it('shows hot water before it is connected', () => {
    expect(hotWater.shown).toBe(true);
  });

  it('follows the pump report, the service and the stored setting', () => {
    hotWater.connect(() => ({ snapshot: noTank, config: doc('auto', true) }));
    expect(hotWater.shown).toBe(false);
    hotWater.connect(() => ({ snapshot: withTank, config: doc('auto', false) }));
    expect(hotWater.shown).toBe(true);
    hotWater.connect(() => ({ snapshot: unreported, config: doc('auto', false) }));
    expect(hotWater.shown).toBe(false);
    hotWater.connect(() => ({ snapshot: noTank, config: doc('on', false) }));
    expect(hotWater.shown).toBe(true);
    hotWater.connect(() => ({ snapshot: withTank, config: doc('off', true) }));
    expect(hotWater.shown).toBe(false);
  });

  it('names a hot-water run neutrally in every translation while hot water is hidden', () => {
    settings.setPreference('en');
    hotWater.connect(() => ({ snapshot: withTank, config: doc('auto', true) }));
    expect(t('pumpStateDhw')).toBe('Hot water');
    hotWater.connect(() => ({ snapshot: noTank, config: doc('auto', true) }));
    expect(t('pumpStateDhw')).toBe('Pump busy elsewhere');
    expect(t('statusDhw')).toBe('Pump busy elsewhere');
    expect(tc('reason_', 'dhw_freeze')).toBe('Pump busy elsewhere');
    expect(tOpt('pumpRefusal_dhw')).toBe('The pump is busy elsewhere. Try again afterwards.');
    expect(t('fact_dhw', { setpoint: 30 })).toBe(
      'The pump is busy elsewhere: corrections are paused and the setpoint is not lowered.',
    );
    expect(t('pumpStateRunning')).toBe('Heating');
    settings.setPreference('nl');
    expect(t('pumpStateDhw')).toBe('Pomp elders bezig');
    expect(tOpt('frozenBy_dhw')).toBe('pomp elders bezig');
  });
});
