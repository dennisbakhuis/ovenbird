<script lang="ts">
  import Card from '$ui/Card.svelte';
  import ForecastErrorCard from '$components/weather/ForecastErrorCard.svelte';
  import Details from '$ui/Details.svelte';
  import Icon from '$ui/Icon.svelte';
  import DayCards from '$components/weather/DayCards.svelte';
  import WeatherChart from '$components/weather/WeatherChart.svelte';
  import WeatherStates from '$components/weather/WeatherStates.svelte';
  import Why from '$ui/Why.svelte';
  import { fetchWeather, isMissing } from '$lib/core/api';
  import { formatDateTime, formatNumber } from '$lib/core/format';
  import type { LiveStore } from '$lib/core/live.svelte';
  import { minus } from '$lib/core/minus';
  import { settings, t, tOpt } from '$lib/core/settings.svelte';
  import type { WeatherResponse } from '$lib/core/types';
  import { dayCards, forecastRange, isStarting, toPoints } from '$lib/weather/weather';
  import { NARROW_QUERY } from '$lib/core/breakpoints';

  let { live }: { live: LiveStore } = $props();

  const BACK_H = 24;
  const AHEAD_H = 48;
  const locale = $derived(settings.language);

  let data = $state<WeatherResponse | null>(null);
  let phase = $state<'loading' | 'ok' | 'missing' | 'failed'>('loading');

  $effect(() => {
    const controller = new AbortController();
    const load = async () => {
      try {
        data = await fetchWeather(BACK_H, AHEAD_H, controller.signal);
        phase = 'ok';
      } catch (error) {
        if (controller.signal.aborted) return;
        phase = isMissing(error) ? 'missing' : 'failed';
      }
    };
    void load();
    const timer = window.setInterval(load, 300_000);
    return () => {
      controller.abort();
      window.clearInterval(timer);
    };
  });

  let phone = $state(false);
  $effect(() => {
    const query = window.matchMedia(NARROW_QUERY);
    const update = () => (phone = query.matches);
    update();
    query.addEventListener('change', update);
    return () => query.removeEventListener('change', update);
  });

  const now = $derived(live.clock);
  const on = $derived(data?.enabled ? data : null);
  const starting = $derived(data !== null && isStarting(data));
  const range = $derived(forecastRange(on?.forecast.points));
  const curveValues = $derived(toPoints(on?.curve_outlook.points).map((p) => p[1]));
  const curveRange = $derived<[number, number] | null>(
    curveValues.length === 0 ? null : [Math.min(...curveValues), Math.max(...curveValues)],
  );
  const days = $derived(dayCards(on?.forecast.points, on?.curve_outlook.points));

  const deg = (v: number | null | undefined) =>
    typeof v === 'number' ? minus(`${formatNumber(v, 1, locale)} °C`) : '–';
  const degShort = (v: number) => minus(`${formatNumber(v, 1, locale)}°`);
  const locationText = $derived.by(() => {
    const loc = on?.location;
    if (!loc) return t('weatherSourceNoLocation');
    const source = tOpt(`weatherSource_${loc.source}`) ?? loc.source;
    return `${formatNumber(loc.latitude, 2, locale)}, ${formatNumber(loc.longitude, 2, locale)} (${source})`;
  });
</script>

<h1>{t('weatherTitle')}</h1>

{#if phase === 'loading'}
  <p class="muted">{t('loading')}</p>
{:else if phase === 'missing'}
  <Card bare data-testid="unavailable"><p>{t('unavailable')}</p></Card>
{:else if phase === 'failed' || !data}
  <Card bare data-testid="weather-failed"><p>{t('weatherFailed')}</p></Card>
{:else if !data.enabled}
  <WeatherStates kind="disabled" reason={data.reason ?? ''} provider={data.provider} />
{:else if starting}
  <WeatherStates kind="starting" />
{:else if on}
  <div class="stack">
    {#if on.stale}
      <WeatherStates kind="stale" age={on.age} />
    {/if}

    <section class="summary" data-testid="weather-now" data-help="weather.now">
      <div class="now">
        <Icon name="thermometer" size={28} />
        <div>
          <div class="lead">{t('weatherSummaryNow', { measured: deg(on.now.measured_c) })}</div>
          <div class="caption">
            {t('weatherSummaryDetail', {
              filtered: deg(on.now.filtered_c),
              forecast: deg(on.now.forecast_c),
            })}
          </div>
        </div>
      </div>
      <div class="ranges">
        {#if range}
          <div>
            <span class="caption">{t('weatherSummaryRangeLabel')}</span>
            <strong>{degShort(range[0])} … {degShort(range[1])}</strong>
          </div>
        {/if}
        {#if curveRange}
          <div>
            <span class="caption">{t('weatherPanelCurve')}</span>
            <strong>{degShort(curveRange[0])} … {degShort(curveRange[1])}</strong>
          </div>
        {/if}
      </div>
    </section>

    <Card title={t('weatherChartTitle')} icon="chart" testid="weather-chart" help="weather.chart">
      {#snippet actions()}
        <Why title={t('weatherOutlookTitle')} testid="weather-curve-why">
          <p>{t('weatherCurveWhy')}</p>
          <p>{t('weatherCurveCaption')}</p>
        </Why>
      {/snippet}
      <WeatherChart data={on} {now} back={BACK_H} ahead={AHEAD_H} />
      <p class="caption note source" data-testid="weather-provider">
        {t('weatherSourceLine', {
          provider: on.provider,
          issued: formatDateTime(on.issued, locale),
          location: locationText,
        })}
        · <a class="hit" href="#/settings/weather">{t('weatherSettingsLink')}</a>
        <Why title={t('weatherProviderTitle')}>{t('weatherSourceWhy')}</Why>
      </p>
    </Card>

    <div class="grid">
      {#if days.length > 0}
        <Card
          title={t('weatherDaysTitle')}
          icon="sun"
          span={7}
          testid="weather-days-card"
          help="weather.days"
        >
          <DayCards {days} {now} />
        </Card>
      {/if}
      {#if phone}
        <div data-help="weather.error">
          <Details
            summary={t('errorTitle')}
            id="weather-error"
            icon="chart"
            testid="forecast-error-details"
          >
            <ForecastErrorCard error={on.error} span={12} />
          </Details>
        </div>
      {:else}
        <ForecastErrorCard error={on.error} span={days.length > 0 ? 5 : 12} help="weather.error" />
      {/if}
    </div>
  </div>
{/if}

<style>
  .summary {
    display: flex;
    flex-wrap: wrap;
    justify-content: space-between;
    align-items: center;
    gap: var(--space-3) var(--space-5);
    padding: var(--space-3) var(--card-pad);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    background: var(--surface);
  }
  .now {
    display: flex;
    align-items: center;
    gap: var(--space-3);
  }
  .lead {
    font-size: var(--fs-emph);
    font-weight: var(--fw-semibold);
  }
  .ranges {
    display: flex;
    flex-wrap: wrap;
    gap: var(--space-2) var(--space-5);
  }
  .ranges > div {
    display: flex;
    flex-direction: column;
  }
  .ranges strong {
    font-variant-numeric: tabular-nums;
    font-size: var(--fs-emph);
  }
  .note {
    margin: var(--space-2) 0 0;
  }
  .source {
    overflow-wrap: anywhere;
  }
</style>
