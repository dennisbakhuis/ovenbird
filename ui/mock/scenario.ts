export const SCENARIO_COOKIE = 'ovenbird_mock';
export const CLOCK_COOKIE = 'ovenbird_clock';

/**
 * Largest clock shift the `ovenbird_clock` cookie accepts: one day.
 */
export const MAX_SHIFT_MIN = 1440;

export type PumpPhase = 'idle' | 'heating' | 'defrost' | 'dhw';

/**
 * Per-browser overrides of the mock data, set with the `ovenbird_mock` cookie so parallel
 * Playwright contexts do not affect each other. Value: `key:value` pairs joined by dots, e.g.
 * `pump:defrost.weather:stale`.
 *
 * - `pump`: heating | idle | defrost | dhw (forces the snapshot and the last 15 min of history)
 * - `deice`: 1 | 2 (the pump is the known WH-MXC12J9E8: `pump/settings` names its profile and a
 *   defrost in the snapshot carries that deice mode; without it the model is unknown and a defrost
 *   has no mode). In mode 2 a defrost has no water flow and 25.5 °C return water, as by design.
 *   Combine with `pump:defrost` to show one now.
 * - `quiet`: on | off (forces the quiet level in the snapshot)
 * - `dhw`: none (the pump has no hot-water tank: it reports `main/DHW_Installed` 0, runs no
 *   scheduled hot-water runs and the config says `hot_water.installed` false; `pump:dhw` still
 *   forces a run, to show it while hot water is hidden)
 * - `weather`: off | stale
 * - `pumpsettings`: missing (GET pump/settings answers 404)
 * - `alarms`: none | critical
 * - `room`: stale (room sensor not fresh for 2.5 h) | old (held so long that ovenbird trusts it
 *   at 45 %) | untrusted (cooling authority 0)
 * - `clock`: behind (the service clock runs four days behind the browser, as the simulator does)
 * - `mode`: shadow (configured Shadow: another controller writes the pump, which runs 2 K above what
 *   ovenbird would send; never live, so no go-live snapshot) | paused (an auto installation
 *   paused by hand; the pump kept 1 K more)
 * - `hold`: latched (the third foreign-writer hold, latched until an administrator releases it)
 *   | timed (the second hold, 35 min left, also after the default hold was released)
 *   | none (the default hold already released, whatever other browsers did to the shared one)
 * - `simulation`: on (the `simulation` config field is true; default false in the mock)
 * - `stove`: active (wood-stove mode detected automatically 80 min ago) | manual (started by hand
 *   30 min ago, until 3.5 h from now) | waiting (no episode; the detection waits after an
 *   episode that reached its longest time) | disabled (wood-stove mode switched off)
 * - `house`: facts (house facts already stored in the configuration: build period and occupants)
 * - `basics`: collecting | provisional | off | error (`GET insight/basics`: no figure yet, a figure with
 *   the wide band, the feature switched off (the stored setting too), or a 500); default: credible
 * - `boost`: active (a +1 K boost begun 30 min ago, 90 min left)
 * - `away`: active (set 5 h ago, ends in two days, comfort again 6 h before) | returning (inside the
 *   return lead: the comfort target applies again, 3 h to the end)
 * - `summer`: on (the summer switch is stored on and holds heating off, slow outside mean 19.4 °C)
 *   | warming (stored on, still collecting the outside mean)
 * - `dayshift`: idle | boost | setback | recovery | blocked (the phase of the sun day shift, stored
 *   as `shadow`: the offset is only recorded) | shadow (same as boost) | on (stored `on` with the
 *   experimental acknowledgement: the boost is applied)
 * - `notify`: off (ntfy not configured) | failing (the last test failed, dead-man unhealthy);
 *   default: configured, tested, dead-man alive
 * - `snapshot`: none (no go-live snapshot recorded yet)
 * - `envelope`: proven (the envelope rule was seen acting) | none (not declared installed); default:
 *   declared, not seen acting yet
 * - `newapi`: missing (every endpoint added in UI wave 3 answers 404, as an older service does)
 * - `archive`: empty (the yearly archive holds no month yet) | error (its last step failed)
 * - `role`: viewer (the admin-only data actions, `POST history/compact`, `GET export/archive` and
 *   the yearly archive's downloads and `POST archive/delete`,
 *   and the operate actions `POST replay` and `POST replay/{id}/cancel`,
 *   answer 403 as for a login without the admin role)
 * - `mqtt`: env (the broker's host, port, user name and password come from the environment, so
 *   they are locked) | commands (commands to the pump are on, so `PUT config/mqtt` answers 409
 *   `commands_enabled`); the broker connection itself is kept per scenario cookie
 * - `outside`: sensor (the heating curve uses the chosen outside sensor
 *   `ha/sensor.garden_temperature`) | stale (it is chosen but stale: the curve falls back to the
 *   pump's sensor and `outside_sensor_stale` is active)
 * - `tag`: any short word ([a-z0-9], up to 12): keeps a test's own wood-stove requests, releases
 *   and the pause a release leaves apart from other browsers (the mock stores them per scenario
 *   cookie)
 *
 * The configuration (stored values, versions) is kept per scenario cookie, so a test that applies
 * a change never moves the version of another browser; without a cookie it is shared.
 *
 * A second cookie, `ovenbird_clock`, holds a number of minutes (0 … 1440) by which the service
 * clock runs behind the browser. It moves the mock through its 6-hour decision cycle and the
 * day, so a test can pin a cycle minute or the suite can run at another time of day.
 */
