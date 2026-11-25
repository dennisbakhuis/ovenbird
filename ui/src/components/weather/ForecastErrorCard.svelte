<!--
  Forecast error by lead time as two small bar groups: bias (signed average error) and MAE (typical
  size of the error). Props: error (the `error` block of the weather response), span, help (data-help anchor).
  A11y: each Bars group carries its own summary; a visually hidden list repeats bias, MAE and
  sample count per lead time.
-->
<script lang="ts">
  import { formatNumber } from '$lib/core/format';
  import { minus } from '$lib/core/minus';
  import { settings, t } from '$lib/core/settings.svelte';
  import Bars from '$components/charts/Bars.svelte';
  import { SERIES } from '$components/charts/palette';
  import Card from '$ui/Card.svelte';
  import Why from '$ui/Why.svelte';
  import type { BarItem } from '$components/charts/types';

  let {
    error,
    span = 6,
    help,
  }: {
    span?: 5 | 6 | 12;
    help?: string;
    error: { lead_h: number[]; bias_k: (number | null)[]; mae_k: (number | null)[]; n: number[] };
  } = $props();

  const locale = $derived(settings.language);
  const signed = (v: number | null | undefined) =>
    v === undefined || v === null ? '–' : (v > 0 ? '+' : '') + minus(formatNumber(v, 1, locale));
  const labels = $derived(error.lead_h.map((h) => t('errorLeadValue', { h })));
  const maeItems = $derived<BarItem[]>(
    error.lead_h.map((_, i) => ({
      label: labels[i] ?? '',
      value: error.mae_k[i] ?? null,
      color: SERIES.outside,
      note: t('errorN') + ': ' + (error.n[i] ?? '–'),
    })),
  );
  const hasData = $derived(
    error.lead_h.length > 0 && error.mae_k.some((v) => v !== null) && error.n.some((n) => n > 0),
  );
</script>

<Card title={t('errorTitle')} icon="chart" {span} testid="forecast-error" {help}>
  {#snippet actions()}
    <Why title={t('errorTitle')}>{t('errorHelp')}</Why>
  {/snippet}
  {#if hasData}
    <Bars
      title={t('errorMaeTitle')}
      items={maeItems}
      orientation="horizontal"
      unit=" K"
      digits={1}
      min={0}
    />
    <ul class="bias" data-testid="forecast-bias">
      {#each error.lead_h as h, i (h)}
        <li>
          <span>{t('errorLeadValue', { h })}</span>
          <span>{t('errorBiasTitle')}: <strong>{signed(error.bias_k[i])} K</strong></span>
          <span class="caption">{t('errorN')}: {error.n[i] ?? '–'}</span>
        </li>
      {/each}
    </ul>
  {:else}
    <p class="muted">{t('errorNone')}</p>
  {/if}
</Card>

<style>
  .bias {
    list-style: none;
    margin: var(--space-2) 0 0;
    padding: 0;
    display: grid;
    gap: var(--space-1);
    font-size: var(--fs-caption);
  }
  .bias li {
    display: grid;
    grid-template-columns: 5rem minmax(0, 1fr) auto;
    gap: 0 var(--space-2);
    min-width: 0;
  }
</style>
