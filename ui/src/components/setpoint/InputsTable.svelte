<!--
  InputsTable: the inputs a decision used, as chips: icon, human label, value with unit (enum
  states in words), age and a freshness dot; the raw signal id is the small caption. Internal
  flags (such as `stats`) are not shown.

  Props: record (DecisionRecord).
  A11y: a list; freshness is a word in the accessible text, not only the dot colour.
-->
<script lang="ts">
  import { inputViews } from '$lib/setpoint/explain';
  import { formatAge, formatWithUnit } from '$lib/core/format';
  import { settings, t, tOpt } from '$lib/core/settings.svelte';
  import type { DecisionRecord } from '$lib/core/types';
  import Icon from '$ui/Icon.svelte';

  let { record }: { record: DecisionRecord } = $props();

  const items = $derived(inputViews(record));

  function valueText(item: (typeof items)[number]): string {
    if (item.enumKey) return tOpt(`inputEnum_${item.enumKey}`) ?? String(item.value);
    if (typeof item.value === 'number')
      return formatWithUnit(item.value, item.unit, item.digits, settings.language);
    if (item.value === null) return '–';
    return String(item.value);
  }
</script>

<ul class="inputs" data-testid="inputs-table">
  {#each items as item (item.signal)}
    <li class:stale={!item.fresh}>
      <Icon name={item.icon} size={18} />
      <span class="text">
        <span class="label">{tOpt(`input_${item.key}`) ?? item.signal}</span>
        <code class="id">{item.signal}</code>
      </span>
      <span class="reading">
        <strong>{valueText(item)}</strong>
        <span class="age">
          <i class="dot" aria-hidden="true"></i>
          <span class="visually-hidden">{item.fresh ? t('inputFresh') : t('inputStale')},</span>
          {formatAge(item.age)}
        </span>
      </span>
    </li>
  {/each}
</ul>

<style>
  .inputs {
    list-style: none;
    margin: 0;
    padding: 0;
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(13rem, 1fr));
    gap: var(--space-2);
  }
  li {
    display: flex;
    align-items: center;
    gap: var(--space-2);
    padding: 0.4rem 0.6rem;
    border: 1px solid var(--border);
    border-radius: var(--radius-sm);
    background: var(--surface);
    min-width: 0;
  }
  li > :global(svg) {
    color: var(--muted);
  }
  .text {
    display: grid;
    min-width: 0;
    flex: 1;
  }
  .label {
    font-size: var(--fs-body);
  }
  .id {
    font-size: var(--fs-2xs);
    color: var(--muted);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .reading {
    display: grid;
    justify-items: end;
    font-variant-numeric: tabular-nums;
    white-space: nowrap;
  }
  .age {
    display: inline-flex;
    align-items: center;
    gap: var(--space-1);
    font-size: var(--fs-caption);
    color: var(--muted);
  }
  .dot {
    width: 0.5rem;
    height: 0.5rem;
    border-radius: 50%;
    background: var(--status-ok);
  }
  .stale .dot {
    background: var(--status-limited);
  }
  .stale {
    border-color: var(--status-limited);
  }
</style>
