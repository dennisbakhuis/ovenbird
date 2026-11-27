import { describe, expect, it } from 'vitest';
import { initialConfigState, configDoc, validate } from '$mock/config';
import { appliedPlanK, makeHouseControl } from '$mock/house';
import { parseScenario } from '$mock/scenario';
import type { HouseControl } from './shapes';
import { summarisePlan } from './plan';

const NOW = Date.parse('2026-11-27T14:07:00');
const doc = configDoc(initialConfigState(NOW), false);
const control = (cookie: string) => {
  const result = makeHouseControl(NOW, parseScenario(`ovenbird_mock=${cookie}`), doc);
  return { status: result.status, body: result.body as HouseControl };
};

describe('the mock of insight/house/control', () => {
  it('is off by default, computes nothing and has no evaluation', () => {
    const { body } = control('');
    expect(body.use).toBe('off');
    expect(body.now).toBeNull();
    expect(body.history.points).toEqual([]);
    expect(summarisePlan(body.history).evaluated).toBe(0);
    expect(body.bounds).toEqual({
      max_setback_k: 0.5,
      max_preheat_k: 0.3,
      horizon_h: 6,
      max_rmse_k: 0.6,
    });
  });

  it('issues a set-back in shadow that matches the latest history point', () => {
    const { body } = control('modelplan:shadow');
    expect(body.use).toBe('shadow');
    expect(body.now).toMatchObject({ status: 'issued', offset_k: -0.3, applied: false });
    const last = body.history.points[body.history.points.length - 1];
    expect(last).toEqual([body.now?.at, -0.3, 0]);
    expect(body.history.points).toHaveLength(7 * 96 + 1);
    expect(body.history.points.some(([, offset]) => offset === null)).toBe(true);
    expect(body.history.points.every(([, , applied]) => applied !== 1)).toBe(true);
  });

  it('stays inside the dead zone', () => {
    const { body } = control('modelplan:dead');
    expect(body.now).toMatchObject({ status: 'inside_dead_zone', offset_k: 0, reason: null });
  });

  it('is blocked with two reasons and keeps the evaluation from before', () => {
    const { body } = control('modelplan:blocked');
    expect(body.verdict).toEqual({ ok: false, blocks: ['model_not_credible', 'stove_tail'] });
    expect(body.now?.applied).toBe(false);
    expect(Date.parse(body.now?.at ?? '')).toBeLessThan(NOW - 3 * 3_600_000);
  });

  it('applies the shift when on, for the last three days only', () => {
    const { body } = control('modelplan:on');
    expect(body.use).toBe('on');
    expect(body.now?.applied).toBe(true);
    const applied = body.history.points.filter(([, , flag]) => flag === 1).length;
    const computed = body.history.points.filter(([, , flag]) => flag !== null).length;
    expect(applied).toBeGreaterThan(0);
    expect(applied).toBeLessThan(computed);
    expect(appliedPlanK(parseScenario('ovenbird_mock=modelplan:on'), doc)).toBe(-0.3);
    expect(appliedPlanK(parseScenario('ovenbird_mock=modelplan:shadow'), doc)).toBe(0);
  });

  it('answers 404 like an older service', () => {
    expect(control('modelplan:missing').status).toBe(404);
  });

  it('keeps every shift inside the bounds', () => {
    const { body } = control('modelplan:shadow');
    for (const [, offset] of body.history.points)
      if (offset !== null) {
        expect(offset).toBeGreaterThanOrEqual(-body.bounds.max_setback_k);
        expect(offset).toBeLessThanOrEqual(body.bounds.max_preheat_k);
      }
  });
});

describe('the mock configuration check of control_model_use', () => {
  it('refuses on with model_use_on_locked and accepts shadow', () => {
    const state = initialConfigState(NOW);
    const refused = validate(state, { control_model_use: 'on' });
    expect(refused.errors.map((e) => e.code)).toEqual(['model_use_on_locked']);
    expect(refused.errors[0]?.field).toBe('control_model_use');
    expect(validate(state, { control_model_use: 'shadow' }).valid).toBe(true);
  });
});
