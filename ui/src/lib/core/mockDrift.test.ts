import { describe, expect, it } from 'vitest';
import { apply, configDoc, initialConfigState } from '$mock/config';
import { initialState, makeAlarms, makeControl, makeDecision } from '$mock/decisions';
import { configAtFor, pumpWaterOf, scenarioDecision, stoveMock, stoveStatus } from '$mock/plugin';
import { parseScenario } from '$mock/scenario';
import { makeDivergence } from '$mock/shadow';
import { makeNotifications } from '$mock/system';
import {
  makeSnapshotState,
  makeTrialStatus,
  releaseHold,
  resumeRelease,
  startRelease,
} from '$mock/trial';

const NOW = Date.parse('2026-11-18T19:00:00Z');
const HOUR = 3_600_000;
const cookie = (value: string) => `ovenbird_mock=${value}`;

interface Check {
  id: string;
  phase: string;
  status: string;
  evidence: Record<string, unknown>;
}

interface Trial {
  mode: string;
  ready: boolean;
  checklist: Check[];
  groups: Record<string, { ready: boolean; ids: string[] }>;
  summary: { source: string; state: string; met: boolean; criteria_met: boolean };
}

const trial = (value: string, key: string, now = NOW, paused = false) =>
  makeTrialStatus(now, parseScenario(cookie(value)), key, paused) as Trial;
const check = (status: Trial, id: string) => status.checklist.find((item) => item.id === id);

