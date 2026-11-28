<!--
  LossNowCard: the heat loss of the house at the current weather as one big kW figure with its
  band, the outside and room temperature it rests on, and smaller the coming night and the design
  day. A value beyond the measured temperatures is marked as an extrapolation.

  Props: data (InsightBasics with an enabled heat loss).
-->
<script lang="ts">
  import { formatNum } from '$lib/core/chartSummary';
  import { settings, t, tc } from '$lib/core/settings.svelte';
  import { celsius, kw, type InsightBasics, type LossEstimate } from '$lib/house/basics';
  import Card from '$ui/Card.svelte';
  import Pill from '$ui/Pill.svelte';

  let { data }: { data: InsightBasics } = $props();

  const lang = $derived(settings.language);
  const loss = $derived(data.loss_now);
  const now = $derived(loss?.now ?? null);
  const fit = $derived(data.heat_loss);
  const provisional = $derived(fit?.status === 'provisional');
  const band = (estimate: LossEstimate) =>
    t('houseLossBand', { low: kw(estimate.low_w, lang), high: kw(estimate.high_w, lang) });
</script>

{#snippet beyond(estimate: LossEstimate, testid: string)}
  {#if estimate.beyond_data}
    <Pill tone="info" title={t('houseLossBeyondHint')} {testid}>{t('houseLossBeyond')}</Pill>
  {/if}
{/snippet}

<Card
  title={t('houseLossTitle')}
  icon="home"
  testid="house-loss-now"
  help="house.basics"
  span={5}
  data-status={fit?.status}
>
  {#snippet actions()}
    {#if provisional}
      <Pill tone="warn" testid="house-loss-provisional">{t('houseStatusProvisional')}</Pill>
    {/if}
  {/snippet}
  {#if now}
    <p class="big" data-testid="house-loss-value">
      <strong>{kw(now.loss_w, lang)}</strong><span class="unit">kW</span>
      {@render beyond(now, 'house-loss-beyond')}
    </p>
    <p class="band muted" data-testid="house-loss-band">{band(now)}</p>
    <p class="basis" data-testid="house-loss-basis">
      {t(loss?.room_source === 'measured' ? 'houseLossBasis' : 'houseLossBasisTarget', {
        outside: celsius(now.outside_c, lang),
        room: celsius(now.room_c, lang),
      })}
    </p>
  {:else}
    <p class="muted" data-testid="house-loss-none">{t('houseLossNoNow')}</p>
  {/if}
  <dl class="more">
    <div data-testid="house-loss-night">
      {#if loss?.night}
        <dt>{t('houseLossNight', { outside: celsius(loss.night.outside_c, lang) })}</dt>
        <dd>
          <strong>{kw(loss.night.loss_w, lang)} kW</strong>
          <span class="muted">{band(loss.night)}</span>
          {@render beyond(loss.night, 'house-loss-night-beyond')}
        </dd>
      {:else}
        <dt class="muted">{t('houseLossNightMissing')}</dt>
      {/if}
    </div>
    <div data-testid="house-loss-design">
      {#if loss?.design}
        <dt>
          {t('houseLossDesign', { outside: `${formatNum(loss.design.outside_c, 0, lang)} °C` })}
        </dt>
        <dd>
          <strong>{kw(loss.design.loss_w, lang)} kW</strong>
          <span class="muted">{band(loss.design)}</span>
          {@render beyond(loss.design, 'house-loss-design-beyond')}
        </dd>
      {/if}
    </div>
  </dl>
  {#if provisional && fit}
    <ul class="reasons" data-testid="house-loss-reasons">
      {#each fit.reasons as reason (reason)}<li>{tc('houseLossReason_', reason)}</li>{/each}
    </ul>
  {/if}
</Card>

<style>
  .big {
    margin: 0;
    display: flex;
    align-items: baseline;
    flex-wrap: wrap;
    gap: var(--space-2);
  }
  .big strong {
    font-size: var(--fs-hero);
    line-height: 1.05;
    font-variant-numeric: tabular-nums;
  }
  .unit {
    font-size: var(--fs-title-lg);
    color: var(--muted);
  }
  .band {
    margin: 0;
    font-size: var(--fs-md);
  }
  .basis {
    margin: var(--space-2) 0 var(--space-3);
  }
  .more {
    margin: 0;
    display: grid;
    gap: var(--space-2);
    border-top: 1px solid var(--border);
    padding-top: var(--space-3);
  }
  .more div {
    display: flex;
    flex-wrap: wrap;
    justify-content: space-between;
    gap: var(--space-1) var(--space-3);
  }
  .more div:empty {
    display: none;
  }
  dt {
    margin: 0;
  }
  dd {
    margin: 0;
    display: flex;
    flex-wrap: wrap;
    align-items: baseline;
    gap: var(--space-2);
    font-variant-numeric: tabular-nums;
  }
  dd .muted {
    font-size: var(--fs-md);
  }
  .reasons {
    margin: var(--space-3) 0 0;
    padding-left: 1.1rem;
    color: var(--muted);
    font-size: var(--fs-md);
  }
</style>
