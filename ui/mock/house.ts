import type { Curve } from '../src/lib/core/curve.ts';
import type { ConfigDoc } from '../src/lib/core/types';
import { outsideAt, roomAt } from './decisions.ts';
import type { Scenario } from './scenario.ts';
import type { MockResult } from './trial.ts';

const DAY = 86_400_000;
const LABEL = 'Suggested by the house model';
const DESIGN_DELTA_K = 30;
const UA = 240.4;
const UA_BOOTSTRAP: [number, number] = [229.8, 251.3];
const UA_FOLDS: number[] = [224.9, 238.6];
const UA_INTERVAL: [number, number] = [224.9, 251.3];
const CAPACITIES = { loop: 0.35, emitter: 1.25, building: 6.15 };
const EMITTER_TIME_CONSTANT_H = 0.6;
const GAINS_COUPLING_W_PER_K_PER_100_W = 9.0;
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

const SOLAR_APERTURE_M2 = 6.2;
const INTERNAL_W = 318;
const TIME_CONSTANT_H = 52.6;
const TOLD = { ua_w_per_k: 340, solar_aperture_m2: 5.0, internal_gain_w: 300 };
const EMITTER_W_PER_K = 410;
const DELTA_T_K = 5;

const PIN_UA = 300;

type House = NonNullable<Scenario['house']>;
const HEAT_LOSS_FAILS: readonly House[] = ['uncredible', 'not-excited'];

type GateName = 'heat_loss' | 'dynamics' | 'sun';
type GateNeedCode =
  | 'no_signature'
  | 'more_heating_days'
  | 'more_outside_spread'
  | 'no_dynamics_skill'
  | 'more_sunny_days'
  | 'legacy_model';

interface GateState {
  ok: boolean;
  needed: GateNeedCode[];
  source: 'fitted' | 'revalidated' | 'legacy';
}

/**
 * The three gates of the champion of a scenario: all pass by default; `uncredible` and
 * `not-excited` fail the heat-loss gate, `no-skill` the dynamics gate (a re-validated kept
 * champion), `no-sun` the sun gate and `legacy` is a model made before the gates.
 */
export function houseGates(scenario: Scenario): Record<GateName, GateState> {
  const house = scenario.house;
  const source = house === 'no-skill' ? 'revalidated' : house === 'legacy' ? 'legacy' : 'fitted';
  const heatLoss: GateNeedCode[] =
    house === 'uncredible'
      ? ['no_signature', 'more_heating_days', 'more_outside_spread']
      : house === 'not-excited'
        ? ['more_heating_days', 'more_outside_spread']
        : [];
  const dynamics: GateNeedCode[] = house === 'no-skill' ? ['no_dynamics_skill'] : [];
  const sun: GateNeedCode[] =
    house === 'no-sun' ? ['more_sunny_days'] : house === 'legacy' ? ['legacy_model'] : [];
  return {
    heat_loss: { ok: heatLoss.length === 0, needed: heatLoss, source },
    dynamics: { ok: dynamics.length === 0, needed: dynamics, source },
    sun: { ok: sun.length === 0, needed: sun, source },
  };
}

/**
 * Whether the heat-loss gate of the model of a scenario passes (`credible` of the insight, the
 * balance, the proposal and the what-if steady state).
 */
export function houseCredible(scenario: Scenario): boolean {
  return !(scenario.house && HEAT_LOSS_FAILS.includes(scenario.house));
}

/**
 * Whether the dynamics gate passes (`drift.credible` of the what-if).
 */
export function houseDynamicsCredible(scenario: Scenario): boolean {
  return houseGates(scenario).dynamics.ok;
}

const GATE_MESSAGES: Record<GateNeedCode, string> = {
  no_signature: 'the energy signature shows no clear heating pattern',
  more_heating_days: 'more heating days are needed',
  more_outside_spread: 'more spread in outside temperature is needed',
  no_dynamics_skill: "the model does not predict the room better than 'no change'",
  more_sunny_days: "2 more sunny days needed to check the model's sun response",
  legacy_model: 'model made before the gates; the next run judges it',
};

function gateMessage(state: GateState): string | null {
  return state.ok ? null : state.needed.map((code) => GATE_MESSAGES[code]).join('; ');
}

function modelGates(scenario: Scenario): Record<string, unknown> {
  const gates = houseGates(scenario);
  return Object.fromEntries(
    (Object.keys(gates) as GateName[]).map((name) => [
      name,
      {
        ok: gates[name].ok,
        needed: gates[name].needed,
        message: gateMessage(gates[name]),
        source: gates[name].source,
      },
    ]),
  );
}

