<script lang="ts">
  import Select from '$ui/Select.svelte';
  import TextInput from '$ui/TextInput.svelte';
  import Button from '$ui/Button.svelte';
  import type { QuietWindow } from '$lib/core/fieldFormat';
  import { MAX_WINDOWS, overlapping } from '$lib/settings/quiet';
  import { t } from '$lib/core/settings.svelte';
  import QuietBar from './QuietBar.svelte';
  import Icon from '$ui/Icon.svelte';

  interface Props {
    windows: QuietWindow[];
    disabled?: boolean;
    max?: number;
    onchange: (windows: QuietWindow[]) => void;
  }

  let { windows, disabled = false, max = MAX_WINDOWS, onchange }: Props = $props();

  const overlaps = $derived(overlapping(windows));

  function update(index: number, patch: Partial<QuietWindow>): void {
    onchange(windows.map((w, i) => (i === index ? { ...w, ...patch } : w)));
  }
</script>

<div class="quiet" data-testid="quiet-editor">
  <QuietBar {windows} testid="quiet-bar" />

  {#each windows as w, i (i)}
    <div class="window" data-testid="quiet-window-{i}">
      <label>
        <span class="cap">{t('quietStart')}</span>
        <TextInput
          block={false}
          type="time"
          value={w.start}
          {disabled}
          onchange={(e) => update(i, { start: e.currentTarget.value })}
        />
      </label>
      <label>
        <span class="cap">{t('quietEnd')}</span>
        <TextInput
          block={false}
          type="time"
          value={w.end}
          {disabled}
          onchange={(e) => update(i, { end: e.currentTarget.value })}
        />
      </label>
      <label>
        <span class="cap">{t('quietLevel')}</span>
        <Select
          value={String(w.level)}
          {disabled}
          onchange={(e) => update(i, { level: Number(e.currentTarget.value) })}
        >
          {#each [1, 2, 3] as level (level)}
            <option value={String(level)}>{t('quietLevelOption', { level })}</option>
          {/each}
        </Select>
      </label>
      <Button
        {disabled}
        onclick={() => onchange(windows.filter((_, j) => j !== i))}
        aria-label={t('quietRemove', { n: i + 1 })}
        class="quiet-remove"
        title={t('quietRemove', { n: i + 1 })}
        data-testid="quiet-remove-{i}"><Icon name="close" size={18} /></Button
      >
      {#if overlaps.includes(i)}
        <p class="warn">{t('quietOverlap')}</p>
      {/if}
    </div>
  {/each}

  <Button
    disabled={disabled || windows.length >= max}
    onclick={() => onchange([...windows, { start: '22:00', end: '06:00', level: 1 }])}
    data-testid="quiet-add"
    class="quiet-add"
  >
    <Icon name="plus" size={18} />{t('quietAdd')}
  </Button>
  {#if windows.length === 0}<p class="muted">{t('quietEmpty')}</p>{/if}
</div>

<style>
  .quiet {
    display: flex;
    flex-direction: column;
    gap: var(--space-3);
    align-items: flex-start;
    min-width: 0;
    width: 100%;
  }
  .window {
    display: grid;
    grid-template-columns: minmax(0, 1fr) minmax(0, 1fr) minmax(0, 0.9fr) var(--tap);
    align-items: end;
    gap: var(--space-2) var(--space-2);
    width: 100%;
    padding: 0.6rem;
    border: 1px solid var(--border);
    border-radius: var(--radius-control);
  }
  label {
    display: flex;
    flex-direction: column;
    gap: 0.2rem;
  }
  .cap {
    font-size: var(--fs-sm);
    color: var(--muted);
  }
  :global(.quiet-remove) {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    min-width: var(--tap);
    min-height: var(--tap);
    padding: 0;
    color: var(--muted);
  }
  :global(.quiet-add) {
    display: inline-flex;
    align-items: center;
    gap: 0.35rem;
    min-height: var(--tap);
  }
  .warn {
    grid-column: 1 / -1;
    margin: 0;
    font-size: var(--fs-md);
    color: var(--warn-text);
    background: var(--warn-bg);
    padding: var(--space-1) var(--space-2);
    border-radius: var(--radius-sm);
  }
</style>
