import { ApiError, failureKind } from '$lib/core/api';
import {
  cancelReplay,
  fetchReplayJob,
  startReplay,
  type ReplayBody,
  type ReplayJob,
} from './replay';

export type RunProblem = 'forbidden' | 'invalid' | 'missing' | 'expired' | 'failed';

const POLL_MS = 600;

/**
 * The replay the page runs: started on the service as a job and polled until it ends. Kept at
 * module level, so leaving the tab and coming back shows the running or finished replay.
 */
export class ReplayRun {
  job = $state<ReplayJob | null>(null);
  problem = $state<RunProblem | null>(null);
  detail = $state<string | null>(null);
  starting = $state(false);
  #timer: ReturnType<typeof setTimeout> | null = null;
  #cancelAsked = false;
  #poll: (id: string) => Promise<ReplayJob>;
  #start: (body: ReplayBody) => Promise<ReplayJob>;
  #cancel: (id: string) => Promise<ReplayJob>;

  constructor(
    api: {
      poll?: (id: string) => Promise<ReplayJob>;
      start?: (body: ReplayBody) => Promise<ReplayJob>;
      cancel?: (id: string) => Promise<ReplayJob>;
    } = {},
  ) {
    this.#poll = api.poll ?? ((id) => fetchReplayJob(id));
    this.#start = api.start ?? startReplay;
    this.#cancel = api.cancel ?? cancelReplay;
  }

  get running(): boolean {
    return this.starting || this.job?.state === 'running';
  }

  async start(body: ReplayBody): Promise<void> {
    this.#stop();
    this.starting = true;
    this.#cancelAsked = false;
    this.problem = null;
    this.detail = null;
    try {
      this.job = await this.#start(body);
      this.#schedule();
    } catch (error) {
      this.#fail(error);
    } finally {
      this.starting = false;
    }
    if (this.#cancelAsked) await this.cancel();
  }

  /** Stop the running job; asked while it is still being started, it stops once it has an id. */
  async cancel(): Promise<void> {
    if (this.starting) {
      this.#cancelAsked = true;
      return;
    }
    this.#cancelAsked = false;
    const job = this.job;
    if (!job || job.state !== 'running') return;
    try {
      this.job = await this.#cancel(job.id);
      this.#schedule();
    } catch (error) {
      this.#fail(error);
    }
  }

  /** Poll again after a return to the page (polling stops while nothing shows the job). */
  resume(): void {
    if (this.job?.state === 'running' && this.#timer === null) this.#schedule();
  }

  /** Stop polling (the job keeps running on the service). */
  pause(): void {
    this.#stop();
  }

  #schedule(): void {
    this.#stop();
    if (this.job?.state !== 'running') return;
    this.#timer = setTimeout(() => void this.#tick(), POLL_MS);
  }

  async #tick(): Promise<void> {
    this.#timer = null;
    const job = this.job;
    if (!job) return;
    try {
      const next = await this.#poll(job.id);
      if (this.job?.id !== job.id) return;
      this.job = next;
      this.#schedule();
    } catch (error) {
      if (error instanceof ApiError && error.status === 404) {
        this.problem = 'expired';
        this.job = null;
        return;
      }
      this.#schedule();
    }
  }

  #fail(error: unknown): void {
    const kind = failureKind(error);
    this.problem =
      kind === 'forbidden' || kind === 'unauthorized'
        ? 'forbidden'
        : kind === 'invalid'
          ? 'invalid'
          : kind === 'missing'
            ? 'missing'
            : 'failed';
    const detail = error instanceof ApiError ? (error.body as { detail?: unknown } | null) : null;
    this.detail = typeof detail?.detail === 'string' ? detail.detail : null;
  }

  #stop(): void {
    if (this.#timer !== null) clearTimeout(this.#timer);
    this.#timer = null;
  }
}

export const replayRun = new ReplayRun();
