<!--
  Crosshair: transparent overlay that turns a plot into a keyboard and pointer operable time
  cursor (role="slider"). Used inside TimeChart, Sparkline and StateStrip; not for pages.

  Props: from, to (ms); times (sorted sample times to snap to; empty = continuous);
  cursor (bindable, ms or null); label (aria-label); valuetext (aria-valuetext, the read-out);
  left, top, width, height (px inside the positioned parent); onpick(t) on click/Enter;
  orientation 'x' (default, time runs left to right) or 'y' (rows top to bottom, ↑/↓ keys).
  Keys: ←/→ one sample, Shift+←/→ or PageUp/PageDown a twelfth of the span, Home/End, Esc clears.
  Mouse hover moves the cursor and leaving clears it; touch drag scrubs and the cursor stays
  after lifting the finger (vertical page scroll keeps working: touch-action pan-y).
-->
<script lang="ts">
  import { nearestIndex, stepCursor } from '$lib/core/chart';

  interface Props {
    from: number;
    to: number;
    times: number[];
    cursor?: number | null;
    label: string;
    valuetext: string;
    left: number;
    top: number;
    width: number;
    height: number;
    onpick?: (t: number) => void;
    orientation?: 'x' | 'y';
  }

  let {
    from,
    to,
    times,
    cursor = $bindable(null),
    label,
    valuetext,
    left,
    top,
    width,
    height,
    onpick,
    orientation = 'x',
  }: Props = $props();

  function timeAt(event: PointerEvent): number {
    const box = (event.currentTarget as HTMLElement).getBoundingClientRect();
    const offset = orientation === 'x' ? event.clientX - box.left : event.clientY - box.top;
    const size = orientation === 'x' ? box.width : box.height;
    const ratio = Math.min(Math.max(offset / Math.max(size, 1), 0), 1);
    const raw = from + ratio * (to - from);
    if (times.length === 0) return raw;
    return times[nearestIndex(times, raw)] ?? raw;
  }

  function onpointerdown(event: PointerEvent): void {
    cursor = timeAt(event);
  }

  function onpointermove(event: PointerEvent): void {
    if (event.pointerType === 'mouse' || event.buttons > 0) cursor = timeAt(event);
  }

  function onpointerleave(event: PointerEvent): void {
    if (event.pointerType === 'mouse') cursor = null;
  }

  function onkeydown(event: KeyboardEvent): void {
    if (event.key === 'Escape') {
      cursor = null;
      return;
    }
    if (event.key === 'Enter' || event.key === ' ') {
      if (cursor !== null && onpick) {
        event.preventDefault();
        onpick(cursor);
      }
      return;
    }
    const SWAP: Record<string, string> = { ArrowUp: 'ArrowDown', ArrowDown: 'ArrowUp' };
    const key = orientation === 'y' ? (SWAP[event.key] ?? event.key) : event.key;
    const next = stepCursor(times, cursor, key, from, to, event.shiftKey);
    if (next === undefined) return;
    event.preventDefault();
    cursor = next;
  }
</script>

<div
  class="crosshair"
  class:pickable={onpick !== undefined}
  role="slider"
  tabindex="0"
  aria-label={label}
  aria-orientation={orientation === 'x' ? 'horizontal' : 'vertical'}
  aria-valuemin={from}
  aria-valuemax={to}
  aria-valuenow={cursor ?? to}
  aria-valuetext={valuetext}
  style="left: {left}px; top: {top}px; width: {width}px; height: {height}px"
  data-testid="chart-crosshair"
  {onpointerdown}
  {onpointermove}
  {onpointerleave}
  onclick={() => cursor !== null && onpick?.(cursor)}
  {onkeydown}
  onblur={() => (cursor = null)}
></div>

<style>
  .crosshair {
    position: absolute;
    touch-action: pan-y;
    border-radius: var(--radius-s);
  }
  .crosshair:focus-visible {
    outline: 2px solid var(--accent);
    outline-offset: 2px;
  }
  .pickable {
    cursor: crosshair;
  }
</style>
