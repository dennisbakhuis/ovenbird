import { fetchSchema, fetchSignals, isForbidden, isMissing, validateConfig } from './api';
import type { ConfigSchema, ConfigSignals, ValidateResult } from './types';

export type Availability = 'unknown' | 'ok' | 'missing' | 'forbidden' | 'failed';

/**
 * Schema, signal candidates and live server-side validation of the draft. A 404 from an older
 * server marks the feature as missing instead of failing.
 */
export class ConfigStore {
  schema = $state<ConfigSchema | null>(null);
  schemaState = $state<Availability>('unknown');
  signals = $state<ConfigSignals | null>(null);
  signalsState = $state<Availability>('unknown');
  validation = $state<ValidateResult | null>(null);
  validating = $state(false);
  #timer: number | null = null;
  #seq = 0;

  async loadSchema(): Promise<void> {
    if (this.schemaState === 'ok' || this.schemaState === 'missing') return;
    try {
      this.schema = await fetchSchema();
      this.schemaState = 'ok';
    } catch (error) {
      this.schemaState = isMissing(error) ? 'missing' : 'failed';
    }
  }

  async loadSignals(): Promise<void> {
    try {
      this.signals = await fetchSignals();
      this.signalsState = 'ok';
    } catch (error) {
      this.signalsState = isForbidden(error)
        ? 'forbidden'
        : isMissing(error)
          ? 'missing'
          : 'failed';
    }
  }

  /**
   * Validate the draft on the server after a short pause; clears the result for an empty draft.
   */
  schedule(changes: Record<string, unknown>, delayMs = 400): void {
    if (this.#timer !== null) window.clearTimeout(this.#timer);
    if (Object.keys(changes).length === 0) {
      this.validation = null;
      this.validating = false;
      this.#seq += 1;
      return;
    }
    this.validating = true;
    this.#timer = window.setTimeout(() => void this.#run({ ...changes }), delayMs);
  }

  async #run(changes: Record<string, unknown>): Promise<void> {
    const seq = (this.#seq += 1);
    try {
      const result = await validateConfig(changes);
      if (seq === this.#seq) this.validation = result;
    } catch {
      if (seq === this.#seq) this.validation = null;
    } finally {
      if (seq === this.#seq) this.validating = false;
    }
  }

  errorsFor(field: string): string[] {
    return (this.validation?.errors ?? []).filter((e) => e.field === field).map((e) => e.code);
  }

  warningsFor(field: string): string[] {
    return (this.validation?.warnings ?? []).filter((e) => e.field === field).map((e) => e.code);
  }
}

export const cfg = new ConfigStore();
