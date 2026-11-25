import { asCurve, curveWater } from '../src/lib/core/curve.ts';
import type { ConfigDoc } from '../src/lib/core/types';
import { health } from './fixtures.ts';
import type { Scenario } from './scenario.ts';
import type { MockResult } from './trial.ts';

const MINUTE = 60_000;
const HOUR = 3_600_000;
const DAY = 24 * HOUR;
const OUTSIDE_C = 4.2;

interface TestRecord {
  at: string;
  ok: boolean;
  error: string | null;
  by: string;
}

const tests = new Map<string, TestRecord>();

const iso = (ms: number) => new Date(ms).toISOString();

function numberField(doc: ConfigDoc, id: string, fallback: number): number {
  const value = doc.fields[id]?.value;
  return typeof value === 'number' ? value : fallback;
}

/**
 * The envelope band around the envelope curve at the mock's outside temperature.
 */
function envelopeNow(doc: ConfigDoc): { outside_c: number; low_c: number; high_c: number } {
  const curve = asCurve(doc.fields['control_envelope_curve']?.value) ?? [
    [-10, 39],
    [0, 34],
    [15, 25],
  ];
  const middle = curveWater(curve, OUTSIDE_C);
  const round = (value: number) => Math.round(value * 10) / 10;
  return {
    outside_c: OUTSIDE_C,
    low_c: round(middle - numberField(doc, 'control_envelope_below_k', 6)),
    high_c: round(middle + numberField(doc, 'control_envelope_above_k', 5)),
  };
}

/**
 * `GET system/about`: the installation's facts under the scenario. The envelope rule is declared
 * by default, proven with `envelope:proven` and not declared with `envelope:none`. `releasing`:
 * a release of control restores the go-live snapshot (the controller is stopped meanwhile).
 */
export function makeAbout(
  now: number,
  scenario: Scenario,
  doc: ConfigDoc,
  paused: boolean,
  releasing = false,
): unknown {
  const shadow = scenario.mode === 'shadow';
  const inShadow = paused || scenario.mode !== undefined;
  const band = envelopeNow(doc);
  const state =
    scenario.envelope === 'proven'
      ? 'proven'
      : scenario.envelope === 'none'
        ? 'not_declared'
        : 'declared';
  const started = now - 3 * DAY - 5 * HOUR - 12 * MINUTE;
  const proof =
    state === 'proven'
      ? {
          at: iso(now - 2 * DAY - 3 * HOUR),
          from_c: 45,
          to_c: Math.round((band.low_c + band.high_c) / 2),
          outside_c: 3.1,
          low_c: band.low_c - 0.6,
          high_c: band.high_c - 0.6,
        }
      : null;
  return {
    version: health.version,
    api_version: health.api_version,
    service_time: iso(now),
    timezone: String(doc.fields['control_timezone']?.value ?? 'UTC'),
    started_at: iso(started),
    uptime_s: Math.round((now - started) / 1000),
    service_starts: 7,
    previous_start: iso(started - 6 * DAY),
    failing_components: {},
    restored_state: true,
    setpoint_register: String(doc.fields['command_setpoint_register']?.value ?? ''),
    control_interval_s: numberField(doc, 'control_interval_s', 60),
    control: {
      mode: inShadow || releasing ? 'shadow' : 'auto',
      configured_mode: shadow ? 'shadow' : 'auto',
      interval_s: numberField(doc, 'control_interval_s', 60),
      ticks: Math.round((now - started) / MINUTE),
      last_tick_at: iso(Math.floor(now / MINUTE) * MINUTE),
      publishing: !inShadow,
      paused: paused || scenario.mode === 'paused',
      releasing,
      restored_state: true,
    },
    connections: {
      mqtt: {
        connected: true,
        tls: false,
        heishamon_base: 'panasonic_heat_pump',
        heishamon_alive: true,
      },
      ha: { configured: true, connected: true },
      integration_token: false,
    },
    simulation: scenario.simulation === 'on',
    clock_speed: scenario.simulation === 'on' ? 60 : 1,
    safety_net: {
      envelope_rule: {
        installed: state !== 'not_declared',
        state,
        count: proof ? 1 : 0,
        first_at: proof?.at ?? null,
        last: proof,
        adopted: inShadow ? null : state === 'proven' ? 1 : 0,
      },
      envelope_now: band,
      max_supply_c: numberField(doc, 'control_max_supply_c', 40),
      min_setpoint_c: numberField(doc, 'control_min_setpoint_c', 24),
      envelope_below_k: numberField(doc, 'control_envelope_below_k', 6),
      envelope_above_k: numberField(doc, 'control_envelope_above_k', 5),
      ovenbird_corrections: { recent: 0, limit: 3, window_s: 3600, total: 0 },
    },
  };
}

