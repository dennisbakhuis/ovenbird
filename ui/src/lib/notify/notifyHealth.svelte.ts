import { fetchNotifications, type NotificationStatus } from '$lib/system/about';
import { notifyVerdict, type NotifyVerdict } from './notify';

const REFRESH_MS = 5 * 60_000;

/**
 * The notification channels as the whole app sees them, so Home and the status strip can say
 * "alerts are not reaching you" without the System page open. Polled every 5 minutes; the System
 * tile hands over what it loads (and the result of a test) through `set`. Stays null on a service
 * without `notifications/status` and after a failed load.
 */
class NotifyHealth {
  status = $state<NotificationStatus | null>(null);

  get verdict(): NotifyVerdict | null {
    return notifyVerdict(this.status);
  }

  /** Alerts are set up but do not reach anyone. */
  get failing(): boolean {
    return this.verdict?.failing === true;
  }

  set(status: NotificationStatus | null): void {
    this.status = status;
  }

  /**
   * Start polling; returns the function that stops it.
   */
  start(): () => void {
    const controller = new AbortController();
    let timer: number | undefined;
    const load = async () => {
      try {
        const status = await fetchNotifications(controller.signal);
        if (!controller.signal.aborted) this.status = status;
      } catch {
        if (!controller.signal.aborted) this.status = null;
      }
      if (!controller.signal.aborted) timer = window.setTimeout(load, REFRESH_MS);
    };
    void load();
    return () => {
      controller.abort();
      window.clearTimeout(timer);
    };
  }
}

export const notifyHealth = new NotifyHealth();
