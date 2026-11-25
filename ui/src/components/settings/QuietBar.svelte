<!--
  QuietBar: quiet-mode windows on a 24 h bar (darker = higher level), hour ticks underneath and
  an optional "now" marker. role="img" with the windows as text.
-->
<script lang="ts">
  import type { QuietWindow } from '$lib/core/fieldFormat';
  import { DAY_MINUTES, windowSegments } from '$lib/settings/quiet';
  import { t } from '$lib/core/settings.svelte';

  interface Props {
    windows: QuietWindow[];
    ticks?: boolean;
    now?: number | null;
    height?: number;
    label?: string;
    testid?: string;
  }

  let { windows, ticks = true, now = null, height = 18, label, testid }: Props = $props();

  const segments = $derived(windowSegments(windows));
  const hours = [0, 6, 12, 18, 24];
  const text = $derived(
    windows.length === 0
      ? t('quietNone')
      : windows
          .map((w) => t('quietWindowText', { start: w.start, end: w.end, level: w.level }))
          .join(', '),
  );
</script>

<div
  class="bar"
  class:ticks
  style:height="{height}px"
  role="img"
  aria-label="{label ?? t('quietBarLabel')}: {text}"
  data-testid={testid}
>
  {#each segments as segment, i (i)}
    <span
      class="seg level-{segment.level}"
      style:left="{(segment.from / DAY_MINUTES) * 100}%"
      style:width="{((segment.to - segment.from) / DAY_MINUTES) * 100}%"
    ></span>
  {/each}
  {#if now !== null}
    <span class="now" style:left="{(now / DAY_MINUTES) * 100}%"></span>
  {/if}
  {#if ticks}
    {#each hours as hour (hour)}
      <span
        class="tick"
        class:first={hour === 0}
        class:last={hour === 24}
        style:left="{(hour / 24) * 100}%"><i>{hour}</i></span
      >
    {/each}
  {/if}
</div>

<style>
  .bar {
    position: relative;
    width: 100%;
    background: var(--surface-2);
    border: 1px solid var(--border);
    border-radius: var(--radius-sm);
  }
  .bar.ticks {
    margin-bottom: 1.1rem;
  }
  .seg {
    position: absolute;
    top: 0;
    bottom: 0;
    background: var(--series-quiet);
  }
  .seg.level-1 {
    opacity: 0.45;
  }
  .seg.level-2 {
    opacity: 0.72;
  }
  .seg.level-3 {
    opacity: 1;
  }
  .now {
    position: absolute;
    top: -3px;
    bottom: -3px;
    width: 2px;
    margin-left: -1px;
    background: var(--text);
  }
  .tick {
    position: absolute;
    top: 100%;
    width: 1px;
    height: 4px;
    background: var(--border);
  }
  .tick i {
    position: absolute;
    top: 4px;
    transform: translateX(-50%);
    font-style: normal;
    font-size: var(--fs-3xs);
    color: var(--muted);
  }
  .tick.first i {
    transform: none;
  }
  .tick.last i {
    transform: translateX(-100%);
  }
</style>
