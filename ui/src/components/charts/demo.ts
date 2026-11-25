import { runLengthSegments, type Point, type StateSegment } from '$lib/core/chart';

export const DEMO_NOW = Date.parse('2026-11-15T14:00:00+01:00');
export const DEMO_LOCATION = { lat: 52.09, lon: 5.12 };

const MINUTE = 60_000;
const HOUR = 3_600_000;

/**
 * Deterministic 24 h of heat-pump history (5 min samples) and a 24 h forecast ending/starting at
 * `now`, shaped like the recorded house: on-change room sensor, cycling compressor with
 * defrosts below 3 °C, one hot-water run, quiet mode at night.
 */
export function demoDay(now = DEMO_NOW) {
  const from = now - 24 * HOUR;
  const step = 5 * MINUTE;
  const hourOf = (t: number) => {
    const d = new Date(t);
    return d.getHours() + d.getMinutes() / 60;
  };
  const outsideAt = (t: number) =>
    2.6 + 2.3 * Math.sin(((hourOf(t) - 9) / 24) * 2 * Math.PI) + 0.25 * Math.sin(t / (37 * MINUTE));

  const outside: Point[] = [];
  const forecast: Point[] = [];
  const room: Point[] = [];
  const setpoint: Point[] = [];
  const outlet: Point[] = [];
  const inlet: Point[] = [];
  const hz: Point[] = [];
  const defrost: Point[] = [];
  const dhw: Point[] = [];
  const quiet: Point[] = [];
  const electric: Point[] = [];
  const heat: Point[] = [];

  let water = 27;
  let lastRoom = NaN;
  let lastSetpoint = NaN;
  for (let t = from; t <= now; t += step) {
    const minute = Math.round((t - from) / MINUTE);
    const hour = hourOf(t);
    const out = outsideAt(t);
    outside.push([t, Number(out.toFixed(2))]);

    const roomValue =
      Math.round((20.95 + 0.3 * Math.sin(((hour - 16) / 24) * 2 * Math.PI)) * 10) / 10;
    if (roomValue !== lastRoom) {
      room.push([t, roomValue]);
      lastRoom = roomValue;
    }

    const sp = Math.round(34 - 0.55 * out + (21.0 - roomValue) * 1.2);
    if (sp !== lastSetpoint) {
      setpoint.push([t, sp]);
      lastSetpoint = sp;
    }

    const cycle = minute % 220;
    const isDhw = hour >= 6.5 && hour < 7.17;
    const on = cycle < 180 || isDhw;
    const isDefrost = on && !isDhw && out < 3 && cycle >= 90 && cycle < 96;
    const frequency = on ? Math.round(30 + (5 - out) * 3.2 + (cycle < 20 ? cycle : 20) * 0.4) : 0;
    hz.push([t, frequency]);
    defrost.push([t, isDefrost ? 1 : 0]);
    dhw.push([t, isDhw ? 1 : 0]);
    quiet.push([t, hour >= 22 || hour < 7 ? 2 : 0]);

    const targetWater = isDhw ? 48 : on ? sp + 0.4 * Math.sin(minute / 7) : 24;
    water += (targetWater - water) * (isDefrost ? -0.15 : 0.35);
    outlet.push([t, Number(water.toFixed(2))]);
    inlet.push([t, Number((water - (on ? 4.5 : 0.6)).toFixed(2))]);

    const watts = on ? 550 + frequency * 32 : 18;
    electric.push([t, watts]);
    heat.push([t, on && !isDefrost ? Math.round(watts * (3.1 + 0.22 * out)) : 0]);
  }

  for (let t = now; t <= now + 24 * HOUR; t += HOUR) {
    forecast.push([t, Number((outsideAt(t) + 0.3 + 0.4 * Math.sin(t / (5 * HOUR))).toFixed(2))]);
  }
  const curveOutlook: Point[] = forecast.map(([t, v]) => [t, Number((34 - 0.55 * v).toFixed(2))]);
  const radiation: Point[] = forecast.map(([t]) => {
    const h = hourOf(t);
    return [t, h > 8 && h < 17 ? Math.round(320 * Math.sin(((h - 8) / 9) * Math.PI)) : 0];
  });

  const lanes = {
    compressor: runLengthSegments(hz, (v) => (v > 0 ? 'on' : null), {
      endT: now,
      level: (v) => (v - 20) / 50,
    }),
    defrost: runLengthSegments(defrost, (v) => (v > 0 ? 'defrost' : null), { endT: now }),
    dhw: runLengthSegments(dhw, (v) => (v > 0 ? 'dhw' : null), { endT: now }),
    quiet: runLengthSegments(quiet, (v) => (v > 0 ? `level${v}` : null), { endT: now }),
  } satisfies Record<string, StateSegment[]>;

  return {
    from,
    to: now,
    now,
    outside,
    forecast,
    curveOutlook,
    radiation,
    room,
    setpoint,
    outlet,
    inlet,
    hz,
    electric,
    heat,
    lanes,
    comfort: { target: 21.0, low: 20.5, high: 21.5 },
    hold: { from: now - 43 * MINUTE, to: now + 22 * MINUTE },
    configChange: now - 52 * MINUTE,
  };
}

export const DEMO_ENERGY = [
  { label: 'Mon', value: 9.6 },
  { label: 'Tue', value: 10.4 },
  { label: 'Wed', value: 8.1 },
  { label: 'Thu', value: 11.9 },
  { label: 'Fri', value: 12.4 },
  { label: 'Sat', value: 9.2 },
  { label: 'Sun', value: 6.1, note: 'so far' },
];

export const DEMO_FORECAST_ERROR = {
  bias: [
    { label: '6 h', value: 0.3 },
    { label: '24 h', value: 0.8 },
    { label: '48 h', value: -0.4 },
  ],
  mae: [
    { label: '6 h', value: 0.9 },
    { label: '24 h', value: 1.4 },
    { label: '48 h', value: 2.1 },
  ],
};

export const DEMO_MONITORS = [
  { label: 'Outlet temperature', value: 30.8, limit: 45, direction: 'above', unit: '°C' },
  { label: 'Flow', value: 17.4, limit: 7, warn: 9, direction: 'below', unit: 'l/min' },
  { label: 'Starts per hour', value: 5, limit: 6, warn: 4, direction: 'above', unit: '' },
  { label: 'Room sensor age', value: 2100, limit: 1800, direction: 'above', unit: 's' },
] as const;
