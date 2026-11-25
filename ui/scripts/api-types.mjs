// Generates src/lib/core/api-types.gen.ts from docs/openapi.json (the API v1 contract).
// `node scripts/api-types.mjs` writes the file; `--check` fails when it is stale.
import { readFile, writeFile } from 'node:fs/promises';
import openapiTS, { astToString } from 'openapi-typescript';
import * as prettier from 'prettier';

const schema = new URL('../../docs/openapi.json', import.meta.url);
const target = new URL('../src/lib/core/api-types.gen.ts', import.meta.url);
const banner =
  '// Generated from docs/openapi.json by `npm run api-types`; do not edit.\n' +
  '// The Python response models are the source: run `make api-schema` first.\n\n';

const ast = await openapiTS(schema, { alphabetize: true });
const options = (await prettier.resolveConfig(target)) ?? {};
const text = await prettier.format(banner + astToString(ast), {
  ...options,
  filepath: target.pathname,
});

if (process.argv.includes('--check')) {
  const current = await readFile(target, 'utf8').catch(() => '');
  if (current !== text) {
    console.error('src/lib/core/api-types.gen.ts is stale; run npm run api-types');
    process.exit(1);
  }
} else {
  await writeFile(target, text);
}
