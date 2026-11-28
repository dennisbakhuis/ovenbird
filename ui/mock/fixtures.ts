import ui from '../package.json' with { type: 'json' };
import type { DefrostState, Health, History, Signal, Snapshot } from '../src/lib/core/types';
import { outsideAt, roomAt, roomFacts } from './decisions.ts';
import type { PumpPhase, Scenario } from './scenario.ts';

export const health: Health = {
  live: true,
  ready: true,
  version: ui.version,
  api_version: 1,
  checks: {
    mqtt: 'connected',
    heishamon: 'alive',
    ha: 'disabled',
    history: 'ok',
    alarms: 'ok',
    weather: 'disabled',
  },
};

const MINUTE = 60_000;
const HOUR = 3_600_000;
const FORCE_WINDOW_MS = 15 * MINUTE;
const WATTS_PER_LPM_K = 69.7;

const targetAt = (ms: number) => 33 - 0.4 * Math.sin(ms / HOUR);
const waterTargetAt = (ms: number) => Math.round(targetAt(ms));

function localMinutes(ms: number): number {
  const date = new Date(ms);
  return date.getHours() * 60 + date.getMinutes() + date.getSeconds() / 60;
}

function localDay(ms: number): number {
  const date = new Date(ms);
  return Math.floor(Date.UTC(date.getFullYear(), date.getMonth(), date.getDate()) / 86_400_000);
}

/**
 * Hot water runs: every morning 06:30–07:10 and every other evening 17:30–17:55 (local time).
 */
export function dhwAt(ms: number): boolean {
  const m = localMinutes(ms);
  if (m >= 390 && m < 430) return true;
  return localDay(ms) % 2 === 0 && m >= 1050 && m < 1075;
}

/**
 * Quiet level 2 from 22:00 to 07:00 local time, matching the mock config's quiet window.
 */
export function quietLevelAt(ms: number): number {
  const m = localMinutes(ms);
  return m >= 1320 || m < 420 ? 2 : 0;
}

const cycleMinute = (ms: number) => (((ms / MINUTE) % 150) + 150) % 150;
const cycleIndex = (ms: number) => Math.floor(ms / (150 * MINUTE));

/**
 * Compressor cycles: 105 min on, 45 min off in a 150-minute cycle.
 */
export function runningAt(ms: number): boolean {
  return cycleMinute(ms) < 105;
}

/**
 * Defrost for 7 minutes in the middle of every other run while it is colder than 7 °C outside.
 */
export function defrostAt(ms: number): boolean {
  if (outsideAt(ms) >= 7 || cycleIndex(ms) % 2 !== 0) return false;
  const m = cycleMinute(ms);
  return m >= 60 && m < 67;
}

export interface PumpState {
  phase: PumpPhase;
  hz: number;
  electricW: number;
  heatW: number;
  outlet: number;
  inlet: number;
  flow: number;
  duty: number;
  valve: 0 | 1;
  quietLevel: number;
  dhwTemp: number;
}

function phaseAt(ms: number, tank: boolean): PumpPhase {
  if (tank && dhwAt(ms)) return 'dhw';
  if (!runningAt(ms)) return 'idle';
  if (defrostAt(ms)) return 'defrost';
  return 'heating';
}

function dhwTempAt(ms: number): number {
  const m = localMinutes(ms);
  if (dhwAt(ms)) {
    const start = m >= 1050 ? 1050 : 390;
    const span = m >= 1050 ? 25 : 40;
    return 41 + (9 * (m - start)) / span;
  }
  const sinceMorning = m >= 430 ? m - 430 : m + 1440 - 430;
  const eveningRun = localDay(ms) % 2 === 0 && m >= 1075;
  const since = eveningRun ? m - 1075 : sinceMorning;
  return Math.max(40, 50 - (0.35 * since) / 60);
}

/**
 * Coherent pump state at a moment: phase, compressor frequency, electric and heat power, water
 * temperatures, flow, duty, valve, quiet level and tank temperature. A forced phase or quiet
 * level applies when `forced` is given; without a tank (`tank: false`) no hot-water run is
 * scheduled.
 */
