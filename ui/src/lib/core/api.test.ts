import { afterEach, describe, expect, it, vi } from 'vitest';
import {
  ApiError,
  acknowledgeReset,
  applyConfig,
  conflictVersion,
  failureKind,
  pauseControl,
  releaseHold,
  resumeControl,
  rollbackConfig,
  seriesStep,
  validateConfig,
} from './api';

function stubFetch(status = 200, body: unknown = {}) {
  const calls: { path: string; init: RequestInit }[] = [];
  vi.stubGlobal(
    'fetch',
    vi.fn((path: string, init: RequestInit) => {
      calls.push({ path, init });
      return Promise.resolve(new Response(JSON.stringify(body), { status }));
    }),
  );
  return calls;
}

afterEach(() => vi.unstubAllGlobals());

describe('state-changing requests', () => {
  it('send the JSON content type and the request marker', async () => {
    const calls = stubFetch();
    await Promise.all([
      releaseHold('why'),
      pauseControl(),
      resumeControl(),
      validateConfig({ a: 1 }),
      applyConfig({ base_version: 1, changes: {}, comment: '', acknowledge: [] }),
      rollbackConfig({ version: 1, base_version: 2, comment: '', acknowledge: [] }),
      acknowledgeReset(),
    ]);
    expect(calls.map((c) => c.init.method)).toEqual([
      'POST',
      'POST',
      'POST',
      'POST',
      'PUT',
      'POST',
      'POST',
    ]);
    for (const call of calls) {
      const headers = call.init.headers as Record<string, string>;
      expect(headers['Content-Type'], call.path).toBe('application/json');
      expect(headers['X-Ovenbird-Request'], call.path).toBe('1');
      expect(() => JSON.parse(call.init.body as string)).not.toThrow();
    }
    expect(calls.map((c) => c.path)).toContain('api/v1/config/rollback');
  });

  it('sends only the reason that was given', async () => {
    const calls = stubFetch();
    await pauseControl();
    await pauseControl('maintenance');
    expect(calls.map((c) => c.init.body)).toEqual(['{}', '{"reason":"maintenance"}']);
  });
});

describe('failures', () => {
  it.each([
    [401, 'unauthorized'],
    [403, 'forbidden'],
    [404, 'missing'],
    [409, 'conflict'],
    [413, 'too_large'],
    [415, 'unsupported'],
    [422, 'invalid'],
    [429, 'rate_limited'],
    [500, 'failed'],
  ])('classifies HTTP %i as %s', (status, kind) => {
    expect(failureKind(new ApiError('x', status))).toBe(kind);
  });

  it('reads the current version from a 409 body', async () => {
    stubFetch(409, { detail: 'changed', version: 7 });
    const error = await applyConfig({
      base_version: 1,
      changes: {},
      comment: '',
      acknowledge: [],
    }).catch((e: unknown) => e);
    expect(conflictVersion(error)).toBe(7);
    expect(conflictVersion(new Error('x'))).toBeNull();
  });
});

describe('seriesStep', () => {
  it('snaps to a step the series endpoint accepts', () => {
    expect([0, 60, 300, 600, 900, 1800, 3600, 7200].map(seriesStep)).toEqual([
      0, 300, 300, 900, 900, 3600, 3600, 3600,
    ]);
  });
});
