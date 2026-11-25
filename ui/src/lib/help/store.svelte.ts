import { STORAGE_PREFIX } from '$lib/core/brand';
const SEEN_KEY = `${STORAGE_PREFIX}helpSeen`;

function readSeen(): boolean {
  try {
    return localStorage.getItem(SEEN_KEY) === '1';
  } catch {
    return false;
  }
}

/**
 * Whether the help drawer is open, the last request to open it (optionally at a `data-help`
 * target), and whether help was ever opened in this browser. Kept small: it is part of the
 * first paint; the drawer keeps its own navigation state (nav.svelte.ts).
 */
export class HelpStore {
  open = $state(false);
  seen = $state(readSeen());
  request = $state<{ target: string | null; seq: number }>({ target: null, seq: 0 });
  #returnTo: HTMLElement | null = null;

  /** Open the drawer at the current page, or at the section of a `data-help` target. */
  show(target: string | null = null): void {
    if (!this.open) {
      const active = document.activeElement;
      this.#returnTo = active instanceof HTMLElement && active !== document.body ? active : null;
    }
    this.request = { target, seq: this.request.seq + 1 };
    this.open = true;
    if (this.seen) return;
    this.seen = true;
    try {
      localStorage.setItem(SEEN_KEY, '1');
    } catch {
      return;
    }
  }

  /** Close the drawer and return focus to where it was before it opened. */
  close(): void {
    if (!this.open) return;
    this.open = false;
    const back = this.#returnTo;
    this.#returnTo = null;
    if (back?.isConnected) back.focus();
  }

  toggle(): void {
    if (this.open) this.close();
    else this.show();
  }
}

export const help = new HelpStore();
