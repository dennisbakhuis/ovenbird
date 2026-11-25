import { describe, expect, it } from 'vitest';
import { buildRecord } from '$mock/decisions';
import recorded from '$mock/fixtures/decisions-sim.json';
import type { Decision, DecisionRecord } from '$lib/core/types';
import { buildWaterfall, reportedTarget } from './waterfall';

const scenarioMinute = (minuteOfCycle: number) => (minuteOfCycle + 360 * 4000) * 60_000;

function termSum(record: DecisionRecord): number {
  return record.terms
    .filter((term) => term.name !== 'safety')
    .reduce((sum, term) => sum + term.value, 0);
}

describe('buildWaterfall', () => {
  it('adds up to safety.raw on every recorded decision', () => {
    const decisions = recorded.decisions as unknown as Decision[];
    expect(decisions.length).toBeGreaterThan(40);
    for (const decision of decisions) {
      const model = buildWaterfall(decision.record, reportedTarget(decision));
      expect(model.kind).toBe('bars');
      expect(model.balanced).toBe(true);
      expect(model.sum).toBeCloseTo(model.safetyRaw ?? Number.NaN, 9);
      expect(model.sum).toBeCloseTo(termSum(decision.record), 9);
    }
  });

  it('lays out the recorded pipeline in order with collapsed zero terms', () => {
    const decision = (recorded.decisions as unknown as Decision[])[0] as Decision;
    const model = buildWaterfall(decision.record, reportedTarget(decision));
    expect(model.rows.map((row) => row.id)).toEqual([
      'curve',
      'room_feedback',
      'sum',
      'safety',
      'stage',
      'issued',
      'reported',
    ]);
    expect(model.collapsed).toEqual(['plan', 'start_ramp', 'cycling_floor']);
    const issued = model.rows.find((row) => row.id === 'issued');
    expect(issued?.end).toBe(decision.setpoint);
    expect(model.allowed).toEqual({
      low: decision.record.controller_state['safety_low_c'],
      high: decision.record.controller_state['safety_high_c'],
    });
  });

  it('keeps all rows inside the axis', () => {
    for (const minute of [10, 70, 110, 210, 255, 285, 345]) {
      const { record } = buildRecord(scenarioMinute(minute));
      const model = buildWaterfall(record, record.setpoint);
      for (const row of model.rows) {
        expect(row.start).toBeGreaterThanOrEqual(model.axis.min);
        expect(row.end).toBeLessThanOrEqual(model.axis.max);
      }
    }
  });

  it('shows the safety clamp as a step from raw to applied', () => {
    const { record, scenario } = buildRecord(scenarioMinute(210));
    expect(scenario).toBe('clamp_high');
    const model = buildWaterfall(record);
    expect(model.balanced).toBe(true);
    const clamp = model.rows.find((row) => row.kind === 'clamp');
    expect(clamp?.limited).toBe(true);
    expect(clamp?.delta).toBeLessThan(0);
    expect(clamp?.start).toBeCloseTo(model.safetyRaw ?? Number.NaN, 9);
    expect(clamp?.binding).toBe('envelope_max');
    const feedback = model.rows.find((row) => row.id === 'room_feedback');
    expect(feedback?.limited).toBe(true);
    expect(feedback?.raw).toBeGreaterThan(feedback?.delta ?? 0);
  });

  it('includes the start ramp as a negative step', () => {
    const { record, scenario } = buildRecord(scenarioMinute(5));
    expect(scenario).toBe('ramp');
    const model = buildWaterfall(record);
    const ramp = model.rows.find((row) => row.id === 'start_ramp');
    expect(ramp?.delta).toBeLessThan(0);
    expect(model.balanced).toBe(true);
    expect(model.collapsed).not.toContain('start_ramp');
  });

  it('includes cycling protection as a positive step with its binding', () => {
    const { record, scenario } = buildRecord(scenarioMinute(110));
    expect(scenario).toBe('cycling');
    const model = buildWaterfall(record);
    expect(model.rows.find((row) => row.id === 'cycling_floor')?.delta).toBeCloseTo(0.8, 9);
    expect(model.balanced).toBe(true);
    expect(record.binding).toBe('cycling_floor');
  });

  it('includes an override step that lands on the override value', () => {
    const { record, scenario } = buildRecord(scenarioMinute(345));
    expect(scenario).toBe('override');
    const model = buildWaterfall(record);
    expect(model.balanced).toBe(true);
    expect(model.sum).toBeCloseTo(33, 9);
    expect(model.rows.some((row) => row.id === 'override')).toBe(true);
  });

  it('labels the rounding stage with its binding', () => {
    const { record, scenario } = buildRecord(scenarioMinute(70));
    expect(scenario).toBe('dwell');
    const stage = buildWaterfall(record).rows.find((row) => row.kind === 'stage');
    expect(stage?.binding).toBe('dwell');
    expect(stage?.delta).toBeLessThan(0);
  });

  it('returns a reason-only model for hold and refuse decisions', () => {
    const hold = buildRecord(scenarioMinute(301));
    expect(hold.record.ladder).toBe('hold');
    const heldModel = buildWaterfall(hold.record);
    expect(heldModel.kind).toBe('reason');
    expect(heldModel.rows).toEqual([]);
    expect(heldModel.setpoint).toBe(30);

    const refuse = buildRecord(scenarioMinute(331));
    expect(refuse.record.ladder).toBe('refuse');
    const refusedModel = buildWaterfall(refuse.record);
    expect(refusedModel.kind).toBe('reason');
    expect(refusedModel.setpoint).toBeNull();
  });

  it('sums to safety.raw across a full synthetic cycle', () => {
    for (let minute = 0; minute < 360; minute += 1) {
      const { record } = buildRecord(scenarioMinute(minute));
      const model = buildWaterfall(record);
      if (model.kind === 'bars') expect(model.balanced).toBe(true);
    }
  });
});
