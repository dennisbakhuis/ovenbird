import { sameValue, type DiffEntry } from './draft.svelte';
import type { ConfigDoc, ConfigSchema } from './types';

/**
 * Differences between the active configuration and an older version's stored values, as the
 * rollback would apply them: locked and non-editable fields are left alone, a field the old
 * version did not store returns to its default.
 */
export function rollbackDiff(
  values: Record<string, unknown>,
  config: ConfigDoc,
  schema: ConfigSchema | null,
): DiffEntry[] {
  const out: DiffEntry[] = [];
  for (const [field, known] of Object.entries(config.fields)) {
    if (known.locked || schema?.fields[field]?.editable === false) continue;
    const wanted = field in values ? values[field] : null;
    const unchanged =
      wanted === null
        ? known.stored === null || known.stored === undefined
        : sameValue(wanted, known.stored) || sameValue(wanted, known.value);
    if (unchanged) continue;
    out.push({
      field,
      from: known.value,
      to: wanted === null ? known.default : wanted,
      reset: wanted === null,
    });
  }
  return out;
}
