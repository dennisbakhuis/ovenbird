<!--
  ChartGallery: dev-only gallery of the chart kit (#/dev-charts, loaded by App in mock mode only) with deterministic data from
  components/charts/demo.ts. Text is English on purpose: this page is never shipped to users.
-->
<script lang="ts">
  import Card from '$ui/Card.svelte';
  import TimeChart from './TimeChart.svelte';
  import ArtGallery from '$components/art/ArtGallery.svelte';
  import BandMeter from './BandMeter.svelte';
  import Bars from './Bars.svelte';
  import BulletBar from './BulletBar.svelte';
  import PowerFlow from './PowerFlow.svelte';
  import Sparkline from './Sparkline.svelte';
  import StateStrip from './StateStrip.svelte';
  import { DEMO_ENERGY, DEMO_FORECAST_ERROR, DEMO_LOCATION, DEMO_MONITORS, demoDay } from './demo';
  import { GLYPHS } from './glyphs';
  import { SERIES } from './palette';
  import type { LaneSpec, PanelSpec } from './types';
  import { nightIntervals } from '$lib/core/chart';
  import { hotWater, hotWaterLanes } from '$lib/core/hotWater.svelte';
  import { trendPerHour } from '$lib/core/chartSummary';

  const day = demoDay();
  const HOUR = 3_600_000;

  const allLanes: LaneSpec[] = [
    {
      id: 'compressor',
      label: 'Compressor',
      icon: GLYPHS.fan,
      color: SERIES.compressor,
      segments: day.lanes.compressor,
      states: { on: { label: 'on' } },
    },
    {
      id: 'defrost',
      label: 'Defrost',
      icon: GLYPHS.snowflake,
      color: SERIES.defrost,
      segments: day.lanes.defrost,
    },
    {
      id: 'dhw',
      label: 'Hot water',
      icon: GLYPHS.tap,
      color: SERIES.dhw,
      segments: day.lanes.dhw,
    },
    {
      id: 'quiet',
      label: 'Quiet',
      icon: GLYPHS.moon,
      color: SERIES.quiet,
      segments: day.lanes.quiet,
      states: { level2: { label: 'level 2' } },
    },
  ];
  const lanes = hotWaterLanes(allLanes, hotWater.shown);

  const todayPanels: PanelSpec[] = [
    {
      id: 'room',
      label: 'Room',
      unit: '°C',
      height: 110,
      lines: [
        {
          id: 'room',
          label: 'Room',
          color: SERIES.room,
          points: day.room,
          step: true,
          maxGapMs: Infinity,
        },
      ],
      bands: [
        {
          id: 'comfort',
          label: 'Comfort band',
          color: SERIES.comfort,
          upper: day.comfort.high,
          lower: day.comfort.low,
          opacity: 0.14,
        },
      ],
      rules: [{ value: day.comfort.target, label: 'target 21.0', color: SERIES.comfort }],
    },
    {
      id: 'water',
      label: 'Water',
      unit: '°C',
      lines: [
        {
          id: 'setpoint',
          label: 'Setpoint',
          color: SERIES.setpoint,
          points: day.setpoint,
          step: true,
          digits: 0,
          maxGapMs: Infinity,
        },
        { id: 'outlet', label: 'Outlet', color: SERIES.outlet, points: day.outlet },
        {
          id: 'inlet',
          label: 'Inlet',
          color: SERIES.inlet,
          points: day.inlet,
          dash: '5 3',
          width: 1.5,
        },
      ],
    },
    {
      id: 'outside',
      label: 'Outside',
      unit: '°C',
      height: 90,
      lines: [{ id: 'outside', label: 'Outside', color: SERIES.outside, points: day.outside }],
    },
    { id: 'pump', lanes },
  ];

  const weatherFrom = day.now - 24 * HOUR;
  const weatherTo = day.now + 24 * HOUR;
  const weatherPanels: PanelSpec[] = [
    {
      id: 'temp',
      label: 'Outside',
      unit: '°C',
      lines: [
        { id: 'measured', label: 'Measured', color: SERIES.outside, points: day.outside },
        {
          id: 'forecast',
          label: 'Forecast',
          color: SERIES.forecast,
          points: day.forecast,
          dash: '6 4',
        },
      ],
    },
    {
      id: 'curve',
      label: 'Curve outlook',
      unit: '°C',
      height: 90,
      lines: [
        {
          id: 'curve',
          label: 'Expected water',
          color: SERIES.outlet,
          points: day.curveOutlook,
          dash: '6 4',
        },
      ],
    },
    {
      id: 'sun',
      label: 'Sun',
      unit: 'W/m²',
      height: 70,
      zero: true,
      digits: 0,
      lines: [{ id: 'sun', label: 'Radiation', color: SERIES.electric, points: day.radiation }],
    },
  ];
  const nights = nightIntervals(weatherFrom, weatherTo, DEMO_LOCATION.lat, DEMO_LOCATION.lon);

  const last6h = (points: [number, number][]) => {
    const start = day.now - 6 * HOUR;
    const before = points.filter(([t]) => t < start).at(-1);
    const inside = points.filter(([t]) => t >= start);
    return before ? [[start, before[1]] as [number, number], ...inside] : inside;
  };
  const roomValue = day.room[day.room.length - 1]?.[1] ?? null;
  const roomTrend = trendPerHour(day.room.filter(([t]) => t >= day.now - 3 * HOUR));

  let selected = $state<number | null>(null);
</script>

<h1>Chart kit</h1>
<p class="muted intro">
  Development gallery (mock mode only). Data is synthetic and deterministic; every chart is keyboard
  operable and has a text alternative.
</p>

<div class="grid">
  <Card bare class="chart-gallery-card chart-gallery-wide" data-testid="dev-timechart-panels">
    <h2>TimeChart · stacked panels with lanes</h2>
    <TimeChart
      from={day.from}
      to={day.to}
      title="Today"
      panels={todayPanels}
      markers={[
        { t: day.configChange, label: 'config v12', icon: GLYPHS.gear },
        { t: day.hold.from, label: 'hold', icon: GLYPHS.pause, color: SERIES.hold },
        { t: day.from + 5 * HOUR, label: 'restart', icon: GLYPHS.warning },
      ]}
      spans={[{ ...day.hold, label: 'Hold', color: SERIES.hold, opacity: 0.1 }]}
      now={day.now}
      nowLabel="now"
      {selected}
      onselect={(t) => (selected = t)}
    />
  </Card>

  <Card bare class="chart-gallery-card chart-gallery-wide" data-testid="dev-timechart-weather">
    <h2>TimeChart · weather, night shading, forecast</h2>
    <TimeChart
      from={weatherFrom}
      to={weatherTo}
      title="Weather"
      panels={weatherPanels}
      night={nights}
      now={day.now}
      nowLabel="now"
      maxGapMs={2 * HOUR}
    />
  </Card>

  <Card bare class="chart-gallery-card chart-gallery-wide" data-testid="dev-timechart-legacy">
    <h2>TimeChart · v1 props (backward compatible)</h2>
    <TimeChart
      from={day.from}
      to={day.to}
      title="Last 24 hours"
      lines={[
        { id: 'outside', label: 'Outside', color: SERIES.outside, points: day.outside },
        { id: 'outlet', label: 'Outlet', color: SERIES.outlet, points: day.outlet },
        {
          id: 'room',
          label: 'Room (right axis)',
          color: SERIES.room,
          points: day.room,
          step: true,
          axis: 'right',
        },
      ]}
      now={day.now}
      nowLabel="now"
      height={220}
    />
  </Card>

  <Card bare class="chart-gallery-card chart-gallery-wide" data-testid="dev-statestrip">
    <h2>StateStrip · day strip</h2>
    <StateStrip from={day.from} to={day.to} title="Pump today" {lanes} now={day.now} />
  </Card>

  <Card bare class="chart-gallery-card" data-testid="dev-sparklines">
    <h2>Sparkline</h2>
    <div class="tiles">
      <div class="tile">
        <span class="muted">Outlet</span>
        <strong>32.5 °C</strong>
        <Sparkline
          points={last6h(day.outlet)}
          label="Outlet"
          unit="°C"
          color={SERIES.outlet}
          minMax
        />
      </div>
      <div class="tile">
        <span class="muted">Room</span>
        <strong>{roomValue} °C</strong>
        <Sparkline
          points={last6h(day.room)}
          label="Room"
          unit="°C"
          color={SERIES.room}
          step
          band={{ lower: day.comfort.low, upper: day.comfort.high }}
          from={day.now - 6 * HOUR}
          to={day.now}
          minMax
        />
      </div>
      <div class="tile">
        <span class="muted">Outside (interactive)</span>
        <strong>2.5 °C</strong>
        <Sparkline
          points={last6h(day.outside)}
          label="Outside"
          unit="°C"
          color={SERIES.outside}
          interactive
          minMax
        />
      </div>
      <div class="tile">
        <span class="muted">Compressor</span>
        <strong>38 Hz</strong>
        <Sparkline
          points={last6h(day.hz)}
          label="Compressor"
          unit="Hz"
          digits={0}
          color={SERIES.compressor}
          step
          area={false}
        />
      </div>
    </div>
  </Card>

  <Card bare class="chart-gallery-card" data-testid="dev-bandmeter">
    <h2>BandMeter</h2>
    <div class="stack">
      <BandMeter
        label="Room"
        value={roomValue}
        target={day.comfort.target}
        low={day.comfort.low}
        high={day.comfort.high}
        trend={roomTrend}
        flip={{ at: 21.5, label: 'flips at 21.5' }}
      />
      <BandMeter label="Room" value={21.1} target={21.0} low={20.5} high={21.5} trend={0.02} />
      <BandMeter label="Room" value={21.9} target={21.0} low={20.5} high={21.5} trend={0.3} />
      <BandMeter label="Room" value={null} target={21.0} low={20.5} high={21.5} />
    </div>
  </Card>

  <Card bare class="chart-gallery-card" data-testid="dev-bulletbar">
    <h2>BulletBar</h2>
    <div class="stack">
      {#each DEMO_MONITORS as monitor (monitor.label)}
        <BulletBar
          label={monitor.label}
          value={monitor.value}
          limit={monitor.limit}
          warn={'warn' in monitor ? monitor.warn : null}
          direction={monitor.direction}
          unit={monitor.unit}
          digits={monitor.unit === 's' ? 0 : 1}
        />
      {/each}
    </div>
  </Card>

  <Card bare class="chart-gallery-card" data-testid="dev-bars">
    <h2>Bars</h2>
    <Bars
      title="Electric energy per day"
      items={DEMO_ENERGY}
      unit="kWh"
      highlight={DEMO_ENERGY.length - 1}
      color={SERIES.electric}
    />
    <h3>Forecast error</h3>
    <Bars
      title="Forecast bias"
      items={DEMO_FORECAST_ERROR.bias}
      unit="K"
      orientation="horizontal"
      color={SERIES.outside}
      min={-1}
      max={1}
    />
    <Bars
      title="Forecast MAE"
      items={DEMO_FORECAST_ERROR.mae}
      unit="K"
      orientation="horizontal"
      color={SERIES.forecast}
    />
  </Card>

  <Card bare class="chart-gallery-card" data-testid="dev-powerflow">
    <h2>PowerFlow</h2>
    <div class="stack">
      <PowerFlow electricW={1900} heatW={8400} />
      <PowerFlow electricW={1400} heatW={0} running={false} />
      <PowerFlow electricW={18} heatW={0} />
      <PowerFlow electricW={null} heatW={null} />
      <PowerFlow electricW={1900} heatW={8400} compact maxW={12000} />
    </div>
  </Card>

  <ArtGallery />
</div>

<style>
  .intro {
    margin: 0 0 var(--space-4);
  }
  .grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(min(100%, 24rem), 1fr));
    gap: var(--space-4);
  }
  :global(.chart-gallery-card) {
    grid-column: auto;
    min-width: 0;
  }
  :global(.chart-gallery-card.chart-gallery-wide) {
    grid-column: 1 / -1;
  }
  .tiles {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: var(--space-3);
  }
  .tile {
    display: flex;
    flex-direction: column;
    gap: var(--chart-space-1);
    padding: var(--chart-space-7);
    border: 1px solid var(--border);
    border-radius: var(--radius-control);
    min-width: 0;
  }
  .tile strong {
    font-size: var(--fs-title-lg);
    font-variant-numeric: tabular-nums;
  }
  .stack {
    display: grid;
    gap: var(--space-4);
  }
  h3 {
    font-size: var(--fs-xl);
    margin-top: var(--space-4);
  }
</style>