/**
 * The gates as the learner wrote them (`credibility.gates`, `champion_revalidation.gates`): the
 * checks with value and limit, the need codes and what each gate guards.
 */
function learnedGates(
  scenario: Scenario,
  shortfall: { heating_days: number; outside_span_k: number },
  detailed = false,
) {
  const gates = houseGates(scenario);
  const fails = (name: GateName, code: GateNeedCode) => gates[name].needed.includes(code);
  const check = (ok: boolean, value: number, limit: number, extra = {}) => ({
    ok,
    value,
    limit,
    ...extra,
  });
  const entry = (name: GateName, uses: string[], checks: Record<string, unknown>, extra = {}) => ({
    ok: gates[name].ok,
    uses,
    checks,
    needed: gates[name].needed,
    reasons: gates[name].needed.map((code) => GATE_MESSAGES[code]),
    message: gateMessage(gates[name]),
    ...extra,
  });
  return {
    heat_loss: entry(
      'heat_loss',
      ['insulation_score', 'curve_proposal', 'whatif_steady_state', 'balance'],
      {
        signature: check(!fails('heat_loss', 'no_signature'), 37, 30),
        excitation: check(
          !fails('heat_loss', 'more_heating_days') && !fails('heat_loss', 'more_outside_spread'),
          20 - shortfall.heating_days,
          20,
        ),
        ua_interval: check(true, 0.11, 0.3),
        ua_agreement: check(true, 0.02, 0.2),
        ua_stability: check(true, 0.05, 0.15, { folds: 2, fold_ua_w_per_k: UA_FOLDS }),
      },
      detailed ? { shortfall } : {},
    ),
    dynamics: entry(
      'dynamics',
      ['whatif_cooldown', 'room_target_planner'],
      { skill_6h: check(gates.dynamics.ok, gates.dynamics.ok ? 0.21 : -0.06, 0) },
      detailed
        ? { diagnostics: { skill_24h: -0.02, note: 'a house held flat is hard to out-predict' } }
        : {},
    ),
    sun: entry('sun', ['water_planner'], {
      sunny_days: check(
        !fails('sun', 'more_sunny_days'),
        fails('sun', 'more_sunny_days') ? 3 : 7,
        5,
      ),
      sun_skill: check(true, 0.12, 0),
      sun_response: check(true, 1.05, 1.5, { interval: [0.8, 1.3], origins: 18 }),
    }),
  };
}

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

const SERIES_STEP_S = 900;
const STOVE_AGO_DAYS = 4;
const LEFT_OUT_AGO_DAYS = 9;

interface SeriesEventRow {
  kind: 'stove' | 'stove_mode' | 'excluded_day';
  from: string;
  to: string;
  tail_to: string;
}

interface SeriesBuild {
  from: number;
  to: number;
  points: [string, number | null, number | null][];
  events: SeriesEventRow[];
  outOfSampleFrom: number;
  rmse: number | null;
  bias: number | null;
  compared: number;
}

/**
 * The series of the champion: measured room temperature, the 24 h-ahead prediction (none where its
 * path touches the wood-stove period with its tail or a left-out day) and the out-of-sample error
 * the service would report for it.
 */
function buildSeries(now: number): SeriesBuild {
  const stepMs = SERIES_STEP_S * 1000;
  const to = Math.floor(now / stepMs) * stepMs;
  const from = to - 14 * DAY;
  const gapFrom = to - 5 * DAY;
  const stoveFrom = Math.floor((now - STOVE_AGO_DAYS * DAY) / 60_000) * 60_000;
  const leftOutFrom = Date.parse(`${day(now - LEFT_OUT_AGO_DAYS * DAY)}T00:00:00Z`);
  const events: SeriesEventRow[] = [
    {
      kind: 'excluded_day',
      from: iso(leftOutFrom),
      to: iso(leftOutFrom + DAY),
      tail_to: iso(leftOutFrom + DAY),
    },
    {
      kind: 'stove',
      from: iso(stoveFrom),
      to: iso(stoveFrom + 5 * HOUR),
      tail_to: iso(stoveFrom + 17 * HOUR),
    },
  ];
  const spans = events.map((event) => [Date.parse(event.from), Date.parse(event.tail_to)]);
  const outOfSampleFrom = to - 9 * DAY;
  const points: [string, number | null, number | null][] = [];
  let compared = 0;
  let squares = 0;
  let signed = 0;
  for (let at = from + DAY, i = 0; at <= to; at += stepMs, i += 1) {
    const inGap = at >= gapFrom && at < gapFrom + 3 * HOUR;
    const touches = spans.some(
      ([start, end]) => at >= (start as number) && at - DAY <= (end as number),
    );
    const measured = roomAt(at) + 0.05 * noise(i);
    const predicted = measured + 0.08 * Math.sin(i / 37) + 0.06 * noise(i + 5) - 0.08;
    const shownMeasured = inGap ? null : round(measured, 2);
    const shownPredicted = inGap || touches ? null : round(predicted, 2);
    points.push([iso(at), shownMeasured, shownPredicted]);
    if (shownMeasured !== null && shownPredicted !== null && at - DAY >= outOfSampleFrom) {
      compared += 1;
      squares += (shownPredicted - shownMeasured) ** 2;
      signed += shownPredicted - shownMeasured;
    }
  }
  return {
    from: Date.parse(points[0]?.[0] ?? iso(from)),
    to,
    points,
    events,
    outOfSampleFrom,
    rmse: compared > 0 ? round(Math.sqrt(squares / compared), 3) : null,
    bias: compared > 0 ? round(signed / compared, 3) : null,
    compared,
  };
}

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
 * The latest check of the champion: a just-promoted model's own held-out test, or (for a model
 * that no longer predicts better than `no change`) a re-validation of the kept champion.
 */