export interface Scenario {
  pump?: PumpPhase;
  deice?: '1' | '2';
  quiet?: 'on' | 'off';
  dhw?: 'none';
  weather?: 'off' | 'stale';
  pumpsettings?: 'missing';
  alarms?: 'none' | 'critical';
  room?: 'stale' | 'old' | 'untrusted';
  clock?: 'behind';
  mode?: 'shadow' | 'paused';
  hold?: 'latched' | 'timed' | 'none';
  simulation?: 'on';
  stove?: 'active' | 'manual' | 'waiting' | 'disabled';
  house?: 'facts';
  basics?: 'collecting' | 'provisional' | 'off' | 'error';
  boost?: 'active';
  away?: 'active' | 'returning';
  summer?: 'on' | 'warming';
  dayshift?: 'idle' | 'boost' | 'setback' | 'recovery' | 'blocked' | 'shadow' | 'on';
  notify?: 'off' | 'failing';
  snapshot?: 'none';
  envelope?: 'proven' | 'none';
  newapi?: 'missing';
  archive?: 'empty' | 'error';
  role?: 'viewer';
  mqtt?: 'env' | 'commands';
  outside?: 'sensor' | 'stale';
  tag?: string;
  shiftMin?: number;
}

export const SCENARIO_OPTIONS: {
  [K in Exclude<keyof Scenario, 'shiftMin' | 'tag'>]-?: readonly NonNullable<Scenario[K]>[];
} = {
  pump: ['idle', 'heating', 'defrost', 'dhw'],
  deice: ['1', '2'],
  quiet: ['on', 'off'],
  dhw: ['none'],
  weather: ['off', 'stale'],
  pumpsettings: ['missing'],
  alarms: ['none', 'critical'],
  room: ['stale', 'old', 'untrusted'],
  clock: ['behind'],
  mode: ['shadow', 'paused'],
  hold: ['latched', 'timed', 'none'],
  simulation: ['on'],
  stove: ['active', 'manual', 'waiting', 'disabled'],
  house: ['facts'],
  basics: ['collecting', 'provisional', 'off', 'error'],
  boost: ['active'],
  away: ['active', 'returning'],
  summer: ['on', 'warming'],
  dayshift: ['idle', 'boost', 'setback', 'recovery', 'blocked', 'shadow', 'on'],
  notify: ['off', 'failing'],
  snapshot: ['none'],
  envelope: ['proven', 'none'],
  newapi: ['missing'],
  archive: ['empty', 'error'],
  role: ['viewer'],
  mqtt: ['env', 'commands'],
  outside: ['sensor', 'stale'],
};

const CLOCK_OFFSET_MS: Record<NonNullable<Scenario['clock']>, number> = {
  behind: -4 * 86_400_000,
};

/**
 * The mock service's current time for a scenario: the real time, shifted for `clock:behind`.
 */
export function scenarioNow(scenario: Scenario, realMs: number): number {
  const offset = scenario.clock ? CLOCK_OFFSET_MS[scenario.clock] : 0;
  return realMs + offset - (scenario.shiftMin ?? 0) * 60_000;
}

function cookieValue(cookie: string, name: string): string | null {
  const entry = cookie
    .split(';')
    .map((part) => part.trim())
    .find((part) => part.startsWith(`${name}=`));
  return entry ? decodeURIComponent(entry.slice(name.length + 1)) : null;
}

/**
 * Minutes the service clock runs behind, from the `ovenbird_clock` cookie value.
 */
export function parseShift(value: string | null): number | null {
  if (value === null || !/^\d{1,4}$/.test(value)) return null;
  const minutes = Number(value);
  return minutes <= MAX_SHIFT_MIN ? minutes : null;
}

/**
 * The raw `ovenbird_mock` cookie value, '' without one: the key under which the mock keeps a
 * browser's own wood-stove requests.
 */
export function scenarioKey(cookie: string | undefined | null): string {
  return cookie ? (cookieValue(cookie, SCENARIO_COOKIE) ?? '') : '';
}

/**
 * Parse the scenario out of a Cookie header or `document.cookie`.
 */
export function parseScenario(cookie: string | undefined | null): Scenario {
  const scenario: Record<string, string | number> = {};
  if (!cookie) return scenario;
  const shift = parseShift(cookieValue(cookie, CLOCK_COOKIE));
  if (shift !== null) scenario['shiftMin'] = shift;
  const value = cookieValue(cookie, SCENARIO_COOKIE);
  if (value === null) return scenario as Scenario;
  for (const pair of value.split('.')) {
    const [key, option] = pair.split(':');
    if (key === 'tag' && option && /^[a-z0-9]{1,12}$/.test(option)) {
      scenario['tag'] = option;
      continue;
    }
    if (!key || !option || !(key in SCENARIO_OPTIONS)) continue;
    const allowed = SCENARIO_OPTIONS[key as keyof typeof SCENARIO_OPTIONS] as readonly string[];
    if (allowed.includes(option)) scenario[key] = option;
  }
  return scenario as Scenario;
}
