<!--
  CoverageStrip: one cell per day of the replayable window, filled by the share of the expected
  decisions that are stored (complete, partly, none), with the chosen period outlined. Picking a
  day chooses that day as the period.

  Props: coverage (GET replay/coverage), period (chosen, ms), now (service clock, ms), onpick.
  A11y: each day is a button named by its date and decision count; the legend repeats the fills.
-->
<script lang="ts">
  import Button from '$ui/Button.svelte';
  import { formatDay, formatNumber } from '$lib/core/format';
  import { settings, t } from '$lib/core/settings.svelte';
  import {
    coverageCells,
    inPeriod,
    type CoverageCell,
    type ReplayCoverage,
  } from '$lib/replay/replay';

  interface Props {
    coverage: ReplayCoverage;
    period: { from: number; to: number } | null;
    now: number;
    onpick: (cell: CoverageCell) => void;
  }

  let { coverage, period, now, onpick }: Props = $props();

  const lang = $derived(settings.language);
  const cells = $derived(coverageCells(coverage));
  const stored = $derived(cells.some((cell) => cell.decisions > 0));
  const kept = $derived(
    coverage.retention_days > 0
      ? t('replayCoverageKept', {
          days: formatNumber(coverage.retention_days, 0, lang),
          max: formatNumber(coverage.max_days, 0, lang),
        })
      : t('replayCoverageForever', { max: formatNumber(coverage.max_days, 0, lang) }),
  );
</script>

<div class="coverage" data-testid="replay-coverage">
  <ol class="cells" aria-label={t('replayCoverageTitle')}>
    {#each cells as cell (cell.date)}
      <li style:--fill={cell.share}>
        <Button
          variant="bare"
          class="cell {cell.level}{inPeriod(cell, period) ? ' chosen' : ''}"
          title={t('replayCoverageDay', {
            date: formatDay(cell.from, lang, now),
            n: cell.decisions,
          })}
          aria-label={t('replayCoverageDay', {
            date: formatDay(cell.from, lang, now),
            n: cell.decisions,
          })}
          aria-pressed={inPeriod(cell, period)}
          disabled={cell.decisions === 0}
          data-testid="replay-day"
          data-level={cell.level}
          onclick={() => onpick(cell)}
        />
      </li>
    {/each}
  </ol>
  <ul class="legend caption muted">
    {#each ['full', 'part', 'none'] as const as level (level)}
      <li>
        <span class="swatch {level}" aria-hidden="true"></span>{t(`replayCoverageLegend_${level}`)}
      </li>
    {/each}
    <li>
      <span class="swatch period" aria-hidden="true"></span>{t('replayCoverageLegend_period')}
    </li>
  </ul>
  <p class="caption muted note">
    {stored ? `${kept} ${t('replayCoverageHint')}` : t('replayCoverageNone')}
  </p>
</div>

<style>
  .coverage {
    display: grid;
    gap: var(--space-2);
    min-width: 0;
  }
  .cells {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(0.9rem, 1fr));
    gap: var(--space-1);
    margin: 0;
    padding: 0;
    list-style: none;
  }
  .cells :global(.cell) {
    display: block;
    width: 100%;
    height: 1.6rem;
    padding: 0;
    border: 2px solid transparent;
    border-radius: var(--radius-s);
    background: var(--surface-2);
    cursor: pointer;
  }
  .cells :global(.cell.full),
  .cells :global(.cell.part) {
    background: color-mix(in srgb, var(--accent) calc(30% + var(--fill) * 70%), var(--surface-2));
  }
  .cells :global(.cell:disabled) {
    cursor: default;
  }
  .cells :global(.cell.chosen) {
    border-color: var(--text);
  }
  .cells :global(.cell:focus-visible) {
    outline: 2px solid var(--accent);
    outline-offset: 2px;
  }
  .legend {
    display: flex;
    flex-wrap: wrap;
    gap: var(--space-1) var(--space-3);
    margin: 0;
    padding: 0;
    list-style: none;
  }
  .legend li {
    display: inline-flex;
    align-items: center;
    gap: var(--space-1);
  }
  .swatch {
    width: 0.9rem;
    height: 0.9rem;
    border-radius: var(--radius-2xs);
    background: var(--surface-2);
    border: 2px solid transparent;
  }
  .swatch.full {
    background: var(--accent);
  }
  .swatch.part {
    background: color-mix(in srgb, var(--accent) 50%, var(--surface-2));
  }
  .swatch.period {
    border-color: var(--text);
    background: transparent;
  }
  .note {
    margin: 0;
  }
</style>
