import { describe, expect, it } from 'vitest';
import { DOWNLOAD_PREFIX, NAME, STORAGE_PREFIX } from './brand';

describe('brand', () => {
  it('keeps the strings that users already hold in storage and downloads', () => {
    expect(NAME).toBe('ovenbird');
    expect(`${STORAGE_PREFIX}details.`).toBe('ovenbird.details.');
    expect(`${STORAGE_PREFIX}theme`).toBe('ovenbird.theme');
    expect(`${DOWNLOAD_PREFIX}diagnostics.json`).toBe('ovenbird-diagnostics.json');
  });
});
