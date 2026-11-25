<!--
  TermHistoryChart: the setpoint terms over time on stacked panels with one shared x axis and
  crosshair: water (heating curve, before rounding, issued step, allowed range and each term as a
  band stacked on the curve), room against its target, and a lane with the reason category per
  moment. Config changes and command holds are markers with icons; holds are also shaded.

  Props: from, to (ms); stacked (from stackSeries); room (Point[], may be empty); target (room
  target °C or null); holds (HoldInterval[]); now; selected (ms of the inspected tick);
  onselect(t) (click/Enter); oncursor(t | null) (crosshair moves, for scrubbing).
  A11y: TimeChart's generated summary, keyboard crosshair and "Show as table".
-->
<script lang="ts">
  import { mergeRuns, type Point } from '$lib/core/chart';
  import type { HoldInterval } from '$lib/setpoint/episodes';
  import { ICONS } from '$lib/core/icons';
  import {
    BAND_TERMS,
    COARSE_REASON_WINDOW_MS,
    dominantReasonRuns,
    reasonCategory,
    REASON_CATEGORY_LIST,
    type StackedSeries,
  } from '$lib/setpoint/series';
  import { formatNumber } from '$lib/core/format';
  import { settings, t, tc } from '$lib/core/settings.svelte';
  import { SERIES } from '$components/charts/palette';
  import TimeChart, {
    type BandSpec,
    type LineSpec,
    type LaneSpec,
    type MarkerSpec,
    type PanelSpec,
    type SpanSpec,
  } from '$components/charts/TimeChart.svelte';

  interface Props {
    from: number;
    to: number;
    stacked: StackedSeries;
    room?: Point[];
    target?: number | null;
    holds?: HoldInterval[];
    now?: number | null;
    selected?: number | null;
    onselect?: (t: number) => void;
    oncursor?: (t: number | null) => void;
  }

  let {
    from,
    to,
    stacked,
    room = [],
    target = null,
    holds = [],
    now = null,
    selected = null,
    onselect,
    oncursor,
  }: Props = $props();

  let width = $state(800);

  function measure(node: HTMLElement): () => void {
    width = node.clientWidth || width;
    if (typeof ResizeObserver === 'undefined') return () => undefined;
    let frame = 0;
    const observer = new ResizeObserver(() => {
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(() => (width = node.clientWidth || width));
    });
    observer.observe(node);
    return () => {
      cancelAnimationFrame(frame);
      observer.disconnect();
    };
  }
  const narrow = $derived(width < 560);

  const BAND_COLOURS: Record<string, string> = {
    room_feedback: 'var(--band-feedback)',
    plan: 'var(--band-plan)',
    start_ramp: 'var(--band-ramp)',
    cycling_floor: 'var(--band-cycling)',
    stove: 'var(--band-stove)',
    other: 'var(--band-other)',
  };

  const CATEGORY_COLOURS: Record<string, string> = {
    normal: 'var(--cat-normal)',
    limited: 'var(--cat-limited)',
    frozen: 'var(--cat-frozen)',
    stopped: 'var(--cat-stopped)',
    manual: 'var(--cat-manual)',
  };

  const water = $derived.by<PanelSpec>(() => {
    const points = stacked.points;
    const bands: BandSpec[] = [];
    const withSafety = points.filter((p) => p.low !== null && p.high !== null);
    if (withSafety.length > 0) {
      bands.push({
        id: 'safety',
        label: t('seriesAllowed'),
        color: 'var(--band-safety)',
        opacity: 0.12,
        hideInLegend: true,
        upper: withSafety.map((p) => [p.t, p.high as number]),
        lower: withSafety.map((p) => [p.t, p.low as number]),
      });
    }
    for (const name of BAND_TERMS) {
      const active = points.some((p) => Math.abs(p.bands[name].hi - p.bands[name].lo) > 1e-6);
      if (!active) continue;
      bands.push({
        id: name,
        label: tc('term_', name),
        color: BAND_COLOURS[name] ?? 'var(--muted)',
        opacity: 0.55,
        upper: points.map((p) => [p.t, p.bands[name].hi]),
        lower: points.map((p) => [p.t, p.bands[name].lo]),
      });
    }
    return {
      id: 'water',
      label: t('setpointPanelWater'),
      unit: '°C',
      height: narrow ? 130 : 200,
      lines: [
        {
          id: 'curve',
          label: t('seriesCurve'),
          color: 'var(--series-curve)',
          points: points.map((p) => [p.t, p.curve]),
        },
        ...(narrow
          ? []
          : [
              {
                id: 'pre_round',
                label: t('seriesPreRound'),
                color: 'var(--series-preround)',
                dash: '4 3',
                width: 1.5,
                points: points
                  .filter((p) => p.preRound !== null)
                  .map((p) => [p.t, p.preRound as number]),
              } satisfies LineSpec,
            ]),
        {
          id: 'setpoint',
          label: t('seriesIssued'),
          color: 'var(--series-issued)',
          step: true,
          width: 2.5,
          digits: 0,
          points: points.filter((p) => p.setpoint !== null).map((p) => [p.t, p.setpoint as number]),
        },
      ],
      bands,
    };
  });

  const roomPanel = $derived.by<PanelSpec | null>(() => {
    if (room.length === 0) return null;
    return {
      id: 'room',
      label: t('setpointPanelRoom'),
      unit: '°C',
      height: narrow ? 70 : 90,
      digits: 1,
      lines: [
        {
          id: 'room',
          label: t('setpointSeriesRoom'),
          color: SERIES.room,
          points: room,
          step: true,
          maxGapMs: Infinity,
        },
      ],
      rules:
        target === null
          ? []
          : [
              {
                value: target,
                label: t('ruleTarget', { value: formatNumber(target, 1, settings.language) }),
                color: SERIES.comfort,
              },
            ],
    };
  });

  const reasonLane = $derived.by<LaneSpec>(() => {
    const segments =
      to - from > COARSE_REASON_WINDOW_MS
        ? dominantReasonRuns(stacked.reasons, from, to)
        : mergeRuns(
            stacked.reasons.map((segment) => ({
              from: segment.from,
              to: segment.to,
              state: reasonCategory(segment.reason),
            })),
          );
    const states: LaneSpec['states'] = {};
    for (const category of REASON_CATEGORY_LIST) {
      states[category] = {
        label: t(`reasonCat_${category}` as 'reasonCat_normal'),
        color: CATEGORY_COLOURS[category] ?? 'var(--muted)',
      };
    }
    return {
      id: 'reason',
      label: t('laneReason'),
      color: 'var(--cat-normal)',
      icon: ICONS.target,
      segments,
      states,
    };
  });

  const panels = $derived<PanelSpec[]>(
    [water, roomPanel, { id: 'reasons', lanes: [reasonLane] }].filter(
      (panel): panel is PanelSpec => panel !== null,
    ),
  );

  const markers = $derived.by<MarkerSpec[]>(() => {
    const out: MarkerSpec[] = [];
    for (const marker of stacked.markers) {
      out.push({
        t: marker.t,
        label: t('markerConfig', { version: marker.label }),
        color: 'var(--accent)',
        icon: ICONS.settings,
      });
    }
    for (const hold of holds) {
      if (hold.from < from) continue;
      out.push({
        t: hold.from,
        label: t('markerHold'),
        color: 'var(--cat-manual)',
        icon: ICONS.pause,
      });
    }
    return out;
  });

  const spans = $derived<SpanSpec[]>(
    holds.map((hold) => ({
      from: Math.max(hold.from, from),
      to: Math.min(hold.to, to),
      label: t('markerHold'),
      color: 'var(--cat-manual)',
      opacity: 0.08,
    })),
  );
</script>

<div class="history" data-testid="term-history" {@attach measure}>
  <TimeChart
    {from}
    {to}
    {panels}
    {markers}
    {spans}
    {now}
    nowLabel={t('chartNow')}
    title={t('historyChartTitle')}
    hidden={['pre_round']}
    {selected}
    {onselect}
    {oncursor}
  />
</div>
