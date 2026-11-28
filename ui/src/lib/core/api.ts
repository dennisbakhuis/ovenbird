import type {
  AlarmsResponse,
  AuditResponse,
  ApplyResult,
  ArchiveDeleteResult,
  ArchiveStatus,
  CommandsResponse,
  ConfigDoc,
  ConfigExport,
  ConfigSchema,
  ConfigSignals,
  AwayResult,
  BoostResult,
  ConfigVersion,
  DayShift,
  ErrorDetail,
  Features,
  DecisionSeries,
  CompactResult,
  HaConnectionResult,
  HaTestResult,
  MqttConnectionResult,
  MqttStatus,
  MqttTestResult,
  HistorySignals,
  HistoryStorage,
  DecisionsLatest,
  DecisionsResponse,
  Health,
  History,
  ModeChange,
  ResetAckResult,
  PreviewResult,
  PumpRefusalCode,
  PumpSettingsResponse,
  PumpWriteResult,
  ReleaseResult,
  Snapshot,
  StoveResult,
  ValidateResult,
  WeatherResponse,
} from './types';

export class ApiError extends Error {
  status: number;
  body: unknown;

  constructor(path: string, status: number, body: unknown = null) {
    super(`${path}: HTTP ${status}`);
    this.status = status;
    this.body = body;
  }

  /**
   * The structured refusal `{code, message, params}` from `{"detail": {...}}`, when the server
   * sent one (a plain-string `detail` gives `null`).
   */
  get detail(): ErrorDetail | null {
    const detail = (this.body as { detail?: unknown } | null)?.detail;
    if (!detail || typeof detail !== 'object') return null;
    const { code, message, params } = detail as Record<string, unknown>;
    if (typeof code !== 'string') return null;
    return {
      code,
      message: typeof message === 'string' ? message : '',
      params: params && typeof params === 'object' ? (params as Record<string, unknown>) : {},
    };
  }

  /**
   * Machine-readable code from the error body (`detail.code`), when the server sent one.
   */
  get code(): string | null {
    return this.detail?.code ?? null;
  }
}

/**
 * Refusal code of a failed pump setting write (`null` for any other failure).
 */
export function pumpRefusal(error: unknown): ErrorDetail<PumpRefusalCode> | null {
  const detail = error instanceof ApiError ? error.detail : null;
  return detail as ErrorDetail<PumpRefusalCode> | null;
}

async function failure(path: string, response: Response): Promise<ApiError> {
  try {
    return new ApiError(path, response.status, await response.json());
  } catch {
    return new ApiError(path, response.status);
  }
}

export async function getJson<T>(path: string, signal?: AbortSignal): Promise<T> {
  const response = await fetch(path, { headers: { Accept: 'application/json' }, signal });
  if (!response.ok) throw await failure(path, response);
  return (await response.json()) as T;
}

async function sendJson<T>(
  method: 'POST' | 'PUT' | 'DELETE',
  path: string,
  body: unknown,
): Promise<T> {
  const response = await fetch(path, {
    method,
    headers: {
      Accept: 'application/json',
      'Content-Type': 'application/json',
      'X-Ovenbird-Request': '1',
    },
    body: JSON.stringify(body),
  });
  if (!response.ok) throw await failure(path, response);
  return (await response.json()) as T;
}

export const postJson = <T>(path: string, body: unknown) => sendJson<T>('POST', path, body);

/**
 * Whether an error means the endpoint does not exist on this server (older backend).
 */
export function isMissing(error: unknown): boolean {
  return error instanceof ApiError && (error.status === 404 || error.status === 405);
}

/**
 * Whether an error is an authorisation refusal (wrong credentials or too low a role).
 */
export function isForbidden(error: unknown): boolean {
  return error instanceof ApiError && (error.status === 401 || error.status === 403);
}

export type FailureKind =
  | 'unauthorized'
  | 'forbidden'
  | 'too_large'
  | 'unsupported'
  | 'missing'
  | 'conflict'
  | 'rate_limited'
  | 'invalid'
  | 'failed';

/**
 * Classify a failed request by its HTTP status.
 */
export function failureKind(error: unknown): FailureKind {
  if (!(error instanceof ApiError)) return 'failed';
  switch (error.status) {
    case 401:
      return 'unauthorized';
    case 403:
      return 'forbidden';
    case 404:
    case 405:
      return 'missing';
    case 409:
      return 'conflict';
    case 413:
      return 'too_large';
    case 415:
      return 'unsupported';
    case 400:
    case 422:
      return 'invalid';
    case 429:
      return 'rate_limited';
    default:
      return 'failed';
  }
}

/**
 * Current config version from a 409 body, when the server sent one.
 */
export function conflictVersion(error: unknown): number | null {
  const version =
    error instanceof ApiError ? (error.body as { version?: unknown } | null)?.version : null;
  return typeof version === 'number' ? version : null;
}