export function pumpStateAt(
  ms: number,
  forced: { phase?: PumpPhase; quiet?: boolean; tank?: boolean } = {},
): PumpState {
  const phase = forced.phase ?? phaseAt(ms, forced.tank ?? true);
  const outside = outsideAt(ms);
  const quietLevel = forced.quiet === undefined ? quietLevelAt(ms) : forced.quiet ? 2 : 0;
  const target = targetAt(ms);
  const dhwTemp = phase === 'dhw' && !dhwAt(ms) ? 45 : dhwTempAt(ms);
  if (phase === 'dhw') {
    const flow = 26;
    const electricW = 2350;
    const heatW = Math.round(electricW * 2.8);
    const outlet = Math.min(55, dhwTemp + 6);
    return {
      phase,
      hz: 52,
      electricW,
      heatW,
      outlet,
      inlet: outlet - heatW / (flow * WATTS_PER_LPM_K),
      flow,
      duty: 159,
      valve: 1,
      quietLevel,
      dhwTemp,
    };
  }
  if (phase === 'defrost') {
    return {
      phase,
      hz: 45,
      electricW: 1650,
      heatW: 0,
      outlet: 21.5,
      inlet: 27,
      flow: 24,
      duty: 220,
      valve: 0,
      quietLevel,
      dhwTemp,
    };
  }
  if (phase === 'idle') {
    const outlet = 27 + 1.2 * Math.sin(ms / (40 * MINUTE));
    return {
      phase,
      hz: 0,
      electricW: 28,
      heatW: 0,
      outlet,
      inlet: outlet - 0.3,
      flow: 12,
      duty: 80,
      valve: 0,
      quietLevel,
      dhwTemp,
    };
  }
  const wave = Math.sin(ms / (20 * MINUTE));
  const base = 22 + (8 - outside) * 2.2 + 4 * wave;
  const hz = Math.round(Math.min(quietLevel > 0 ? 32 : 60, Math.max(18, base)));
  const electricW = Math.round(250 + 48 * hz);
  const outlet = target - 0.8 + 0.6 * wave;
  const cop = 2.6 + 0.09 * (outside + 10) + 0.05 * (35 - outlet);
  const heatW = Math.round(electricW * cop);
  const flow = 22 + Math.sin(ms / (15 * MINUTE));
  return {
    phase,
    hz,
    electricW,
    heatW,
    outlet,
    inlet: outlet - heatW / (flow * WATTS_PER_LPM_K),
    flow,
    duty: 120,
    valve: 0,
    quietLevel,
    dhwTemp,
  };
}

/** Return water at a mode 2 defrost: below the 27 °C of the WH-MXC12J9E8's deice rule. */
const MODE2_INLET_C = 25.5;

function scenarioStateAt(ms: number, nowMs: number, scenario: Scenario): PumpState {
  const recent = nowMs - ms <= FORCE_WINDOW_MS;
  const forced: { phase?: PumpPhase; quiet?: boolean; tank?: boolean } = {
    tank: scenario.dhw !== 'none',
  };
  if (recent && scenario.pump) forced.phase = scenario.pump;
  if (recent && scenario.quiet) forced.quiet = scenario.quiet === 'on';
  const state = pumpStateAt(ms, forced);
  if (scenario.deice === '2' && state.phase === 'defrost')
    return { ...state, inlet: MODE2_INLET_C, flow: 0 };
  return state;
}

type Kind = 'mean' | 'last';

interface Generator {
  unit: string | null;
  kind: Kind;
  value: (ms: number, state: () => PumpState) => number;
}

const temp = (value: Generator['value']): Generator => ({ unit: '°C', kind: 'mean', value });

const GENERATORS: Record<string, Generator> = {
  'main/Outside_Temp': temp((ms) => outsideAt(ms)),
  'main/Main_Outlet_Temp': temp((_, s) => s().outlet),
  'main/Main_Inlet_Temp': temp((_, s) => s().inlet),
  'main/Main_Target_Temp': temp((ms) => targetAt(ms)),
  'main/Z1_Water_Target_Temp': temp((ms) => waterTargetAt(ms)),
  'main/DHW_Temp': temp((_, s) => s().dhwTemp),
  'main/DHW_Target_Temp': temp(() => 50),
  'ha/sensor.living_room_temperature': temp((ms) => roomAt(ms)),
  room_temperature: temp((ms) => roomAt(ms)),
  'main/Compressor_Freq': { unit: 'Hz', kind: 'mean', value: (_, s) => s().hz },
  'main/Heat_Power_Consumption': { unit: 'W', kind: 'mean', value: (_, s) => s().electricW },
  'main/Heat_Power_Production': { unit: 'W', kind: 'mean', value: (_, s) => s().heatW },
  'main/Pump_Flow': { unit: 'l/min', kind: 'mean', value: (_, s) => s().flow },
  'main/Pump_Duty': { unit: null, kind: 'mean', value: (_, s) => s().duty },
  'main/Defrosting_State': {
    unit: null,
    kind: 'last',
    value: (_, s) => (s().phase === 'defrost' ? 1 : 0),
  },
  'main/ThreeWay_Valve_State': { unit: null, kind: 'last', value: (_, s) => s().valve },
  'main/Quiet_Mode_Level': { unit: null, kind: 'last', value: (_, s) => s().quietLevel },
};

