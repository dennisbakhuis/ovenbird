import { readdirSync, readFileSync } from 'node:fs';
import { join, relative } from 'node:path';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';

const SRC = fileURLToPath(new URL('../..', import.meta.url));
const PRIMITIVES = join(SRC, 'components', 'ui');

const ALLOWED: Record<string, string> = {};

const BANNED = [
  { name: '<button', pattern: /<button[\s>]/ },
  { name: '<input', pattern: /<input[\s>]/ },
  { name: '<select', pattern: /<select[\s>]/ },
  { name: '<textarea', pattern: /<textarea[\s>]/ },
  { name: 'class="card"', pattern: /class="(?:[^"]*\s)?card(?:\s[^"]*)?"/ },
];

function files(dir: string): string[] {
  return readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const path = join(dir, entry.name);
    if (entry.isDirectory()) return path === PRIMITIVES ? [] : files(path);
    return entry.name.endsWith('.svelte') && !entry.name.endsWith('.test.svelte') ? [path] : [];
  });
}

describe('shared primitives', () => {
  it('keeps raw controls and cards inside components/ui', () => {
    const offenders: string[] = [];
    for (const path of files(SRC)) {
      const name = relative(SRC, path);
      const markup = readFileSync(path, 'utf8').split('<style>')[0] ?? '';
      for (const { name: banned, pattern } of BANNED) {
        if (pattern.test(markup) && !(name in ALLOWED)) offenders.push(`${name}: ${banned}`);
      }
    }
    expect(offenders, 'use Button, TextInput, Select, Checkbox, Switch, Segmented or Card').toEqual(
      [],
    );
  });

  it('has no allowlisted file that no longer needs it', () => {
    for (const name of Object.keys(ALLOWED)) {
      const markup = readFileSync(join(SRC, name), 'utf8').split('<style>')[0] ?? '';
      expect(
        BANNED.some(({ pattern }) => pattern.test(markup)),
        name,
      ).toBe(true);
    }
  });
});
