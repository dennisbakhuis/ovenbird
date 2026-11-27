import { describe, expect, it } from 'vitest';
import type { HouseWhatIf } from './shapes';
import {
  WHATIF_DEFAULTS,
  driftSummary,
  isLimitedBy,
  parseWhatIfQuery,
  whatIfPath,
  whatIfQuery,
} from './whatif';

describe('parseWhatIfQuery', () => {
  it('takes the defaults without a query', () => {
    expect(parseWhatIfQuery({})).toEqual(WHATIF_DEFAULTS);
  });

  it('reads the four values', () => {
    expect(
      parseWhatIfQuery({ outside: '-3.5', comfort: '20.5', sun: '150', stove: '2000' }),
    ).toEqual({ outside_c: -3.5, comfort_c: 20.5, sun_wm2: 150, stove_w: 2000 });
  });

  it('clamps to the ranges and ignores what is not a number', () => {
    expect(parseWhatIfQuery({ outside: '99', comfort: '1', sun: '-5', stove: 'lots' })).toEqual({
      outside_c: 30,
      comfort_c: 5,
      sun_wm2: 0,
      stove_w: 0,
    });
  });

  it('uses the given defaults, such as the installation comfort', () => {
    expect(parseWhatIfQuery({}, { ...WHATIF_DEFAULTS, comfort_c: 21.4 }).comfort_c).toBe(21.4);
  });
});

describe('whatIfQuery', () => {
  it('keeps only what differs from the defaults and round-trips', () => {
    const inputs = { outside_c: -2, comfort_c: 21, sun_wm2: 150, stove_w: 0 };
    const query = whatIfQuery(inputs);
    expect(query).toEqual({ outside: '-2', sun: '150' });
    expect(parseWhatIfQuery(query)).toEqual(inputs);
    expect(whatIfQuery(WHATIF_DEFAULTS)).toEqual({});
  });
});

describe('whatIfPath', () => {
  it('sends all four inputs', () => {
    expect(whatIfPath({ outside_c: -2, comfort_c: 21.5, sun_wm2: 0, stove_w: 5000 })).toBe(
      'api/v1/insight/house/whatif?outside_c=-2&comfort_c=21.5&sun_wm2=0&stove_w=5000',
    );
  });
});

describe('drift and limits', () => {
  const result = {
    limited_by: ['max_supply'],
    drift: { hours: 8, step_s: 900, room_c: [21, 20.5, 19.8] },
  } as unknown as HouseWhatIf;

  it('summarises the drift', () => {
    expect(driftSummary(result)).toMatchObject({ startC: 21, endC: 19.8, minC: 19.8, hours: 8 });
    expect(driftSummary({ ...result, drift: { ...result.drift, room_c: [] } })).toBeNull();
  });

  it('tells what limited the answer', () => {
    expect(isLimitedBy(result, 'max_supply')).toBe(true);
    expect(isLimitedBy(result, 'no_heat_needed')).toBe(false);
  });
});
