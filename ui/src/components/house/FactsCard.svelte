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
  import { toldRows, type ToldRow } from '$lib/house/told';
  import Card from '$ui/Card.svelte';
  import Details from '$ui/Details.svelte';

  let { house }: { house: HouseInsight } = $props();

  const lang = $derived(settings.language);
  const num = (value: number, digits = 1) => formatNumber(value, digits, lang).replace('-', '−');
  const comfort = $derived(house.proposal?.comfort_c ?? 21);

  const told = $derived(toldRows(house));
  const withUnit = (value: number, row: ToldRow) => `${num(value, row.digits)}\u202f${row.unit}`;
  const toldText = (row: ToldRow) =>
    row.interval
      ? t('houseToldRow', {
          told: withUnit(row.told, row),
          measured: withUnit(row.measured, row),
          lo: num(row.interval[0], row.digits),
          hi: num(row.interval[1], row.digits),
        })
      : t('houseToldRowPlain', {
          told: withUnit(row.told, row),
          measured: withUnit(row.measured, row),
        });

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
  {#if told.length > 0}
    <div class="told">
      <Details
        summary={t('houseToldTitle')}
        id="house-told-details"
        testid="house-told"
        open={told.some((row) => row.differs)}
      >
        <ul>
          {#each told as row (row.id)}
            <li data-testid="house-told-{row.id}" data-differs={row.differs}>
              <strong>{t(`houseTold_${row.id}` as 'houseTold_ua')}</strong>
              <span>{toldText(row)}</span>
            </li>
          {/each}
        </ul>
        {#if told.some((row) => row.differs)}
          <p class="differs" data-testid="house-told-differs">{t('houseToldDiffers')}</p>
        {/if}
      </Details>
    </div>
  {/if}
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
  .told {
    margin-top: var(--space-4);
    padding-top: var(--space-3);
    border-top: 1px solid var(--border);
  }
  .told ul {
    list-style: none;
    margin: 0;
    padding: 0;
    display: grid;
    gap: var(--space-2);
  }
  .told li {
    display: grid;
    gap: var(--space-1);
  }
  .told span {
    color: var(--muted);
  }
  .differs {
    margin: var(--space-2) 0 0;
    padding: var(--space-2) var(--space-3);
    border-radius: var(--radius-control);
    background: var(--status-limited-bg);
    color: var(--status-limited);
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
