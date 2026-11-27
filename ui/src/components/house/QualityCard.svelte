<!--
  QualityCard: how far to trust the model. The heat loss of every promoted model with its 90 %
  range (a small chart from two models on, a list before), the room error of the new model
  against the previous one on the latest 14 days and whether it was promoted, the last run, the
  data span, the low-confidence flag, and in a Details block the limits of the model.

  Props: house (HouseInsight), history (HouseHistory | null).
  A11y: the trend chart is role="img" with a sentence and each model is also in the list below.
-->
<script lang="ts">
  import { formatDateTime, formatNumber, timeLocale } from '$lib/core/format';
  import type { HouseHistory, HouseHistoryModel, HouseInsight } from '$lib/house/house';
  import { settings, t } from '$lib/core/settings.svelte';
  import EvolutionChart from './EvolutionChart.svelte';
  import GateDetails from './GateDetails.svelte';
  import Card from '$ui/Card.svelte';
  import Details from '$ui/Details.svelte';
  import Icon from '$ui/Icon.svelte';

  let { house, history }: { house: HouseInsight; history: HouseHistory | null } = $props();

  const lang = $derived(settings.language);
  const num = (value: number, digits = 1) => formatNumber(value, digits, lang);
  const date = (iso: string | null) =>
    new Date(iso ?? 0).toLocaleDateString(timeLocale(lang), { day: 'numeric', month: 'short' });

  const models = $derived(
    (history?.models ?? []).filter(
      (model): model is HouseHistoryModel & { ua_w_per_k: number } =>
        typeof model.ua_w_per_k === 'number',
    ),
  );
  const validation = $derived(house.validation);
  const rmseText = $derived.by(() => {
    if (!validation || validation.challenger_room_rmse_k === null) return null;
    const challenger = num(validation.challenger_room_rmse_k, 2);
    return validation.champion_room_rmse_k === null
      ? t('houseRmseFirst', { challenger })
      : t('houseRmseBoth', {
          challenger,
          champion: num(validation.champion_room_rmse_k, 2),
        });
  });
  const settingsChangedText = $derived(
    validation?.challenger_room_rmse_k != null && validation.champion_room_rmse_k != null
      ? t('houseSettingsChanged', {
          challenger: num(validation.challenger_room_rmse_k, 2),
          champion: num(validation.champion_room_rmse_k, 2),
        })
      : t('houseSettingsChangedPlain'),
  );
  const run = $derived(house.last_run);
  const capacities = $derived(house.capacities_kwh_per_k ?? null);
  const responseText = $derived.by(() => {
    const building = house.time_constant_h;
    if (!building) return null;
    const emitter = house.emitter_time_constant_h;
    return emitter
      ? t('houseResponseText', { floor: num(emitter.value, 1), house: num(building.value, 0) })
      : t('houseResponseHouseOnly', { house: num(building.value, 0) });
  });
  const structure = $derived(house.structure ?? null);
  const ua = $derived(house.ua);
  const folds = $derived(ua.fold_w_per_k ?? []);
  const rangeSplit = $derived(
    ua.interval_90 && ua.bootstrap_interval_90 && folds.length > 0
      ? {
          lo: num(ua.interval_90[0], 0),
          hi: num(ua.interval_90[1], 0),
          blo: num(ua.bootstrap_interval_90[0], 0),
          bhi: num(ua.bootstrap_interval_90[1], 0),
          flo: num(Math.min(...folds), 0),
          fhi: num(Math.max(...folds), 0),
        }
      : null,
  );
</script>