export const HISTORY_SIGNALS = Object.keys(GENERATORS);

/**
 * Unit and kind of a generated history signal (`last` for states), or null when unknown.
 */
export function historySignalInfo(id: string): { unit: string | null; state: boolean } | null {
  const generator = GENERATORS[id];
  return generator ? { unit: generator.unit, state: generator.kind === 'last' } : null;
}

const round = (value: number) => Math.round(value * 10) / 10;

function signal(partial: Partial<Signal> & Pick<Signal, 'value'>): Signal {
  return {
    unit: null,
    label: null,
    age: 5,
    held: null,
    max_age: 330,
    alive_by: null,
    fresh: true,
    source: 'heishamon',
    retained: false,
    reason: null,
    ...partial,
  };
}

const QUIET_LABELS = ['Off', 'Level 1', 'Level 2', 'Level 3'];

const REFERENCE: PumpState = {
  phase: 'heating',
  hz: 38,
  electricW: 1900,
  heatW: 7600,
  outlet: 32.5,
  inlet: 28,
  flow: 17.4,
  duty: 120,
  valve: 0,
  quietLevel: 0,
  dhwTemp: 47.5,
};

/**
 * Build a snapshot for the given wall-clock time (ms). With a scenario (the mock server always
 * passes one) the pump values follow the same model as the history; without one the pump part is
 * the fixed reference used by unit tests (heating at 38 Hz, 8.4 kW delivered).
 */
export function makeSnapshot(nowMs: number, scenario?: Scenario): Snapshot {
  const jitter = (spread: number) => (Math.random() - 0.5) * spread;
  const s = scenario ? scenarioStateAt(nowMs, nowMs, scenario) : REFERENCE;
  const running = s.phase !== 'idle';
  const delivered = !scenario
    ? 8400
    : s.phase === 'dhw'
      ? null
      : Math.round(s.flow * (s.outlet - s.inlet) * WATTS_PER_LPM_K);
  const roomStale = scenario?.room === 'stale';
  const room = roomFacts(nowMs, roomStale);
  return {
    at: new Date(nowMs).toISOString(),
    heishamon: { alive: true, last_heartbeat_age: 3.2, lwt: 'Online' },
    links: { ha: true, mqtt: true },
    signals: {
      'main/Outside_Temp': signal({
        value: round(outsideAt(nowMs) + jitter(0.2)),
        unit: '°C',
        age: 12,
      }),
      'main/Main_Outlet_Temp': signal({ value: round(s.outlet), unit: '°C', age: 12 }),
      'main/Main_Inlet_Temp': signal({ value: round(s.inlet), unit: '°C', age: 12 }),
      'main/Main_Target_Temp': signal({ value: round(targetAt(nowMs)), unit: '°C', age: 40.1 }),
      'main/Z1_Water_Target_Temp': signal({ value: 29, unit: '°C', age: 40.1 }),
      'main/Compressor_Freq': signal({ value: s.hz, unit: 'Hz', age: 12 }),
      'main/Pump_Flow': signal({ value: round(s.flow), unit: 'l/min', age: 12 }),
      'main/Pump_Duty': signal({ value: s.duty, age: 12 }),
      'main/Max_Pump_Duty': signal({ value: 159, age: 40 }),
      'main/Heat_Power_Consumption': signal({ value: s.electricW, unit: 'W', age: 12 }),
      'main/Heat_Power_Production': signal({ value: s.heatW, unit: 'W', age: 12 }),
      'main/Operating_Mode_State': signal({ value: 0, label: 'Heat', age: 40.1 }),
      'main/Room_Thermostat_Temp': signal({ value: 21.5, unit: '°C', age: 600, fresh: false }),
      'main/Defrosting_State': signal({
        value: s.phase === 'defrost' ? 1 : 0,
        label: s.phase === 'defrost' ? 'On' : 'Off',
        age: 40.1,
      }),
      'main/ThreeWay_Valve_State': signal({
        value: s.valve,
        label: s.valve ? 'DHW' : 'Room',
        age: 40.1,
      }),
      'main/Quiet_Mode_Level': signal({
        value: s.quietLevel,
        label: QUIET_LABELS[s.quietLevel] ?? null,
        age: 40.1,
      }),
      'main/DHW_Temp': signal({ value: round(s.dhwTemp), unit: '°C', age: 30 }),
      'main/DHW_Target_Temp': signal({ value: 50, unit: '°C', age: 40.1 }),
      'main/DHW_Installed': signal({ value: scenario?.dhw === 'none' ? 0 : 1, age: 40.1 }),
      'ha/sensor.living_room_temperature': signal({
        value: room.value,
        unit: '°C',
        age: room.aliveS,
        fresh: !roomStale,
        reason: roomStale ? 'no update for 2.5 h' : null,
        held: room.heldS,
        max_age: roomStale ? 3600 : 86400,
        alive_by: 'ha/sensor.living_room_humidity',
        source: 'ha',
      }),
      'ha/sensor.living_room_humidity': signal({
        value: 46,
        unit: '%',
        age: 95,
        source: 'ha',
        retained: true,
      }),
    },
    derived: {
      compressor_running: { value: running, reason: null },
      defrost_active: { value: s.phase === 'defrost', reason: null },
      dhw_active: { value: s.phase === 'dhw', reason: null },
      heat_delivered_w: {
        value: delivered,
        reason: delivered === null ? 'domestic hot water run' : null,
      },
    },
    defrost: defrostOf(nowMs, s, scenario),
  };
}

