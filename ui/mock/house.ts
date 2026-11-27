import type { Curve } from '../src/lib/core/curve.ts';
import type { ConfigDoc } from '../src/lib/core/types';
import type { Scenario } from './scenario.ts';
import type { MockResult } from './trial.ts';

const DAY = 86_400_000;
const LABEL = 'Suggested by the house model';
const DESIGN_DELTA_K = 30;
const UA = 240.4;
const UA_INTERVAL: [number, number] = [229.8, 251.3];
const BALANCE_C = 16.5;
const COMFORT_C = 21.0;
const DEFAULT_CURVE: Curve = [
  [-10, 39],
  [0, 34],
  [15, 25],
];
const BANDS: [string, number | null][] = [
  ['A', 30],
  ['B', 45],
  ['C', 60],
  ['D', 80],
  ['E', 100],
  ['F', 125],
  ['G', null],
];
const NOTE =
  'Indicative: heat loss per m2 at 20 degC inside and -10 degC outside from the apparent heat-loss coefficient (ventilation included). Not the official energielabel.';
const COLDEST_DATA_C = -3;

const iso = (ms: number) => new Date(ms).toISOString();
const day = (ms: number) => iso(ms).slice(0, 10);
const round = (value: number, digits = 1) => Math.round(value * 10 ** digits) / 10 ** digits;
const noise = (i: number) => Math.sin(i * 12.9898) * 0.5 + Math.sin(i * 4.1414) * 0.5;

function bandOf(wPerM2: number): string {
  for (const [letter, limit] of BANDS) if (limit === null || wPerM2 < limit) return letter;
  return 'G';
}

function modelName(ms: number, suffix = ''): string {
  return `house-${day(ms).replace(/-/g, '')}${suffix}`;
}

function floorArea(doc: ConfigDoc, scenario: Scenario): number | null {
  if (scenario.house === 'noarea') return null;
  const value = doc.fields['house_floor_area_m2']?.value;
  return typeof value === 'number' && value > 0 ? value : null;
}

/**
 * The insulation score as the service computes it from UA and the floor area.
 */
export function houseScore(
  ua: number,
  interval: [number, number] | null,
  area: number | null,
  credible: boolean,
  message: string | null = null,
): Record<string, unknown> {
  const out: Record<string, unknown> = {
    design_indoor_c: 20,
    design_outside_c: -10,
    floor_area_m2: area,
    bands: BANDS.map(([band, below]) => ({ band, below_w_per_m2: below })),
    indicative: true,
    note: NOTE,
  };
  if (!credible) return { ...out, state: 'learning', message: message ?? 'insufficient data' };
  if (area === null)
    return {
      ...out,
      state: 'no_floor_area',
      heat_loss_w: Math.round(ua * DESIGN_DELTA_K),
      message: 'set the heated floor area (house_floor_area_m2) to get W/m2 and a band',
    };
  const perM2 = (ua * DESIGN_DELTA_K) / area;
  const result: Record<string, unknown> = {
    ...out,
    state: 'ready',
    heat_loss_w: Math.round(ua * DESIGN_DELTA_K),
    w_per_m2: round(perM2),
    band: bandOf(perM2),
  };
  if (interval) {
    const [lo, hi] = interval.map((v) => (v * DESIGN_DELTA_K) / area) as [number, number];
    result['interval_90'] = [round(lo), round(hi)];
    result['band_interval'] = [bandOf(lo), bandOf(hi)];
  }
  return result;
}

function currentCurve(doc: ConfigDoc): Curve {
  const value = doc.fields['control_curve']?.value;
  return Array.isArray(value) ? (value as Curve) : DEFAULT_CURVE;
}

function numberField(doc: ConfigDoc, id: string, fallback: number): number {
  const value = doc.fields[id]?.value;
  return typeof value === 'number' ? value : fallback;
}

