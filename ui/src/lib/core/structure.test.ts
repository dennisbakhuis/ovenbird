import { readdirSync, readFileSync } from 'node:fs';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';

const SRC = fileURLToPath(new URL('../..', import.meta.url));
const COMPONENTS = join(SRC, 'components');
const LIB = join(SRC, 'lib');

const COMPONENT_FOLDERS = [
  'activity',
  'art',
  'brand',
  'charts',
  'help',
  'hold',
  'home',
  'house',
  'insight',
  'pump',
  'replay',
  'settings',
  'setpoint',
  'shadow',
  'shell',
  'stove',
  'system',
  'trial',
  'ui',
  'weather',
];

const LIB_FOLDERS = [
  'activity',
  'core',
  'help',
  'home',
  'house',
  'i18n',
  'notify',
  'pump',
  'replay',
  'setpoint',
  'settings',
  'shadow',
  'stove',
  'system',
  'trial',
  'weather',
];

function entries(dir: string): { files: string[]; folders: string[] } {
  const all = readdirSync(dir, { withFileTypes: true });
  return {
    files: all.filter((e) => e.isFile()).map((e) => e.name),
    folders: all.filter((e) => e.isDirectory()).map((e) => e.name),
  };
}

describe('source layout', () => {
  it('keeps components in ui/, shell/ or a feature folder, never loose in components/', () => {
    const { files, folders } = entries(COMPONENTS);
    expect(files, 'move it into components/shell or a feature folder').toEqual([]);
    expect(folders.filter((name) => !COMPONENT_FOLDERS.includes(name))).toEqual([]);
  });

  it('keeps lib modules in core/, i18n/, help/ or a feature folder, never loose in lib/', () => {
    const { files, folders } = entries(LIB);
    expect(files, 'move it into lib/core or a feature folder').toEqual([]);
    expect(folders.filter((name) => !LIB_FOLDERS.includes(name))).toEqual([]);
  });

  it('imports across folders through aliases, never a ../ path, also in dynamic imports', () => {
    const offenders: string[] = [];
    const walk = (dir: string): void => {
      for (const entry of readdirSync(dir, { withFileTypes: true })) {
        const path = join(dir, entry.name);
        if (entry.isDirectory()) walk(path);
        else if (/\.(ts|svelte)$/.test(entry.name) && !entry.name.startsWith('structure.test')) {
          if (/(?:from|import)\s*\(?\s*['"]\.\.\//.test(readFileSync(path, 'utf8')))
            offenders.push(path.slice(SRC.length));
        }
      }
    };
    walk(SRC);
    expect(offenders).toEqual([]);
  });
});
