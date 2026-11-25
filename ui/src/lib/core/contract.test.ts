import { EventEmitter } from 'node:events';
import { readdirSync, readFileSync } from 'node:fs';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { mockApi } from '$mock/plugin';
import { SCENARIO_COOKIE, SCENARIO_OPTIONS } from '$mock/scenario';
import { responseSchema, templateOf, violations, type OpenApi } from './contract';

const api = JSON.parse(
  readFileSync(new URL('../../../../docs/openapi.json', import.meta.url), 'utf8'),
) as OpenApi;
const FIXTURES = new URL('../../../mock/fixtures/', import.meta.url);

interface Answer {
  status: number;
  type: string;
  body: string;
}

type Middleware = (req: unknown, res: unknown, next: () => void) => void;

function mockServer(): Middleware {
  let middleware: Middleware | null = null;
  const plugin = mockApi() as { configureServer: (server: unknown) => void };
  plugin.configureServer({ middlewares: { use: (fn: Middleware) => (middleware = fn) } });
  if (!middleware) throw new Error('the mock plugin registered no middleware');
  return middleware;
}

function call(
  server: Middleware,
  method: string,
  url: string,
  cookie: string,
  body?: unknown,
): Promise<Answer | null> {
  return new Promise((resolve) => {
    const req = Object.assign(new EventEmitter(), {
      method,
      url,
      headers: {
        cookie,
        'content-type': 'application/json',
        'x-ovenbird-request': '1',
      },
    });
    const headers: Record<string, string> = {};
    const res = {
      statusCode: 200,
      setHeader: (name: string, value: string) => (headers[name.toLowerCase()] = value),
      end: (text: string) =>
        resolve({ status: res.statusCode, type: headers['content-type'] ?? '', body: text }),
    };
    server(req, res, () => resolve(null));
    if (method !== 'GET') {
      req.emit('data', Buffer.from(JSON.stringify(body ?? {})));
      req.emit('end');
    }
  });
}

/**
 * Where a JSON body of `method path` with `status` breaks the contract; `null` when the
 * contract describes no JSON body for that status (errors without a model).
 */
function check(method: string, path: string, status: number, body: unknown): string[] | null {
  const template = templateOf(api, path);
  if (template === null) return [`${method} ${path}: not in the contract`];
  const schema = status < 300 ? responseSchema(api, method, template, status) : null;
  if (schema === null) return null;
  return violations(api, schema, body).map((line) => `${method} ${path} ${status} ${line}`);
}

const GETS = Object.entries(api.paths)
  .filter(([path, item]) => 'get' in item && !path.includes('{'))
  .map(([path]) => path);

const WRITES: [string, string, unknown][] = [
  ['POST', '/api/v1/config/validate', { changes: { control_comfort_c: 21.4 } }],
  ['POST', '/api/v1/config/preview', { changes: { control_comfort_c: 21.4 }, hours: 24 }],
  ['POST', '/api/v1/control/pause', { reason: 'contract test' }],
  ['POST', '/api/v1/control/resume', {}],
  ['POST', '/api/v1/control/stove', { on: true }],
  ['POST', '/api/v1/control/release-hold', {}],
  ['POST', '/api/v1/pump/settings/heat_delta', { value: 4, expect: 5 }],
  ['POST', '/api/v1/control/snapshot', {}],
  ['POST', '/api/v1/control/release', { rehearsal: true, dry: true }],
  ['POST', '/api/v1/shadow/episodes/explain', { start: '2026-11-15T10:00:00Z', note: 'x' }],
  ['POST', '/api/v1/notifications/test', {}],
  ['POST', '/api/v1/insight/house/proposal/draft', {}],
  ['POST', '/api/v1/config/reset-ack', {}],
  ['POST', '/api/v1/history/compact', {}],
  ['POST', '/api/v1/replay', { from: '2026-11-14T00:00:00Z', to: '2026-11-15T00:00:00Z' }],
  ['POST', '/api/v1/config/mqtt/test', { host: 'broker.local' }],
  ['PUT', '/api/v1/config/mqtt', { host: 'broker.local' }],
];

function monthsAgo(n: number): string {
  const date = new Date();
  date.setUTCDate(1);
  date.setUTCMonth(date.getUTCMonth() - n);
  return date.toISOString().slice(0, 7);
}

const SCENARIOS = [
  '',
  ...Object.entries(SCENARIO_OPTIONS).flatMap(([key, options]) =>
    options.map((option) => `${SCENARIO_COOKIE}=${key}:${option}`),
  ),
];

