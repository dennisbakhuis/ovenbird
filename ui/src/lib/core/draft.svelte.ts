import { STORAGE_PREFIX } from './brand';
import { asCurve, sameCurve } from './curve';
import { CONNECTION_FIELDS } from './schema';
import type { ConfigDoc, ConfigExport, ConfigSchema } from './types';

const STORAGE_KEY = `${STORAGE_PREFIX}draft`;

export interface StorageLike {
  getItem(key: string): string | null;
  setItem(key: string, value: string): void;
  removeItem(key: string): void;
}

export interface DiffEntry {
  field: string;
  from: unknown;
  to: unknown;
  reset: boolean;
}

/**
 * Where a draft came from when it was not typed by hand, such as a suggestion:
 * a label for the draft bar and the default apply comment.
 */
export interface DraftOrigin {
  label: string;
  comment: string;
}

export interface ImportOutcome {
  imported: string[];
  locked: string[];
  unknown: string[];
}

/**
 * Structural equality for config values (numbers, strings, booleans, lists, window objects).
 */
export function sameValue(a: unknown, b: unknown): boolean {
  if (a === b) return true;
  const curveA = asCurve(a);
  const curveB = asCurve(b);
  if (curveA && curveB) return sameCurve(curveA, curveB);
  if (Array.isArray(a) && Array.isArray(b))
    return a.length === b.length && a.every((item, i) => sameValue(item, b[i]));
  if (a && b && typeof a === 'object' && typeof b === 'object') {
    const keys = [...Object.keys(a), ...Object.keys(b)];
    return keys.every((key) =>
      sameValue((a as Record<string, unknown>)[key], (b as Record<string, unknown>)[key]),
    );
  }
  return false;
}

function browserStorage(): StorageLike | null {
  try {
    return typeof localStorage === 'undefined' ? null : localStorage;
  } catch {
    return null;
  }
}

/**
 * Parse a config export file's text into its stored values, or an error code.
 */
export function parseExport(
  text: string,
): { values: Record<string, unknown> } | { error: 'not_json' | 'not_an_export' } {
  let parsed: unknown;
  try {
    parsed = JSON.parse(text);
  } catch {
    return { error: 'not_json' };
  }
  const doc = parsed as Partial<ConfigExport> | null;
  if (
    !doc ||
    typeof doc !== 'object' ||
    doc.ovenbird_config !== 1 ||
    !doc.values ||
    typeof doc.values !== 'object' ||
    Array.isArray(doc.values)
  )
    return { error: 'not_an_export' };
  return { values: doc.values };
}

/**
 * Browser-side draft of config changes, kept in localStorage per device. A value is a new
 * stored value; `null` removes the stored value so the field returns to its preset/default.
 * A change that equals what is already active is never kept.
 */
export class DraftStore {
  changes = $state<Record<string, unknown>>({});
  base = $state<number | null>(null);
  origin = $state<DraftOrigin | null>(null);
  #storage: StorageLike | null;

  constructor(storage: StorageLike | null = browserStorage()) {
    this.#storage = storage;
    this.#load();
  }

  get count(): number {
    return Object.keys(this.changes).length;
  }

  has(field: string): boolean {
    return field in this.changes;
  }

  /**
   * Value to show for a field: the draft value, the default when the draft resets it, or the
   * active value.
   */
  value(field: string, config: ConfigDoc | null): unknown {
    if (field in this.changes) {
      const draft = this.changes[field];
      return draft === null ? config?.fields[field]?.default : draft;
    }
    return config?.fields[field]?.value;
  }

  set(field: string, value: unknown, config: ConfigDoc | null): void {
    const known = config?.fields[field];
    if (known?.locked) return;
    if (known && sameValue(value, known.value)) delete this.changes[field];
    else this.changes[field] = value;
    this.origin = null;
    this.#touch(config);
  }

  reset(field: string, config: ConfigDoc | null): void {
    const known = config?.fields[field];
    if (known?.locked) return;
    if (known && known.stored !== null && known.stored !== undefined) this.changes[field] = null;
    else delete this.changes[field];
    this.origin = null;
    this.#touch(config);
  }

  revert(field: string, config: ConfigDoc | null): void {
    delete this.changes[field];
    this.origin = null;
    this.#touch(config);
  }

