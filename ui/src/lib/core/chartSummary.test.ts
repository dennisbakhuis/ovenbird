import { describe, expect, it } from 'vitest';
import type { Point } from './chart';
import {
  bandState,
  csvRows,
  chartText,
  copOf,
  describeBand,
  describeBars,
  describeBullet,
  describeLane,
  describePowerFlow,
  describeSegment,
  describeSeries,
  describeTimeChart,
  formatDuration,
  formatValue,
  limitBreached,
  seriesStats,
  tableRows,
  trendDirection,
  trendPerHour,
} from './chartSummary';

const H = 3_600_000;
const NS = ' ';
const strip = (text: string) => text.replaceAll(NS, ' ');

const falling: Point[] = [0, 1, 2, 3].map((h) => [h * H, 21.0 - 0.2 * h]);

describe('numbers and durations', () => {
  it('formats values with a narrow space and a dash for missing', () => {
    expect(formatValue(20.44, '°C', 1, 'en')).toBe(`20.4${NS}°C`);
    expect(formatValue(20.44, '°C', 1, 'nl')).toBe(`20,4${NS}°C`);
    expect(formatValue(null, '°C', 1, 'en')).toBe('–');
    expect(formatValue(-0.04, '', 1, 'en')).toBe('0');
    expect(formatValue(-5.54, 'K', 1, 'en')).toBe(`\u22125.5${NS}K`);
    expect(formatValue(-5.54, 'K', 1, 'nl')).toBe(`\u22125,5${NS}K`);
  });

  it('formats durations', () => {
    expect(formatDuration(20_000, 'en')).toBe('<1 min');
    expect(formatDuration(45 * 60_000, 'en')).toBe('45 min');
    expect(formatDuration(2.5 * H, 'en')).toBe('2 h 30 min');
    expect(formatDuration(3 * H, 'nl')).toBe('3 u');
  });

  it('fills text parameters per language', () => {
    expect(chartText('en', 'cursor', { title: 'Today' })).toBe('Today: time cursor');
    expect(chartText('nl', 'showTable')).toBe('Toon als tabel');
  });
});

describe('series statistics and trend', () => {
  it('summarises a series', () => {
    expect(seriesStats(falling)).toMatchObject({ first: 21.0, last: 20.4, min: 20.4, max: 21.0 });
    expect(seriesStats([])).toBeNull();
  });

  it('fits a per-hour slope over the window', () => {
    expect(trendPerHour(falling)).toBeCloseTo(-0.2, 6);
    expect(trendPerHour(falling, 1.5 * H)).toBeCloseTo(-0.2, 6);
    expect(trendPerHour([[0, 1]])).toBeNull();
    expect(
      trendPerHour([
        [0, 1],
        [60_000, 2],
      ]),
    ).toBeNull();
    expect(trendDirection(-0.2)).toBe('falling');
    expect(trendDirection(0.01)).toBe('steady');
    expect(trendDirection(null)).toBe('steady');
  });

  it('describes a series in one sentence', () => {
    expect(strip(describeSeries('Room', '°C', falling, 'en'))).toBe(
      'Room 20.4 °C, range 20.4–21 °C, falling 0.2 K per hour',
    );
    expect(describeSeries('Room', '°C', [], 'en')).toBe('Room: no data');
    expect(strip(describeSeries('Ruimte', '°C', falling, 'nl'))).toBe(
      'Ruimte 20,4 °C, bereik 20,4–21 °C, dalend 0,2 K per uur',
    );
  });

  it('describes a whole chart with lanes', () => {
    const text = strip(
      describeTimeChart(
        'Today',
        Date.parse('2026-11-15T00:00:00'),
        Date.parse('2026-11-15T03:00:00'),
        [{ label: 'Room', unit: '°C', points: falling }],
        [{ label: 'Defrost', segments: [{ from: 0, to: 600_000, state: 'defrost' }] }],
        'en',
      ),
    );
    expect(text).toBe(
      'Today, 00:00–03:00. Room 20.4 °C, range 20.4–21 °C, falling 0.2 K per hour. Defrost: once, 10 min in total.',
    );
  });
});

describe('lanes', () => {
  const segments = [
    { from: 0, to: 2 * H, state: 'on', level: 0.5 },
    { from: 2 * H, to: 3 * H, state: 'on', level: 1 },
    { from: 4 * H, to: 4.5 * H, state: 'on' },
  ];

  it('counts merged runs per state', () => {
    expect(
      describeLane({ label: 'Compressor', segments, states: { on: { label: 'on' } } }, 'en'),
    ).toBe('Compressor: on 2 times, 3 h 30 min in total');
    expect(describeLane({ label: 'Hot water', segments: [] }, 'en')).toBe('Hot water: none');
  });

  it('describes one segment for the list', () => {
    const from = Date.parse('2026-11-15T06:10:00');
    expect(describeSegment({ from, to: from + 2.5 * H, state: 'on' }, 'on', 'en')).toBe(
      '06:10–08:40, on, 2 h 30 min',
    );
  });
});