const FAILED_SENDS = 3;
const FAILING_SINCE_MS = 70 * MINUTE;

/**
 * Since when notifications fail under `notify:failing` (the `notify_failing` alarm's start).
 */
export function notifyFailingSince(now: number): string {
  return iso(now - FAILING_SINCE_MS);
}

/** The `notify_failing` alarm message under `notify:failing`. */
export const NOTIFY_FAILING_MESSAGE = `the last ${FAILED_SENDS} notifications could not be sent: HTTP 403`;

/**
 * `GET notifications/status`: configured and healthy by default; `notify:off` has no channel,
 * `notify:failing` a failed last test, the last sends failed and an unhealthy dead-man ping.
 * `health` is the service's one verdict (the System tile and the trial checklist). A test sent
 * from this browser (`POST notifications/test`) shows up as the last test.
 */
export function makeNotifications(now: number, scenario: Scenario, key: string): unknown {
  if (scenario.notify === 'off')
    return {
      ntfy: {
        configured: false,
        server: null,
        token: false,
        min_severity: 'warning',
        events: false,
        sent: 0,
        suppressed: 0,
        dropped: 0,
        queued: 0,
        last_sent: null,
        last_error: null,
        last_test: null,
        rate_limit_per_hour: 20,
      },
      deadman: {
        configured: false,
        server: null,
        interval_s: 300,
        pings: 0,
        last_ok: null,
        last_error: null,
        last_skip: null,
        healthy: false,
        unhealthy_reason: 'not configured',
      },
      health: {
        state: 'not_configured',
        reason: 'ntfy is not configured',
        failing_since: null,
        failures_in_row: 0,
        pending: [],
        deadman_state: 'not_configured',
      },
    };
  const failing = scenario.notify === 'failing';
  const test: TestRecord = tests.get(key) ?? {
    at: iso(now - 26 * HOUR),
    ok: !failing,
    error: failing ? 'HTTP 403 from ntfy.sh' : null,
    by: 'admin from 192.168.1.20',
  };
  return {
    ntfy: {
      configured: true,
      server: 'ntfy.sh',
      token: true,
      min_severity: 'warning',
      events: false,
      sent: failing ? 1 : 4,
      suppressed: 1,
      dropped: failing ? FAILED_SENDS : 0,
      queued: 0,
      last_sent: {
        at: iso(now - 2 * HOUR - 14 * MINUTE),
        title: 'ovenbird warning: foreign_writer',
      },
      last_error: failing ? { at: iso(now - 40 * MINUTE), error: 'HTTP 403 from ntfy.sh' } : null,
      last_test: test,
      rate_limit_per_hour: 20,
    },
    deadman: {
      configured: true,
      server: 'hc-ping.com',
      interval_s: 300,
      pings: failing ? 12 : 288,
      last_ok: iso(now - (failing ? 3 * HOUR : 3 * MINUTE)),
      last_error: failing ? { at: iso(now - 2 * MINUTE), error: 'timeout after 10 s' } : null,
      last_skip: null,
      healthy: !failing,
      unhealthy_reason: failing ? 'no successful ping for 3 h' : null,
    },
    health: failing
      ? {
          state: 'failing',
          reason: `the last ${FAILED_SENDS} sends failed: HTTP 403`,
          failing_since: notifyFailingSince(now),
          failures_in_row: FAILED_SENDS,
          pending: [],
          deadman_state: 'failing',
        }
      : {
          state: test.ok ? 'ok' : 'failing',
          reason: test.ok ? null : `the last test failed: ${test.error}`,
          failing_since: test.ok ? null : test.at,
          failures_in_row: 0,
          pending: [],
          deadman_state: 'ok',
        },
  };
}

/**
 * `POST notifications/test` for a browser: 409 without ntfy; otherwise the test is recorded
 * (failing under `notify:failing`).
 */
export function testNotification(now: number, scenario: Scenario, key: string): MockResult {
  if (scenario.notify === 'off')
    return { status: 409, body: { detail: 'notifications are not configured' } };
  const failing = scenario.notify === 'failing';
  const test: TestRecord = {
    at: iso(now),
    ok: !failing,
    error: failing ? 'HTTP 403 from ntfy.sh' : null,
    by: 'admin from 127.0.0.1',
  };
  tests.set(key, test);
  return { status: 200, body: { test, status: makeNotifications(now, scenario, key) } };
}

/**
 * `GET diagnostics?format=json`: a small redacted bundle.
 */
export function makeDiagnostics(now: number, scenario: Scenario): unknown {
  return {
    version: health.version,
    generated: iso(now),
    health,
    notifications: makeNotifications(now, scenario, ''),
    config: { effective: { notify_ntfy_topic: 'set', notify_deadman_url: 'set' } },
    decisions: [],
    commands: [],
    alarms: [],
  };
}
