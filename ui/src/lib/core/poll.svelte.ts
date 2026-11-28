export interface PollOptions {
  /** Delay between the end of one run and the start of the next, fixed or read per run. */
  intervalMs: number | (() => number);
  /** Upper bound for the back-off after failed runs; unset keeps the plain interval. */
  maxBackoffMs?: number;
  /** Run the task at once on start (default); false waits one interval first. */
  immediate?: boolean;
}

export type PollTask = (signal: AbortSignal) => Promise<unknown>;

/**
 * Delay before the next run: the interval, doubled per consecutive failure up to `maxBackoffMs`.
 */
export function pollDelay(intervalMs: number, failures: number, maxBackoffMs?: number): number {
  if (maxBackoffMs === undefined || failures === 0) return intervalMs;
  return Math.min(maxBackoffMs, intervalMs * 2 ** failures);
}

/**
 * Runs `task` now and again after every interval until stopped. A task that resolves to `'stop'`
 * ends the loop; one that rejects counts as a failure and backs off when `maxBackoffMs` is set.
 * The next run is scheduled when the previous one ends, so runs never overlap, and stopping
 * aborts the signal handed to the running task.
 */
export class Poller {
  failures = $state(0);

  #task: PollTask;
  #options: PollOptions;
  #controller: AbortController | null = null;
  #timer: ReturnType<typeof setTimeout> | undefined;
  #running = false;

  constructor(task: PollTask, options: PollOptions) {
    this.#task = task;
    this.#options = options;
  }

  /**
   * Start polling and return the function that stops it, ready to return from an `$effect`. The
   * first run starts synchronously, so the effect tracks what the task reads before its first
   * await.
   */
  start(): () => void {
    this.stop();
    const controller = new AbortController();
    this.#controller = controller;
    this.failures = 0;
    if (this.#options.immediate === false) this.#schedule(controller);
    else void this.#run(controller);
    return () => this.stop();
  }

  stop(): void {
    clearTimeout(this.#timer);
    this.#timer = undefined;
    this.#controller?.abort();
    this.#controller = null;
    this.#running = false;
  }

  /**
   * Run the task now instead of waiting for the timer; ignored while a run is in flight.
   */
  refresh(): void {
    const controller = this.#controller;
    if (!controller || this.#running) return;
    clearTimeout(this.#timer);
    void this.#run(controller);
  }

  async #run(controller: AbortController): Promise<void> {
    this.#running = true;
    let stop = false;
    try {
      stop = (await this.#task(controller.signal)) === 'stop';
      this.failures = 0;
    } catch {
      if (!controller.signal.aborted) this.failures += 1;
    }
    if (controller.signal.aborted || this.#controller !== controller) return;
    this.#running = false;
    if (!stop) this.#schedule(controller);
  }

  #schedule(controller: AbortController): void {
    const { intervalMs, maxBackoffMs } = this.#options;
    const base = typeof intervalMs === 'function' ? intervalMs() : intervalMs;
    this.#timer = setTimeout(
      () => void this.#run(controller),
      pollDelay(base, this.failures, maxBackoffMs),
    );
  }
}

/**
 * Poll `task` for the lifetime of an `$effect`: `$effect(() => poll(load, { intervalMs }))`.
 */
export function poll(task: PollTask, options: PollOptions): () => void {
  return new Poller(task, options).start();
}
