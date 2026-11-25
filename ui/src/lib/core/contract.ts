/**
 * A small JSON Schema check over `docs/openapi.json`, for the contract tests: does a body fit
 * the schema the service's response models generate? Objects are closed unless the schema says
 * otherwise (`additionalProperties`), so a key the API never sends is reported too; an empty
 * schema (a route without a model) accepts anything.
 */

export type Schema = { [key: string]: unknown };

export interface OpenApi {
  paths: Record<string, Record<string, { responses: Record<string, Response> }>>;
  components: { schemas: Record<string, Schema> };
}

interface Response {
  content?: Record<string, { schema?: Schema }>;
}

const REF = '#/components/schemas/';

function jsonType(value: unknown): string {
  if (value === null) return 'null';
  if (Array.isArray(value)) return 'array';
  return typeof value;
}

function fitsType(type: string, value: unknown): boolean {
  switch (type) {
    case 'integer':
      return Number.isInteger(value);
    case 'number':
      return typeof value === 'number';
    case 'object':
      return jsonType(value) === 'object';
    default:
      return jsonType(value) === type;
  }
}

/**
 * Where `value` breaks `schema`: one line per problem, empty when it fits.
 */
export function violations(api: OpenApi, schema: Schema, value: unknown, path = '$'): string[] {
  const ref = schema['$ref'];
  if (typeof ref === 'string') {
    const target = api.components.schemas[ref.slice(REF.length)];
    if (!ref.startsWith(REF) || !target) return [`${path}: unknown reference ${ref}`];
    return violations(api, target, value, path);
  }
  const options = (schema['anyOf'] ?? schema['oneOf']) as Schema[] | undefined;
  if (options) {
    const tried = options.map((option) => violations(api, option, value, path));
    if (tried.some((problems) => problems.length === 0)) return [];
    const nearest = tried.reduce((best, next) => (next.length < best.length ? next : best));
    return nearest.length ? nearest : [`${path}: fits none of the alternatives`];
  }
  if ('const' in schema && schema['const'] !== value) {
    return [`${path}: ${JSON.stringify(value)} is not ${JSON.stringify(schema['const'])}`];
  }
  const allowed = schema['enum'] as unknown[] | undefined;
  if (allowed && !allowed.includes(value)) {
    return [`${path}: ${JSON.stringify(value)} is not one of ${JSON.stringify(allowed)}`];
  }
  const type = schema['type'];
  if (typeof type === 'string' && !fitsType(type, value)) {
    return [`${path}: ${jsonType(value)} where the schema has ${type}`];
  }
  if (Array.isArray(value)) return arrayViolations(api, schema, value, path);
  if (jsonType(value) === 'object' && (type === 'object' || 'properties' in schema)) {
    return objectViolations(api, schema, value as Record<string, unknown>, path);
  }
  return [];
}

function arrayViolations(api: OpenApi, schema: Schema, value: unknown[], path: string): string[] {
  const prefix = (schema['prefixItems'] as Schema[] | undefined) ?? [];
  const items = schema['items'] as Schema | undefined;
  const out: string[] = [];
  const min = schema['minItems'];
  const max = schema['maxItems'];
  if (typeof min === 'number' && value.length < min) out.push(`${path}: fewer than ${min} items`);
  if (typeof max === 'number' && value.length > max) out.push(`${path}: more than ${max} items`);
  value.forEach((item, index) => {
    const own = prefix[index] ?? items;
    if (own) out.push(...violations(api, own, item, `${path}[${index}]`));
  });
  return out;
}

function objectViolations(
  api: OpenApi,
  schema: Schema,
  value: Record<string, unknown>,
  path: string,
): string[] {
  const properties = (schema['properties'] as Record<string, Schema> | undefined) ?? {};
  const required = (schema['required'] as string[] | undefined) ?? [];
  const extra = schema['additionalProperties'];
  const out = required.filter((key) => !(key in value)).map((key) => `${path}.${key}: missing`);
  for (const [key, item] of Object.entries(value)) {
    const own = properties[key];
    if (own) out.push(...violations(api, own, item, `${path}.${key}`));
    else if (typeof extra === 'object' && extra !== null) {
      out.push(...violations(api, extra as Schema, item, `${path}.${key}`));
    } else if (extra !== true) out.push(`${path}.${key}: not in the schema`);
  }
  return out;
}

/**
 * The schema of the JSON body `method path` answers with `status`, if the contract has one.
 */
export function responseSchema(
  api: OpenApi,
  method: string,
  path: string,
  status: number,
): Schema | null {
  const responses = api.paths[path]?.[method.toLowerCase()]?.responses;
  const response = responses?.[String(status)];
  return response?.content?.['application/json']?.schema ?? null;
}

/**
 * The path template of the contract that serves `path` (`/api/v1/config/versions/{number}`).
 */
export function templateOf(api: OpenApi, path: string): string | null {
  for (const template of Object.keys(api.paths)) {
    const pattern = new RegExp(`^${template.replace(/\{[^}]+\}/g, '[^/]+')}$`);
    if (pattern.test(path)) return template;
  }
  return null;
}
