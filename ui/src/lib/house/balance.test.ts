import { describe, expect, it } from 'vitest';
import { translate } from '$lib/i18n';
import {
  MAX_ARROW_PX,
  MIN_ARROW_PX,
  balanceSentence,
  flowWeight,
  formatPower,
  storageKind,
  wrapLabel,
} from './balance';
import type { HouseBalance } from './shapes';

const tr = (key: Parameters<typeof translate>[1], params?: Parameters<typeof translate>[2]) =>
  translate('en', key, params);

function balance(flows: Partial<HouseBalance['flows']> = {}): HouseBalance {
  return {
    at: '2026-11-27T12:00:00Z',
    source: 'model',
    credible: true,
    room_c: 21,
    outside_c: 5,
    sun_wm2: 100,
    flows: {
      heat_pump_w: 2400,
      loss_w: 2100,
      sun_w: 300,
      internal_w: 300,
      stove_active: false,
      storage_w: 900,
      ...flows,
    },
    ua_w_per_k: 240,
    notes: [],
  };
}

describe('flowWeight', () => {
  it('grows with the power and is clamped', () => {
    expect(flowWeight(0)).toBe(MIN_ARROW_PX);
    expect(flowWeight(1000)!).toBeGreaterThan(flowWeight(500)!);
    expect(flowWeight(100000)).toBe(MAX_ARROW_PX);
    expect(flowWeight(-1000)).toBe(flowWeight(1000));
  });

  it('is null for an unknown flow, not the minimum', () => {
    expect(flowWeight(null)).toBeNull();
  });
});

describe('formatPower', () => {
  it('uses watts below 1 kW and kW above', () => {
    expect(formatPower(342, 'en')).toBe('340\u202fW');
    expect(formatPower(2140, 'en')).toBe('2.1\u202fkW');
    expect(formatPower(-2140, 'nl')).toBe('2,1\u202fkW');
    expect(formatPower(null, 'en')).toBe('–');
  });
});

describe('storageKind', () => {
  it('tells storing, giving back, steady and unknown', () => {
    expect(storageKind(900)).toBe('storing');
    expect(storageKind(-400)).toBe('giving');
    expect(storageKind(20)).toBe('steady');
    expect(storageKind(null)).toBe('unknown');
  });
});

describe('wrapLabel', () => {
  it('breaks at spaces and keeps long words whole', () => {
    expect(wrapLabel('People and appliances', 12)).toEqual(['People and', 'appliances']);
    expect(wrapLabel('Verwarmingskring', 8)).toEqual(['Verwarmingskring']);
  });
});

describe('balanceSentence', () => {
  it('says the flows and what the building does with the difference', () => {
    expect(balanceSentence(balance(), tr, 'en')).toBe(
      'Right now the house loses about 2.1\u202fkW to outside; the heat pump delivers 2.4\u202fkW, the sun adds about 300\u202fW and people and appliances add about 300\u202fW, so the building is storing about 900\u202fW.',
    );
  });

  it('says giving back for a negative storage', () => {
    expect(balanceSentence(balance({ storage_w: -600 }), tr, 'en')).toContain(
      'giving back about 600\u202fW',
    );
  });

  it('names unknown flows instead of writing zero', () => {
    const text = balanceSentence(
      balance({ sun_w: null, heat_pump_w: null, loss_w: null, storage_w: null }),
      tr,
      'en',
    );
    expect(text).toContain('the heat loss to outside is not known');
    expect(text).toContain('the heat pump output is not known');
    expect(text).toContain("the sun's share is not known");
    expect(text).toContain('how much heat the building stores is not known');
  });

  it('says that the stove heat is not measured', () => {
    expect(balanceSentence(balance({ stove_active: true, storage_w: null }), tr, 'en')).toContain(
      'the wood stove is burning too',
    );
  });

  it('says the heat pump draws heat during a defrost', () => {
    expect(balanceSentence(balance({ heat_pump_w: -300 }), tr, 'en')).toContain(
      'drawing about 300\u202fW',
    );
  });

  it('speaks Dutch', () => {
    expect(balanceSentence(balance(), (k, p) => translate('nl', k, p), 'nl')).toMatch(
      /^Op dit moment verliest het huis ongeveer 2,1\u202fkW naar buiten; de warmtepomp levert 2,4\u202fkW/,
    );
  });
});
