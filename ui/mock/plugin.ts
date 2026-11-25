import type { IncomingMessage } from 'node:http';
import type { Plugin } from 'vite';
import {
  initialState,
  makeAlarms,
  makeAudit,
  makeCommands,
  makeControl,
  type MockControl,
  makeDecision,
  makeDecisions,
  makeSeries,
  roomFacts,
  roomSilentMonitor,
  ROOM_STALE_S,
  STOVE_ROOM_C,
  stoveActiveAt,
  TARGET_C,
  type ConfigAt,
  type StoveMock,
} from './decisions.ts';
import {
  apply,
  configDoc,
  hotWaterState,
  exportDoc,
  initialConfigState,
  preview,
  rollback,
  schema,
  type ConfigState,
  makeSignals,
  setConnection,
  testConnection,
  validate,
  versionsList,
} from './config.ts';
import { health, makeHistory, makeSnapshot } from './fixtures.ts';
import {
  initialMqtt,
  integrationAlarms,
  mqttApply,
  mqttStatus,
  mqttTest,
  OUTSIDE_SIGNAL,
  settleMqtt,
  withMqtt,
  withOutside,
  withOutsideDecision,
  type MqttMock,
} from './integrations.ts';
import { framePage } from './frame.ts';
import { makeInsightDaily } from './insight.ts';
import { parseScenario, scenarioKey, scenarioNow, type Scenario } from './scenario.ts';
import { initialPumpState, pumpSettings, writeSetting } from './pump.ts';
import { makeWeather } from './weather.ts';
import { sendCsv } from './csv.ts';
import {
  archiveExport,
  compact,
  journalExport,
  makeHistorySignals,
  makeStorage,
  sendDownload,
  seriesExport,
} from './data.ts';
import { makeHouse, makeHouseHistory, makeProposalDraft } from './house.ts';
import { archiveDelete, archiveDownload, makeArchive } from './archive.ts';
import { explainEpisode, makeDivergence, withExplained, type LiveMinute } from './shadow.ts';
import {
  cancelReplay,
  makeCoverage,
  replayJob,
  startReplay,
  type ReplayContext,
} from './replay.ts';
import {
  makeAbout,
  makeDiagnostics,
  makeNotifications,
  NOTIFY_FAILING_MESSAGE,
  notifyFailingSince,
  testNotification,
} from './system.ts';
import {
  captureSnapshot,
  makeRuns,
  makeSnapshotState,
  makeTrialStatus,
  releaseHold,
  releaseState,
  resumeRelease,
  startRelease,
  type EnvelopeFacts,
} from './trial.ts';
import type { Curve } from '../src/lib/core/curve.ts';
import type {
  ConfigDoc,
  ControlStatus,
  Decision,
  Snapshot,
  StoveStatus,
} from '../src/lib/core/types';

const MINUTE = 60_000;
const HOUR = 3_600_000;

/**
 * Endpoints added in UI wave 3; `newapi:missing` answers 404 on all of them (an older service).
 */
const WAVE3_PATHS = [
  '/shadow/divergence',
  '/trial/status',
  '/insight/runs',
  '/control/snapshot',
  '/control/release',
  '/notifications/status',
  '/notifications/test',
  '/shadow/episodes/explain',
  '/system/about',
  '/diagnostics',
  '/insight/house',
  '/insight/house/history',
  '/insight/house/proposal/draft',
  '/history/signals',
  '/history/storage',
  '/history/compact',
  '/export/series',
  '/export/archive',
  '/replay/coverage',
  '/replay',
  '/archive',
  '/archive/delete',
];
const WAVE3_PREFIXES = ['/archive/'];
const FOREIGN_TARGET = 31;
const LIVE_MS = 3 * HOUR;
const HOLD_LIVE_MS = 25 * MINUTE;
const WATER_SIGNAL = 'main/Z1_Water_Target_Temp';
const WATER_LOOKBACK_MIN = 30;
const WATER_FALLBACK_C = 29;
const STOVE_DEFAULT_H = 8;
const STOVE_MAX_AHEAD_MS = 24 * HOUR;

/**
 * A wood-stove request as `POST control/stove` stores it.
 */
export interface StoveRequestState {
  on: boolean;
  untilMs: number | null;
  atMs: number;
  actor: string;
}

/**
 * Wood-stove mode under the scenario and the browser's own request: a manual request wins over
 * the scenario's episode; a stop leaves the detection blocked.
 */
export function stoveMock(
  scenario: Scenario,
  request: StoveRequestState | null,
  now: number,
  doc: ConfigDoc,
): StoveMock {
  const value = (id: string) => doc.fields[id]?.value;
  const base = {
    enabled: scenario.stove !== 'disabled' && value('control_stove_enabled') === true,
    auto: value('control_stove_auto') !== false,
    backoffK:
      typeof value('control_stove_backoff_k') === 'number'
        ? (value('control_stove_backoff_k') as number)
        : 3,
  };
  if (request?.on && (request.untilMs === null || request.untilMs > now))
    return {
      ...base,
      episode: {
        source: 'manual',
        trigger: 'manual',
        sinceMs: request.atMs,
        untilMs: request.untilMs,
        entryC: STOVE_ROOM_C,
      },
      waiting: null,
    };
  if (request && !request.on) return { ...base, episode: null, waiting: 'blocked' };
  if (scenario.stove === 'active')
    return {
      ...base,
      episode: {
        source: 'auto',
        trigger: 'level',
        sinceMs: now - 80 * 60_000,
        untilMs: null,
        entryC: 23.3,
      },
      waiting: null,
    };
  if (scenario.stove === 'manual')
    return {
      ...base,
      episode: {
        source: 'manual',
        trigger: 'manual',
        sinceMs: now - 30 * 60_000,
        untilMs: now + 3.5 * HOUR,
        entryC: STOVE_ROOM_C,
      },
      waiting: null,
    };
  if (scenario.stove === 'waiting') return { ...base, episode: null, waiting: 'level_blocked' };
  return { ...base, episode: null, waiting: null };
}

