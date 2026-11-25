<!--
  HomeTiles: energy, COP, starts today and the forecast mini.

  Props: stats (TodayStats | null), forecast (ForecastPoint[] | null; null hides the tile),
  nowMs (clock for the 24 h window), forecastOff (weather is configured off: shows a hint with a link to enable it),
  zone (the service's time zone when it differs from the browser's: "today" counts from its
  midnight, said under the tiles), yesterdayKwh (electricity used yesterday up to this time of day,
  shown under the energy tile for comparison; null hides it).
-->
<script lang="ts">
  import { formatDuration, formatNumber } from '$lib/core/format';
  import { minus } from '$lib/core/minus';
  import { settings, t } from '$lib/core/settings.svelte';
  import type { ForecastPoint } from '$lib/core/types';
  import { SERIES } from '$components/charts/palette';
  import Sparkline from '$components/charts/Sparkline.svelte';
  import StatChip from '$ui/StatChip.svelte';
  import type { TodayStats } from './model';

  interface Props {
    stats: TodayStats | null;
    forecast: ForecastPoint[] | null;
    forecastOff: boolean;
    nowMs: number;
    zone?: string | null;
    yesterdayKwh?: number | null;
  }

  let { stats, forecast, forecastOff, nowMs, zone = null, yesterdayKwh = null }: Props = $props();

  const locale = $derived(settings.language);
  const num = (value: number, digits = 1) => minus(formatNumber(value, digits, locale));
  const incomplete = $derived(stats !== null && stats.energy.coverage < 0.8);
  const energyCaption = $derived(
    stats === null
      ? ''
      : incomplete
        ? t('tileIncomplete')
        : t('tileEnergyHeat', { kwh: num(stats.energy.heatKwh) }),
  );
  const yesterdayCaption = $derived(
    yesterdayKwh === null ? null : t('tileEnergyYesterday', { kwh: num(yesterdayKwh) }),
  );
  const yesterdayTitle = $derived(
    yesterdayKwh === null ? undefined : t('tileEnergyYesterdayTitle', { kwh: num(yesterdayKwh) }),
  );
  const yesterdayTrend = $derived.by(() => {
    if (yesterdayKwh === null || stats === null || incomplete) return null;
    const today = stats.energy.electricKwh;
    const margin = Math.max(0.2, yesterdayKwh * 0.05);
    return today > yesterdayKwh + margin ? 'up' : today < yesterdayKwh - margin ? 'down' : 'flat';
  });
  const startsCaption = $derived.by(() => {
    if (stats === null) return '';
    const defrosts = stats.defrosts;
    return stats.meanRunS === null
      ? t('tileStartsNoteNone', { defrosts })
      : t('tileStartsNote', { defrosts, run: formatDuration(stats.meanRunS) });
  });

  const next = $derived.by(() => {
    if (!forecast) return [];
    return forecast.flatMap((point): [number, number][] => {
      const time = Date.parse(point[0]);
      const value = point[1];
      const inside = time >= nowMs - 3_600_000 && time <= nowMs + 24 * 3_600_000;
      return inside && value !== null && Number.isFinite(value) ? [[time, value]] : [];
    });
  });
  const range = $derived(
    next.length === 0
      ? null
      : { min: Math.min(...next.map(([, v]) => v)), max: Math.max(...next.map(([, v]) => v)) },
  );
</script>

<div class="tiles" data-testid="home-tiles" data-help="home.tiles">
  <StatChip
    label={t('tileEnergy')}
    icon="bolt"
    value={stats ? num(stats.energy.electricKwh) : '–'}
    unit="kWh"
    caption={energyCaption}
    title={yesterdayTitle}
    trend={yesterdayTrend}
    trendLabel={yesterdayTitle}
    stale={incomplete}
    testid="tile-energy"
  >
    {#if yesterdayCaption}<span class="yday" data-testid="tile-energy-yesterday"
        >{yesterdayCaption}</span
      >{/if}
  </StatChip>
  <StatChip
    label={t('tileCop')}
    icon="flame"
    value={stats?.energy.cop != null ? num(stats.energy.cop) : '–'}
    caption={t('tileCopNote')}
    stale={incomplete}
    testid="tile-cop"
  />
  <StatChip
    label={t('tileStarts')}
    icon="fan"
    value={stats ? String(stats.starts) : '–'}
    caption={startsCaption}
    testid="tile-starts"
  />
  {#if forecast && range}
    <StatChip
      label={t('tileForecast')}
      icon="cloud"
      value={t('tileForecastRange', { min: num(range.min), max: num(range.max) })}
      href="#/weather"
      testid="forecast-strip"
    >
      <Sparkline
        points={next}
        label={t('tileForecast')}
        unit="°C"
        color={SERIES.forecast}
        height={28}
      />
    </StatChip>
  {:else if forecastOff}
    <p class="caption off" data-testid="forecast-off">
      {t('forecastOff')} <a class="hit" href="#/settings/weather">{t('weatherDisabledLink')}</a>
    </p>
  {/if}
</div>
{#if zone}
  <p class="caption zone" data-testid="tiles-zone">{t('tileZone', { zone })}</p>
{/if}

<style>
  .tiles {
    container: tiles / inline-size;
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(9.5rem, 1fr));
    gap: var(--space-3);
  }
  .yday {
    color: var(--muted);
    font-size: var(--fs-caption);
  }
  @container tiles (max-width: 36rem) {
    .yday {
      display: none;
    }
  }
  .zone {
    margin: calc(-1 * var(--space-2)) 0 0;
    color: var(--muted);
  }
  .off {
    margin: 0;
    align-self: center;
  }
  .off a {
    display: inline-block;
  }
</style>
