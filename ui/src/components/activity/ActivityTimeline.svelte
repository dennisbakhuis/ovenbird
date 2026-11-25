<!--
  ActivityTimeline: the last 24 hours of events on one axis, shared by the Activity tabs: alarms
  and holds as spans, config changes and commands as ticks, listed as moments ("12:19 · Water
  setpoint 32 · failed") in the list view.

  Props: from, to (ms); alarms, holds (JournalPair[]); configEvents, commandEvents (LaneEvent[]:
  time and text of each event).
-->
<script lang="ts">
  import Card from '$ui/Card.svelte';
  import type { JournalPair } from '$lib/activity/commandGroups';
  import { ICONS } from '$lib/core/icons';
  import { t } from '$lib/core/settings.svelte';
  import StateStrip from '$components/charts/StateStrip.svelte';
  import type { LaneEvent, LaneSpec } from '$components/charts/types';
  import type { StateSegment } from '$lib/core/chart';

  interface Props {
    from: number;
    to: number;
    alarms: JournalPair[];
    holds: JournalPair[];
    configEvents: LaneEvent[];
    commandEvents: LaneEvent[];
    help?: string;
  }

  let { from, to, alarms, holds, configEvents, commandEvents, help }: Props = $props();

  const TICK_MS = 4 * 60_000;

  function spans(pairs: JournalPair[], state: string): StateSegment[] {
    return pairs
      .map((pair) => ({
        from: Math.max(from, Date.parse(pair.from)),
        to: Math.min(to, pair.to === null ? to : Date.parse(pair.to)),
        state,
      }))
      .filter((segment) => segment.to >= segment.from && Number.isFinite(segment.from))
      .map((segment) => ({ ...segment, to: Math.max(segment.to, segment.from + TICK_MS) }))
      .sort((a, b) => a.from - b.from);
  }

  function inWindow(events: LaneEvent[]): LaneEvent[] {
    return events
      .filter((event) => Number.isFinite(event.at) && event.at >= from && event.at <= to)
      .sort((a, b) => a.at - b.at);
  }

  function ticks(events: LaneEvent[], state: string): StateSegment[] {
    return events.map((event) => ({ from: event.at, to: Math.min(to, event.at + TICK_MS), state }));
  }

  function lane(
    id: string,
    label: string,
    color: string,
    icon: string,
    segments: StateSegment[],
    events?: LaneEvent[],
  ): LaneSpec {
    return { id, label, color, icon, segments, events, states: { [id]: { label, color } } };
  }

  const configShown = $derived(inWindow(configEvents));
  const commandShown = $derived(inWindow(commandEvents));

  const lanes = $derived<LaneSpec[]>([
    lane(
      'alarms',
      t('timelineAlarms'),
      'var(--status-stopped)',
      ICONS.bell,
      spans(alarms, 'alarms'),
    ),
    lane('holds', t('timelineHolds'), 'var(--status-manual)', ICONS.pause, spans(holds, 'holds')),
    lane(
      'config',
      t('timelineConfig'),
      'var(--status-frozen)',
      ICONS.settings,
      ticks(configShown, 'config'),
      configShown,
    ),
    lane(
      'commands',
      t('timelineCommands'),
      'var(--status-limited)',
      ICONS.bolt,
      ticks(commandShown, 'commands'),
      commandShown,
    ),
  ]);
</script>

<Card
  bare
  class="activity-timeline-timeline"
  data-testid="activity-timeline"
  data-help={help}
  aria-labelledby="timeline-title"
>
  <h2 id="timeline-title">{t('timelineTitle')}</h2>
  <StateStrip {from} {to} {lanes} now={to} title={t('timelineTitle')} />
</Card>

<style>
  :global(.activity-timeline-timeline) {
    margin-bottom: var(--space-3);
  }
  h2 {
    margin: 0 0 var(--space-2);
    font-size: var(--fs-emph);
  }
</style>