/**
 * The request behind a manual episode the scenario started (`stove:manual`): the service always
 * has one, with the episode's start and end.
 */
export function manualRequest(stove: StoveMock): StoveRequestState | null {
  const episode = stove.episode;
  if (episode?.source !== 'manual') return null;
  return {
    on: true,
    untilMs: episode.untilMs,
    atMs: episode.sinceMs,
    actor: 'admin from 192.168.1.20',
  };
}

/**
 * The `stove` block of the control status for the mock's wood-stove state; without a stored
 * request a manual episode reports the request that started it.
 */
export function stoveStatus(
  stove: StoveMock,
  stored: StoveRequestState | null,
  now: number,
  comfortC = TARGET_C,
): StoveStatus {
  const active = stoveActiveAt(stove, now);
  const episode = active ? stove.episode : null;
  const request = stored ?? (active ? manualRequest(stove) : null);
  const enter = Math.round((comfortC + 1.5) * 10) / 10;
  return {
    enabled: stove.enabled,
    auto: stove.auto,
    active,
    source: episode?.source ?? null,
    trigger: episode?.trigger ?? null,
    since: episode ? new Date(episode.sinceMs).toISOString() : null,
    entry_c: episode?.entryC ?? null,
    integral_k: active ? -0.6 : null,
    blocked: stove.waiting === 'blocked',
    level_blocked: stove.waiting === 'level_blocked',
    reentry_wait: stove.waiting === 'reentry_wait',
    backoff_k: active ? stove.backoffK : null,
    enter_c: enter,
    exit_c: Math.round((enter - 1) * 10) / 10,
    reference_c: null,
    request: request
      ? {
          on: request.on,
          until: request.untilMs === null ? null : new Date(request.untilMs).toISOString(),
          actor: request.actor,
          at: new Date(request.atMs).toISOString(),
        }
      : null,
  };
}

/**
 * A journal response cut to the requested window, `from`/`to` echoed as the service does.
 */
export function inWindow<T extends { at: string }, R extends { events: T[] }>(
  response: R,
  from: number,
  to: number,
): R & { from: string; to: string } {
  return {
    ...response,
    from: new Date(from).toISOString(),
    to: new Date(to).toISOString(),
    events: response.events.filter((event) => {
      const at = Date.parse(event.at);
      return at >= from && at <= to;
    }),
  };
}

/**
 * The room value in the snapshot and the control status while the stove heats the room.
 */
function stoveRoom<T extends Snapshot | ControlStatus>(value: T, active: boolean): T {
  if (!active) return value;
  if ('signals' in value) {
    const id = 'ha/sensor.living_room_temperature';
    const room = value.signals[id];
    return room
      ? { ...value, signals: { ...value.signals, [id]: { ...room, value: STOVE_ROOM_C } } }
      : value;
  }
  return value.room ? { ...value, room: { ...value.room, value: STOVE_ROOM_C } } : value;
}

/**
 * Whether the mock runs as an effective Shadow: paused by hand or by the scenario, or configured
 * as Shadow.
 */
function inShadow(scenario: Scenario, paused: boolean): boolean {
  return paused || scenario.mode !== undefined;
}

/**
 * The configuration document under the scenario: the mode for `mode:*`, the `simulation` field
 * (false unless `simulation:on`) and the pump's report of a hot-water tank (none for `dhw:none`).
 */
export function scenarioConfig(base: ConfigDoc, scenario: Scenario): ConfigDoc {
  const doc = {
    ...base,
    hot_water: hotWaterState(base.hot_water.setting, scenario.dhw !== 'none'),
  };
  const simulation = doc.fields['simulation'];
  const fields = simulation
    ? { ...doc.fields, simulation: { ...simulation, value: scenario.simulation === 'on' } }
    : doc.fields;
  if (scenario.mode === 'shadow')
    return {
      ...doc,
      fields,
      mode: { configured: 'shadow', effective: 'shadow', paused: false, reset_pending: false },
    };
  if (scenario.mode === 'paused')
    return {
      ...doc,
      fields,
      mode: { configured: 'auto', effective: 'shadow', paused: true, reset_pending: false },
    };
  return { ...doc, fields };
}

/**
 * A response body with its config document under the scenario, as `GET config` gives it.
 */
function withScenarioDoc(
  body: unknown,
  scenario: Scenario,
  extra: (doc: ConfigDoc) => ConfigDoc = (doc) => doc,
): unknown {
  if (typeof body !== 'object' || body === null || !('config' in body)) return body;
  const doc = (body as { config: unknown }).config;
  return typeof doc === 'object' && doc !== null && 'hot_water' in doc
    ? { ...body, config: extra(scenarioConfig(doc as ConfigDoc, scenario)) }
    : body;
}

/**
 * The latest decision's arbiter as the pump stands under the scenario: in Shadow next to another controller
 * the pump runs 2 K above ovenbird's value (`send` records what would be sent); paused, it kept
 * 1 K more; during a foreign-writer hold it keeps the foreign 31 °C and the arbiter skips.
 */
