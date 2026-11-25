<!--
  Stepper: − value + with a typed input. `step` per click or arrow key; `fineStep` with Shift
  (e.g. 1 K by default, 0.5 K with Shift). Values are shown with the UI language's decimal
  separator and accept both point and comma. size 'lg' is the large comfort-target variant.
-->
<script lang="ts">
  import { formatInputNumber, parseInputNumber } from '$lib/core/fieldFormat';
  import { settings, t } from '$lib/core/settings.svelte';
  import Button from './Button.svelte';
  import Icon from './Icon.svelte';

  interface Props {
    id?: string;
    value: number;
    step: number;
    fineStep?: number;
    min?: number;
    max?: number;
    label: string;
    unit?: string;
    size?: 'md' | 'lg';
    disabled?: boolean;
    invalid?: boolean;
    onchange: (value: number) => void;
    testid?: string;
  }

  let {
    id,
    value,
    step,
    fineStep,
    min,
    max,
    label,
    unit,
    size = 'md',
    disabled = false,
    invalid = false,
    onchange,
    testid,
  }: Props = $props();

  const locale = $derived(settings.language);
  const clamp = (v: number) => Math.min(Math.max(v, min ?? -Infinity), max ?? Infinity);
  const round = (v: number) => Math.round(v * 1000) / 1000;
  const shown = $derived(formatInputNumber(value, locale));

  function nudge(direction: 1 | -1, fine: boolean): void {
    const size = fine && fineStep ? fineStep : step;
    const snapped = Math.round(value / size) * size;
    const base =
      Math.abs(snapped - value) < 1e-9
        ? value
        : direction > 0
          ? Math.floor(value / size) * size
          : Math.ceil(value / size) * size;
    onchange(clamp(round(base + direction * size)));
  }

  function commit(input: HTMLInputElement): void {
    const parsed = parseInputNumber(input.value);
    if (parsed !== null) onchange(clamp(parsed));
    input.value = formatInputNumber(parsed === null ? value : clamp(parsed), locale);
  }

  function onkeydown(event: KeyboardEvent): void {
    if (event.key === 'ArrowUp' || event.key === 'ArrowDown') {
      event.preventDefault();
      nudge(event.key === 'ArrowUp' ? 1 : -1, event.shiftKey);
    } else if (event.key === 'Enter') {
      commit(event.currentTarget as HTMLInputElement);
    }
  }
</script>

<div class="stepper {size}" class:invalid data-testid={testid}>
  <Button
    class="stepper-btn"
    aria-label={t('stepperDecrease', { label })}
    disabled={disabled || (min !== undefined && value <= min)}
    onclick={(e) => nudge(-1, e.shiftKey)}
    data-testid={testid ? `${testid}-dec` : undefined}
    ><Icon name="minus" size={size === 'lg' ? 22 : 18} /></Button
  >
  <span class="box">
    <input
      {id}
      type="text"
      inputmode="decimal"
      autocomplete="off"
      aria-label={label}
      aria-invalid={invalid || undefined}
      value={shown}
      {disabled}
      onchange={(e) => commit(e.currentTarget)}
      {onkeydown}
    />
    {#if unit}<span class="unit" aria-hidden="true">{unit}</span>{/if}
  </span>
  <Button
    class="stepper-btn"
    aria-label={t('stepperIncrease', { label })}
    disabled={disabled || (max !== undefined && value >= max)}
    onclick={(e) => nudge(1, e.shiftKey)}
    data-testid={testid ? `${testid}-inc` : undefined}
    ><Icon name="plus" size={size === 'lg' ? 22 : 18} /></Button
  >
</div>

<style>
  .stepper {
    display: grid;
    grid-template-columns: var(--tap) minmax(3.5rem, 1fr) var(--tap);
    align-items: stretch;
    min-width: 0;
  }
  :global(.stepper-btn) {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    min-width: var(--tap);
    min-height: var(--tap);
    padding: 0;
    color: var(--text);
  }
  :global(.stepper-btn:first-child) {
    border-radius: var(--radius-control) 0 0 var(--radius-control);
  }
  :global(.stepper-btn:last-child) {
    border-radius: 0 var(--radius-control) var(--radius-control) 0;
  }
  .box {
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 0.15rem;
    min-width: 0;
    border: 1px solid var(--border);
    border-left: none;
    border-right: none;
    background: var(--surface);
  }
  .box:focus-within {
    outline: 3px solid var(--accent);
    outline-offset: -1px;
  }
  .invalid .box {
    border-color: var(--err-text);
  }
  input {
    width: 100%;
    min-width: 0;
    min-height: calc(var(--tap) - 2px);
    padding: 0 var(--space-1);
    border: none;
    background: transparent;
    color: var(--text);
    text-align: center;
    font-variant-numeric: tabular-nums;
  }
  input:focus-visible {
    outline: none;
  }
  .box:has(.unit) input {
    text-align: right;
    width: 4ch;
    flex: 1;
  }
  .unit {
    flex: 1;
    color: var(--muted);
    font-size: var(--fs-caption);
    white-space: nowrap;
  }
  input:disabled {
    color: var(--muted);
  }
  .lg {
    grid-template-columns: 3.25rem minmax(6rem, 1fr) 3.25rem;
  }
  .lg :global(.stepper-btn) {
    min-height: 3.25rem;
  }
  .lg input {
    min-height: calc(3.25rem - 2px);
    font-size: var(--fs-value);
    font-weight: var(--fw-bold);
  }
  .lg .unit {
    font-size: var(--fs-body);
  }
</style>
