<!--
  ExcludedDaysEditor: the days the learner leaves out of the fit (`house_learn_excluded_days`).
  A date field with an Add button and the days as removable chips, oldest first. The list is
  handed back sorted and without repeats; a day more than a day ahead or beyond the limit is
  refused with a sentence. Edits go into the settings draft through `onchange`.

  Props: days, onchange, disabled, invalid, max.
-->
<script lang="ts">
  import Button from '$ui/Button.svelte';
  import InlineMessage from '$ui/InlineMessage.svelte';
  import Pill from '$ui/Pill.svelte';
  import TextInput from '$ui/TextInput.svelte';
  import { clockNow } from '$lib/core/format';
  import { settings, t } from '$lib/core/settings.svelte';
  import {
    MAX_EXCLUDED_DAYS,
    addDay,
    cleanDays,
    dayLabel,
    latestDay,
    type AddRefusal,
  } from '$lib/house/settings';

  interface Props {
    days: unknown;
    onchange: (days: string[]) => void;
    disabled?: boolean;
    invalid?: boolean;
    max?: number;
  }

  let {
    days,
    onchange,
    disabled = false,
    invalid = false,
    max = MAX_EXCLUDED_DAYS,
  }: Props = $props();

  const list = $derived(cleanDays(days));
  const lang = $derived(settings.language);
  const full = $derived(list.length >= max);
  let picked = $state('');
  let refusal = $state<AddRefusal | null>(null);

  const REFUSAL_KEYS = {
    invalid: 'check_date_format',
    future: 'houseDaysFuture',
    full: 'houseDaysFull',
  } as const;

  function add(): void {
    if (picked === '') return;
    const next = addDay(list, picked, clockNow(), max);
    refusal = next.refusal;
    if (next.refusal === null) {
      picked = '';
      if (next.days !== list) onchange(next.days);
    }
  }

  function remove(day: string): void {
    refusal = null;
    onchange(list.filter((d) => d !== day));
  }
</script>

<div class="days" data-testid="excluded-days-editor">
  <p class="why">{t('houseDaysWhy')}</p>
  <div class="add">
    <TextInput
      type="date"
      value={picked}
      max={latestDay(clockNow())}
      disabled={disabled || full}
      {invalid}
      block={false}
      aria-label={t('houseDaysDate')}
      data-testid="excluded-day-input"
      oninput={(event) => {
        picked = event.currentTarget.value;
        refusal = null;
      }}
    />
    <Button
      onclick={add}
      disabled={disabled || full || picked === ''}
      data-testid="excluded-day-add"
    >
      {t('houseDaysAdd')}
    </Button>
  </div>
  {#if refusal}
    <InlineMessage tone="error" icon>{t(REFUSAL_KEYS[refusal])}</InlineMessage>
  {:else if full}
    <InlineMessage tone="warn" icon>{t('houseDaysFull')}</InlineMessage>
  {/if}
  {#if list.length === 0}
    <p class="muted none" data-testid="excluded-days-none">{t('houseDaysNone')}</p>
  {:else}
    <ul
      class="chips"
      data-testid="excluded-days-list"
      aria-label={t('houseDaysCount', { n: list.length, max })}
    >
      {#each list as day (day)}
        <li>
          <Pill
            tone="neutral"
            size="md"
            removable={!disabled}
            onremove={() => remove(day)}
            removeLabel={t('houseDaysRemove', { day: dayLabel(day, lang) })}
            testid="excluded-chip-{day}"
          >
            {dayLabel(day, lang)}
          </Pill>
        </li>
      {/each}
    </ul>
    <p class="caption muted">{t('houseDaysCount', { n: list.length, max })}</p>
  {/if}
</div>

<style>
  .days {
    display: grid;
    gap: var(--space-2);
    min-width: 0;
  }
  p {
    margin: 0;
  }
  .add {
    display: flex;
    flex-wrap: wrap;
    gap: var(--space-2);
    align-items: center;
  }
  .chips {
    list-style: none;
    margin: 0;
    padding: 0;
    display: flex;
    flex-wrap: wrap;
    gap: var(--space-2);
  }
</style>