const DEFROST_MAX_S = 1200;
const DEICE_MODE2_LIMIT_S = 2100;
const DEFROST_SHOWN_FOR_MS = 3 * 60_000;

/**
 * The snapshot's `defrost` as the service latches it: a mode only for the known model
 * (`deice:1|2`), with the inlet and outdoor temperature at the start.
 */
function defrostOf(nowMs: number, s: PumpState, scenario?: Scenario): DefrostState {
  if (s.phase !== 'defrost')
    return {
      active: false,
      mode: null,
      since: null,
      inlet_at_start_c: null,
      outside_at_start_c: null,
      max_s: null,
    };
  const mode = scenario?.deice === '2' ? 2 : scenario?.deice === '1' ? 1 : null;
  const startMs = nowMs - DEFROST_SHOWN_FOR_MS;
  return {
    active: true,
    mode,
    since: new Date(startMs).toISOString(),
    inlet_at_start_c: round(s.inlet),
    outside_at_start_c: round(outsideAt(startMs)),
    max_s: mode === 2 ? DEICE_MODE2_LIMIT_S : DEFROST_MAX_S,
  };
}

/**
 * Step the real service would pick for a window: the smallest of 60, 900 and 3600 s that keeps a
 * series at about 1,500 points or fewer.
 */
export function defaultStep(fromMs: number, toMs: number): number {
  const span = Math.max(0, toMs - fromMs) / 1000;
  return [60, 900, 3600].find((step) => span / step <= 1500) ?? 3600;
}

/**
 * Build aligned history series for the requested signals. Buckets start on multiples of `step`;
 * numeric signals are the mean of 1-minute samples in the bucket and state signals take the last
 * sample, as the service does. Unknown signals are left out.
 */
export function makeHistory(
  ids: string[],
  fromMs: number,
  toMs: number,
  stepSeconds: number | null,
  scenario: Scenario = {},
  nowMs: number = toMs,
): History {
  const step = stepSeconds === null ? defaultStep(fromMs, toMs) : Math.max(60, stepSeconds);
  const stepMs = step * 1000;
  const start = Math.floor(fromMs / stepMs) * stepMs;
  const series: History['series'] = {};
  for (const id of ids) {
    const generator = GENERATORS[id];
    if (!generator) continue;
    const points: History['series'][string]['points'] = [];
    for (let bucket = start; bucket <= toMs; bucket += stepMs) {
      const end = Math.min(bucket + stepMs, toMs + 1);
      let sum = 0;
      let count = 0;
      let last = 0;
      for (let t = bucket; t < end; t += MINUTE) {
        let cached: PumpState | null = null;
        const state = () => (cached ??= scenarioStateAt(t, nowMs, scenario));
        last = generator.value(t, state);
        sum += last;
        count += 1;
      }
      if (count === 0) continue;
      const value = generator.kind === 'last' ? last : sum / count;
      points.push([new Date(bucket).toISOString(), round(value)]);
    }
    series[id] = { unit: generator.unit, points };
  }
  return {
    from: new Date(fromMs).toISOString(),
    to: new Date(toMs).toISOString(),
    step,
    series,
  };
}