  /**
   * Replace the draft with a set of changes that came from elsewhere (a suggestion), with the
   * label and default comment that go with them. Values equal to the active config are left out;
   * the origin is kept only when something remains.
   */
  loadChanges(
    changes: Record<string, unknown>,
    origin: DraftOrigin,
    config: ConfigDoc | null,
  ): number {
    this.changes = {};
    this.base = null;
    for (const [field, value] of Object.entries(changes)) {
      const known = config?.fields[field];
      if (known?.locked) continue;
      if (known && sameValue(value, known.value)) continue;
      this.changes[field] = value;
    }
    this.origin = this.count > 0 ? origin : null;
    this.#touch(config);
    return this.count;
  }

  clear(): void {
    this.changes = {};
    this.base = null;
    this.origin = null;
    this.#save();
  }

  /**
   * Drop changes that no longer differ from the active config (after a refresh or rebase).
   */
  prune(config: ConfigDoc): void {
    for (const [field, value] of Object.entries(this.changes)) {
      const known = config.fields[field];
      if (!known || known.locked) delete this.changes[field];
      else if (
        value === null
          ? known.stored === null || known.stored === undefined
          : sameValue(value, known.value)
      )
        delete this.changes[field];
    }
    this.base = this.count > 0 ? config.version : null;
    this.#save();
  }

  /**
   * Whether the config moved on since the draft was started.
   */
  isStale(config: ConfigDoc | null): boolean {
    return this.count > 0 && config !== null && this.base !== null && this.base !== config.version;
  }

  diff(config: ConfigDoc | null): DiffEntry[] {
    return Object.entries(this.changes).map(([field, value]) => {
      const known = config?.fields[field];
      const reset = value === null;
      return { field, from: known?.value, to: reset ? known?.default : value, reset };
    });
  }

  /**
   * Turn a complete stored-values document (an import file or an old version) into a draft:
   * every unlocked schema field takes the document's value, or is reset when absent.
   */
  loadDocument(
    values: Record<string, unknown>,
    config: ConfigDoc,
    schema: ConfigSchema | null,
  ): ImportOutcome {
    const outcome: ImportOutcome = { imported: [], locked: [], unknown: [] };
    const next: Record<string, unknown> = {};
    for (const key of Object.keys(values)) {
      if (!config.fields[key] || (schema && !schema.fields[key])) outcome.unknown.push(key);
      else if (config.fields[key].locked) outcome.locked.push(key);
    }
    for (const [field, known] of Object.entries(config.fields)) {
      if (
        known.locked ||
        CONNECTION_FIELDS.has(field) ||
        (schema && schema.fields[field]?.tier === 'expert')
      )
        continue;
      const wanted = field in values ? values[field] : null;
      const unchanged =
        wanted === null
          ? known.stored === null || known.stored === undefined
          : sameValue(wanted, known.value);
      if (unchanged) continue;
      next[field] = wanted;
      outcome.imported.push(field);
    }
    this.changes = next;
    this.origin = null;
    this.#touch(config);
    return outcome;
  }

  #touch(config: ConfigDoc | null): void {
    if (this.count === 0) {
      this.base = null;
      this.origin = null;
    } else if (this.base === null) this.base = config?.version ?? null;
    this.#save();
  }

  #save(): void {
    try {
      if (this.count === 0) this.#storage?.removeItem(STORAGE_KEY);
      else
        this.#storage?.setItem(
          STORAGE_KEY,
          JSON.stringify({ base: this.base, changes: this.changes, origin: this.origin }),
        );
    } catch {
      return;
    }
  }

  #load(): void {
    try {
      const raw = this.#storage?.getItem(STORAGE_KEY);
      if (!raw) return;
      const stored = JSON.parse(raw) as { base?: unknown; changes?: unknown; origin?: unknown };
      if (stored.changes && typeof stored.changes === 'object' && !Array.isArray(stored.changes)) {
        this.changes = stored.changes as Record<string, unknown>;
        this.base = typeof stored.base === 'number' ? stored.base : null;
        const origin = stored.origin as Partial<DraftOrigin> | null | undefined;
        this.origin =
          origin && typeof origin.label === 'string' && typeof origin.comment === 'string'
            ? { label: origin.label, comment: origin.comment }
            : null;
      }
    } catch {
      this.changes = {};
    }
  }
}

export const draft = new DraftStore();