function proposal(doc: ConfigDoc, credible: boolean): Record<string, unknown> {
  const curve = currentCurve(doc);
  const maxSupply = numberField(doc, 'control_max_supply_c', 40);
  const minSetpoint = numberField(doc, 'control_min_setpoint_c', 24);
  const points = curve.map(([outside, current]) => {
    const model = 25 + 0.62 * (BALANCE_C - outside);
    let water = Math.round(model * 2) / 2;
    let limited: string | null = null;
    if (water > maxSupply) {
      water = maxSupply;
      limited = 'max_supply';
    } else if (water < minSetpoint) {
      water = minSetpoint;
      limited = 'min_setpoint';
    }
    return {
      outside_c: outside,
      model_c: round(model, 2),
      current_c: current,
      heat_w: Math.max(0, Math.round(UA * (BALANCE_C - outside))),
      extrapolated: outside < COLDEST_DATA_C,
      water_c: water,
      change_k: round(water - current),
      limited_by: limited,
    };
  });
  const changes = points.map((p) => Math.abs(p.change_k));
  return {
    comfort_c: numberField(doc, 'control_comfort_c', COMFORT_C),
    flow_lpm: 25.9,
    credible,
    stale: false,
    based_on_curve: curve,
    current_curve: curve,
    curve: points.map((p) => [p.outside_c, p.water_c]),
    points,
    mean_change_k: round(changes.reduce((a, b) => a + b, 0) / Math.max(changes.length, 1), 2),
    max_change_k: round(Math.max(0, ...changes), 2),
    method:
      'water temperature that holds the comfort target in the fitted plant at each curve point',
  };
}

function signature(now: number, cold: boolean): Record<string, unknown>[] {
  const points: Record<string, unknown>[] = [];
  for (let i = 0; i < 40; i += 1) {
    const at = now - (41 - i) * DAY;
    const trend = 12.5 - (i / 39) * (cold ? 14 : 9);
    const outside = round(trend + noise(i) * 2.2, 2);
    const ghi = round(Math.max(15, 110 - i * 2 + noise(i + 3) * 30), 1);
    const heat = Math.max(0, UA * (BALANCE_C - outside) - ghi * 2.4 + 140 + noise(i + 7) * 160);
    points.push({
      date: day(at),
      outside_c: outside,
      heat_w: round(heat),
      indoor_c: round(21.0 + noise(i + 11) * 0.3, 2),
      ghi_w_m2: ghi,
    });
  }
  return points;
}

const LEARNER_INTERVAL_H = 168;
const HOUR = 3_600_000;

/**
 * One wood-stove period as the learner reports it (`ovenbird_sim.data.events.Event.to_json`).
 */
function stoveEvent(startMs: number): Record<string, unknown> {
  const local = (ms: number) => `${iso(ms).slice(0, 16)}+00:00`;
  return {
    kind: 'stove',
    start_local: local(startMs),
    end_local: local(startMs + 5 * HOUR),
    tail_end_local: local(startMs + 17 * HOUR),
    hours: 5,
    excluded_hours: 17,
    peak_k: 3.4,
    rise_k_per_h: 2.6,
    utc_days: [day(startMs), day(startMs + 17 * HOUR)],
    reason:
      'wood stove: living room 3.4 K above its usual excess over hall and bedroom, rising 2.6 K/h; the model has no stove heat',
  };
}

/**
 * The `learner` block: when the learner last ran and whether that is too long ago (twice its
 * interval).
 */
function learner(now: number, runAt: number | null): Record<string, unknown> {
  const age = runAt === null ? null : Math.round(((now - runAt) / 3_600_000) * 10) / 10;
  return {
    last_run_at: runAt === null ? null : iso(runAt),
    age_h: age,
    interval_h: LEARNER_INTERVAL_H,
    stale_after_h: 2 * LEARNER_INTERVAL_H,
    stale: age !== null && age > 2 * LEARNER_INTERVAL_H,
  };
}

/**
 * `GET insight/house`: a ready, credible champion by default; see the `house` scenario key. Always
 * `200`, also while no model has been promoted (`state` `not_run` or `learning`).
 */
