<!--
  SignatureChart: the energy signature. One dot per day: the mean heat the house needed against
  that day's mean outside temperature, the fitted line (heat loss × (balance − outside), zero above
  the balance temperature) and the balance point. Days with a wood-stove fire are not in it.

  Props: house (HouseInsight).
  A11y: role="img" with a text summary; "Show as table" lists the days.
-->
<script lang="ts">
  import Button from '$ui/Button.svelte';
  import { linearScale, niceTicks } from '$lib/core/chart';
  import { chartText, formatNum, formatValue } from '$lib/core/chartSummary';
  import { formatDay } from '$lib/core/format';
  import { signatureHeat, type HouseInsight } from '$lib/house/house';
  import { settings, t } from '$lib/core/settings.svelte';
  import Card from '$ui/Card.svelte';
  import { SERIES } from '$components/charts/palette';

  let { house }: { house: HouseInsight } = $props();

  const lang = $derived(settings.language);
  let measured = $state(0);
  let showTable = $state(false);
  const width = $derived(measured > 0 ? measured : 600);
  const height = $derived(width < 480 ? 210 : 250);
  const pad = { left: 40, right: 12, top: 26, bottom: 36 };

  const points = $derived(house.signature?.points ?? []);
  const fit = $derived(house.signature?.fit ?? null);
  const balance = $derived(fit?.balance_c ?? house.balance_temperature_c?.value ?? null);
  const xs = $derived(points.map((p) => p.outside_c));
  const kws = $derived(points.map((p) => p.heat_w / 1000));
  const xMin = $derived(Math.floor(Math.min(...xs, 0) - 1));
  const xMax = $derived(Math.ceil(Math.max(...xs, balance ?? 15) + 1));
  const yMax = $derived(Math.max(1, Math.ceil(Math.max(...kws, 0) + 0.5)));
  const sx = $derived(linearScale(xMin, xMax, pad.left, width - pad.right));
  const sy = $derived(linearScale(0, yMax, height - pad.bottom, pad.top));
  const xTicks = $derived(niceTicks(xMin, xMax, width < 480 ? 5 : 8));
  const yTicks = $derived(niceTicks(0, yMax, 4));
  const line = $derived.by(() => {
    if (!fit || balance === null) return null;
    const left = signatureHeat(fit, xMin) ?? 0;
    const end = Math.min(balance, xMax);
    return [
      [sx(xMin), sy(Math.min(left / 1000, yMax))],
      [sx(end), sy(0)],
      [sx(xMax), sy(0)],
    ]
      .map(([x, y]) => `${x},${y}`)
      .join(' ');
  });
  const summary = $derived(
    points.length === 0
      ? t('houseSignatureNone')
      : t('houseSignatureSummary', {
          n: points.length,
          min: formatValue(Math.min(...xs), '°C', 0, lang),
          max: formatValue(Math.max(...xs), '°C', 0, lang),
          low: formatNum(Math.min(...kws), 1, lang),
          high: formatNum(Math.max(...kws), 1, lang),
          slope: formatNum(fit?.h_w_per_k ?? 0, 0, lang),
          balance: formatValue(balance, '°C', 1, lang),
        }),
  );
</script>

<Card
  title={t('houseSignatureTitle')}
  subtitle={t('houseSignatureSubtitle')}
  icon="chart"
  testid="house-signature"
  help="house.signature"
  span={7}