describe('meters', () => {
  it('places a value against a band', () => {
    expect(bandState(20.4, 20.5, 21.5)).toBe('below');
    expect(bandState(20.5, 20.5, 21.5)).toBe('within');
    expect(bandState(21.6, 20.5, 21.5)).toBe('above');
  });

  it('describes the comfort meter like the plan', () => {
    const text = describeBand(
      { label: 'Room', value: 20.4, unit: '°C', low: 20.5, high: 21.5, target: 21.0, trend: -0.2 },
      'en',
    );
    expect(strip(text)).toBe(
      'Room 20.4 °C, 0.6 K below target 21 °C, below the comfort band 20.5–21.5 °C, falling 0.2 K per hour',
    );
    expect(
      strip(
        describeBand(
          {
            label: 'Room',
            value: 21.0,
            unit: '°C',
            low: 20.5,
            high: 21.5,
            target: 21.0,
            flip: 20.7,
          },
          'en',
        ),
      ),
    ).toBe('Room 21 °C, on target 21 °C, within the comfort band, changes at 20.7 °C');
    expect(describeBand({ label: 'Room', value: null, unit: '°C', low: 1, high: 2 }, 'en')).toBe(
      'Room: no data',
    );
  });

  it('describes monitors against their limit', () => {
    expect(limitBreached(46, 45, 'above')).toBe(true);
    expect(limitBreached(8, 7, 'below')).toBe(false);
    expect(limitBreached(null, 7, 'below')).toBe(false);
    expect(
      strip(
        describeBullet(
          { label: 'Outlet', value: 30.8, unit: '°C', limit: 45, direction: 'above' },
          'en',
        ),
      ),
    ).toBe('Outlet 30.8 °C, alarm above 45 °C, 14.2 K margin');
    expect(
      strip(
        describeBullet(
          { label: 'Flow', value: 6, unit: 'l/min', limit: 7, direction: 'below', digits: 0 },
          'en',
        ),
      ),
    ).toBe('Flow 6 l/min, below the alarm limit 7 l/min by 1 l/min');
    expect(
      describeBullet({ label: 'X', value: 1, unit: '', limit: null, direction: 'above' }, 'en'),
    ).toBe('X 1, no limit');
  });

  it('describes bars', () => {
    const week = [
      { label: 'Mon', value: 9.6 },
      { label: 'Tue', value: null },
    ];
    expect(strip(describeBars('Energy', week, 'kWh', 'en'))).toBe('Energy: Mon 9.6 kWh, Tue –');
    const many = Array.from({ length: 10 }, (_, i) => ({ label: `d${i}`, value: i }));
    expect(strip(describeBars('Energy', many, 'kWh', 'en'))).toBe(
      'Energy: lowest 0 kWh (d0), highest 9 kWh (d9), mean 4.5 kWh',
    );
    expect(describeBars('Energy', [], 'kWh', 'en')).toBe('Energy: no data');
  });

  it('describes power flow and COP', () => {
    expect(copOf(1900, 8400)).toBeCloseTo(4.42, 2);
    expect(copOf(1900, 0)).toBeNull();
    expect(copOf(null, 8400)).toBeNull();
    expect(strip(describePowerFlow(1900, 8400, copOf(1900, 8400), 'en'))).toBe(
      'Electric 1.9 kW in, heat 8.4 kW out, of which 6.5 kW from the outside air, COP 4.4',
    );
    expect(strip(describePowerFlow(1400, 0, null, 'en'))).toBe('Electric 1.4 kW in, no heat out');
    expect(describePowerFlow(18, 0, null, 'en', 100)).toBe(
      'Idle: no electric input or heat output',
    );
    expect(describePowerFlow(null, null, null, 'en')).toBe('Power not available');
  });
});

describe('table rows', () => {
  it('samples every series at round times', () => {
    const from = Date.parse('2026-11-15T00:00:00');
    const series = [
      { points: [0, 1, 2, 3].map((h): Point => [from + h * H, h]) },
      { points: [[from, 5] as Point], step: true, maxDistMs: Infinity },
    ];
    const rows = tableRows(series, from, from + 3 * H, 3, H);
    expect(rows.map((r) => r.values)).toEqual([
      [0, 5],
      [1, 5],
      [2, 5],
      [3, 5],
    ]);
  });
});

describe('csvRows', () => {
  it('puts every sample time of every line in one row, empty where a line has no value', () => {
    const room: Point[] = [
      [0, 21],
      [60_000, 20.7],
    ];
    const water: Point[] = [[120_000 + 3_600_000, 33]];
    const rows = csvRows([{ points: room }, { points: water, step: true }], 90_000);
    expect(rows).toHaveLength(3);
    expect(rows[0]).toEqual([new Date(0).toISOString(), 21, null]);
    expect(rows[1]?.[1]).toBe(20.7);
    expect(rows[2]?.[1]).toBeNull();
    expect(rows[2]?.[2]).toBe(33);
  });
});