export function scenarioDecision(
  decision: Decision,
  scenario: Scenario,
  holdActive: boolean,
  paused: boolean,
): Decision {
  const intent = decision.setpoint;
  if (intent === null) return decision;
  let actual: number | null = null;
  let action = 'send';
  if (scenario.mode === 'shadow') actual = intent + 2;
  else if (scenario.mode === 'paused' || paused) actual = intent + 1;
  else if (holdActive) {
    actual = FOREIGN_TARGET;
    action = 'skip';
  }
  if (actual === null) return decision;
  if (actual === intent) action = 'none';
  return {
    ...decision,
    commands: [],
    arbiter: decision.arbiter.map((entry) =>
      entry.kind === 'water_setpoint'
        ? {
            ...entry,
            actual,
            action,
            reason:
              action === 'none'
                ? 'already applied'
                : action === 'skip'
                  ? 'hold: foreign writer'
                  : `pump reports ${actual}`,
          }
        : entry,
    ),
  };
}

/**
 * The configuration each decision ran with, from the version history: the newest version applied
 * by the decision's minute (an apply reaches the decision of the current minute at once). The
 * comfort target falls back to the current value.
 */
export function configAtFor(state: ConfigState): (ms: number) => ConfigAt {
  const current = configDoc(state, false).fields['control_comfort_c'];
  const fallback = typeof current?.value === 'number' ? current.value : TARGET_C;
  const versions = state.versions
    .map((version) => {
      const comfort = version.values?.['control_comfort_c'];
      return {
        fromMs: Math.floor(Date.parse(version.applied_at ?? version.created_at) / MINUTE) * MINUTE,
        version: version.version,
        comfortC: typeof comfort === 'number' ? comfort : fallback,
      };
    })
    .sort((a, b) => a.fromMs - b.fromMs);
  return (ms) => {
    let found = { version: state.version, comfortC: fallback };
    for (const version of versions) if (version.fromMs <= ms) found = version;
    return { version: found.version, comfortC: found.comfortC };
  };
}

/**
 * The water target the pump reports at `now`: the `actual` of the latest decision's water
 * setpoint arbitration (looking back past ticks without one, such as a refusal).
 */
export function pumpWaterOf(decisionAt: (ms: number) => Decision, now: number): number {
  for (let back = 0; back <= WATER_LOOKBACK_MIN; back += 1) {
    const decision = decisionAt(now - back * MINUTE);
    const water = decision.arbiter.find((entry) => entry.kind === 'water_setpoint');
    if (typeof water?.actual === 'number') return water.actual;
  }
  return WATER_FALLBACK_C;
}

/**
 * The snapshot with the pump's water target as the decisions report it.
 */
function withWaterTarget(snapshot: Snapshot, waterC: number): Snapshot {
  const signal = snapshot.signals[WATER_SIGNAL];
  return signal
    ? {
        ...snapshot,
        signals: { ...snapshot.signals, [WATER_SIGNAL]: { ...signal, value: waterC } },
      }
    : snapshot;
}

/**
 * The control status while a release restores the go-live snapshot: the controller is stopped
 * (the loop runs as `shadow`, `releasing: true`) while the adapter still publishes the restore.
 */
function releasing(control: ControlStatus, active: boolean): ControlStatus {
  if (!active) return control;
  const status: ControlStatus & { releasing: boolean } = {
    ...control,
    mode: 'shadow',
    releasing: true,
  };
  return status;
}

/**
 * FastAPI-style 422 detail for a numeric query parameter that must lie in (0, max], or null.
 */
export function rangeError(
  name: string,
  raw: string | null,
  max: number,
):
  | { type: string; loc: string[]; msg: string; input: string; ctx?: Record<string, number> }[]
  | null {
  if (raw === null) return null;
  const value = Number(raw);
  const loc = ['query', name];
  if (raw.trim() === '' || !Number.isFinite(value))
    return [
      {
        type: 'float_parsing',
        loc,
        msg: 'Input should be a valid number, unable to parse string as a number',
        input: raw,
      },
    ];
  if (value <= 0)
    return [
      {
        type: 'greater_than',
        loc,
        msg: 'Input should be greater than 0',
        input: raw,
        ctx: { gt: 0 },
      },
    ];
  if (value > max)
    return [
      {
        type: 'less_than_equal',
        loc,
        msg: `Input should be less than or equal to ${max}`,
        input: raw,
        ctx: { le: max },
      },
    ];
  return null;
}

function readBody(req: IncomingMessage): Promise<Record<string, unknown>> {
  return new Promise((resolve) => {
    let raw = '';
    req.on('data', (chunk: Buffer) => (raw += chunk.toString()));
    req.on('end', () => {
      try {
        resolve(raw ? (JSON.parse(raw) as Record<string, unknown>) : {});
      } catch {
        resolve({});
      }
    });
  });
}

/**
 * Apply the read-only scenario overrides to a control status.
 */