export function makeHouse(now: number, scenario: Scenario, doc: ConfigDoc): MockResult {
  const runAt = now - 2 * 3_600_000;
  if (scenario.house === 'notrun')
    return {
      status: 200,
      body: {
        state: 'not_run',
        missing: [
          'the house model learner has not run yet; it refits weekly by default, in the service or in a separate learner container (docs/design.md, House insight)',
        ],
        last_run: null,
        learner: learner(now, null),
      },
    };
  if (scenario.house === 'learning')
    return {
      status: 200,
      body: {
        state: 'learning',
        missing: ['9 more days of 1 min history (have 13.0, the fit needs 22)'],
        last_run: {
          at: iso(runAt),
          outcome: 'learning',
          missing: ['9 more days of 1 min history (have 13.0, the fit needs 22)'],
          runtime_s: 1.4,
        },
        learner: learner(now, runAt),
      },
    };
  const credible = scenario.house !== 'uncredible';
  const points = signature(now, credible);
  const coldDays = points.filter((p) => (p['outside_c'] as number) < 5).length;
  const shownCold = credible ? Math.max(coldDays, 12) : 6;
  const message = credible
    ? null
    : 'insufficient data: 4 more cold days (daily mean below 5 °C) needed';
  const model = modelName(now - DAY);
  const dataTo = now - DAY;
  const area = floorArea(doc, scenario);
  return {
    status: 200,
    body: {
      state: 'ready',
      schema: 'ovenbird.house-insight/1',
      model,
      champion: { model, promoted_at: iso(runAt) },
      last_run: {
        at: iso(runAt),
        outcome: 'promoted',
        model,
        champion: model,
        message: null,
        runtime_s: 275.7,
        interval_h: LEARNER_INTERVAL_H,
      },
      learner: learner(now, runAt),
      data: {
        from: iso(now - 42 * DAY),
        to: iso(dataTo),
        fit_days: 40.7,
        signature_days: points.length,
        excluded_days: [day(now - 4 * DAY)],
      },
      ua: {
        w_per_k: UA,
        interval_90: UA_INTERVAL,
        source: 'rc_model',
        signature_w_per_k: 236.1,
        signature_interval_90: [221.0, 252.6],
        low_confidence: false,
      },
      time_constant_h: { value: 52.6, interval_90: [48.9, 56.4] },
      solar_aperture_m2: { value: 6.2, interval_90: [5.4, 7.1] },
      internal_gains_w: { value: 318, interval_90: [262, 381] },
      balance_temperature_c: { value: BALANCE_C, interval_90: [16.0, 17.1] },
      signature: {
        indoor: 'house_mean',
        points,
        fit: {
          h_w_per_k: 236.1,
          h_interval_90: [221.0, 252.6],
          gains_w: 341.3,
          solar_m2: 6.0,
          balance_c: BALANCE_C,
          balance_interval_90: [16.0, 17.1],
          rmse_w: 207.2,
          mean_indoor_c: 21.06,
          mean_ghi_w_m2: 76.2,
          model: 'change-point regression',
        },
      },
      credibility: {
        credible,
        days: points.length,
        heating_days: points.length - 1,
        cold_days: shownCold,
        outside_span_k: credible ? 16.2 : 13.4,
        rules: {
          heating_days: 30,
          heating_day_w: 300,
          cold_days: 10,
          cold_day_below_c: 5,
          outside_span_k: 10,
        },
        needed: { heating_days: 0, cold_days: credible ? 0 : 4, outside_span_k: 0 },
        reasons: credible ? [] : ['6 days below 5 degC < 10'],
        low_confidence: false,
        message,
      },
      score: houseScore(UA, UA_INTERVAL, area, credible, message),
      validation: {
        test_from: iso(now - 15 * DAY),
        test_to: iso(now - DAY),
        score_horizon_h: 24,
        challenger_room_rmse_k: 0.093,
        champion_room_rmse_k: 0.101,
        champion: modelName(now - 8 * DAY),
        promoted: true,
        rule: 'challenger 0.093 K <= champion 0.101 K',
      },
      error_trend: history(now, area, credible).map((entry) => ({
        model: entry['model'],
        data_to: entry['data_to'],
        promoted: true,
        ua_w_per_k: entry['ua_w_per_k'],
        room_rmse_24h_k: entry['room_rmse_24h_k'],
      })),
      daily_error: Array.from({ length: 14 }, (_, i) => ({
        date: day(now - (15 - i) * DAY),
        room_rmse_24h_k: round(0.09 + noise(i) * 0.02, 3),
        origins: 9,
      })),
      proposal: proposal(doc, credible),
      events: [stoveEvent(now - 4 * DAY)],
      limits: [
        'single room sensor: the UA is apparent (ventilation and the other rooms are in it)',
        'solar aperture from global horizontal irradiance only (no orientation)',
        'no data below -3 °C: the proposal at colder points is extrapolated',
      ],
      provenance: {
        data_from: iso(now - 42 * DAY),
        data_to: iso(dataTo),
        fit_days: 40.7,
        step_s: 60,
        config_hash: '35767f480b5ce141',
        code_version: '0.4.1',
        method: 'building_only',
        fallback_reason: null,
        seed: 0,
        bootstrap: 20,
        folds: 2,
        generated: iso(runAt),
      },
    },
  };
}

