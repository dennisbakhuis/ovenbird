import { displayUnit, toDisplay } from '$lib/core/schema';
import type { FieldDef, ValidationIssue } from '$lib/core/types';

export type Lookup = (key: string, params: Record<string, string | number>) => string | undefined;

const BOUND_CODES = new Set(['below_min', 'above_max', 'below_soft_min', 'above_soft_max']);
const BOUNDS = ['min', 'max', 'soft_min', 'soft_max'] as const;

function plain(value: unknown): string | number | null {
  if (typeof value === 'number') return Math.round(value * 100) / 100;
  if (typeof value === 'string') return value;
  if (typeof value === 'boolean') return value ? 'true' : 'false';
  if (Array.isArray(value)) return value.map((item) => plain(item) ?? '').join(', ');
  return null;
}

/**
 * Text parameters for an issue: the server's `params` (lists joined), and for bound codes the
 * schema's bounds converted to the display unit of the field.
 */
export function issueParams(
  code: string,
  params: Record<string, unknown> | undefined,
  def: FieldDef | undefined,
): Record<string, string | number> {
  const out: Record<string, string | number> = { unit: def ? displayUnit(def) : '' };
  for (const [key, value] of Object.entries(params ?? {})) {
    const text = plain(value);
    if (text !== null) out[key] = text;
  }
  if (def && BOUND_CODES.has(code)) {
    for (const key of BOUNDS) {
      const bound = def[key];
      out[key] = bound === null || bound === undefined ? '' : toDisplay(def, bound);
    }
  }
  return out;
}

/**
 * Human text for a validation issue from its code and params, falling back to the server's
 * English message and finally the code.
 */
export function issueText(
  issue: Pick<ValidationIssue, 'code' | 'message'> & Partial<Pick<ValidationIssue, 'params'>>,
  def: FieldDef | undefined,
  lookup: Lookup,
): string {
  return (
    lookup(`check_${issue.code}`, issueParams(issue.code, issue.params, def)) ||
    issue.message ||
    issue.code
  );
}
