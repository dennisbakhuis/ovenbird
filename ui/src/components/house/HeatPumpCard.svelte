<!--
  HeatPumpCard: the heat the heat pump delivers now and over 24 h, and a water-temperature slider
  that shows the expected steady heat into the house next to the heat loss now, with surplus or
  shortfall in words and the water temperature that balances the house.

  Props: data (InsightBasics with an enabled heat loss and a heat-pump part), span (7).
-->
<script lang="ts">
  import Bars from '$components/charts/Bars.svelte';
  import { SERIES } from '$components/charts/palette';
  import { formatNum } from '$lib/core/chartSummary';
  import { settings, t, tc } from '$lib/core/settings.svelte';
  import {
    celsius,
    kw,
    nearestRow,
    verdict,
    type EmitterRow,
    type InsightBasics,
  } from '$lib/house/basics';
  import Card from '$ui/Card.svelte';
  import Icon from '$ui/Icon.svelte';
  import Pill from '$ui/Pill.svelte';
  import Slider from '$ui/Slider.svelte';

  let { data, span = 7 }: { data: InsightBasics; span?: 7 | 12 } = $props();

  const lang = $derived(settings.language);
  const pump = $derived(data.heat_pump);
  const delivered = $derived(pump?.delivered ?? null);
  const emitter = $derived(pump?.emitter ?? null);
  const table = $derived(emitter?.table ?? []);

  let picked = $state<number | null>(null);
  const index = $derived(
    Math.min(picked ?? nearestRow(table, emitter?.balance_supply_c ?? null), table.length - 1),
  );
  const row = $derived<EmitterRow | null>(table[index] ?? null);
  const outcome = $derived(row ? verdict(row) : null);
  const lossNowW = $derived(row?.loss_now_w ?? null);

  const ceiling = $derived(
    Math.max(...table.flatMap((r) => [r.high_w, r.loss_now_w ?? 0]), 1000) / 1000,
  );
  const compare = $derived(
    row
      ? [
          {
            label: t('houseHeatIntoHouse'),
            value: row.heat_w / 1000,
            color: SERIES.heat,
            note: t('houseHeatBand', { low: kw(row.low_w, lang), high: kw(row.high_w, lang) }),
          },
          ...(lossNowW === null
            ? []
            : [{ label: t('houseHeatLossNow'), value: lossNowW / 1000, color: SERIES.neutral }]),
        ]
      : [],
  );

  const nowText = $derived(
    delivered === null
      ? '–'
      : delivered.now_w !== null
        ? `${kw(delivered.now_w, lang)} kW`
        : delivered.now_reason === 'hot_water'
          ? t('houseHeatHotWater')
          : t('houseHeatUnknown'),
  );
  const coverage = $derived(delivered ? Math.round(delivered.coverage_24h * 100) : 100);

  const range = $derived(
    emitter
      ? {
          min: celsius(emitter.setpoint_min_c, lang),
          max: celsius(emitter.setpoint_max_c, lang),
        }
      : null,
  );
</script>

