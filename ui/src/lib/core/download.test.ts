import { describe, expect, it } from 'vitest';
import { csvPath, dispositionName, toCsv } from './download';

describe('dispositionName', () => {
  it('reads plain and encoded file names', () => {
    expect(dispositionName('attachment; filename="ovenbird-alarms.csv"')).toBe(
      'ovenbird-alarms.csv',
    );
    expect(dispositionName("attachment; filename*=UTF-8''ovenbird%20export.csv")).toBe(
      'ovenbird export.csv',
    );
    expect(dispositionName('attachment; filename=plain.json')).toBe('plain.json');
  });

  it('is null without a header or a name', () => {
    expect(dispositionName(null)).toBeNull();
    expect(dispositionName('inline')).toBeNull();
  });
});

describe('csvPath', () => {
  it('adds format=csv and keeps the other parameters', () => {
    expect(csvPath('api/v1/alarms')).toBe('api/v1/alarms?format=csv');
    const path = csvPath('api/v1/commands?from=2026-11-18T00%3A00%3A00Z&format=json');
    const params = new URLSearchParams(path.split('?')[1]);
    expect(params.get('from')).toBe('2026-11-18T00:00:00Z');
    expect(params.get('format')).toBe('csv');
  });
});

describe('toCsv', () => {
  it('quotes cells that need it and leaves empty cells empty', () => {
    const text = toCsv(
      ['at', 'value', 'note'],
      [
        ['t1', 33, 'a, "b"'],
        ['t2', null, undefined],
      ],
    );
    expect(text).toBe('at,value,note\r\nt1,33,"a, ""b"""\r\nt2,,\r\n');
  });

  it('neutralises text a spreadsheet would evaluate, but not negative numbers', () => {
    const text = toCsv(['a', 'b', 'c'], [['=SUM(A1)', '@x', -2.5]]);
    expect(text.split('\r\n')[1]).toBe("'=SUM(A1),'@x,-2.5");
  });
});