function history(now: number, area: number | null, credible: boolean): Record<string, unknown>[] {
  const runs: [number, number, [number, number], number, number, boolean][] = [
    [15, 252.2, [236.0, 270.4], 121.0, 0.112, false],
    [8, 246.8, [233.5, 260.9], 119.6, 0.101, credible],
    [1, UA, UA_INTERVAL, 52.6, 0.093, credible],
  ];
  return runs.map(([ago, ua, interval, tau, rmse, ok], index) => ({
    model: modelName(now - ago * DAY),
    data_to: iso(now - ago * DAY),
    generated: iso(now - ago * DAY + 2 * 3_600_000),
    champion: index === runs.length - 1,
    ua_w_per_k: ua,
    ua_interval_90: interval,
    time_constant_h: tau,
    credible: ok,
    room_rmse_24h_k: rmse,
    score: houseScore(ua, interval, area, ok),
  }));
}

/**
 * `GET insight/house/history`: one entry per promoted model, oldest first.
 */
export function makeHouseHistory(now: number, scenario: Scenario, doc: ConfigDoc): MockResult {
  const area = floorArea(doc, scenario);
  if (scenario.house === 'learning' || scenario.house === 'notrun')
    return { status: 200, body: { floor_area_m2: area, models: [] } };
  return {
    status: 200,
    body: { floor_area_m2: area, models: history(now, area, scenario.house !== 'uncredible') },
  };
}

/**
 * `POST insight/house/proposal/draft`: the champion's proposal as a configuration draft.
 */
export function makeProposalDraft(now: number, scenario: Scenario, doc: ConfigDoc): MockResult {
  if (scenario.house === 'learning' || scenario.house === 'notrun')
    return { status: 404, body: { detail: 'no house model has been promoted yet' } };
  const model = modelName(now - DAY);
  const suggestion = proposal(doc, scenario.house !== 'uncredible');
  return {
    status: 200,
    body: {
      label: LABEL,
      model,
      comment: `${LABEL} (${model})`,
      changes: { control_curve: suggestion['curve'] },
      current: { control_curve: currentCurve(doc) },
      stale: false,
      credible: suggestion['credible'],
      points: suggestion['points'],
      validation: null,
    },
  };
}

export const RUN_MS = 4_000;

/**
 * The mock learner of one scenario cookie: when the last manual run started (it finishes
 * `RUN_MS` later, after which the run endpoint answers a fresh `last`).
 */
export interface RunMockState {
  startedAt: number;
}

interface RunLast {
  at: string;
  outcome: string;
  message: string | null;
  runtime_s: number | null;
  model: string | null;
}

