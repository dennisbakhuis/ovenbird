<!--
  ScoreCard: the indicative insulation score. Heat loss in W/K with its 90 % range and the heat
  loss at the design conditions; when the score is ready also W/m² with its range and the band
  A–G on a small scale with the range marked and the W/m² limits of each band under it. While the model is not credible it says what is
  still needed; without a floor area it links to the field. Always says that the band is
  indicative and not the official energielabel.

  Props: house (HouseInsight).
  A11y: the band scale is role="img" with a sentence; letters are printed, colour is not needed.
-->
<script lang="ts">
  import { formatNumber } from '$lib/core/format';
  import {
    bandLimits,
    bandPosition,
    BAND_LETTERS,
    learningNeeds,
    needsText,
    type HouseInsight,
  } from '$lib/house/house';
  import { buildHash } from '$lib/core/router.svelte';
  import { settings, t } from '$lib/core/settings.svelte';
  import Card from '$ui/Card.svelte';
  import Icon from '$ui/Icon.svelte';

  let { house }: { house: HouseInsight } = $props();

  const lang = $derived(settings.language);
  const num = (value: number, digits = 1) => formatNumber(value, digits, lang);
  const score = $derived(house.score);
  const ua = $derived(house.ua);
  const needs = $derived(learningNeeds(house.credibility));
  const heatLossKw = $derived(
    score.heat_loss_w !== undefined
      ? score.heat_loss_w / 1000
      : (ua.w_per_k * (score.design_indoor_c - score.design_outside_c)) / 1000,
  );
  const position = $derived(
    score.w_per_m2 !== undefined ? bandPosition(score.w_per_m2, score.bands) : null,
  );
  const rangeAt = $derived.by((): [number, number] | null => {
    const range = score.interval_90;
    return range
      ? [bandPosition(range[0], score.bands), bandPosition(range[1], score.bands)]
      : null;
  });
  const bandRange = $derived(score.band_interval ?? null);
  const limits = $derived(bandLimits(score.bands, (value) => num(value, 0)));
  const limitsText = $derived(
    BAND_LETTERS.filter((letter) => limits[letter])
      .map((letter) => `${letter} ${limits[letter]}`)
      .join(', '),
  );
  const scaleText = $derived(
    score.band && score.w_per_m2 !== undefined
      ? `${t('houseScaleAria', { band: score.band, value: num(score.w_per_m2) })} ${t('houseLimitsAria', { limits: limitsText })}`
      : '',
  );
</script>

