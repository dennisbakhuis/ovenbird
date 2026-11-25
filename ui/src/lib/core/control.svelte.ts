import {
  failureKind,
  type FailureKind,
  fetchConfig,
  fetchDecisionsLatest,
  isMissing,
  pauseControl,
  releaseHold,
  resumeControl,
  setStove,
} from './api';
import type { MessageKey } from '$lib/i18n';
import type {
  ConfigDoc,
  ControlStatus,
  Decision,
  ModeChange,
  ReleaseResult,
  StoveResult,
} from './types';

export type ActionError = FailureKind;

export function classifyError(error: unknown): ActionError {
  return failureKind(error);
}

const ACTION_KEYS = {
  unauthorized: 'actionUnauthorized',
  forbidden: 'actionForbidden',
  too_large: 'actionTooLarge',
  unsupported: 'actionUnsupported',
  missing: 'actionMissing',
  conflict: 'actionConflict',
  rate_limited: 'actionRateLimited',
  invalid: 'actionFailed',
  failed: 'actionFailed',
} as const satisfies Record<ActionError, MessageKey>;

/**
 * Message key explaining a failed action by its HTTP status class.
 */
export function actionKey(kind: ActionError): MessageKey {
  return ACTION_KEYS[kind];
}

/**
 * Control-loop state: latest decision, control status and config document, with the actions that
 * change the mode or release a hold. `admin` is learned from responses: null until an admin
 * action succeeded or was refused.
 */
export class ControlStore {
  decision = $state<Decision | null>(null);
  control = $state<ControlStatus | null>(null);
  config = $state<ConfigDoc | null>(null);
  configMissing = $state(false);
  loaded = $state(false);
  failed = $state(false);
  admin = $state<boolean | null>(null);

  #timer: number | null = null;
  #busy = false;

  start(intervalMs = 15_000): void {
    void this.refresh();
    if (this.#timer === null)
      this.#timer = window.setInterval(() => void this.refresh(), intervalMs);
  }

  stop(): void {
    if (this.#timer !== null) window.clearInterval(this.#timer);
    this.#timer = null;
  }

  async refresh(): Promise<void> {
    if (this.#busy) return;
    this.#busy = true;
    try {
      const latest = await fetchDecisionsLatest();
      this.decision = latest.decision;
      this.control = latest.control;
      this.failed = false;
    } catch {
      this.failed = true;
    } finally {
      this.loaded = true;
      this.#busy = false;
    }
    try {
      this.config = await fetchConfig();
      this.configMissing = false;
    } catch (error) {
      if (isMissing(error)) this.configMissing = true;
    }
  }

  #learn(error: unknown): ActionError {
    const kind = classifyError(error);
    if (kind === 'forbidden' || kind === 'unauthorized') this.admin = false;
    return kind;
  }

  #apply(result: ModeChange | ReleaseResult): void {
    if (result.control) this.control = result.control;
    this.admin = true;
  }

  /**
   * Start wood-stove mode by hand for `hours` from `nowMs` (the service clock), or stop it
   * (`hours` null): the stop is one-shot, the detection stays blocked until the room has cooled
   * below the exit threshold.
   */
  async stove(hours: number | null, nowMs: number): Promise<ActionError | null> {
    try {
      const until = hours === null ? undefined : nowMs + hours * 3_600_000;
      const result: StoveResult = await setStove(hours !== null, until);
      if (this.control && result.stove) this.control = { ...this.control, stove: result.stove };
    } catch (error) {
      return this.#learn(error);
    }
    await this.refresh();
    return null;
  }

  async pause(): Promise<ActionError | null> {
    try {
      this.#apply(await pauseControl());
    } catch (error) {
      return this.#learn(error);
    }
    await this.refresh();
    return null;
  }

  async resume(): Promise<ActionError | null> {
    try {
      this.#apply(await resumeControl());
    } catch (error) {
      return this.#learn(error);
    }
    await this.refresh();
    return null;
  }

  async release(reason: string): Promise<ActionError | null> {
    try {
      this.#apply(await releaseHold(reason));
    } catch (error) {
      return this.#learn(error);
    }
    await this.refresh();
    return null;
  }
}