function revalidationOf(
  now: number,
  runAt: number,
  model: string,
  scenario: Scenario,
  credible: boolean,
  skill: number,
  series: SeriesBuild,
  reasons: string[],
  shortfall: { heating_days: number; outside_span_k: number },
): Record<string, unknown> {
  const revalidated = scenario.house === 'no-skill';
  const legacy = scenario.house === 'legacy';
  return {
    model,
    at: iso(runAt),
    source: revalidated ? 'revalidated' : 'held_out',
    data_to: iso(now - DAY),
    fitted_to: iso(now - (revalidated ? 8 : 15) * DAY),
    from: iso(now - 15 * DAY),
    to: iso(now - DAY),
    origins: 104,
    in_sample: false,
    room_rmse_k: revalidated ? 0.14 : 0.093,
    persistence_room_rmse_k: revalidated ? 0.13 : 0.13,
    skill_horizon_h: 6,
    skill,
    series_rmse_k: series.rmse,
    series_bias_k: series.bias,
    gates: legacy ? null : learnedGates(scenario, shortfall),
    credible,
    reasons,
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
  const credible = houseCredible(scenario);
  const changed = scenario.house === 'changed';
  const pinned = scenario.house === 'pin-cost';
  const points = signature(now, credible);
  const gates = houseGates(scenario);
  const legacy = scenario.house === 'legacy';
  const checks = {
    signature: scenario.house !== 'uncredible',
    excitation: credible,
    ua_consistent: true,
    ...(legacy ? {} : { ua_stable: true }),
    predictive: gates.dynamics.ok,
    ...(legacy ? {} : { sun: gates.sun.ok }),
  };
  const needed = checks.excitation
    ? { heating_days: 0, outside_span_k: 0 }
    : scenario.house === 'not-excited'
      ? { heating_days: 6, outside_span_k: 1.4 }
      : { heating_days: 9, outside_span_k: 2.4 };
  const skill = checks.predictive ? 0.21 : -0.06;
  const message = credible
    ? null
    : `insufficient data: ${needed.heating_days} more heating days, ${needed.outside_span_k} K more spread in daily outside temperature needed`;
  const reasons = credible
    ? []
    : [`${20 - needed.heating_days} heating days in the fit window < 20`];
  const ua = pinned ? PIN_UA : UA;
  const uaInterval: [number, number] = pinned ? [PIN_UA, PIN_UA] : UA_INTERVAL;
  const uaBootstrap: [number, number] = pinned ? [PIN_UA, PIN_UA] : UA_BOOTSTRAP;
  const uaFolds = pinned ? [PIN_UA] : UA_FOLDS;
  const model = modelName(now - DAY);
  const dataTo = now - DAY;
  const area = floorArea(doc, scenario);
  const series = buildSeries(now);
  const revalidation = revalidationOf(
    now,
    runAt,
    model,
    scenario,
    credible,
    skill,
    series,
    reasons,
    needed.heating_days > 0 || needed.outside_span_k > 0
      ? { heating_days: needed.heating_days, outside_span_k: needed.outside_span_k }
      : { heating_days: 0, outside_span_k: 0 },
  );
  const warnings =
    scenario.house === 'no-skill'
      ? [`wood-stove episode of ${day(now - 3 * DAY)} has no recorded end; capped at 12 h`]
      : [];
  const heldOut = pinned ? 0.31 : changed ? 0.108 : 0.093;
  const unconstrained = pinned ? 0.24 : null;
  return {
    status: 200,
    body: {
      state: 'ready',
      schema: 'ovenbird.house-insight/1',
      model,
      champion: { model, promoted_at: iso(runAt) },
      last_run: {
        at: iso(runAt),
        outcome: scenario.house === 'no-skill' ? 'kept_champion' : 'promoted',
        model,
        champion: model,
        message: null,
        runtime_s: 275.7,
        interval_h: LEARNER_INTERVAL_H,
        warnings,
        champion_revalidation: revalidation,
      },
      credible,
      gates: modelGates(scenario),
      revalidation,
      learner: learner(now, runAt),
      data: {
        from: iso(now - 42 * DAY),
        to: iso(dataTo),
        fit_days: 40.7,
        signature_days: points.length,
        excluded_days: [day(now - LEFT_OUT_AGO_DAYS * DAY)],
        warnings,
      },
      ua: {
        w_per_k: ua,
        interval_90: uaInterval,
        ...(legacy
          ? {}
          : {
              interval_source: 'bootstrap_and_folds',
              bootstrap_interval_90: uaBootstrap,
              fold_w_per_k: uaFolds,
            }),
        source: 'rc_model',
        signature_w_per_k: 236.1,
        signature_interval_90: [221.0, 252.6],
        low_confidence: false,
      },
      time_constant_h: { value: 52.6, interval_90: [48.9, 56.4] },
      heat_capacity_kwh_per_k: 7.75,
      ...(legacy
        ? {}
        : {
            capacities_kwh_per_k: CAPACITIES,
            emitter_time_constant_h: { value: EMITTER_TIME_CONSTANT_H, interval_90: [0.5, 0.7] },
            structure: {
              name: 'chain',
              fixed: {
                h_water_air: 5.0,
                solar_mass_fraction: 0.0,
                q_int_modulation: 0.0,
                q_int_peak_hour: 19.0,
              },
              free: [
                'c_water',
                'c_mass',
                'c_air',
                'h_water_mass',
                'h_mass_air',
                'h_air_out',
                'solar_aperture_m2',
                'q_int_w',
              ],
              nodes: { c_water: 'loop', c_mass: 'emitter', c_air: 'building' },
            },
          }),
      solar_aperture_m2: { value: 6.2, interval_90: [5.4, 7.1] },
      internal_gains_w: {
        value: 318,
        interval_90: [262, 381],
        ...(legacy
          ? {}
          : {
              identified: false,
              label: 'net_free_heat',
              note: 'net free heat (people, appliances, other sources); cannot be separated from the heat loss with this data',
              at_zero: false,
              ua_w_per_k_per_100_w: GAINS_COUPLING_W_PER_K_PER_100_W,
            }),
      },
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
      excitation: {
        excited: checks.excitation,
        days: 36,
        heating_days: 20 - needed.heating_days + (checks.excitation ? 4 : 0),
        delta_t_days: 30,
        run_share_days: 15,
        heat_days: 12,
        mean_delta_t_k: 9.8,
        mean_run_share: 0.31,
        heat_kwh_per_day: 22.4,
        outside_sd_k: 2.9,
        outside_range_k: round(10 - needed.outside_span_k + (checks.excitation ? 5.2 : 0), 1),
        ua_relative_width: 0.07,
        ua_tight: true,
        rules: {
          heating_days: 20,
          delta_t_k: 5,
          run_share: 0.2,
          outside_range_k: 10,
          ua_relative_width: 0.3,
          heat_day_kwh: 20,
        },
        needed: { heating_days: needed.heating_days, outside_range_k: needed.outside_span_k },
        reasons,
      },
      credibility: {
        credible,
        ...(legacy ? {} : { gates: learnedGates(scenario, needed, true) }),
        checks,
        days: points.length,
        heating_days: points.length - 1,
        cold_days: credible ? 12 : 6,
        outside_span_k: credible ? 16.2 : 13.4,
        agreement: 0.02,
        skill,
        rules: {
          heating_days: 30,
          heating_day_w: 300,
          outside_span_k: 10,
          cold_day_below_c: 5,
          ua_agreement: 0.2,
          skill_horizon_h: 6,
          min_skill: 0,
        },
        needed,
        reasons,
        low_confidence: false,
        message,
      },
      score: houseScore(ua, uaInterval, area, credible, message),
      validation: {
        test_from: iso(now - 15 * DAY),
        test_to: iso(now - DAY),
        score_horizon_h: 24,
        held_out_room_rmse_k: heldOut,
        persistence_room_rmse_k: round(heldOut * 1.4, 3),
        skill_horizon_h: 6,
        skill_at_horizon: skill,
        series_rmse_k: series.rmse,
        series_bias_k: series.bias,
        series_points: series.compared,
        challenger_room_rmse_k: heldOut,
        champion_room_rmse_k: 0.101,
        champion: modelName(now - 8 * DAY),
        challenger_credible: credible,
        champion_credible: true,
        challenger_gates: {
          heat_loss: gates.heat_loss.ok,
          dynamics: gates.dynamics.ok,
          sun: gates.sun.ok,
        },
        champion_gates: { heat_loss: true, dynamics: true, sun: true },
        same_house: true,
        promoted: true,
        settings_changed: changed || pinned,
        tolerance_k: 0.02,
        unconstrained_room_rmse_k: unconstrained,
        constraint_cost: pinned ? { excess_k: 0.07, limit_k: 0.05, worse: true } : null,
        rule: changed
          ? 'house settings changed: promoted although challenger 0.108 K > champion 0.101 K'
          : pinned
            ? 'house settings changed: promoted although challenger 0.31 K > champion 0.101 K'
            : 'challenger 0.093 K <= champion 0.101 K',
      },
      at_bound: pinned
        ? [
            { parameter: 'h_air_out', value: PIN_UA, side: 'pinned', limit: PIN_UA, kind: 'owner' },
            {
              parameter: 'h_water_air',
              value: 5.1,
              side: 'lower',
              limit: 5,
              kind: 'structural',
            },
          ]
        : [{ parameter: 'h_water_air', value: 5.1, side: 'lower', limit: 5, kind: 'structural' }],
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
      events: [stoveEvent(now - STOVE_AGO_DAYS * DAY)],
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
        code_version: '0.5.0',
        method: 'building_only',
        fallback_reason: null,
        seed: 0,
        bootstrap: 20,
        folds: 2,
        generated: iso(runAt),
        constraints: constraints(doc),
        told: scenario.house === 'facts' ? { ...TOLD, solar_aperture_m2: 2.5 } : TOLD,
        learning: {
          fit_days: numberField(doc, 'house_learn_fit_days', 42),
          test_days: numberField(doc, 'house_learn_test_days', 14),
          tolerance_k: 0.02,
          excluded_days: [day(now - LEFT_OUT_AGO_DAYS * DAY)],
          excluded_days_in_fit: 1,
        },
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
    body: { floor_area_m2: area, models: history(now, area, houseCredible(scenario)) },
  };
}

/**
 * `POST insight/house/proposal/draft`: the champion's proposal as a configuration draft.
 */
export function makeProposalDraft(now: number, scenario: Scenario, doc: ConfigDoc): MockResult {
  if (scenario.house === 'learning' || scenario.house === 'notrun')
    return { status: 404, body: { detail: 'no house model has been promoted yet' } };
  const model = modelName(now - DAY);
  const suggestion = proposal(doc, houseCredible(scenario));
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

function constraints(doc: ConfigDoc): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  for (const [id, field] of Object.entries(doc.fields)) {
    if (!id.startsWith('house_') || id.startsWith('house_learn_')) continue;
    if (field.value !== null && field.value !== undefined) out[id] = field.value;
  }
  return out;
}

const round10 = (value: number) => Math.round(value / 10) * 10;

function notFound(code: string, message: string): MockResult {
  return { status: 404, body: { detail: { code, message, params: {} } } };
}

/**
 * Sunshine on the ground (W/m2) at a time of day: a smooth bell between 07:00 and 17:00.
 */
export function sunAt(ms: number): number {
  const date = new Date(ms);
  const hour = date.getHours() + date.getMinutes() / 60;
  if (hour < 7 || hour > 17) return 0;
  return Math.round(260 * Math.sin(((hour - 7) / 10) * Math.PI));
}

function usesEstimate(scenario: Scenario): boolean {
  return (
    scenario.balance === 'estimate' || scenario.house === 'learning' || scenario.house === 'notrun'
  );
}

/**
 * `GET insight/house/balance`: the heat flows of the house now, computed from the mock's own
 * constants (loss = UA x (room - outside)); storage = pump + sun + internal - loss, and null while
 * the stove burns or when the sun is unknown. `404 house_model_missing` for `balance:missing`.
 */
export function makeBalance(now: number, scenario: Scenario, stoveActive: boolean): MockResult {
  if (scenario.balance === 'missing')
    return notFound('house_model_missing', 'no house model and no house facts to estimate from');
  const estimate = usesEstimate(scenario);
  const ua = estimate ? TOLD.ua_w_per_k : UA;
  const aperture = estimate ? TOLD.solar_aperture_m2 : SOLAR_APERTURE_M2;
  const internal = estimate ? TOLD.internal_gain_w : INTERNAL_W;
  const room = round(roomAt(now), 1);
  const outside = round(outsideAt(now), 1);
  const sunKnown = scenario.balance !== 'nosun';
  const sun = sunAt(now);
  const loss = round10(ua * (room - outside));
  const sunW = sunKnown ? round10(aperture * sun) : null;
  const wobble = 400 * Math.sin(now / 7_200_000);
  const stoveW = stoveActive ? 3000 : 0;
  const defrosting = scenario.pump === 'defrost';
  const hotWater = scenario.pump === 'dhw';
  const pump = hotWater
    ? null
    : defrosting
      ? -round10(300)
      : Math.max(0, round10(loss - (sunW ?? 0) - internal - stoveW + wobble));
  const tail = scenario.balance === 'tail';
  const known = sunW !== null && !stoveActive && !tail && pump !== null;
  const credible = !estimate && houseCredible(scenario);
  const notes = [
    ...(estimate ? ['estimate'] : []),
    ...(!credible ? ['not_credible'] : []),
    ...(sunKnown ? [] : ['sun_unknown']),
    ...(stoveActive ? ['stove_active'] : []),
    ...(tail ? ['stove_tail'] : []),
    ...(hotWater ? ['dhw_active'] : []),
    ...(defrosting ? ['defrost'] : []),
  ];
  return {
    status: 200,
    body: {
      at: iso(now),
      source: estimate ? 'estimate' : 'model',
      credible,
      room_c: room,
      outside_c: outside,
      sun_wm2: sunKnown ? sun : null,
      flows: {
        heat_pump_w: pump,
        loss_w: loss,
        sun_w: sunW,
        internal_w: internal,
        stove_active: stoveActive,
        storage_w: known ? (pump ?? 0) + (sunW ?? 0) + internal - loss : null,
      },
      ua_w_per_k: ua,
      notes,
    },
  };
}

/**
 * `GET insight/house/series`: measured room temperature and the temperature the model predicted
 * 24 h ahead, every 15 minutes over the last 14 days, with a three-hour gap in both, a wood-stove
 * period and a left-out day (no prediction where its path touches them).
 */
export function makeHouseSeries(now: number, scenario: Scenario): MockResult {
  if (
    scenario.balance === 'missing' ||
    scenario.house === 'learning' ||
    scenario.house === 'notrun'
  )
    return notFound('house_series_missing', 'no model has predicted the room yet');
  const built = buildSeries(now);
  return {
    status: 200,
    body: {
      model: modelName(now - DAY),
      step_s: SERIES_STEP_S,
      from: iso(built.from),
      to: iso(built.to),
      points: built.points,
      events: built.events,
      out_of_sample_from: iso(built.outOfSampleFrom),
      rmse_k: built.rmse,
      bias_k: built.bias,
      compared_points: built.compared,
    },
  };
}

function interpolate(curve: Curve, x: number): number {
  const sorted = [...curve].sort((a, b) => a[0] - b[0]);
  const first = sorted[0] as [number, number];
  const last = sorted[sorted.length - 1] as [number, number];
  if (x <= first[0]) return first[1];
  if (x >= last[0]) return last[1];
  for (let i = 1; i < sorted.length; i += 1) {
    const [x1, y1] = sorted[i] as [number, number];
    const [x0, y0] = sorted[i - 1] as [number, number];
    if (x <= x1) return y0 + ((y1 - y0) * (x - x0)) / (x1 - x0);
  }
  return last[1];
}

const WHATIF_RANGES: Record<string, [number, number]> = {
  outside_c: [-30, 30],
  comfort_c: [5, 30],
  sun_wm2: [0, 1000],
  stove_w: [0, 15000],
};

/**
 * `GET insight/house/whatif`: a steady-state heat balance at the asked conditions (loss = UA x
 * (comfort - outside), free heat = aperture x sun + internal gains + stove), the water
 * temperature that carries the remaining demand and an exponential drift of the room with the
 * heating off. `422` outside the ranges.
 */
export function makeWhatIf(
  now: number,
  scenario: Scenario,
  doc: ConfigDoc,
  query: URLSearchParams,
): MockResult {
  if (scenario.balance === 'missing')
    return notFound('house_model_missing', 'no house model and no house facts to estimate from');
  const inputs: Record<string, number> = {
    outside_c: 0,
    comfort_c: numberField(doc, 'control_comfort_c', COMFORT_C),
    sun_wm2: 0,
    stove_w: 0,
  };
  for (const [key, [lo, hi]] of Object.entries(WHATIF_RANGES)) {
    const raw = query.get(key);
    if (raw === null) continue;
    const value = Number(raw);
    if (!Number.isFinite(value) || value < lo || value > hi)
      return {
        status: 422,
        body: {
          detail: [
            { loc: ['query', key], msg: `must be between ${lo} and ${hi}`, type: 'value_error' },
          ],
        },
      };
    inputs[key] = value;
  }
  const estimate = usesEstimate(scenario);
  const ua = estimate ? TOLD.ua_w_per_k : UA;
  const aperture = estimate ? TOLD.solar_aperture_m2 : SOLAR_APERTURE_M2;
  const internal = estimate ? TOLD.internal_gain_w : INTERNAL_W;
  const tau = estimate ? null : TIME_CONSTANT_H;
  const { outside_c: outside, comfort_c: comfort } = inputs as {
    outside_c: number;
    comfort_c: number;
  };
  const free = round10(
    aperture * (inputs['sun_wm2'] as number) + internal + (inputs['stove_w'] as number),
  );
  const loss = Math.max(0, round10(ua * (comfort - outside)));
  const demand = Math.max(0, loss - free);
  const maxSupply = numberField(doc, 'control_max_supply_c', 40);
  const limited: string[] = [];
  let mean = comfort;
  let supply = comfort;
  if (demand === 0) limited.push('no_heat_needed');
  else {
    mean = comfort + demand / EMITTER_W_PER_K;
    supply = mean + DELTA_T_K / 2;
    if (supply > maxSupply) {
      supply = maxSupply;
      limited.push('max_supply');
    }
  }
  const equilibrium = outside + free / ua;
  const decay = (hours: number) => Math.exp(-hours / (tau ?? 48));
  const steps = (8 * 3600) / SERIES_STEP_S;
  const room = Array.from({ length: steps + 1 }, (_, i) =>
    round(equilibrium + (comfort - equilibrium) * decay((i * SERIES_STEP_S) / 3600), 2),
  );
  return {
    status: 200,
    body: {
      source: estimate ? 'estimate' : 'model',
      model: estimate ? null : modelName(now - DAY),
      credible: !estimate && houseCredible(scenario),
      inputs,
      heat_demand_w: demand,
      free_heat_w: free,
      loss_w: loss,
      loop_mean_c: round(mean, 1),
      supply_c: round(supply, 1),
      curve_c: round(interpolate(currentCurve(doc), outside), 1),
      max_supply_c: maxSupply,
      limited_by: limited,
      balance_outside_c: round(comfort - free / ua, 1),
      drift: {
        credible: !estimate && houseDynamicsCredible(scenario),
        hours: 8,
        step_s: SERIES_STEP_S,
        room_c: room,
      },
      time_constant_h: tau,
    },
  };
}

type Situation = 'setback' | 'preheat' | 'dead' | 'blocked';

interface PlanState {
  use: 'off' | 'shadow' | 'on';
  situation: Situation;
}

/**
 * The switch and what the planner computed, from the scenario and the stored configuration: a
 * `modelplan` scenario forces both; without one the switch is `control_model_use` and the planner
 * issues a set-back.
 */
export function planState(scenario: Scenario, doc: ConfigDoc): PlanState {
  switch (scenario.modelplan) {
    case 'shadow':
      return { use: 'shadow', situation: 'setback' };
    case 'preheat':
      return { use: 'shadow', situation: 'preheat' };
    case 'dead':
      return { use: 'shadow', situation: 'dead' };
    case 'blocked':
      return { use: 'shadow', situation: 'blocked' };
    case 'on':
      return { use: 'on', situation: 'setback' };
    default: {
      const stored = doc.fields['control_model_use']?.value;
      const use = stored === 'shadow' || stored === 'on' ? stored : 'off';
      return { use, situation: 'setback' };
    }
  }
}

export const PLAN_SHIFT_K = 0.3;

/**
 * The room-target shift the controller applies in the mock decisions: only with the switch on.
 */
export function appliedPlanK(scenario: Scenario, doc: ConfigDoc): number {
  const state = planState(scenario, doc);
  if (state.use !== 'on') return 0;
  return state.situation === 'preheat'
    ? PLAN_SHIFT_K
    : state.situation === 'setback'
      ? -PLAN_SHIFT_K
      : 0;
}

const QUARTER = 900_000;
const bell = (hour: number, from: number, to: number) =>
  hour <= from || hour >= to ? 0 : Math.sin(((hour - from) / (to - from)) * Math.PI);

function pastOffset(at: number, maxDown: number, maxUp: number): number {
  const date = new Date(at);
  const hour = date.getHours() + date.getMinutes() / 60;
  const dayIndex = Math.floor((at - date.getTimezoneOffset() * 60_000) / DAY);
  const sunny = dayIndex % 7 !== 2 && dayIndex % 7 !== 5;
  const cold = dayIndex % 3 === 1;
  const down = sunny ? -maxDown * 0.8 * bell(hour, 8.5, 14) : 0;
  const up = cold ? maxUp * bell(hour, 15, 19) : 0;
  const value = Math.round((down + up) * 10) / 10;
  return Math.abs(value) < 0.1 ? 0 : value;
}

function bound(doc: ConfigDoc, id: string, fallback: number): number {
  const value = doc.fields[id]?.value;
  return typeof value === 'number' ? value : fallback;
}

/**
 * `GET insight/house/control`: the switch, whether the planner may act, the latest evaluation
 * and 7 days of computed shifts every 15 minutes. The history is one pattern per day (a set-back
 * on sunny mornings, a pre-heat before some cold evenings); the last two hours and `now` follow
 * the scenario. Off: nothing is computed. On: the last three days were applied, the days before
 * only computed.
 */
export function makeHouseControl(now: number, scenario: Scenario, doc: ConfigDoc): MockResult {
  if (scenario.modelplan === 'missing') return notFound('not_found', 'no such endpoint');
  const { use, situation } = planState(scenario, doc);
  const maxDown = bound(doc, 'control_model_max_setback_k', 0.5);
  const maxUp = bound(doc, 'control_model_max_preheat_k', 0.3);
  const horizon = bound(doc, 'control_model_horizon_h', 6);
  const maxRmse = bound(doc, 'control_model_max_rmse_k', 0.4);
  const blocked = situation === 'blocked';
  const blocks = blocked ? ['model_not_credible', 'stove_tail'] : [];
  const slot = Math.floor(now / QUARTER) * QUARTER;
  const from = slot - 7 * DAY;
  const points: [string, number | null, 0 | 1 | null][] = [];
  const currentK =
    situation === 'preheat' ? PLAN_SHIFT_K : situation === 'setback' ? -PLAN_SHIFT_K : 0;
  const gapFrom = slot - 2 * DAY - 5 * HOUR;
  const appliedFrom = slot - 3 * DAY;
  for (let at = from; at <= slot; at += QUARTER) {
    let offset: number | null = pastOffset(at, maxDown, maxUp);
    const recent = at > slot - 2 * HOUR;
    if (recent) offset = blocked ? null : currentK;
    if (
      use === 'off' ||
      (at >= gapFrom && at < gapFrom + 5 * HOUR) ||
      (blocked && at > slot - 6 * HOUR)
    )
      offset = null;
    const applied = offset === null ? null : use === 'on' && at >= appliedFrom ? 1 : 0;
    points.push([iso(at), offset, applied]);
  }
  const evaluatedAt = blocked ? slot - 4 * HOUR : slot;
  const evaluating = use !== 'off';
  const dead = situation === 'dead';
  const rise = dead ? 0.2 : situation === 'preheat' ? 0.1 : 0.6;
  const fall = dead ? 0.1 : situation === 'preheat' ? 0.7 : 0.1;
  const body = {
    use,
    verdict: { ok: blocks.length === 0, blocks },
    model: modelName(now - DAY),
    model_rmse_k: blocked ? 0.62 : 0.21,
    bounds: {
      max_setback_k: maxDown,
      max_preheat_k: maxUp,
      horizon_h: horizon,
      max_rmse_k: maxRmse,
    },
    now: evaluating
      ? {
          at: iso(evaluatedAt),
          status: dead ? 'inside_dead_zone' : 'issued',
          offset_k: currentK,
          applied: use === 'on' && !dead && !blocked,
          reason: dead ? null : currentK < 0 ? 'plan_setback' : 'plan_preheat',
          valid_until: dead ? null : iso(evaluatedAt + 20 * 60_000),
          rise_k: rise,
          rise_at: iso(evaluatedAt + 3 * HOUR),
          fall_k: -fall,
          fall_at: iso(evaluatedAt + 5 * HOUR),
          solar_k: situation === 'preheat' ? 0.1 : rise,
          outside_k: situation === 'preheat' ? -0.7 : dead ? 0 : -0.1,
        }
      : null,
    history: { step_s: 900, from: iso(from), to: iso(slot), points: use === 'off' ? [] : points },
  };
  return { status: 200, body };
}
