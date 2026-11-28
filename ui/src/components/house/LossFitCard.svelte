<!--
  LossFitCard: how the heat loss was measured, in a closed Details: the points of the fit (used,
  outlier, near balance) with the fitted line, the heat loss in W/K, the balance temperature, the
  days used and the days left out by reason, and the limits of the method.

  Props: data (InsightBasics with an enabled heat loss).
-->
<script lang="ts">
  import Scatter, { type ScatterMark } from '$components/charts/Scatter.svelte';
  import { SERIES, STATUS } from '$components/charts/palette';
  import { formatNum } from '$lib/core/chartSummary';
  import { settings, t } from '$lib/core/settings.svelte';
  import {
    celsius,
    fitLine,
    fitPoints,
    kw,
    shortDate,
    type InsightBasics,
  } from '$lib/house/basics';
  import Card from '$ui/Card.svelte';
  import Details from '$ui/Details.svelte';

  let { data }: { data: InsightBasics } = $props();

  const lang = $derived(settings.language);
  const fit = $derived(data.heat_loss);
  const marks = $derived<Record<string, ScatterMark>>({
    used: { label: t('houseMarkUsed'), color: SERIES.heat, shape: 'dot' },
    outlier: { label: t('houseMarkOutlier'), color: STATUS.critical, shape: 'cross' },
    near_balance: { label: t('houseMarkNear'), color: SERIES.neutral, shape: 'ring' },
  });
  const points = $derived(
    fit
      ? fitPoints(fit.points, (p) =>
          t('houseFitPoint', {
            first: shortDate(p.first_date, lang),
            last: shortDate(p.last_date, lang),
            kw: kw(p.heat_w, lang),
            dt: formatNum(p.delta_k, 1, lang),
          }),
        )
      : [],
  );
  const line = $derived(
    fit ? fitLine(fit, Math.max(...fit.points.map((p) => p.delta_k), fit.span_k ?? 1)) : null,
  );
  const excluded = $derived(
    fit
      ? (['low_coverage', 'stove', 'no_heating', 'away'] as const).filter(
          (key) => fit.excluded[key] > 0,
        )
      : [],
  );
  const meta = $derived(fit?.h_w_per_k == null ? '' : `${formatNum(fit.h_w_per_k, 0, lang)} W/K`);
</script>

{#if fit}
  <Card testid="house-loss-fit-card" span={12}>
    <Details summary={t('houseFitTitle')} {meta} icon="chart" testid="house-loss-fit">
      <p class="intro">{t('houseFitIntro')}</p>
      <Scatter
        title={t('houseFitTitle')}
        {points}
        {marks}
        {line}
        lineLabel={t('houseFitLine')}
        xLabel={t('houseFitX')}
        yLabel={t('houseFitY')}
      />
      <dl class="facts">
        <div data-testid="house-fit-h">
          <dt>{t('houseFitH')}</dt>
          <dd>
            {formatNum(fit.h_w_per_k ?? 0, 0, lang)} W/K
            <span class="muted"
              >({formatNum(fit.h_low_w_per_k ?? 0, 0, lang)} – {formatNum(
                fit.h_high_w_per_k ?? 0,
                0,
                lang,
              )})</span
            >
          </dd>
        </div>
        <div data-testid="house-fit-balance" title={t('houseFitBalanceHint')}>
          <dt>{t('houseFitBalance')}</dt>
          <dd>{celsius(fit.balance_c, lang)}</dd>
        </div>
        <div data-testid="house-fit-days">
          <dt>{t('houseFitDays')}</dt>
          <dd>{fit.days_used}</dd>
        </div>
        <div data-testid="house-fit-excluded">
          <dt>{t('houseFitExcluded')}</dt>
          <dd>
            {#if excluded.length === 0}
              {t('houseExcludedNone')}
            {:else}
              {excluded
                .map((key) => t(`houseExcluded_${key}`, { n: fit.excluded[key] }))
                .join('; ')}
            {/if}
          </dd>
        </div>
      </dl>
      <p class="limits muted" data-testid="house-fit-limits">{t('houseFitLimits')}</p>
    </Details>
  </Card>
{/if}

<style>
  .intro {
    margin: 0 0 var(--space-2);
  }
  .facts {
    margin: var(--space-3) 0;
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(11rem, 1fr));
    gap: var(--space-2) var(--space-4);
  }
  .facts div {
    min-width: 0;
  }
  dt {
    color: var(--muted);
    font-size: var(--fs-md);
  }
  dd {
    margin: 0;
    font-weight: var(--fw-semibold);
    font-variant-numeric: tabular-nums;
  }
  dd .muted {
    font-weight: var(--fw-regular);
  }
  .limits {
    margin: 0;
  }
</style>
