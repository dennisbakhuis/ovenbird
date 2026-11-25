<!--
  FactsCard: what the model learned besides the heat loss: time constant, balance temperature,
  solar aperture and internal gains, each with its 90 % range and one plain sentence.

  Props: house (HouseInsight).
-->
<script lang="ts">
  import { formatNumber } from '$lib/core/format';
  import type { Estimate, HouseInsight } from '$lib/house/house';
  import type { MessageKey } from '$lib/i18n';
  import { settings, t } from '$lib/core/settings.svelte';
  import Card from '$ui/Card.svelte';

  let { house }: { house: HouseInsight } = $props();

  const lang = $derived(settings.language);
  const num = (value: number, digits = 1) => formatNumber(value, digits, lang).replace('-', '−');
  const comfort = $derived(house.proposal?.comfort_c ?? 21);

  interface Row {
    id: string;
    label: MessageKey;
    estimate: Estimate;
    unit: string;
    digits: number;
    text: string;
  }

  const rows = $derived.by(() => {
    const out: Row[] = [];
    const tau = house.time_constant_h;
    if (tau)
      out.push({
        id: 'tau',
        label: 'houseTau',
        estimate: tau,
        unit: 'h',
        digits: 0,
        text: t('houseTauText', {
          hours: num(tau.value / Math.max(comfort, 1), 1),
          days: num(tau.value / 24, 1),
        }),
      });
    const balance = house.balance_temperature_c;
    if (balance)
      out.push({
        id: 'balance',
        label: 'houseBalance',
        estimate: balance,
        unit: '°C',
        digits: 1,
        text: t('houseBalanceText', { value: num(balance.value, 1) }),
      });
    const solar = house.solar_aperture_m2;
    if (solar)
      out.push({
        id: 'solar',
        label: 'houseSolar',
        estimate: solar,
        unit: 'm²',
        digits: 1,
        text: t('houseSolarText', { kw: num((solar.value * 500) / 1000, 1) }),
      });
    const gains = house.internal_gains_w;
    if (gains)
      out.push({
        id: 'gains',
        label: 'houseGains',
        estimate: gains,
        unit: 'W',
        digits: 0,
        text: t('houseGainsText', { value: num(gains.value, 0) }),
      });
    return out;
  });
</script>

<Card
  title={t('houseFactsTitle')}
  icon="thermometer"
  testid="house-facts"
  help="house.facts"
  span={6}
>
  <dl class="rows">
    {#each rows as row (row.id)}
      <div class="row" data-testid="house-fact-{row.id}">
        <dt>{t(row.label)}</dt>
        <dd class="reading">
          <span class="value"
            >{num(row.estimate.value, row.digits)}<span class="unit">&#8239;{row.unit}</span></span
          >
          {#if row.estimate.interval_90}
            <span class="caption"
              >{t('houseRange', {
                lo: num(row.estimate.interval_90[0], row.digits),
                hi: num(row.estimate.interval_90[1], row.digits),
              })}</span
            >
          {/if}
        </dd>
        <dd class="text">{row.text}</dd>
      </div>
    {/each}
  </dl>
</Card>

<style>
  .rows {
    display: grid;
    gap: var(--space-3);
    margin: 0;
  }
  .row {
    display: grid;
    grid-template-columns: minmax(7rem, 9rem) minmax(0, 1fr);
    grid-template-areas:
      'label reading'
      'label text';
    gap: 0.1rem var(--space-3);
  }
  dt {
    grid-area: label;
    font-weight: var(--fw-semibold);
  }
  dd {
    margin: 0;
  }
  .reading {
    grid-area: reading;
    display: flex;
    flex-wrap: wrap;
    align-items: baseline;
    gap: 0 var(--space-2);
  }
  .value {
    font-weight: var(--fw-bold);
    font-variant-numeric: tabular-nums;
  }
  .text {
    grid-area: text;
    color: var(--muted);
    font-size: var(--fs-body);
  }
  @container main (max-width: 30rem) {
    .row {
      grid-template-columns: auto minmax(0, 1fr);
      grid-template-areas:
        'label reading'
        'text text';
    }
  }
</style>