function windowQuery(from?: Date, to?: Date, extra: Record<string, string | number> = {}): string {
  const query = new URLSearchParams();
  if (from) query.set('from', from.toISOString());
  if (to) query.set('to', to.toISOString());
  for (const [key, value] of Object.entries(extra)) query.set(key, String(value));
  const text = query.toString();
  return text ? `?${text}` : '';
}

export const fetchHealth = (signal?: AbortSignal) => getJson<Health>('api/v1/health', signal);

export const fetchSnapshot = (signal?: AbortSignal) => getJson<Snapshot>('api/v1/snapshot', signal);

/**
 * Fetch a single-use pass for the live connection, or null when the service has none to give.
 */
export async function fetchLiveTicket(): Promise<string | null> {
  const body = await postJson<{ ticket?: unknown }>('api/v1/live/ticket', {});
  return typeof body.ticket === 'string' ? body.ticket : null;
}

/**
 * Fetch aligned history series for the given signal ids (default window: last 24 h).
 */
export function fetchHistory(
  ids: string[],
  signal?: AbortSignal,
  window: { from?: Date; to?: Date; step?: number } = {},
): Promise<History> {
  const query = new URLSearchParams({ signals: ids.join(',') });
  if (window.from) query.set('from', window.from.toISOString());
  if (window.to) query.set('to', window.to.toISOString());
  if (window.step) query.set('step', String(window.step));
  return getJson<History>(`api/v1/history?${query.toString()}`, signal);
}

export const fetchDecisionsLatest = (signal?: AbortSignal) =>
  getJson<DecisionsLatest>('api/v1/decisions/latest', signal);

export const fetchDecisions = (
  opts: { from?: Date; to?: Date; limit?: number },
  signal?: AbortSignal,
) =>
  getJson<DecisionsResponse>(
    `api/v1/decisions${windowQuery(opts.from, opts.to, opts.limit ? { limit: opts.limit } : {})}`,
    signal,
  );

export const SERIES_STEPS = [0, 300, 900, 3600] as const;

/**
 * Smallest step the series endpoint accepts that is at least `step` (0 stays 0).
 */
export function seriesStep(step: number): number {
  return SERIES_STEPS.find((allowed) => allowed >= step) ?? 3600;
}

export const fetchSeries = (opts: { from: Date; to: Date; step?: number }, signal?: AbortSignal) =>
  getJson<DecisionSeries>(
    `api/v1/decisions/series${windowQuery(opts.from, opts.to, { step: seriesStep(opts.step ?? 0) })}`,
    signal,
  );

export const fetchCommands = (
  opts: { from?: Date; to?: Date; limit?: number },
  signal?: AbortSignal,
) =>
  getJson<CommandsResponse>(
    `api/v1/commands${windowQuery(opts.from, opts.to, opts.limit ? { limit: opts.limit } : {})}`,
    signal,
  );

export const fetchAlarms = (
  opts: { from?: Date; to?: Date; limit?: number },
  signal?: AbortSignal,
) =>
  getJson<AlarmsResponse>(
    `api/v1/alarms${windowQuery(opts.from, opts.to, opts.limit ? { limit: opts.limit } : {})}`,
    signal,
  );

export const fetchConfig = (signal?: AbortSignal) => getJson<ConfigDoc>('api/v1/config', signal);

export const fetchAudit = (
  opts: { from?: Date; to?: Date; limit?: number },
  signal?: AbortSignal,
) =>
  getJson<AuditResponse>(
    `api/v1/audit${windowQuery(opts.from, opts.to, opts.limit ? { limit: opts.limit } : {})}`,
    signal,
  );

export const releaseHold = (reason: string) =>
  postJson<ReleaseResult>('api/v1/control/release-hold', reason ? { reason } : {});

export const pauseControl = (reason?: string) =>
  postJson<ModeChange>('api/v1/control/pause', reason ? { reason } : {});

export const setStove = (on: boolean, untilMs?: number) =>
  postJson<StoveResult>(
    'api/v1/control/stove',
    untilMs === undefined ? { on } : { on, until: new Date(untilMs).toISOString() },
  );

export interface BoostBody {
  offset_k: number;
  duration_s: number;
}

export interface AwayBody {
  until: string;
  target_c?: number;
  comfort_lead_s?: number;
}

export const fetchFeatures = (signal?: AbortSignal) =>
  getJson<Features>('api/v1/control/features', signal);

export const fetchDayShift = (signal?: AbortSignal) =>
  getJson<DayShift>('api/v1/control/dayshift', signal);

export const startBoost = (body: BoostBody) => postJson<BoostResult>('api/v1/control/boost', body);

export const endBoost = () => sendJson<BoostResult>('DELETE', 'api/v1/control/boost', {});

export const setAway = (body: AwayBody) => sendJson<AwayResult>('PUT', 'api/v1/control/away', body);

export const endAway = () => sendJson<AwayResult>('DELETE', 'api/v1/control/away', {});