function withScenario(control: MockControl, scenario: Scenario, now: number): MockControl {
  if (scenario.mode === 'shadow') {
    control = {
      ...control,
      mode: 'shadow',
      configured_mode: 'shadow',
      paused: false,
      publishing: false,
      refusals: ['control mode is shadow, not auto'],
      alarms: control.alarms.filter((alarm) => alarm.code !== 'foreign_writer'),
      safety: { ...control.safety, level: 'ok' },
      adapter: null,
    };
  } else if (scenario.mode === 'paused') {
    control = {
      ...control,
      mode: 'shadow',
      configured_mode: 'auto',
      paused: true,
      publishing: false,
      refusals: ['control is paused'],
      adapter: null,
    };
  }
  if (scenario.hold === 'timed') {
    const held = makeControl(now, { paused: false, holdReleased: false });
    control = {
      ...control,
      alarms: control.alarms.some((alarm) => alarm.code === 'foreign_writer')
        ? control.alarms
        : [...held.alarms.filter((alarm) => alarm.code === 'foreign_writer'), ...control.alarms],
      adapter: control.adapter ? held.adapter : null,
    };
  }
  if (scenario.hold === 'latched') {
    const adapter =
      control.adapter ?? makeControl(now, { paused: false, holdReleased: false }).adapter;
    if (!adapter) return control;
    control = {
      ...control,
      alarms: [
        {
          code: 'hold_latched',
          severity: 'warning',
          message: 'hold 3 within 12 h (foreign writer), latched until an operator releases it',
          since: new Date(now - 10 * 60_000).toISOString(),
          detail: {},
        },
        ...control.alarms,
      ],
      adapter: {
        ...adapter,
        hold: 'foreign writer',
        hold_until: null,
        hold_latched: true,
        hold_incidents: 3,
      },
    };
  }
  if ((scenario.room === 'old' || scenario.room === 'untrusted') && control.room) {
    control = {
      ...control,
      room: {
        ...control.room,
        held_s: 166 * 86_400,
        authority: scenario.room === 'old' ? 0.45 : 0,
      },
    };
  }
  if (scenario.room === 'stale' && control.room) {
    const room = roomFacts(now, true);
    control = {
      ...control,
      safety: {
        ...control.safety,
        monitors: control.safety.monitors.map((monitor) =>
          monitor.code === 'room_sensor_silent' ? roomSilentMonitor(room.aliveS, now) : monitor,
        ),
      },
      room: {
        ...control.room,
        value: room.value,
        fresh: false,
        held_s: room.heldS,
        alive_s: room.aliveS,
      },
    };
  }
  if (scenario.notify === 'failing')
    control = {
      ...control,
      alarms: [
        ...control.alarms,
        {
          code: 'notify_failing',
          severity: 'warning',
          message: NOTIFY_FAILING_MESSAGE,
          since: notifyFailingSince(now),
          detail: {},
        },
      ],
    };
  if (scenario.alarms === 'none') {
    return {
      ...control,
      alarms: [],
      safety: { ...control.safety, level: 'ok' },
      adapter: control.adapter
        ? { ...control.adapter, hold: null, hold_until: null, hold_incidents: 0 }
        : null,
    };
  }
  if (scenario.alarms === 'critical') {
    const since = new Date(now - 4 * 60_000).toISOString();
    const limit =
      control.safety.monitors.find((monitor) => monitor.code === 'outlet_overshoot')?.limit ?? 45;
    const outlet = limit + 3.2;
    return {
      ...control,
      alarms: [
        {
          code: 'outlet_overshoot',
          severity: 'critical',
          message: `outlet ${outlet.toFixed(1)} °C above the ${limit.toFixed(1)} °C limit`,
          since,
          detail: {},
        },
        ...control.alarms,
      ],
      safety: {
        ...control.safety,
        level: 'critical',
        monitors: control.safety.monitors.map((monitor) =>
          monitor.code === 'outlet_overshoot'
            ? {
                ...monitor,
                status: 'active' as const,
                value: outlet,
                limit,
                message: `Main_Outlet_Temp ${outlet.toFixed(1)} °C against a limit of ${limit.toFixed(1)} °C`,
                since,
              }
            : monitor,
        ),
      },
    };
  }
  return control;
}

/**
 * Vite plugin serving fixture JSON for the api/v1 endpoints in mock mode: health, snapshot,
 * history, decisions (+latest, series), commands, alarms, config, audit and the control actions.
 */
