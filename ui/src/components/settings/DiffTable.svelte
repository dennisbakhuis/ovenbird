<!--
  DiffTable: a list of setting changes drawn as pictures where that helps — a curve change as the
  old and new curve with the area between them shaded, quiet windows as two 24 h bars, numbers
  as from → to chips with a signed difference — and from → to chips otherwise.
-->
<script lang="ts">
  import { asCurve } from '$lib/core/curve';
  import { asWindows, formatDelta, formatValue } from '$lib/core/fieldFormat';
  import { displayUnit, toDisplay } from '$lib/core/schema';
  import { settings, t, tOpt } from '$lib/core/settings.svelte';
  import type { ConfigSchema } from '$lib/core/types';
  import MiniCurve from './MiniCurve.svelte';
  import QuietBar from './QuietBar.svelte';
  import Icon from '$ui/Icon.svelte';

  interface Entry {
    field: string;
    from: unknown;
    to: unknown;
    reset?: boolean;
  }

  let { entries, schema }: { entries: Entry[]; schema: ConfigSchema | null } = $props();

  const locale = $derived(settings.language);
  const words = $derived({
    on: t('on'),
    off: t('off'),
    none: t('fieldNone'),
    forever: t('retentionForeverValue'),
  });
  const show = (field: string, value: unknown) =>
    formatValue(schema?.fields[field], value, locale, words);
  const delta = (entry: Entry) => {
    const def = schema?.fields[entry.field];
    if (!def || typeof entry.from !== 'number' || typeof entry.to !== 'number') return null;
    const text = formatDelta(toDisplay(def, entry.from), toDisplay(def, entry.to), locale, 2);
    const unit = displayUnit(def);
    return text ? `${text}${unit ? `\u202f${unit === '°C' ? 'K' : unit}` : ''}` : null;
  };
</script>

<ul class="diff" data-testid="diff-table">
  {#each entries as entry (entry.field)}
    {@const before = asCurve(entry.from)}
    {@const after = asCurve(entry.to)}
    {@const oldWindows = asWindows(entry.from)}
    {@const newWindows = asWindows(entry.to)}
    {@const change = delta(entry)}
    <li
      data-testid="diff-row-{entry.field}"
      class:pictured={Boolean(after) || Boolean(oldWindows && newWindows)}
    >
      <div class="name">
        <span>{tOpt(`cfg.${entry.field}.label`) ?? entry.field}</span>
        {#if entry.reset}<span class="tag">{t('diffReset')}</span>{/if}
      </div>
      {#if after && after.length > 0}
        <div class="visual">
          <MiniCurve curve={after} before={before ?? null} height={112} labels axis />
          <p class="caption">
            <span class="key old"></span>{t('diffBefore')}
            <span class="key new"></span>{t('diffAfter')}
          </p>
        </div>
      {:else if oldWindows && newWindows}
        <div class="visual bars">
          <span class="caption">{t('diffBefore')}</span>
          <QuietBar windows={oldWindows} ticks={false} height={12} />
          <span class="caption">{t('diffAfter')}</span>
          <QuietBar windows={newWindows} height={12} />
        </div>
      {:else}
        <div class="values">
          <span class="chip old">{show(entry.field, entry.from)}</span>
          <Icon name="arrowRight" size={16} />
          <span class="chip new">{show(entry.field, entry.to)}</span>
          {#if change}<span class="delta">{change}</span>{/if}
        </div>
      {/if}
    </li>
  {/each}
</ul>

<style>
  .diff {
    list-style: none;
    margin: 0;
    padding: 0;
    display: flex;
    flex-direction: column;
  }
  li {
    display: grid;
    grid-template-columns: minmax(0, 14rem) minmax(0, 1fr);
    gap: var(--space-1) var(--space-4);
    align-items: center;
    padding: var(--space-2) 0;
    border-bottom: 1px solid var(--border);
  }
  li:last-child {
    border-bottom: none;
  }
  .name {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 0.35rem;
    font-weight: var(--fw-semibold);
  }
  .tag {
    padding: 0 0.45rem;
    border-radius: var(--radius-pill);
    background: var(--surface-2);
    color: var(--muted);
    font-size: var(--fs-caption);
    font-weight: var(--fw-medium);
  }
  .values {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 0.35rem;
    min-width: 0;
  }
  .values :global(.icon) {
    color: var(--muted);
  }
  .chip {
    padding: 0.1rem 0.55rem;
    border-radius: var(--radius-sm);
    font-variant-numeric: tabular-nums;
    overflow-wrap: anywhere;
  }
  .chip.old {
    background: var(--surface-2);
    color: var(--muted);
    text-decoration: line-through;
    text-decoration-color: color-mix(in srgb, var(--muted) 50%, transparent);
  }
  .chip.new {
    background: var(--status-manual-bg);
    color: var(--status-manual);
    font-weight: var(--fw-bold);
  }
  .delta {
    font-size: var(--fs-caption);
    font-weight: var(--fw-bold);
    color: var(--muted);
  }
  .visual {
    min-width: 0;
    max-width: 26rem;
  }
  .visual .caption {
    display: flex;
    align-items: center;
    gap: 0.35rem;
    margin: 0.15rem 0 0;
  }
  .bars {
    display: grid;
    gap: 0.15rem;
  }
  .key {
    display: inline-block;
    width: 16px;
    height: 0;
    border-top: 2px dashed var(--muted);
  }
  .key.new {
    border-top: 2.5px solid var(--accent);
    margin-left: var(--space-2);
  }
  @media (--narrow) {
    li {
      grid-template-columns: minmax(0, 1fr) auto;
      gap: var(--space-1) var(--space-2);
    }
    li.pictured {
      grid-template-columns: minmax(0, 1fr);
    }
    .values {
      justify-content: flex-end;
    }
    .delta {
      width: 100%;
      text-align: right;
    }
  }
</style>
