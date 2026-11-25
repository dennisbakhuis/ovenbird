<!--
  Weather chart: one shared time axis with panels for outside temperature (measured, filtered,
  forecast made a day earlier, current forecast), the expected curve water temperature (curve only,
  before room correction), solar radiation, cloud cover and wind. Night is shaded, "now" is a line.
  Props: data (WeatherOn), now (ms), back/ahead (hours shown).
  A11y: delegated to TimeChart (generated summary, keyboard crosshair, table toggle).
-->
<script lang="ts">
  import { nightByHours, nightIntervals } from '$lib/core/chart';
  import { formatClockTime } from '$lib/core/chartSummary';
  import { settings, t } from '$lib/core/settings.svelte';
  import type { WeatherOn } from '$lib/core/types';
  import { forecastColumn, toPoints } from '$lib/weather/weather';
  import { SERIES } from '$components/charts/palette';
  import TimeChart, { type PanelSpec } from '$components/charts/TimeChart.svelte';

  let {
    data,
    now,
    back = 24,
    ahead = 48,
  }: { data: WeatherOn; now: number; back?: number; ahead?: number } = $props();

  const HOUR = 3_600_000;
  const GAP_MS = 2 * HOUR;
  const lang = $derived(settings.language);
  const from = $derived(now - back * HOUR);
  const to = $derived(now + ahead * HOUR);
  const night = $derived(
    data.location
      ? nightIntervals(from, to, data.location.latitude, data.location.longitude)
      : nightByHours(from, to),
  );
  const forecast = $derived(data.forecast.points);

  const panels = $derived<PanelSpec[]>([
    {
      id: 'outside',
      label: t('weatherPanelOutside'),
      unit: '°C',
      height: 150,
      lines: [
        {
          id: 'measured',
          label: t('weatherMeasuredShort'),
          color: SERIES.outside,
          points: toPoints(data.measured.points),
          step: true,
          width: 1.5,
          maxGapMs: GAP_MS,
        },
        {
          id: 'filtered',
          label: t('weatherFilteredShort'),
          color: SERIES.setpoint,
          points: toPoints(data.filtered.points),
          maxGapMs: GAP_MS,
        },
        {
          id: 'past',
          label: t('weatherForecastPastShort', { h: data.forecast_past.lead_h }),
          color: SERIES.neutral,
          dash: '5 4',
          width: 1.5,
          points: toPoints(data.forecast_past.points),
          maxGapMs: GAP_MS,
        },
        {
          id: 'forecast',
          label: t('weatherForecast'),
          color: SERIES.outlet,
          points: forecastColumn(forecast, 1),
          maxGapMs: GAP_MS,
        },
      ],
    },
    {
      id: 'curve',
      label: t('weatherPanelCurve'),
      unit: '°C',
      height: 90,
      lines: [
        {
          id: 'outlook',
          hideInLegend: true,
          label: t('weatherOutlookLine'),
          color: SERIES.heat,
          points: toPoints(data.curve_outlook.points),
          maxGapMs: GAP_MS,
        },
      ],
    },
    {
      id: 'sun',
      label: t('weatherPanelSun'),
      unit: ' W/m²',
      height: 50,
      min: 0,
      digits: 0,
      lines: [
        {
          id: 'radiation',
          hideInLegend: true,
          label: t('weatherMultiple_radiation'),
          color: SERIES.electric,
          points: forecastColumn(forecast, 2),
          maxGapMs: GAP_MS,
        },
      ],
    },
    {
      id: 'cloud',
      label: t('weatherPanelCloud'),
      unit: ' %',
      height: 44,
      min: 0,
      max: 100,
      digits: 0,
      lines: [
        {
          id: 'cloud',
          hideInLegend: true,
          label: t('weatherMultiple_cloud'),
          color: SERIES.quiet,
          points: forecastColumn(forecast, 3),
          maxGapMs: GAP_MS,
        },
      ],
    },
    {
      id: 'wind',
      label: t('weatherPanelWind'),
      unit: ' m/s',
      height: 44,
      min: 0,
      digits: 1,
      lines: [
        {
          id: 'wind',
          hideInLegend: true,
          label: t('weatherMultiple_wind'),
          color: SERIES.dhw,
          points: forecastColumn(forecast, 4),
          maxGapMs: GAP_MS,
        },
      ],
    },
  ]);

  const summary = $derived(
    t('weatherChartSummary', {
      from: formatClockTime(from, lang, true),
      to: formatClockTime(to, lang, true),
    }),
  );
</script>

<TimeChart
  {from}
  {to}
  {panels}
  {night}
  {now}
  nowLabel={t('chartNow')}
  title={t('weatherChartTitle')}
  {summary}
/>