>
  <div class="plot" bind:clientWidth={measured}>
    {#if points.length > 0}
      <svg
        {width}
        {height}
        viewBox="0 0 {width} {height}"
        role="img"
        aria-label={summary}
        data-testid="signature-plot"
        data-dots={points.length}
      >
        {#each yTicks as tick (tick)}
          <line class="grid" x1={pad.left} x2={width - pad.right} y1={sy(tick)} y2={sy(tick)} />
          <text class="tick" x={pad.left - 6} y={sy(tick) + 4} text-anchor="end"
            >{formatNum(tick, 1, lang)}</text
          >
        {/each}
        {#each xTicks as tick (tick)}
          <text class="tick" x={sx(tick)} y={height - pad.bottom + 16} text-anchor="middle"
            >{formatNum(tick, 0, lang)}</text
          >
        {/each}
        <text
          class="axis"
          x={(pad.left + width - pad.right) / 2}
          y={height - 4}
          text-anchor="middle">{t('houseAxisOutside')}</text
        >
        <text class="axis" x="4" y="12">{t('houseAxisHeat')}</text>
        {#if line}
          <polyline class="fit" points={line} />
        {/if}
        {#each points as point (point.date)}
          <circle
            class="dot"
            cx={sx(point.outside_c)}
            cy={sy(point.heat_w / 1000)}
            r="4"
            style:fill={SERIES.heat}
          >
            <title
              >{formatDay(point.date, lang)} · {formatValue(point.outside_c, '°C', 1, lang)} · {formatValue(
                point.heat_w / 1000,
                'kW',
                2,
                lang,
              )}</title
            >
          </circle>
        {/each}
        {#if balance !== null && balance <= xMax}
          <circle class="balance" cx={sx(balance)} cy={sy(0)} r="5" />
        {/if}
      </svg>
      <p class="caption legend">
        <span class="key dot-key" style:background={SERIES.heat}></span>{t('houseLegendDays')}
        <span class="key line-key"></span>{t('houseLegendFit')}
        {#if balance !== null}<span class="key ring-key"></span>{t('houseBalanceMarker', {
            value: formatNum(balance, 1, lang),
          })}{/if}
      </p>
      <Button
        variant="link"
        class="sig-link"
        aria-expanded={showTable}
        onclick={() => (showTable = !showTable)}
        data-testid="signature-table-toggle"
        >{chartText(lang, showTable ? 'hideTable' : 'showTable')}</Button
      >
      {#if showTable}
        <div class="table-wrap">
          <table data-testid="signature-table">
            <thead>
              <tr>
                <th scope="col">{t('houseColDay')}</th>
                <th scope="col">{t('houseColOutside')}</th>
                <th scope="col">{t('houseColHeat')}</th>
                <th scope="col">{t('houseColFit')}</th>
              </tr>
            </thead>
            <tbody>
              {#each points as point (point.date)}
                <tr>
                  <td>{formatDay(point.date, lang)}</td>
                  <td class="num">{formatValue(point.outside_c, '°C', 1, lang)}</td>
                  <td class="num">{formatValue(point.heat_w / 1000, 'kW', 2, lang)}</td>
                  <td class="num"
                    >{formatValue(
                      (signatureHeat(fit, point.outside_c) ?? NaN) / 1000,
                      'kW',
                      2,
                      lang,
                    )}</td
                  >
                </tr>
              {/each}
            </tbody>
          </table>
        </div>
      {/if}
    {:else}
      <p class="muted" data-testid="signature-none">{t('houseSignatureNone')}</p>
    {/if}
  </div>
</Card>

<style>
  .plot {
    min-width: 0;
    display: grid;
    gap: var(--space-2);
  }
  svg {
    display: block;
    max-width: 100%;
  }
  .grid {
    stroke: var(--chart-grid, var(--border));
    stroke-width: 1;
  }
  .tick,
  .axis {
    fill: var(--chart-axis, var(--muted));
    font-size: var(--fs-caption);
    font-variant-numeric: tabular-nums;
  }
  .fit {
    fill: none;
    stroke: var(--text);
    stroke-width: 1.5;
    stroke-dasharray: 5 4;
  }
  .dot {
    fill-opacity: 0.6;
    stroke: var(--surface);
    stroke-width: 0.75;
  }
  .balance {
    fill: var(--surface);
    stroke: var(--text);
    stroke-width: 2;
  }
  .legend {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 0.35rem;
    margin: 0;
  }
  .key {
    display: inline-block;
    margin-left: var(--space-2);
  }
  .key:first-child {
    margin-left: 0;
  }
  .dot-key {
    width: 0.6rem;
    height: 0.6rem;
    border-radius: 50%;
  }
  .ring-key {
    width: 0.6rem;
    height: 0.6rem;
    border-radius: 50%;
    border: 2px solid var(--text);
  }
  .line-key {
    width: 1.2rem;
    border-top: 2px dashed var(--text);
  }
  :global(.sig-link) {
    justify-self: start;
    min-height: var(--control-h);
    padding: 0.2rem 0;
  }
  .table-wrap {
    max-height: 20rem;
    overflow: auto;
  }
</style>
