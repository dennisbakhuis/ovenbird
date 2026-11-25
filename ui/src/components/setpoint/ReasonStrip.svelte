<!--
  ReasonStrip: how the time in the window was spent per reason category (normal control, limited
  or smoothed, frozen, held or refused, manual), as one proportional bar with a legend of shares.
  The per-moment reason is the lane in the history chart; this is its summary.

  Props: segments (ReasonSegment[] from stackSeries), from, to (ms).
  A11y: the bar is role="img" with "Normal control 72 %, limited or smoothed 25 % …"; the
  legend repeats every share as text.
-->
<script lang="ts">
  import { formatDuration } from '$lib/core/format';
  import {
    REASON_CATEGORY_LIST,
    reasonCategory,
    type ReasonCategory,
    type ReasonSegment,
  } from '$lib/setpoint/series';
  import { settings, t } from '$lib/core/settings.svelte';

  interface Props {
    segments: ReasonSegment[];
    from: number;
    to: number;
  }

  let { segments, from, to }: Props = $props();

  const shares = $derived.by(() => {
    const totals: Partial<Record<ReasonCategory, number>> = {};
    for (const segment of segments) {
      const ms = Math.max(0, Math.min(segment.to, to) - Math.max(segment.from, from));
      const category = reasonCategory(segment.reason);
      totals[category] = (totals[category] ?? 0) + ms;
    }
    const all = Object.values(totals).reduce((sum, ms) => sum + ms, 0);
    return REASON_CATEGORY_LIST.filter((category) => (totals[category] ?? 0) > 0).map(
      (category) => {
        const ms = totals[category] ?? 0;
        return { category, ms, share: all > 0 ? ms / all : 0 };
      },
    );
  });

  const percent = (share: number) =>
    new Intl.NumberFormat(settings.language, { style: 'percent', maximumFractionDigits: 0 }).format(
      share,
    );
  const label = (category: ReasonCategory) => t(`reasonCat_${category}` as 'reasonCat_normal');
  const summary = $derived(
    `${t('reasonStripLabel')}: ${shares
      .map((item) => `${label(item.category)} ${percent(item.share)}`)
      .join(', ')}`,
  );
</script>

<div class="strip" data-testid="reason-strip">
  <div class="bar" role="img" aria-label={summary}>
    {#each shares as item (item.category)}
      <span class="seg {item.category}" style:flex-grow={item.share}></span>
    {/each}
  </div>
  <ul class="legend">
    {#each shares as item (item.category)}
      <li>
        <i class="dot {item.category}"></i>
        <span>{label(item.category)}</span>
        <strong>{percent(item.share)}</strong>
        <span class="muted duration">{formatDuration(item.ms / 1000)}</span>
      </li>
    {/each}
  </ul>
</div>

<style>
  .strip {
    display: grid;
    gap: var(--space-2);
  }
  .bar {
    display: flex;
    gap: 2px;
    height: 10px;
    border-radius: var(--radius-m);
    overflow: hidden;
    background: var(--surface-2);
  }
  .seg {
    flex-basis: 0;
    min-width: 3px;
  }
  .legend {
    list-style: none;
    display: flex;
    flex-wrap: wrap;
    gap: var(--space-1) var(--space-4);
    margin: 0;
    padding: 0;
    font-size: var(--fs-caption);
  }
  .legend li {
    display: inline-flex;
    align-items: center;
    gap: 0.35rem;
  }
  .legend strong {
    font-variant-numeric: tabular-nums;
  }
  @container main (max-width: 40rem) {
    .legend {
      gap: var(--space-1) var(--space-3);
    }
    .duration {
      display: none;
    }
  }
  .dot {
    display: inline-block;
    width: 0.65rem;
    height: 0.65rem;
    border-radius: var(--radius-2xs);
  }
  .normal {
    background: var(--cat-normal);
  }
  .limited {
    background: var(--cat-limited);
  }
  .frozen {
    background: var(--cat-frozen);
  }
  .stopped {
    background: var(--cat-stopped);
  }
  .manual {
    background: var(--cat-manual);
  }
</style>