<Card title={t('houseScoreTitle')} icon="home" testid="house-score" help="house.score" span={6}>
  <div class="ua">
    <span class="big">{num(ua.w_per_k, 0)}<span class="unit">&#8239;W/K</span></span>
    <span class="label">{t('houseUaLabel')}</span>
    {#if ua.interval_90}
      <span class="caption"
        >{t('houseRange', { lo: num(ua.interval_90[0], 0), hi: num(ua.interval_90[1], 0) })}</span
      >
    {/if}
  </div>
  <p class="line">
    {t('houseUaSentence', {
      kw: num(heatLossKw),
      inside: num(score.design_indoor_c, 0),
      outside: num(score.design_outside_c, 0).replace('-', '−'),
    })}
  </p>

  {#if score.state === 'ready' && score.w_per_m2 !== undefined && score.band}
    <div class="band-row" data-testid="house-band">
      <span class="letter band-{score.band}" aria-hidden="true">{score.band}</span>
      <span class="band-text">
        <strong
          >{t('houseBandValue', { band: score.band })} · {num(score.w_per_m2)}<span class="unit"
            >&#8239;W/m²</span
          ></strong
        >
        <span class="caption">
          {#if score.interval_90}{t('houseRange', {
              lo: num(score.interval_90[0]),
              hi: num(score.interval_90[1]),
            })}{/if}
          {#if bandRange}
            · {bandRange[0] === bandRange[1]
              ? t('houseBandSure', { band: bandRange[0] })
              : t('houseBandBetween', { lo: bandRange[0], hi: bandRange[1] })}
          {/if}
        </span>
      </span>
    </div>
    <div class="scale" role="img" aria-label={scaleText} data-testid="house-scale">
      {#if rangeAt}
        <span
          class="range"
          style:left="{rangeAt[0] * 100}%"
          style:width="{Math.max(1, (rangeAt[1] - rangeAt[0]) * 100)}%"
        ></span>
      {/if}
      {#each BAND_LETTERS as letter (letter)}
        <span class="cell band-{letter}" class:here={letter === score.band}>{letter}</span>
      {/each}
      {#if position !== null}
        <span class="marker" style:left="{position * 100}%"></span>
      {/if}
    </div>
    <div class="limits caption" aria-hidden="true" data-testid="house-band-limits">
      {#each BAND_LETTERS as letter (letter)}
        <span>{limits[letter] ?? ''}</span>
      {/each}
    </div>
    <p class="caption floor">
      {t('houseFloorArea', { area: num(score.floor_area_m2 ?? 0, 0) })} ·
      <a href={buildHash('settings', ['house'])}>{t('houseChangeArea')}</a>
    </p>
  {:else if score.state === 'no_floor_area'}
    <p class="notice" data-testid="house-no-area">
      <Icon name="info" size={16} />
      <span
        >{t('houseNoArea')}
        <a href={buildHash('settings', ['house'])} data-testid="house-area-link"
          >{t('houseNoAreaLink')}</a
        ></span
      >
    </p>
  {:else}
    <p class="notice" data-testid="house-learning-score">
      <Icon name="clock" size={16} />
      <span>
        <strong>{needsText(needs, house.credibility, t, num)}</strong>
        {#if house.credibility.message}
          <span class="caption service"
            >{t('houseServiceSays', { message: house.credibility.message })}</span
          >
        {/if}
      </span>
    </p>
  {/if}
  <p class="caption indicative" data-testid="house-indicative">{t('houseIndicative')}</p>
</Card>

<style>
  .ua {
    display: flex;
    flex-wrap: wrap;
    align-items: baseline;
    gap: var(--space-1) var(--space-3);
  }
  .big {
    font-size: var(--fs-value);
    font-weight: var(--fw-bold);
    font-variant-numeric: tabular-nums;
  }
  .label {
    font-weight: var(--fw-semibold);
  }
  .line,
  .floor,
  .indicative {
    margin: 0;
  }
  .band-row {
    display: flex;
    align-items: center;
    gap: var(--space-3);
  }
  .band-text {
    display: grid;
    gap: 0.1rem;
    min-width: 0;
  }
  .letter {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 2.75rem;
    height: 2.75rem;
    border-radius: var(--radius);
    font-size: var(--fs-display-1);
    font-weight: var(--fw-extrabold);
    color: var(--on-label);
    flex: none;
  }
  .scale {
    position: relative;
    display: grid;
    grid-template-columns: repeat(7, 1fr);
    gap: 2px;
    padding-top: 6px;
    padding-bottom: 6px;
  }
  .limits {
    display: grid;
    grid-template-columns: repeat(7, 1fr);
    gap: 2px;
    margin-top: -2px;
    color: var(--muted);
    font-variant-numeric: tabular-nums;
    text-align: center;
    white-space: nowrap;
    font-size: var(--fs-2xs);
  }
  .cell {
    text-align: center;
    font-size: var(--fs-caption);
    font-weight: var(--fw-bold);
    color: var(--on-label);
    border-radius: var(--radius-s);
    line-height: 1.5rem;
    opacity: 0.55;
  }
  .cell.here {
    opacity: 1;
    outline: 2px solid var(--text);
    outline-offset: 1px;
  }
  .range {
    position: absolute;
    top: 0;
    bottom: 0;
    border-top: 3px solid var(--text);
    border-bottom: 3px solid var(--text);
    pointer-events: none;
  }
  .marker {
    position: absolute;
    top: -2px;
    bottom: -2px;
    width: 3px;
    margin-left: -1.5px;
    background: var(--text);
    border-radius: var(--radius-2xs);
  }
  .band-A {
    background: var(--label-a);
  }
  .band-B {
    background: var(--label-b);
  }
  .band-C {
    background: var(--label-c);
  }
  .band-D {
    background: var(--label-d);
  }
  .band-E {
    background: var(--label-e);
  }
  .band-F {
    background: var(--label-f);
  }
  .band-G {
    background: var(--label-g);
  }
  .notice {
    display: flex;
    gap: var(--space-2);
    align-items: flex-start;
    margin: 0;
    padding: 0.6rem var(--space-3);
    border-radius: var(--radius-control);
    background: var(--status-manual-bg);
    color: var(--text);
  }
  .notice :global(.icon) {
    flex: none;
    margin-top: 0.15rem;
    color: var(--status-manual);
  }
  .service {
    display: block;
    margin-top: 0.2rem;
  }
</style>