<Card title={t('houseHeatTitle')} icon="pump" testid="house-heat-pump" help="house.basics" {span}>
  {#snippet actions()}
    {#if emitter?.status === 'provisional'}
      <Pill tone="warn" testid="house-heat-provisional">{t('houseStatusProvisional')}</Pill>
    {/if}
  {/snippet}
  <dl class="delivered">
    <div data-testid="house-delivered-now">
      <dt>{t('houseHeatNow')}</dt>
      <dd>{nowText}</dd>
    </div>
    <div data-testid="house-delivered-mean">
      <dt>{t('houseHeatMean24')}</dt>
      <dd>{delivered?.mean_24h_w == null ? '–' : `${kw(delivered.mean_24h_w, lang)} kW`}</dd>
    </div>
  </dl>
  {#if coverage < 90}
    <p class="caption muted">{t('houseHeatCoverage', { p: coverage })}</p>
  {/if}

  {#if emitter && row && range}
    <div class="slider" data-testid="house-emitter">
      <p class="label" id="house-supply-label">{t('houseSliderLabel')}</p>
      <p class="value" data-testid="house-supply-value" aria-live="polite">
        {t('houseSliderValue', {
          supply: celsius(row.supply_c, lang),
          mean: celsius(row.mean_water_c, lang),
        })}
      </p>
      <Slider
        id="house-supply-slider"
        label={t('houseSliderLabel')}
        value={index}
        max={table.length - 1}
        valuetext={celsius(row.supply_c, lang)}
        onchange={(next) => (picked = next)}
        testid="house-supply-slider"
      />
      <p class="ends caption muted" aria-hidden="true">
        <span>{range.min}</span><span>{range.max}</span>
      </p>
      <Bars
        title={t('houseHeatIntoHouse')}
        items={compare}
        unit="kW"
        digits={1}
        orientation="horizontal"
        min={0}
        max={ceiling}
      />
      {#if outcome}
        <p class="verdict {outcome}" data-testid="house-verdict" data-verdict={outcome}>
          <Icon name={outcome === 'shortfall' ? 'warning' : 'check'} size={18} />
          <span>
            {outcome === 'balanced'
              ? t('houseBalancedNow')
              : t(outcome === 'surplus' ? 'houseSurplus' : 'houseShortfall', {
                  kw: kw(Math.abs(row.margin_w ?? 0), lang),
                })}
          </span>
        </p>
      {:else}
        <p class="muted" data-testid="house-verdict">{t('houseNoLossToCompare')}</p>
      {/if}
      <p class="balance" data-testid="house-balance">
        {#if emitter.balance_supply_c === null}
          {t('houseBalanceNone')}
        {:else if emitter.balance_in_range === false}
          {t('houseBalanceOutOfRange', {
            supply: celsius(emitter.balance_supply_c, lang),
            min: formatNum(emitter.setpoint_min_c, 0, lang),
            max: celsius(emitter.setpoint_max_c, lang),
          })}
        {:else}
          {t('houseBalanceAt', {
            supply: celsius(emitter.balance_supply_c, lang),
            mean: celsius(emitter.balance_mean_water_c, lang),
          })}
        {/if}
      </p>
      {#if emitter.status === 'provisional'}
        <ul class="reasons">
          {#each emitter.reasons as reason (reason)}<li>
              {tc('houseEmitterReason_', reason)}
            </li>{/each}
        </ul>
      {/if}
      <p class="caption muted" data-testid="house-steady-note">{t('houseSteadyNote')}</p>
    </div>
  {:else if emitter}
    <div data-testid="house-emitter-collecting">
      <p class="muted">{t('houseEmitterCollecting')}</p>
      <ul class="reasons">
        {#each emitter.reasons as reason (reason)}<li>
            {tc('houseEmitterReason_', reason)}
          </li>{/each}
      </ul>
    </div>
  {/if}
</Card>

<style>
  .delivered {
    margin: 0 0 var(--space-3);
    display: flex;
    flex-wrap: wrap;
    gap: var(--space-2) var(--space-6);
  }
  .delivered div {
    display: grid;
  }
  dt {
    color: var(--muted);
    font-size: var(--fs-md);
  }
  dd {
    margin: 0;
    font-size: var(--fs-value);
    font-weight: var(--fw-semibold);
    font-variant-numeric: tabular-nums;
  }
  .caption {
    margin: 0 0 var(--space-2);
  }
  .slider {
    border-top: 1px solid var(--border);
    padding-top: var(--space-3);
    display: grid;
    gap: var(--space-1);
  }
  .label {
    margin: 0;
    font-weight: var(--fw-semibold);
  }
  .value {
    margin: 0;
    font-variant-numeric: tabular-nums;
  }
  .ends {
    display: flex;
    justify-content: space-between;
    margin: calc(-1 * var(--space-2)) 0 var(--space-2);
  }
  .verdict {
    display: flex;
    gap: var(--space-2);
    align-items: flex-start;
    margin: var(--space-2) 0 0;
    padding: var(--space-2) var(--space-3);
    border-radius: var(--radius-sm);
    font-weight: var(--fw-semibold);
  }
  .verdict.surplus,
  .verdict.balanced {
    background: var(--status-ok-bg);
    color: var(--status-ok);
  }
  .verdict.shortfall {
    background: var(--status-limited-bg);
    color: var(--status-limited);
  }
  .balance {
    margin: var(--space-2) 0 0;
  }
  .reasons {
    margin: 0;
    padding-left: 1.1rem;
    color: var(--muted);
    font-size: var(--fs-md);
  }
</style>
