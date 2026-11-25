import { splitTarget } from './resolve';
import type { HelpTopicId } from './types';

export type HelpView =
  | { kind: 'page' }
  | { kind: 'topic'; id: HelpTopicId }
  | { kind: 'index' }
  | { kind: 'glossary'; entry?: string };

export interface HelpFocus {
  section?: string;
  target?: string;
  question?: string;
  seq: number;
}

/**
 * Navigation inside the help drawer: what it shows, the way back, the section or question to
 * bring into view, and the element "Show me" rings.
 */
export class HelpNav {
  view = $state<HelpView>({ kind: 'page' });
  history = $state<HelpView[]>([]);
  focus = $state<HelpFocus | null>(null);
  spotlight = $state<{ target: string; seq: number } | null>(null);
  #seq = 0;

  /** Start over at the current page, or at the section a `data-help` target belongs to. */
  start(target: string | null = null): void {
    this.history = [];
    this.spotlight = null;
    if (!target) {
      this.view = { kind: 'page' };
      this.focus = null;
      return;
    }
    const { topic, section } = splitTarget(target);
    this.view = topic ? { kind: 'topic', id: topic } : { kind: 'page' };
    this.focus = { target, section, seq: ++this.#seq };
  }

  /** Show the help of the page the router is on now (after navigation). */
  follow(): void {
    this.start();
  }

  /** Move to another view, keeping a way back. */
  go(view: HelpView, focus?: Omit<HelpFocus, 'seq'>): void {
    this.history = [...this.history, this.view];
    this.view = view;
    this.focus = focus ? { ...focus, seq: ++this.#seq } : null;
  }

  back(): void {
    const previous = this.history[this.history.length - 1];
    if (!previous) return;
    this.history = this.history.slice(0, -1);
    this.view = previous;
    this.focus = null;
  }

  /** Ring the element marked `data-help="<target>"`, again when it is already ringed. */
  point(target: string): void {
    this.spotlight = { target, seq: ++this.#seq };
  }

  unpoint(): void {
    this.spotlight = null;
  }
}