async function sweep(cookie: string): Promise<{ problems: string[]; checked: number }> {
  const server = mockServer();
  const problems: string[] = [];
  let checked = 0;
  const record = async (method: string, path: string, query: string, body?: unknown) => {
    const answer = await call(server, method, path + query, cookie, body);
    if (answer === null || !answer.type.startsWith('application/json')) return;
    const found = check(method, path, answer.status, JSON.parse(answer.body));
    if (found !== null) checked += 1;
    problems.push(...(found ?? []));
  };
  for (const path of GETS) await record('GET', path, '');
  const config = await call(server, 'GET', '/api/v1/config', cookie);
  const version = config ? (JSON.parse(config.body) as { version: number }).version : 0;
  await record('GET', `/api/v1/config/versions/${version}`, '');
  for (const [method, path, body] of WRITES) await record(method, path, '', body);
  await record('PUT', '/api/v1/config', '', {
    base_version: version,
    changes: { control_comfort_c: 21.6 },
  });
  await record('POST', '/api/v1/config/rollback', '', { version, base_version: version + 1 });
  await record('POST', '/api/v1/archive/delete', '', { period: monthsAgo(3) });
  return { problems, checked };
}

describe('the mock API answers what the contract describes', () => {
  it.each(SCENARIOS)('scenario %j', async (cookie) => {
    const { problems, checked } = await sweep(cookie);
    expect(problems).toEqual([]);
    expect(checked).toBeGreaterThan(GETS.length / 2);
  });
});

describe('the mock replay', () => {
  afterEach(() => vi.useRealTimers());

  it('answers a finished job, its coverage and a cancel as the contract describes', async () => {
    vi.useFakeTimers({ now: Date.parse('2026-11-20T12:00:00Z'), toFake: ['Date'] });
    const server = mockServer();
    const started = await call(server, 'POST', '/api/v1/replay', '', {
      from: '2026-11-19T00:00:00Z',
      to: '2026-11-20T00:00:00Z',
      config: 'draft',
      changes: { control_comfort_c: 21.6 },
    });
    expect(started?.status).toBe(202);
    const job = JSON.parse(started!.body) as { id: string; state: string };
    expect(job.state).toBe('running');
    vi.setSystemTime(Date.parse('2026-11-20T12:00:05Z'));
    const done = await call(server, 'GET', `/api/v1/replay/${job.id}`, '');
    const body = JSON.parse(done!.body) as {
      state: string;
      result: {
        ticks: number;
        series: { at: unknown[]; replayed: (number | null)[]; recorded: (number | null)[] };
        episodes: { ovenbird_c: number }[];
      };
    };
    expect(body.state).toBe('done');
    expect(body.result.ticks).toBeGreaterThan(0);
    expect(body.result.series.at.length).toBeGreaterThan(0);
    const issued = [...body.result.series.replayed, ...body.result.series.recorded].filter(
      (value): value is number => value !== null,
    );
    expect(issued.length).toBeGreaterThan(0);
    expect(issued.every(Number.isInteger)).toBe(true);
    expect(body.result.episodes.every((ep) => Number.isInteger(ep.ovenbird_c))).toBe(true);
    expect(check('GET', `/api/v1/replay/${job.id}`, 200, body)).toEqual([]);
    const coverage = await call(server, 'GET', '/api/v1/replay/coverage', '');
    expect(check('GET', '/api/v1/replay/coverage', 200, JSON.parse(coverage!.body))).toEqual([]);
    const next = await call(server, 'POST', '/api/v1/replay', '', {
      from: '2026-11-19T00:00:00Z',
      to: '2026-11-20T00:00:00Z',
    });
    const id = (JSON.parse(next!.body) as { id: string }).id;
    const cancelled = await call(server, 'POST', `/api/v1/replay/${id}/cancel`, '', {});
    const cancelBody = JSON.parse(cancelled!.body) as { state: string };
    expect(cancelBody.state).toBe('cancelled');
    expect(check('POST', `/api/v1/replay/${id}/cancel`, 200, cancelBody)).toEqual([]);
    const missing = await call(server, 'GET', '/api/v1/replay/feedbeef', '');
    expect(missing?.status).toBe(404);
  });

  it('refuses a too long period, an unknown version and a viewer', async () => {
    const server = mockServer();
    const long = await call(server, 'POST', '/api/v1/replay', '', {
      from: '2026-09-01T00:00:00Z',
      to: '2026-11-01T00:00:00Z',
    });
    expect(long?.status).toBe(400);
    const unknown = await call(server, 'POST', '/api/v1/replay', '', {
      from: '2026-11-19T00:00:00Z',
      to: '2026-11-20T00:00:00Z',
      config: 'version',
      version: 999,
    });
    expect(unknown?.status).toBe(404);
    const viewer = await call(server, 'POST', '/api/v1/replay', `${SCENARIO_COOKIE}=role:viewer`, {
      from: '2026-11-19T00:00:00Z',
      to: '2026-11-20T00:00:00Z',
    });
    expect(viewer?.status).toBe(403);
  });
});