export function mockApi(): Plugin {
  const state = initialState();
  const configState = initialConfigState();
  const pump = initialPumpState();
  const stoveRequests = new Map<string, StoveRequestState>();
  const brokers = new Map<string, MqttMock>();
  return {
    name: 'ovenbird-mock-api',
    configureServer(server) {
      server.middlewares.use((req, res, next) => {
        const url = new URL(req.url ?? '/', 'http://localhost');
        const path = url.pathname;
        const send = (body: unknown, status = 200) => {
          res.statusCode = status;
          res.setHeader('Content-Type', 'application/json');
          res.end(JSON.stringify(body));
        };
        const scenario = parseScenario(req.headers.cookie);
        const now = scenarioNow(scenario, Date.now());
        const param = (name: string) => url.searchParams.get(name);
        const from = param('from') ? Date.parse(param('from') as string) : now - 24 * HOUR;
        const to = param('to') ? Date.parse(param('to') as string) : now;
        const key = scenarioKey(req.headers.cookie);
        const release = () => releaseHold(key, now);
        const paused = () => state.paused || release() === 'paused';
        const mode = () =>
          inShadow(scenario, paused()) || release() === 'releasing' ? 'shadow' : 'auto';
        const controlState = () => ({
          ...state,
          paused: paused(),
          holdReleased: state.holdReleased || scenario.hold === 'none',
        });
        if (req.method === 'GET' && (path === '/__frame' || path.endsWith('/__frame.html'))) {
          res.statusCode = 200;
          res.setHeader('Content-Type', 'text/html; charset=utf-8');
          return void res.end(framePage(url.searchParams.get('route') ?? 'home'));
        }
        state.configVersion = configState.version;
        const mqtt = () => {
          let broker = brokers.get(key);
          if (!broker) {
            broker = initialMqtt();
            brokers.set(key, broker);
          }
          settleMqtt(broker, now);
          return broker;
        };
        const integrations = (current: ConfigDoc) =>
          withOutside(withMqtt(current, mqtt(), scenario), scenario);
        const doc = () => {
          const current = integrations(scenarioConfig(configDoc(configState, paused()), scenario));
          return release() === 'releasing'
            ? { ...current, mode: { ...current.mode, effective: 'shadow' as const } }
            : current;
        };
        const modeDoc = () => doc().mode;
        const stove = () => stoveMock(scenario, stoveRequests.get(key) ?? null, now, doc());
        const stoveOn = () => stoveActiveAt(stove(), now);
        const configAt = configAtFor(configState);
        const comfort = () => configAt(now).comfortC;
        const decisionOptions = {
          roomStaleSince: scenario.room === 'stale' ? now - ROOM_STALE_S * 1000 : null,
          stove: stove(),
          configAt,
        };
        const holdActive = () =>
          Boolean(withScenario(makeControl(now, controlState()), scenario, now).adapter?.hold);
        const stored = configState.stored['control_outside_signal'];
        const outsideSignal = scenario.outside
          ? OUTSIDE_SIGNAL
          : typeof stored === 'string' && stored
            ? stored
            : null;
        const decisionAt = (ms: number) =>
          withOutsideDecision(
            scenarioDecision(
              makeDecision(ms, now, mode(), decisionOptions),
              scenario,
              holdActive(),
              paused(),
            ),
            outsideSignal,
            scenario.outside === 'stale',
          );
        const pumpWater = () => pumpWaterOf(decisionAt, now);
        const envelopeFacts = () =>
          (
            makeAbout(now, scenario, doc(), paused()) as {
              safety_net: { envelope_rule: EnvelopeFacts };
            }
          ).safety_net.envelope_rule;
        const control = () => {
          const current = releasing(
            stoveRoom(
              {
                ...withScenario(makeControl(now, controlState(), pumpWater()), scenario, now),
                stove: stoveStatus(stove(), stoveRequests.get(key) ?? null, now, comfort()),
              },
              stoveOn(),
            ),
            release() === 'releasing',
          );
          const extra = scenario.alarms === 'none' ? [] : integrationAlarms(mqtt(), scenario, now);
          return extra.length > 0 ? { ...current, alarms: [...current.alarms, ...extra] } : current;
        };

        if (
          scenario.newapi === 'missing' &&
          (WAVE3_PATHS.some((p) => path.endsWith(`/api/v1${p}`)) ||
            WAVE3_PREFIXES.some((p) => path.includes(`/api/v1${p}`)))
        )
          return send({ detail: 'Not Found' }, 404);
        const replayContext = (): ReplayContext => ({
          now,
          key,
          scenario,
          version: configState.version,
          stored: configState.stored,
          versions: configState.versions,
        });
        const publishing = !inShadow(scenario, paused());

        if (req.method === 'POST' || req.method === 'PUT') {
          if (!path.includes('/api/v1/')) return next();
          if (!String(req.headers['content-type'] ?? '').startsWith('application/json'))
            return send({ detail: 'content type must be application/json' }, 415);
          if (req.headers['x-ovenbird-request'] !== '1')
            return send({ detail: 'missing X-Ovenbird-Request header' }, 403);
          return void readBody(req).then((body) => {
            if (path.endsWith('/config/validate'))
              return send(
                validate(configState, (body['changes'] ?? {}) as Record<string, unknown>),
              );
            if (path.endsWith('/config/preview')) {
              const hours = body['hours'] ?? 24;
              if (typeof hours !== 'number' || hours < 1 || hours > 72)
                return send({ detail: 'hours must be a number from 1 to 72' }, 400);
              return send(
                preview(
                  configState,
                  (body['changes'] ?? {}) as Record<string, unknown>,
                  hours,
                  now,
                ),
              );
            }
            if (req.method === 'PUT' && path.endsWith('/api/v1/config')) {
              const result = apply(configState, body, now, paused());
              return send(withScenarioDoc(result.body, scenario, integrations), result.status);
            }
            if (path.endsWith('/config/rollback')) {
              const result = rollback(configState, body, now, paused());
              return send(withScenarioDoc(result.body, scenario, integrations), result.status);
            }
            if (path.endsWith('/api/v1/config/mqtt/test') || path.endsWith('/api/v1/config/mqtt')) {
              if (scenario.role === 'viewer')
                return send({ detail: 'this action needs the admin role' }, 403);
              if (path.endsWith('/test')) {
                const result = mqttTest(mqtt(), body, scenario, now);
                return send(result.body, result.status);
              }
              if (req.method !== 'PUT') return send({ detail: 'Method Not Allowed' }, 405);
              const result = mqttApply(mqtt(), body, scenario, now);
              if (result.status !== 200) return send(result.body, result.status);
              return send({ config: doc(), mqtt: mqttStatus(mqtt(), scenario, now) });
            }
            if (req.method === 'PUT' && path.endsWith('/api/v1/config/ha')) {
              const result = setConnection(configState, body, paused());
              return send(result.body, result.status);
            }
            if (path.endsWith('/config/ha/test')) {
              const fields = configDoc(configState, paused()).fields;
              const active = [
                'control_room_signal',
                'control_room_liveness_signals',
                'control_room_crosscheck_signal',
                'control_stove_reference_signal',
                'control_outside_signal',
              ].flatMap((id) => {
                const value = fields[id]?.value;
                return (Array.isArray(value) ? value : [value]).filter(
                  (v): v is string => typeof v === 'string',
                );
              });
              const result = testConnection(configState, body, active);
              return send(result.body, result.status);
            }
            if (path.endsWith('/config/reset-ack'))
              return send({ detail: 'no configuration reset is pending' }, 409);
            const pumpMatch = /\/pump\/settings\/([a-z_]+)$/.exec(path);
            if (pumpMatch) {
              const result = writeSetting(pump, pumpMatch[1] as string, body, now, paused());
              return send(result.body, result.status);
            }
            if (path.endsWith('/control/release-hold')) {
              if (state.holdReleased) return send({ detail: 'no hold' }, 409);
              state.holdReleased = true;
              return send({
                released: { reason: 'foreign writer', until: null, latched: false, incident: 2 },
                by: `admin from 127.0.0.1${body['reason'] ? `: ${String(body['reason'])}` : ''}`,
                hold: null,
                safety_hold: [],
                control: control(),
              });
            }
            if (path.endsWith('/api/v1/control/release')) {
              const result = startRelease(key, body, now, scenario, publishing);
              return result.status < 300
                ? send({ ...(result.body as object), control: control() }, result.status)
                : send(result.body, result.status);
            }
            if (path.endsWith('/api/v1/control/snapshot')) {
              const result = captureSnapshot(key, now, scenario, publishing);
              return send(result.body, result.status);
            }
            if (path.endsWith('/api/v1/shadow/episodes/explain')) {
              const result = explainEpisode(key, body, now);
              return send(result.body, result.status);
            }
            if (path.endsWith('/api/v1/notifications/test')) {
              const result = testNotification(now, scenario, key);
              return send(result.body, result.status);
            }
            if (path.endsWith('/api/v1/replay')) {
              const result = startReplay(replayContext(), body);
              return send(result.body, result.status);
            }
            const cancelMatch = /\/api\/v1\/replay\/([a-z0-9]+)\/cancel$/.exec(path);
            if (cancelMatch) {
              const result = cancelReplay(cancelMatch[1] as string, scenario);
              return send(result.body, result.status);
            }
            if (path.endsWith('/api/v1/archive/delete')) {
              const result = archiveDelete(body, now, doc(), key, scenario);
              return send(result.body, result.status);
            }
            if (path.endsWith('/api/v1/history/compact')) {
              if (scenario.role === 'viewer')
                return send({ detail: 'this action needs the admin role' }, 403);
              return send(compact(now, key), 202);
            }
            if (path.endsWith('/api/v1/insight/house/proposal/draft')) {
              const result = makeProposalDraft(now, scenario, doc());
              return send(result.body, result.status);
            }
            if (path.endsWith('/control/stove')) {
              const on = body['on'];
              const untilRaw = body['until'];
              if (typeof on !== 'boolean') return send({ detail: 'on must be true or false' }, 400);
              if (!stove().enabled) return send({ detail: 'wood-stove mode is not enabled' }, 409);
              let untilMs: number | null = null;
              if (untilRaw !== undefined && untilRaw !== null) {
                untilMs = typeof untilRaw === 'string' ? Date.parse(untilRaw) : NaN;
                if (!Number.isFinite(untilMs))
                  return send({ detail: 'until must be an ISO time' }, 400);
                if (untilMs <= now) return send({ detail: 'until lies in the past' }, 400);
                if (untilMs > now + STOVE_MAX_AHEAD_MS)
                  return send({ detail: 'until lies more than 24 h ahead' }, 400);
              } else if (on) untilMs = now + STOVE_DEFAULT_H * HOUR;
              const request: StoveRequestState = {
                on,
                untilMs,
                atMs: now,
                actor: 'admin from 127.0.0.1',
              };
              stoveRequests.set(key, request);
              const status = stoveStatus(stove(), request, now);
              return send({
                request: status.request,
                stove: status,
              });
            }
            if (path.endsWith('/control/pause')) {
              state.paused = true;
              return send({ mode: modeDoc(), control: control() });
            }
            if (path.endsWith('/control/resume')) {
              const refused = resumeRelease(key, now);
              if (refused)
                return send({ ...(refused.body as object), mode: modeDoc() }, refused.status);
              state.paused = false;
              return send({ mode: modeDoc(), control: control() });
            }
            return send({ detail: 'not found' }, 404);
          });
        }

        const csv = param('format') === 'csv';
        if (param('format') !== null && !['csv', 'json'].includes(param('format') ?? ''))
          return send({ detail: 'format must be json or csv' }, 422);

        if (path.endsWith('/api/v1/health')) return send(health);
        if (path.endsWith('/api/v1/snapshot'))
          return send(
            withWaterTarget(stoveRoom(makeSnapshot(now, scenario), stoveOn()), pumpWater()),
          );
        if (path.endsWith('/api/v1/history')) {
          const ids = (param('signals') ?? '').split(',').filter(Boolean);
          const step = param('step');
          if (step !== null && !['0', '60', '900', '3600'].includes(step))
            return send({ detail: 'step must be 0, 60, 900 or 3600' }, 400);
          const history = makeHistory(
            ids,
            from,
            Math.min(to, now),
            step === null ? null : Number(step),
            scenario,
            now,
          );
          if (csv)
            return sendCsv(
              res,
              'history',
              from,
              Object.entries(history.series).flatMap(([signal, series]) =>
                series.points.map(([at, value]) => ({ signal, unit: series.unit, at, value })),
              ),
            );
          return send(history);
        }
        if (path.endsWith('/api/v1/decisions/latest')) {
          return send({ decision: decisionAt(now), control: control() });
        }
        if (path.endsWith('/api/v1/decisions/series')) {
          const span = to - from;
          const step = Number(
            param('step') ?? (span <= 6 * HOUR ? 0 : span <= 36 * HOUR ? 300 : 3600),
          );
          if (![0, 300, 900, 3600].includes(step))
            return send({ detail: 'step must be 0, 300, 900 or 3600' }, 400);
          return send(makeSeries(from, to, step, now, stove(), configAt));
        }
        if (path.endsWith('/api/v1/decisions')) {
          const limit = Math.min(Math.max(Number(param('limit') ?? 500), 1), 5000);
          const decisions = makeDecisions(from, to, limit, now, decisionOptions).map((d) => ({
            ...d,
            mode: mode(),
          }));
          if (csv)
            return sendCsv(
              res,
              'decisions',
              from,
              decisions.map((d) => ({ ...d, reason: d.record?.reason ?? null })),
            );
          return send({
            from: new Date(from).toISOString(),
            to: new Date(to).toISOString(),
            limit,
            decisions,
          });
        }
        if (path.endsWith('/api/v1/commands')) {
          const commands = makeCommands(now).filter((command) => {
            const at = Date.parse(command.at);
            return at >= from && at <= to;
          });
          if (csv) return sendCsv(res, 'commands', from, commands);
          return send({
            from: new Date(from).toISOString(),
            to: new Date(to).toISOString(),
            limit: 500,
            commands,
          });
        }
        if (path.endsWith('/api/v1/alarms')) {
          const alarms = makeAlarms(
            now,
            scenario.hold === 'none'
              ? { ...state, holdReleased: true }
              : scenario.hold
                ? { ...state, holdReleased: false }
                : state,
            stove(),
            scenario.hold === 'latched',
          );
          const notifyEvents =
            scenario.notify === 'failing' && scenario.alarms !== 'none'
              ? [
                  {
                    at: notifyFailingSince(now),
                    code: 'notify_failing',
                    severity: 'warning' as const,
                    event: 'raised',
                    message: NOTIFY_FAILING_MESSAGE,
                    detail: {},
                  },
                ]
              : [];
          const events = [...alarms.events, ...notifyEvents].sort(
            (a, b) => Date.parse(a.at) - Date.parse(b.at),
          );
          const windowed = inWindow({ ...alarms, events, active: control().alarms }, from, to);
          if (csv) return sendCsv(res, 'alarms', from, windowed.events);
          return send(windowed);
        }
        if (path.endsWith('/api/v1/config')) return send(doc());
        if (path.endsWith('/api/v1/config/schema')) return send(schema);
        if (path.endsWith('/api/v1/config/signals'))
          return send(
            makeSignals(
              now,
              scenario.room === 'stale',
              configState.stored['mqtt_inputs'],
              scenario.outside === 'stale',
            ),
          );
        if (path.endsWith('/api/v1/config/mqtt')) return send(mqttStatus(mqtt(), scenario, now));
        if (path.endsWith('/api/v1/config/export')) {
          res.setHeader(
            'Content-Disposition',
            `attachment; filename="ovenbird-config-v${configState.version}.json"`,
          );
          return send(exportDoc(configState, now, paused()));
        }
        if (path.endsWith('/api/v1/config/versions'))
          return send(versionsList(configState, Number(param('limit') ?? 50)));
        const versionMatch = /\/config\/versions\/(\d+)$/.exec(path);
        if (versionMatch) {
          const found = configState.versions.find((v) => v.version === Number(versionMatch[1]));
          return found ? send(found) : send({ detail: 'not found' }, 404);
        }
        if (path.endsWith('/api/v1/weather')) {
          const invalid = [
            ...(rangeError('back_h', param('back_h'), 168) ?? []),
            ...(rangeError('ahead_h', param('ahead_h'), 72) ?? []),
          ];
          if (invalid.length > 0) return send({ detail: invalid }, 422);
          const current = doc();
          const value = (id: string) => current.fields[id]?.value;
          const weather = makeWeather(
            now - (scenario.weather === 'stale' ? 3 * HOUR : 0),
            Number(param('back_h') ?? 24),
            Number(param('ahead_h') ?? 48),
            {
              enabled: value('weather_enabled') === true && scenario.weather !== 'off',
              source: String(value('weather_location_source') ?? 'ha_zone_home'),
              latitude: (value('weather_latitude') as number | null) ?? null,
              longitude: (value('weather_longitude') as number | null) ?? null,
              curve: value('control_curve') as Curve,
            },
          );
          if (scenario.weather === 'stale' && weather.enabled)
            return send({ ...weather, age: 3 * 3600 + 1200, stale: true });
          return send(weather);
        }
        if (path.endsWith('/api/v1/pump/settings'))
          return scenario.pumpsettings === 'missing'
            ? send({ detail: 'Not Found' }, 404)
            : send(pumpSettings(pump, now, paused()));
        if (path.endsWith('/api/v1/insight/daily')) {
          const days = Number(param('days') ?? 7);
          if (!Number.isInteger(days) || days < 1 || days > 90)
            return send({ detail: 'days must be an integer from 1 to 90' }, 422);
          return send(makeInsightDaily(days, now));
        }
        if (path.endsWith('/api/v1/audit')) {
          const audit = inWindow(
            {
              limit: Math.min(Math.max(Number(param('limit') ?? 500), 1), 5000),
              events: [
                ...makeAudit(now, stoveRequests.get(key) ?? manualRequest(stove())),
                ...mqtt().audit,
              ].sort((a, b) => Date.parse(a.at) - Date.parse(b.at)),
            },
            from,
            to,
          );
          if (csv) return sendCsv(res, 'audit', from, audit.events);
          return send(audit);
        }
        if (path.endsWith('/api/v1/shadow/divergence')) {
          const span = to - from;
          if (!(span > 0) || span > 31 * 24 * HOUR)
            return send({ detail: 'the window must be positive and at most 31 days' }, 400);
          const raw = param('step');
          if (raw !== null && !['60', '300', '900', '3600'].includes(raw))
            return send({ detail: 'step must be 60, 300, 900 or 3600' }, 400);
          const step =
            raw === null
              ? ([60, 300, 900, 3600].find((s) => span / 1000 / s <= 1500) ?? 3600)
              : Number(raw);
          const threshold = Number(param('threshold_k') ?? 1);
          const hold = holdActive();
          const live = (ms: number): LiveMinute | null => {
            if (ms < now - LIVE_MS || ms > now) return null;
            const decision = scenarioDecision(
              makeDecision(ms, now, mode(), decisionOptions),
              scenario,
              hold && ms >= now - HOLD_LIVE_MS,
              paused(),
            );
            const water = decision.arbiter.find((entry) => entry.kind === 'water_setpoint');
            return {
              ovenbird: decision.setpoint,
              pump: water?.actual ?? null,
              mode: mode(),
              reason: decision.reason,
            };
          };
          return send(
            withExplained(key, makeDivergence(from, to, step, threshold, now, scenario, live)),
          );
        }
        if (path.endsWith('/api/v1/trial/status'))
          return send(makeTrialStatus(now, scenario, key, paused(), envelopeFacts()));
        if (path.endsWith('/api/v1/insight/runs')) {
          const days = Number(param('days') ?? 7);
          if (!Number.isInteger(days) || days < 1 || days > 90)
            return send({ detail: 'days must be an integer from 1 to 90' }, 422);
          return send(makeRuns(days, now));
        }
        if (path.endsWith('/api/v1/control/snapshot'))
          return send(makeSnapshotState(now, scenario, publishing, key));
        if (path.endsWith('/api/v1/control/release')) return send(releaseState(key, now));
        if (path.endsWith('/api/v1/notifications/status'))
          return send(makeNotifications(now, scenario, key));
        if (path.endsWith('/api/v1/system/about'))
          return send(makeAbout(now, scenario, doc(), paused(), release() === 'releasing'));
        if (path.endsWith('/api/v1/diagnostics')) {
          const format = param('format') ?? 'json';
          if (format !== 'json') return send({ detail: 'the mock serves format=json only' }, 422);
          res.setHeader(
            'Content-Disposition',
            `attachment; filename="ovenbird-diagnostics-${new Date(now).toISOString().slice(0, 10)}.json"`,
          );
          return send(makeDiagnostics(now, scenario));
        }
        if (path.endsWith('/api/v1/replay/coverage'))
          return send(
            makeCoverage(replayContext(), param('from') ? from : null, param('to') ? to : null),
          );
        const jobMatch = /\/api\/v1\/replay\/([a-z0-9]+)$/.exec(path);
        if (jobMatch) {
          const result = replayJob(jobMatch[1] as string);
          return send(result.body, result.status);
        }
        if (path.endsWith('/api/v1/history/signals')) return send(makeHistorySignals(now));
        if (path.endsWith('/api/v1/history/storage')) return send(makeStorage(now, doc(), key));
        if (path.endsWith('/api/v1/export/series'))
          return sendDownload(res, seriesExport(url.searchParams, now));
        if (path.endsWith('/api/v1/export/archive'))
          return sendDownload(res, archiveExport(now, scenario));
        if (path.endsWith('/api/v1/archive')) return send(makeArchive(now, doc(), key, scenario));
        const archived = /\/api\/v1\/archive\/(months|years|seasons)\/([^/]+)$/.exec(path);
        if (archived)
          return sendDownload(
            res,
            archiveDownload(archived[1] ?? '', archived[2] ?? '', now, key, scenario),
          );
        const journal = /\/api\/v1\/export\/journal\/([a-z]+)$/.exec(path);
        if (journal) {
          const kind = journal[1] ?? '';
          const rows = (start: number, end: number): readonly object[] => {
            const inside = (at: string) => Date.parse(at) >= start && Date.parse(at) < end;
            if (kind === 'decisions')
              return makeDecisions(
                Math.max(start, end - 48 * HOUR),
                end,
                5000,
                now,
                decisionOptions,
              )
                .map((d) => ({ ...d, mode: mode(), reason: d.record?.reason ?? null }))
                .filter((d) => inside(d.at));
            if (kind === 'commands') return makeCommands(now).filter((c) => inside(c.at));
            if (kind === 'alarms')
              return makeAlarms(now, state, stove(), scenario.hold === 'latched').events.filter(
                (e) => inside(e.at),
              );
            return [];
          };
          return sendDownload(res, journalExport(kind, url.searchParams, now, rows));
        }
        if (path.endsWith('/api/v1/insight/house/history')) {
          const result = makeHouseHistory(now, scenario, doc());
          return send(result.body, result.status);
        }
        if (path.endsWith('/api/v1/insight/house')) {
          const result = makeHouse(now, scenario, doc());
          return send(result.body, result.status);
        }
        next();
      });
    },
  };
}
