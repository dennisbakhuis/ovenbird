<!--
  Day cards for the coming days: icon for the sky, min/max temperature, cloud, sun hours, wind and
  the expected curve water range.
  Props: days (DayCard[] from lib/weather dayCards), now (ms, for "Today"/"Tomorrow").
  A11y: every card is a list item whose text reads in full; the icon is decorative.
-->
<script lang="ts">
  import { formatDay, formatNumber } from '$lib/core/format';
  import { minus } from '$lib/core/minus';
  import type { DayCard } from '$lib/weather/weather';
  import { settings, t } from '$lib/core/settings.svelte';
  import Icon from '$ui/Icon.svelte';

  let { days, now }: { days: DayCard[]; now: number } = $props();

  const locale = $derived(settings.language);
  const deg = (v: number | null) => (v === null ? '–' : minus(`${formatNumber(v, 1, locale)}°`));
  const icon = (sky: DayCard['sky']) => (sky === 'sunny' ? 'sun' : 'cloud');
</script>

<div class="wrap">
  <ol class="days" data-testid="weather-days">
    {#each days as day (day.start)}
      <li class="day" data-testid="weather-day">
        <div class="head">
          <span class="name" title={day.hours < 20 ? t('weatherDayPartial') : undefined}
            >{formatDay(day.start, locale, now)}{day.hours < 20 ? '*' : ''}</span
          >
          <span class="sky" class:sunny={day.sky === 'sunny'}>
            <Icon name={icon(day.sky)} size={22} />
            <span class="sky-label">{t(`weatherSky_${day.sky}` as 'weatherSky_sunny')}</span>
          </span>
        </div>
        <div class="temps">
          <strong>{deg(day.max)}</strong>
          <span class="low">{deg(day.min)}</span>
        </div>
        <ul class="facts">
          <li>
            <Icon name="cloud" size={14} />
            {t('weatherDayCloud', { pct: formatNumber(day.meanCloud ?? 0, 0, locale) })}
          </li>
          <li>
            <Icon name="sun" size={14} />
            {t('weatherDaySun', { h: day.sunHours })}
          </li>
          <li>
            <Icon name="wind" size={14} />
            {t('weatherDayWind', { v: formatNumber(day.maxWind ?? 0, 0, locale) })}
          </li>
          {#if day.curveMin !== null && day.curveMax !== null}
            <li>
              <Icon name="droplet" size={14} />
              {t('weatherDayCurve', {
                min: deg(day.curveMin),
                max: deg(day.curveMax),
              })}
            </li>
          {/if}
        </ul>
      </li>
    {/each}
  </ol>
  {#if days.some((d) => d.hours < 20)}
    <p class="caption foot">* {t('weatherDayPartial')}</p>
  {/if}
</div>

<style>
  .wrap {
    container-type: inline-size;
  }
  .foot {
    margin: var(--space-2) 0 0;
  }
  .days {
    list-style: none;
    margin: 0;
    padding: 0;
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(13rem, 1fr));
    gap: var(--space-3);
  }
  .day {
    border: 1px solid var(--border);
    border-radius: var(--radius);
    padding: var(--space-3);
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
    min-width: 0;
  }
  .head {
    display: flex;
    justify-content: space-between;
    align-items: center;
    gap: var(--space-2);
  }
  .name {
    font-weight: var(--fw-semibold);
  }
  .sky {
    display: inline-flex;
    align-items: center;
    gap: var(--space-1);
    color: var(--muted);
    font-size: var(--fs-caption);
  }
  .sky.sunny :global(svg) {
    color: var(--series-electric, var(--muted));
  }
  .temps {
    display: flex;
    align-items: baseline;
    gap: var(--space-2);
    font-variant-numeric: tabular-nums;
  }
  .temps strong {
    font-size: var(--fs-value);
  }
  .low {
    color: var(--muted);
    font-size: var(--fs-emph);
  }
  .facts {
    list-style: none;
    margin: 0;
    padding: 0;
    display: grid;
    gap: 2px;
    font-size: var(--fs-caption);
    color: var(--muted);
  }
  .facts li {
    display: flex;
    align-items: center;
    gap: var(--space-1);
  }
  @container (max-width: 34rem) {
    .days {
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: var(--space-2);
    }
    .day {
      padding: var(--space-2);
    }
    .sky-label,
    .facts li:nth-child(n + 3) {
      display: none;
    }
    .name {
      font-size: var(--fs-caption);
    }
    .facts {
      font-size: var(--fs-xs);
    }
    .facts {
      grid-template-columns: minmax(0, 1fr);
    }
    .facts li {
      gap: 2px;
      min-width: 0;
      overflow: hidden;
    }
    .facts li :global(svg) {
      display: none;
    }
    .temps strong {
      font-size: var(--fs-emph);
    }
  }
</style>