export const resumeControl = () => postJson<ModeChange>('api/v1/control/resume', {});

export const fetchSchema = (signal?: AbortSignal) =>
  getJson<ConfigSchema>('api/v1/config/schema', signal);

export const fetchSignals = (signal?: AbortSignal) =>
  getJson<ConfigSignals>('api/v1/config/signals', signal);

export const fetchExport = (signal?: AbortSignal) =>
  getJson<ConfigExport>('api/v1/config/export', signal);

export const rollbackConfig = (body: {
  version: number;
  base_version: number;
  comment: string;
  acknowledge: string[];
}) => sendJson<ApplyResult>('POST', 'api/v1/config/rollback', body);

export const fetchVersions = (limit = 50, signal?: AbortSignal) =>
  getJson<{ versions: ConfigVersion[] }>(`api/v1/config/versions?limit=${limit}`, signal);

export const fetchVersion = (version: number, signal?: AbortSignal) =>
  getJson<ConfigVersion>(`api/v1/config/versions/${version}`, signal);

export const validateConfig = (changes: Record<string, unknown>) =>
  postJson<ValidateResult>('api/v1/config/validate', { changes });

export const previewConfig = (changes: Record<string, unknown>, hours = 24) =>
  postJson<PreviewResult>('api/v1/config/preview', { changes, hours });

export const applyConfig = (body: {
  base_version: number;
  changes: Record<string, unknown>;
  comment: string;
  acknowledge: string[];
}) => sendJson<ApplyResult>('PUT', 'api/v1/config', body);

export const fetchWeather = (backH = 24, aheadH = 48, signal?: AbortSignal) =>
  getJson<WeatherResponse>(`api/v1/weather?back_h=${backH}&ahead_h=${aheadH}`, signal);

export const fetchPumpSettings = (signal?: AbortSignal) =>
  getJson<PumpSettingsResponse>('api/v1/pump/settings', signal);

export const writePumpSetting = (
  id: string,
  body: { value: number; expect: number | null; comment?: string },
) => postJson<PumpWriteResult>(`api/v1/pump/settings/${id}`, body);

export const acknowledgeReset = () => postJson<ResetAckResult>('api/v1/config/reset-ack', {});

export const fetchHistorySignals = (signal?: AbortSignal) =>
  getOptional<HistorySignals>('api/v1/history/signals', signal);

export const fetchStorage = (signal?: AbortSignal) =>
  getOptional<HistoryStorage>('api/v1/history/storage', signal);

export const fetchArchive = (signal?: AbortSignal) =>
  getOptional<ArchiveStatus>('api/v1/archive', signal);

/**
 * Delete a frozen month (`YYYY-MM`) or every frozen month of a year (`YYYY`) from the yearly
 * archive (admin).
 */
export const deleteArchive = (period: string) =>
  postJson<ArchiveDeleteResult>('api/v1/archive/delete', { period });

/**
 * Ask the service to compact `history.db` (admin); it runs between two writer batches.
 */
export const compactHistory = () => postJson<CompactResult>('api/v1/history/compact', {});

/**
 * Store the Home Assistant connection (admin). A key left out keeps its value; `null` removes it.
 * The token is write-only: the answer shows it only as "set"/"unset".
 */
export const saveHaConnection = (body: { url?: string | null; token?: string | null }) =>
  sendJson<HaConnectionResult>('PUT', 'api/v1/config/ha', body);

/**
 * Test a Home Assistant connection without saving it (read-only on the HA side). Without `url`
 * the effective one; without `token` the stored one, only for the effective URL.
 */
export const testHaConnection = (body: { url?: string; token?: string; signals?: string[] }) =>
  postJson<HaTestResult>('api/v1/config/ha/test', body);

/**
 * The broker link and the last broker change made in the app; null for a service without an
 * MQTT ingest (or an older one).
 */
export const fetchMqttStatus = (signal?: AbortSignal) =>
  getOptional<MqttStatus>('api/v1/config/mqtt', signal);

/**
 * Test broker settings without saving them (admin): a key left out keeps the effective value,
 * `null` the default. A new host or port without a password drops the stored password.
 */
export const testMqttConnection = (body: Record<string, unknown>) =>
  postJson<MqttTestResult>('api/v1/config/mqtt/test', body);

/**
 * Apply broker settings (admin); the body must equal one that passed a test in the last 10
 * minutes. The service then watches the new connection for 60 s and reverts when it fails.
 */
export const saveMqttConnection = (body: Record<string, unknown>) =>
  sendJson<MqttConnectionResult>('PUT', 'api/v1/config/mqtt', body);

/**
 * GET an endpoint that an older backend may not have: null on 404/405, the body otherwise.
 */
export async function getOptional<T>(path: string, signal?: AbortSignal): Promise<T | null> {
  try {
    return await getJson<T>(path, signal);
  } catch (error) {
    if (isMissing(error)) return null;
    throw error;
  }
}