<Card title={t('houseQualityTitle')} icon="check" testid="house-quality" help="house.quality">
  <div class="body">
    <div class="trend">
      <h3>{t('houseTrendTitle')}</h3>
      {#if models.length >= 2}
        <EvolutionChart {models} />
      {/if}
      {#snippet list()}
        <ul class="models" data-testid="house-models">
          {#each models as model (model.model)}
            <li>
              <span>{date(model.data_to)}</span>
              <strong>{num(model.ua_w_per_k, 0)}&#8239;W/K</strong>
              {#if model.ua_interval_90}<span class="caption"
                  >{t('houseRange', {
                    lo: num(model.ua_interval_90[0], 0),
                    hi: num(model.ua_interval_90[1], 0),
                  })}</span
                >{/if}
              {#if model.champion}<span class="champion-tag">{t('houseChampion')}</span>{/if}
            </li>
          {/each}
        </ul>
      {/snippet}
      {#if models.length >= 2}
        <Details
          summary={t('houseTrendList', { n: models.length })}
          id="house-runs"
          testid="house-runs"
        >
          {@render list()}
        </Details>
      {:else if models.length > 0}
        {@render list()}
      {:else}
        <p class="muted">{t('houseTrendNone')}</p>
      {/if}
    </div>

    <dl class="facts">
      {#if rmseText}
        <div>
          <dt>{t('houseRmseLabel')}</dt>
          <dd data-testid="house-rmse">{rmseText}</dd>
        </div>
      {/if}
      {#if house.heat_capacity_kwh_per_k != null}
        <div>
          <dt>{t('houseCapacityLabel')}</dt>
          <dd data-testid="house-capacity">
            {t('houseCapacityText', { value: num(house.heat_capacity_kwh_per_k, 1) })}
            {#if capacities}<span class="caption" data-testid="house-capacity-parts"
                >{t('houseCapacityParts', {
                  loop: num(capacities.loop, 2),
                  emitter: num(capacities.emitter, 2),
                  building: num(capacities.building, 2),
                })}</span
              >{/if}
          </dd>
        </div>
      {/if}
      {#if responseText}
        <div>
          <dt>{t('houseResponseLabel')}</dt>
          <dd data-testid="house-response">{responseText}</dd>
        </div>
      {/if}
      {#if validation}
        <div>
          <dt>{t('houseValidationLabel')}</dt>
          <dd>
            {#if validation.settings_changed}
              <span data-testid="house-settings-changed">{settingsChangedText}</span>
            {:else}
              {validation.promoted ? t('housePromoted') : t('houseKept')}
            {/if}
          </dd>
        </div>
      {/if}
    </dl>
    {#if house.learner?.stale}
      <p class="warn" data-testid="house-learner-stale">
        <Icon name="warning" size={16} />{t('houseLearnerStale', {
          days: num((house.learner.age_h ?? 0) / 24, 0),
        })}
      </p>
    {/if}
    {#if house.ua.low_confidence}
      <p class="warn" data-testid="house-low-confidence">
        <Icon name="warning" size={16} />{t('houseLowConfidence')}
      </p>
    {/if}
  </div>
  <Details summary={t('houseAboutModel')} id="house-limits" icon="info" testid="house-limits">
    <dl class="facts about">
      {#if run}
        <div>
          <dt>{t('houseLastRunLabel')}</dt>
          <dd>{formatDateTime(run.at, lang)}</dd>
        </div>
      {/if}
      {#if rangeSplit}
        <div>
          <dt>{t('houseUaRangeLabel')}</dt>
          <dd data-testid="house-ua-range">{t('houseUaRangeText', rangeSplit)}</dd>
        </div>
      {/if}
      {#if structure && structure.name === 'chain'}
        <div>
          <dt>{t('houseStructureLabel')}</dt>
          <dd data-testid="house-structure">
            {t('houseStructureText', {
              free: structure.free.length,
              fixed: Object.keys(structure.fixed).length,
            })}
          </dd>
        </div>
      {/if}
      <div>
        <dt>{t('houseDataLabel')}</dt>
        <dd>
          {t('houseDataSpan', {
            from: date(house.data.from),
            to: date(house.data.to),
            days: num(house.data.fit_days, 0),
          })}
          {#if house.data.excluded_days.length > 0}
            <span class="caption">{t('houseExcluded', { n: house.data.excluded_days.length })}</span
            >
          {/if}
        </dd>
      </div>
    </dl>
    <GateDetails {house} />
    {#if house.limits.length > 0}
      <h3 class="limits-title">{t('houseLimitsTitle')}</h3>
      <ul class="limits">
        {#each house.limits as limit (limit)}
          <li>{limit}</li>
        {/each}
      </ul>
      <p class="caption">{t('houseLimitsNote', { model: house.model })}</p>
    {/if}
  </Details>
</Card>

<style>
  .body {
    display: grid;
    gap: var(--space-4);
    grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
    align-items: start;
  }
  @container main (max-width: 48rem) {
    .body {
      grid-template-columns: minmax(0, 1fr);
    }
  }
  h3 {
    margin: 0 0 var(--space-2);
    font-size: var(--fs-body);
  }
  .models {
    list-style: none;
    margin: var(--space-2) 0 0;
    padding: 0;
    display: grid;
    gap: 0.2rem;
    font-size: var(--fs-body);
  }
  .models li {
    display: flex;
    flex-wrap: wrap;
    align-items: baseline;
    gap: 0 var(--space-2);
  }
  .champion-tag {
    font-size: var(--fs-caption);
    font-weight: var(--fw-semibold);
    color: var(--accent);
  }
  .facts {
    grid-template-columns: minmax(0, 1fr);
    gap: var(--space-2);
  }
  .facts dd {
    font-weight: var(--fw-regular);
  }
  .facts .caption {
    display: block;
  }
  .warn {
    grid-column: 1 / -1;
    display: flex;
    gap: var(--space-2);
    margin: 0;
    padding: var(--space-2) var(--space-3);
    border-radius: var(--radius-control);
    background: var(--status-limited-bg);
    color: var(--status-limited);
  }
  .about {
    margin-bottom: var(--space-3);
  }
  .limits-title {
    margin: 0 0 var(--space-1);
  }
  .limits {
    margin: 0;
    padding-left: 1.2rem;
    display: grid;
    gap: var(--space-1);
  }
</style>
