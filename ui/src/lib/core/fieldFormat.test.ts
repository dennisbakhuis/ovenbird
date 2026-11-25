import { describe, expect, it } from 'vitest';
import {
  curveText,
  decimalSeparator,
  formatDelta,
  formatInputNumber,
  parseInputNumber,
} from './fieldFormat';

describe('number input formatting', () => {
  it('uses the decimal separator of the UI language', () => {
    expect(decimalSeparator('en')).toBe('.');
    expect(decimalSeparator('nl')).toBe(',');
    expect(formatInputNumber(21.6, 'en')).toBe('21.6');
    expect(formatInputNumber(21.6, 'nl')).toBe('21,6');
    expect(formatInputNumber(-10, 'en')).toBe('−10');
    expect(formatInputNumber(null, 'en')).toBe('');
    expect(formatInputNumber(0.1 + 0.2, 'en')).toBe('0.3');
  });

  it('parses points, commas and typographic minus signs', () => {
    expect(parseInputNumber('21.6')).toBe(21.6);
    expect(parseInputNumber(' 21,6 ')).toBe(21.6);
    expect(parseInputNumber('−10')).toBe(-10);
    expect(parseInputNumber('.5')).toBe(0.5);
    expect(parseInputNumber('')).toBeNull();
    expect(parseInputNumber('-')).toBeNull();
    expect(parseInputNumber('21.6.1')).toBeNull();
    expect(parseInputNumber('abc')).toBeNull();
  });

  it('formats signed differences', () => {
    expect(formatDelta(21.6, 22.2, 'en')).toBe('+0.6');
    expect(formatDelta(34, 32, 'en')).toBe('−2');
    expect(formatDelta(1, 1, 'en')).toBe('±0');
    expect(formatDelta(21.6, 22.2, 'nl')).toBe('+0,6');
    expect(formatDelta('a', 1, 'en')).toBeNull();
  });

  it('writes a curve as water and outside lists', () => {
    expect(
      curveText(
        [
          [-10, 39],
          [0, 34],
          [15, 25],
        ],
        'en',
      ),
    ).toEqual({ water: '39 / 34 / 25', outside: '−10 / 0 / 15' });
  });
});
