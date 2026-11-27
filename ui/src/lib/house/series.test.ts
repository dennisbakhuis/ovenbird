import { describe, expect, it } from 'vitest';
import type { HouseSeries } from './shapes';
import { translate } from '$lib/i18n';
import {
  differences,
  eventKinds,
  eventSpans,
  isOutOfSample,
  lastDays,
  typicalErrorSentence,
} from './series';

const series: HouseSeries = {
  model: 'm',
  step_s: 900,
  from: '2026-11-13T00:00:00Z',
  to: '2026-11-27T00:00:00Z',
  events: [],
  out_of_sample_from: null,
  rmse_k: null,
  bias_k: null,
  compared_points: 0,
  points: [
    ['2026-11-13T00:00:00Z', 21, null],
    ['2026-11-22T00:00:00Z', 21, 21.1],
    ['2026-11-25T00:00:00Z', 21, 20.8],
    ['2026-11-26T00:00:00Z', null, 20.9],
    ['2026-11-27T00:00:00Z', 20.5, 20.9],
  ],
};

describe('lastDays', () => {
  it('cuts the last days before the end of the series', () => {
    expect(lastDays(series, 3)).toHaveLength(3);
    expect(lastDays(series, 7)).toHaveLength(4);
    expect(lastDays(series, 14)).toHaveLength(5);
  });
});

describe('differences', () => {
  it('takes the median and the largest where both values exist', () => {
    const found = differences(series.points);
    expect(found?.count).toBe(3);
    expect(found?.typicalK).toBeCloseTo(0.2, 5);
    expect(found?.largestK).toBeCloseTo(0.4, 5);
    expect(found?.largestAt).toBe('2026-11-27T00:00:00Z');
  });

  it('is null without a pair', () => {
    expect(differences([['2026-11-13T00:00:00Z', 21, null]])).toBeNull();
  });
});

describe('differences with events', () => {
  const events = [
    {
      kind: 'stove' as const,
      from: '2026-11-25T00:00:00Z',
      to: '2026-11-25T02:00:00Z',
      tail_to: '2026-11-25T12:00:00Z',
    },
  ];

  it('leaves out the rows inside an event and its tail', () => {
    const found = differences(series.points, events);
    expect(found?.count).toBe(2);
    expect(found?.largestK).toBeCloseTo(0.4, 5);
  });

  it('leaves out rows predicted from days the model had seen', () => {
    const found = differences(series.points, [], '2026-11-26T00:00:00Z');
    expect(found?.count).toBe(1);
    expect(found?.largestAt).toBe('2026-11-27T00:00:00Z');
    expect(differences(series.points, events, '2026-11-27T00:00:00Z')).toBeNull();
  });

  it('counts a row as unseen from a day after the first unseen origin', () => {
    expect(isOutOfSample(Date.parse('2026-11-26T00:00:00Z'), '2026-11-26T00:00:00Z')).toBe(false);
    expect(isOutOfSample(Date.parse('2026-11-27T00:00:00Z'), '2026-11-26T00:00:00Z')).toBe(true);
    expect(isOutOfSample(Date.parse('2026-11-01T00:00:00Z'), null)).toBe(true);
  });
});

describe('event spans', () => {
  const events = [
    {
      kind: 'stove' as const,
      from: '2026-11-10T00:00:00Z',
      to: '2026-11-10T05:00:00Z',
      tail_to: '2026-11-10T17:00:00Z',
    },
    {
      kind: 'excluded_day' as const,
      from: '2026-11-20T00:00:00Z',
      to: '2026-11-21T00:00:00Z',
      tail_to: '2026-11-21T00:00:00Z',
    },
  ];

  it('keeps the events that reach into the window', () => {
    const from = Date.parse('2026-11-15T00:00:00Z');
    const to = Date.parse('2026-11-27T00:00:00Z');
    const spans = eventSpans(events, from, to);
    expect(spans.map((span) => span.kind)).toEqual(['excluded_day']);
    expect(eventKinds(spans)).toEqual(['excluded_day']);
    expect(eventKinds(eventSpans(events, 0, to))).toEqual(['stove', 'excluded_day']);
  });
});

describe('typicalErrorSentence', () => {
  const f = (value: number, digits: number) => value.toFixed(digits);
  const en = (key: Parameters<typeof translate>[1], params?: Record<string, string | number>) =>
    translate('en', key, params);
  const nl = (key: Parameters<typeof translate>[1], params?: Record<string, string | number>) =>
    translate('nl', key, params);

  it('says the typical error and the lean in plain words', () => {
    expect(typicalErrorSentence(0.4, -0.3, en, f)).toBe(
      'On unseen days the model is typically 0.4 °C off, and on average 0.3 °C too cold.',
    );
    expect(typicalErrorSentence(0.4, 0.3, en, f)).toContain('0.3 °C too warm');
    expect(typicalErrorSentence(0.4, -0.3, nl, f)).toContain('te koud');
  });

  it('leaves the lean out when there is none, and everything when unknown', () => {
    expect(typicalErrorSentence(0.4, 0.02, en, f)).toContain('without a lasting lean');
    expect(typicalErrorSentence(0.4, null, en, f)).toBe(
      'On unseen days the model is typically 0.4 °C off.',
    );
    expect(typicalErrorSentence(null, -0.3, en, f)).toBe('');
  });
});