describe('the mock yearly archive', () => {
  it('lists, downloads and deletes months as the service does', async () => {
    const server = mockServer();
    const cookie = `${SCENARIO_COOKIE}=tag:archive`;
    const listed = await call(server, 'GET', '/api/v1/archive', cookie);
    const body = JSON.parse(listed!.body) as {
      months: { period: string; state: string }[];
      years: { id: string; months: string[] }[];
      seasons: { id: string; period: string }[];
    };
    const open = body.months[0]!;
    expect(open.state).toBe('open');
    expect(body.months.filter((m) => m.state === 'frozen').length).toBe(14);
    expect(body.seasons.every((s) => /^\d{4}\/\d{2}$/.test(s.period))).toBe(true);
    const month = await call(server, 'GET', `/api/v1/archive/months/${monthsAgo(2)}`, cookie);
    expect(month?.type).toBe('application/zip');
    const partial = await call(server, 'GET', `/api/v1/archive/months/${open.period}`, cookie);
    expect(partial?.status).toBe(200);
    const year = body.years.at(-1)!;
    const bundle = await call(server, 'GET', `/api/v1/archive/years/${year.id}`, cookie);
    expect(bundle?.type).toBe('application/zip');
    const season = await call(
      server,
      'GET',
      `/api/v1/archive/seasons/${body.seasons[0]!.id}`,
      cookie,
    );
    expect(season?.status).toBe(200);
    const bad = await call(server, 'GET', '/api/v1/archive/months/2026-13', cookie);
    expect(bad?.status).toBe(400);
    const busy = await call(server, 'POST', '/api/v1/archive/delete', cookie, {
      period: open.period,
    });
    expect(busy?.status).toBe(409);
    const gone = await call(server, 'POST', '/api/v1/archive/delete', cookie, {
      period: year.id,
    });
    const result = JSON.parse(gone!.body) as { deleted: string[]; archive: unknown };
    expect(result.deleted).toEqual(year.months);
    expect(check('POST', '/api/v1/archive/delete', 200, result)).toEqual([]);
    const again = await call(server, 'POST', '/api/v1/archive/delete', cookie, {
      period: year.id,
    });
    expect(again?.status).toBe(404);
  });

  it('refuses a viewer and answers 404 for an older service', async () => {
    const server = mockServer();
    const viewer = `${SCENARIO_COOKIE}=role:viewer`;
    const month = await call(server, 'GET', `/api/v1/archive/months/${monthsAgo(2)}`, viewer);
    expect(month?.status).toBe(403);
    const removed = await call(server, 'POST', '/api/v1/archive/delete', viewer, {
      period: monthsAgo(2),
    });
    expect(removed?.status).toBe(403);
    const older = `${SCENARIO_COOKIE}=newapi:missing`;
    expect((await call(server, 'GET', '/api/v1/archive', older))?.status).toBe(404);
    const download = await call(server, 'GET', `/api/v1/archive/months/${monthsAgo(2)}`, older);
    expect(download?.status).toBe(404);
  });
});

const RECORDED: Record<string, [string, string]> = {
  'config.json': ['GET', '/api/v1/config'],
  'schema.json': ['GET', '/api/v1/config/schema'],
  'decisions-sim.json': ['GET', '/api/v1/decisions'],
  'real/config-preview-hours-error.json': ['POST', '/api/v1/config/preview'],
  'real/config-preview-invalid.json': ['POST', '/api/v1/config/preview'],
  'real/config-preview.json': ['POST', '/api/v1/config/preview'],
  'real/config-signals.json': ['GET', '/api/v1/config/signals'],
  'real/decisions.json': ['GET', '/api/v1/decisions'],
  'real/pump-settings-after-write.json': ['GET', '/api/v1/pump/settings'],
  'real/pump-settings-paused.json': ['GET', '/api/v1/pump/settings'],
  'real/pump-settings.json': ['GET', '/api/v1/pump/settings'],
  'real/pump-write-accepted.json': ['POST', '/api/v1/pump/settings/heat_delta'],
  'real/pump-write-refused-in-flight.json': ['POST', '/api/v1/pump/settings/heat_delta'],
  'real/pump-write-refused-not-publishing.json': ['POST', '/api/v1/pump/settings/heat_delta'],
  'real/pump-write-refused-out-of-range.json': ['POST', '/api/v1/pump/settings/heat_delta'],
  'real/pump-write-refused-unknown.json': ['POST', '/api/v1/pump/settings/max_pump_duty'],
  'real/pump-write-refused-value-changed.json': ['POST', '/api/v1/pump/settings/heat_delta'],
  'real/weather-off.json': ['GET', '/api/v1/weather'],
  'real/weather-on.json': ['GET', '/api/v1/weather'],
};

describe('the recorded responses fit the contract', () => {
  it('names every recorded fixture', () => {
    const real = readdirSync(new URL('real/', FIXTURES)).map((name) => `real/${name}`);
    expect(real.filter((name) => !(name in RECORDED))).toEqual([]);
  });

  it.each(Object.entries(RECORDED))('%s', (name, [method, path]) => {
    const recorded = JSON.parse(readFileSync(new URL(name, FIXTURES), 'utf8')) as Record<
      string,
      unknown
    >;
    const { status = 200, ...body } = recorded;
    const raw = 'status' in recorded ? body : recorded;
    expect(check(method, path, status as number, raw) ?? []).toEqual([]);
  });
});
