<!--
  NoteClauses: the controller's own note for the decision, split into its clauses, one per row
  with an icon for what it is about (room, sensor, defrost, hot water, plan, ramp, cycling,
  safety, outcome). The text is the controller's, verbatim (English), except that with hot water
  hidden a hot-water run is named "pump busy elsewhere" under a gear.

  Props: note (string).
  A11y: a list of sentences; icons are decorative.
-->
<script lang="ts">
  import { noteClauses, type ClauseKind } from '$lib/setpoint/explain';
  import { BUSY_ICON, hotWater } from '$lib/core/hotWater.svelte';
  import type { IconName } from '$lib/core/icons';
  import Icon from '$ui/Icon.svelte';

  let { note }: { note: string } = $props();

  const ICON: Record<ClauseKind, IconName> = {
    room: 'home',
    sensor: 'thermometer',
    defrost: 'snowflake',
    dhw: 'tap',
    plan: 'clock',
    ramp: 'ramp',
    cycling: 'fan',
    safety: 'warning',
    stove: 'flame',
    outcome: 'target',
    other: 'info',
  };

  const clauses = $derived(noteClauses(note, hotWater.shown));
  const iconOf = (kind: ClauseKind): IconName =>
    kind === 'dhw' && !hotWater.shown ? BUSY_ICON : ICON[kind];
</script>

<ul class="clauses" data-testid="note-clauses" lang="en">
  {#each clauses as clause, index (index)}
    <li class={clause.kind}>
      <Icon name={iconOf(clause.kind)} size={16} />
      <span>{clause.text}</span>
    </li>
  {/each}
</ul>

<style>
  .clauses {
    list-style: none;
    margin: 0;
    padding: 0;
    display: grid;
    gap: 0.3rem;
    font-size: var(--fs-caption);
  }
  li {
    display: flex;
    align-items: flex-start;
    gap: 0.45rem;
  }
  li :global(svg) {
    flex: none;
    margin-top: 0.1rem;
    color: var(--muted);
  }
  .outcome {
    font-weight: var(--fw-semibold);
  }
  .defrost :global(svg),
  .dhw :global(svg) {
    color: var(--status-frozen);
  }
  .safety :global(svg),
  .cycling :global(svg),
  .ramp :global(svg) {
    color: var(--status-limited);
  }
</style>