describe('mock scenarios agree across endpoints', () => {
  it('builds the notifications item from the notifications status', () => {
    const off = check(trial('notify:off', 'n1'), 'notifications');
    expect(off).toMatchObject({
      status: 'fail',
      evidence: { health: { state: 'not_configured' } },
    });
    expect(off?.evidence['last_test']).toBeUndefined();
    const failing = check(trial('notify:failing', 'n2'), 'notifications');
    const status = makeNotifications(NOW, parseScenario(cookie('notify:failing')), 'n2') as {
      ntfy: { last_test: unknown; last_error: unknown };
      health: unknown;
    };
    expect(failing).toMatchObject({
      status: 'fail',
      evidence: {
        health: status.health,
        last_test: status.ntfy.last_test,
        last_error: status.ntfy.last_error,
      },
    });
    expect(check(trial('', 'n3'), 'notifications')?.status).toBe('ok');
  });

  it('has no go-live snapshot and no met trial in a configured Shadow', () => {
    const shadow = trial('mode:shadow', 's1');
    expect(shadow.summary).toMatchObject({ source: 'default', state: 'no_trial', met: false });
    expect(check(shadow, 'pump_snapshot')?.evidence).toEqual({ snapshot: null });
    expect(makeSnapshotState(NOW, parseScenario(cookie('mode:shadow')), false, 's1')).toMatchObject(
      { snapshot: null, armed: false },
    );
    expect(trial('snapshot:none', 's2').summary.met).toBe(false);
    expect(trial('', 's3').summary).toMatchObject({
      source: 'go_live',
      state: 'running',
      criteria_met: true,
      met: false,
    });
  });

  it('groups the checklist by phase', () => {
    const status = makeTrialStatus(NOW, parseScenario(cookie('envelope:proven')), 'p1', false, {
      installed: true,
      state: 'proven',
      count: 1,
      last: { at: '2026-11-16T16:00:00Z' },
    }) as Trial;
    expect(status.checklist).toHaveLength(10);
    expect(status.groups['trial']?.ids).toEqual(['envelope_proof', 'rollback_rehearsal']);
    expect(check(status, 'envelope_rule')).toMatchObject({ phase: 'go_live', status: 'ok' });
    expect(check(status, 'envelope_proof')?.status).toBe('ok');
    expect(status.ready).toBe(status.groups['go_live']?.ready);
  });

  it('pauses only the releasing browser after a rehearsal until it resumes', () => {
    const scenario = parseScenario(cookie('tag:r1'));
    const started = startRelease('tag:r1', { rehearsal: true }, NOW, scenario, true);
    expect(started.status).toBe(202);
    expect(releaseHold('tag:r1', NOW + 1000)).toBe('releasing');
    expect(resumeRelease('tag:r1', NOW + 1000)?.status).toBe(409);
    const later = NOW + 60_000;
    expect(releaseHold('tag:r1', later)).toBe('paused');
    expect(releaseHold('tag:r2', later)).toBeNull();
    expect(trial('tag:r1', 'tag:r1', later, true).mode).toBe('shadow');
    expect(startRelease('tag:r1', {}, later, scenario, false).status).toBe(409);
    expect(resumeRelease('tag:r1', later)).toBeNull();
    expect(releaseHold('tag:r1', later)).toBeNull();
    expect(makeSnapshotState(later, scenario, true, 'tag:r1')).toMatchObject({ armed: true });
  });

  it('gives a manual stove episode from the scenario its request with an end', () => {
    const doc = configDoc(initialConfigState(NOW), false);
    const stove = stoveMock(parseScenario(cookie('stove:manual')), null, NOW, doc);
    const status = stoveStatus(stove, null, NOW);
    expect(status.request).toMatchObject({ on: true });
    expect(Date.parse(status.request?.until ?? '')).toBe(NOW + 3.5 * HOUR);
  });

  it('ends the divergence series on the live pump value', () => {
    const live = (ms: number) =>
      ms >= NOW - HOUR ? { ovenbird: 30, pump: 32, mode: 'shadow', reason: 'room_feedback' } : null;
    const data = makeDivergence(
      NOW - 6 * HOUR,
      NOW,
      60,
      1,
      NOW,
      parseScenario(cookie('mode:shadow')),
      live,
    ) as { series: { ovenbird: (number | null)[]; pump: (number | null)[] } };
    expect(data.series.ovenbird.at(-1)).toBe(30);
    expect(data.series.pump.at(-1)).toBe(32);
  });

  it('reports the pump water target the latest decision arbitrates', () => {
    const scenario = parseScenario(cookie('mode:shadow'));
    const decisionAt = (ms: number) =>
      scenarioDecision(makeDecision(ms, NOW, 'shadow'), scenario, false, false);
    const water = pumpWaterOf(decisionAt, NOW);
    const latest = decisionAt(NOW);
    if (latest.setpoint !== null) expect(water).toBe(latest.setpoint + 2);
    const control = makeControl(NOW, initialState(), water);
    const monitor = control.safety.monitors.find((m) => m.code === 'setpoint_above_max');
    expect(monitor?.value).toBe(water);
  });

  it('journals as many holds within 12 h as the latched adapter counts', () => {
    const alarms = makeAlarms(NOW, initialState(), null, true);
    const started = alarms.events.filter(
      (event) =>
        event.code === 'command_hold' &&
        event.event === 'started' &&
        Date.parse(event.at) >= NOW - 12 * HOUR,
    );
    expect(started).toHaveLength(3);
    expect(started.at(-1)?.detail).toMatchObject({ latched: true, incident: 3 });
  });

  it('keeps every monitor ok in the default scenario', () => {
    const control = makeControl(NOW, initialState());
    expect(control.safety.monitors.map((m) => m.status)).toEqual(
      control.safety.monitors.map(() => 'ok'),
    );
  });

  it('runs the decisions with the applied comfort target from the next minute', () => {
    const state = initialConfigState(NOW - 1000);
    const result = apply(
      state,
      { base_version: state.version, changes: { control_comfort_c: 22.3 } },
      NOW,
      false,
    );
    expect(result.status).toBe(200);
    const configAt = configAtFor(state);
    const now = makeDecision(NOW, NOW, 'auto', { configAt });
    expect(now.record?.controller_state['room_target_c']).toBe(22.3);
    expect(now.config_version).toBe(state.version);
    const before = makeDecision(NOW - 2 * HOUR, NOW, 'auto', { configAt });
    expect(before.record?.controller_state['room_target_c']).toBe(21.5);
  });
});