function baselineLast(now: number, scenario: Scenario): RunLast | null {
  const at = iso(now - 2 * HOUR);
  if (scenario.house === 'notrun') return null;
  if (scenario.learner === 'failed')
    return {
      at: iso(now - 3 * HOUR),
      outcome: 'failed',
      message: 'the learner stopped after 1800 s',
      runtime_s: 1800,
      model: null,
    };
  if (scenario.house === 'learning')
    return {
      at,
      outcome: 'learning',
      message: '9 more days of 1 min history (have 13.0, the fit needs 22)',
      runtime_s: 1.4,
      model: null,
    };
  const model = modelName(now - DAY);
  return {
    at,
    outcome: 'promoted',
    message: null,
    runtime_s: 275.7,
    model,
  };
}

function runningAt(
  now: number,
  scenario: Scenario,
  state: RunMockState | undefined,
): number | null {
  if (scenario.learner === 'running') return now - 90_000;
  if (state && now >= state.startedAt && now < state.startedAt + RUN_MS) return state.startedAt;
  return null;
}

/**
 * `GET insight/house/run`: the embedded learner's state, per scenario (`learner` key) and per
 * scenario cookie after a manual run (`state`).
 */
export function makeRun(
  now: number,
  scenario: Scenario,
  state: RunMockState | undefined,
): MockResult {
  const base = { enabled: scenario.learner !== 'disabled', interval_h: LEARNER_INTERVAL_H };
  if (scenario.learner === 'unavailable')
    return {
      status: 200,
      body: {
        ...base,
        state: 'unavailable',
        started_at: null,
        next_due_at: null,
        last: null,
        failure: null,
      },
    };
  const startedAt = runningAt(now, scenario, state);
  const finished =
    state && startedAt === null && now >= state.startedAt + RUN_MS
      ? ({
          at: iso(state.startedAt + RUN_MS),
          outcome: scenario.house === 'learning' ? 'learning' : 'kept_champion',
          message:
            scenario.house === 'learning'
              ? '9 more days of 1 min history (have 13.0, the fit needs 22)'
              : null,
          runtime_s: RUN_MS / 1000,
          model: null,
        } satisfies RunLast)
      : null;
  const last = finished ?? baselineLast(now, scenario);
  const failure =
    scenario.learner === 'failed' && finished === null
      ? { at: iso(now - 3 * HOUR), reason: 'timeout', detail: 'stopped after 1800 s' }
      : null;
  const next =
    scenario.learner === 'disabled'
      ? null
      : last === null
        ? iso(now + 20 * 60_000)
        : iso(Date.parse(last.at) + LEARNER_INTERVAL_H * HOUR);
  return {
    status: 200,
    body: {
      ...base,
      state: startedAt === null ? 'idle' : 'running',
      started_at: startedAt === null ? null : iso(startedAt),
      next_due_at: startedAt === null ? next : null,
      last,
      failure,
    },
  };
}

function refusal(code: string, message: string): MockResult {
  return { status: 409, body: { detail: { code, message, params: {} } } };
}

/**
 * `POST insight/house/run`: `202` with the running state; `409` `learner_running` or
 * `learner_unavailable`; `403` for a read-only login. The new state is `started` when a run began.
 */
export function startRunMock(
  now: number,
  scenario: Scenario,
  state: RunMockState | undefined,
): { result: MockResult; started: RunMockState | null } {
  if (scenario.role === 'viewer')
    return {
      result: { status: 403, body: { detail: 'this action needs the operate role' } },
      started: null,
    };
  if (scenario.learner === 'unavailable')
    return {
      result: refusal('learner_unavailable', 'this install has no built-in learner'),
      started: null,
    };
  if (runningAt(now, scenario, state) !== null)
    return { result: refusal('learner_running', 'a learner run is already going'), started: null };
  const started = { startedAt: now };
  const running = makeRun(now, scenario, started);
  return { result: { status: 202, body: running.body }, started };
}
