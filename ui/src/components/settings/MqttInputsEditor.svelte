<!--
  MqttInputsEditor: the extra MQTT topics ovenbird reads as sensors (`mqtt_inputs`), one row per
  topic with an optional signal name, unit and plausible range. Rows are added and removed here;
  every edit goes into the settings draft, so the review and apply flow handles it like any other
  setting. Each row says the signal it will appear as in the sensor lists and its first problem:
  the editor's own check first, else the service's refusal for that row (a reserved topic or
  signal, a repeat, bad bounds).
  Numbers use the UI language's decimal separator and are taken when the field is left.
-->
<script lang="ts">
  import Button from '$ui/Button.svelte';
  import Icon from '$ui/Icon.svelte';
  import TextInput from '$ui/TextInput.svelte';
  import { formatInputNumber, parseInputNumber } from '$lib/core/fieldFormat';
  import { settings, t, tOpt } from '$lib/core/settings.svelte';
  import { issueText } from '$lib/settings/issues';
  import type { ValidationIssue } from '$lib/core/types';
  import {
    MAX_INPUTS,
    cleanInput,
    inputSignal,
    mqttInputProblems,
    type MqttInput,
  } from '$lib/settings/mqtt';

  interface Props {
    inputs: MqttInput[];
    disabled?: boolean;
    base?: string;
    errors?: ValidationIssue[];
    onchange: (inputs: MqttInput[]) => void;
  }

  let { inputs, disabled = false, base, errors = [], onchange }: Props = $props();

  const locale = $derived(settings.language);
  const problems = $derived(mqttInputProblems(inputs, base));
  const refusals = $derived(rowRefusals(errors));

  function rowRefusals(list: ValidationIssue[]): Record<number, ValidationIssue> {
    const out: Record<number, ValidationIssue> = {};
    for (const issue of list) {
      const path = issue.params?.['path'];
      const index = typeof path === 'string' ? Number(path.split('.')[0]) : NaN;
      if (Number.isInteger(index) && !(index in out)) out[index] = issue;
    }
    return out;
  }

  function update(index: number, patch: Partial<MqttInput>): void {
    onchange(inputs.map((row, i) => (i === index ? cleanInput({ ...row, ...patch }) : row)));
  }

  function number(index: number, key: 'minimum' | 'maximum', text: string): void {
    const value = parseInputNumber(text);
    update(index, { [key]: value });
  }

  function add(): void {
    onchange([...inputs, { topic: '' }]);
  }

  function remove(index: number): void {
    onchange(inputs.filter((_, i) => i !== index));
  }
</script>

<div class="inputs" data-testid="mqtt-inputs">
  {#if inputs.length === 0}
    <p class="muted none" data-testid="mqtt-inputs-none">{t('mqttInputNone')}</p>
  {/if}
  {#each inputs as row, i (i)}
    {@const problem = problems[i] ?? null}
    {@const refusal = problem === null ? refusals[i] : undefined}
    <fieldset
      class="row"
      class:bad={problem !== null || refusal !== undefined}
      data-testid="mqtt-input-{i}"
    >
      <legend class="visually-hidden">{t('mqttInputRow', { n: i + 1 })}</legend>
      <label class="topic">
        <span class="cap">{t('mqttInputTopic')}</span>
        <TextInput
          value={row.topic}
          {disabled}
          autocomplete="off"
          spellcheck={false}
          placeholder="garden/temperature"
          invalid={(problem !== null && problem.startsWith('topic')) ||
            refusal?.params?.['path'] === `${i}.topic`}
          oninput={(e) => update(i, { topic: e.currentTarget.value })}
          data-testid="mqtt-input-topic"
        />
      </label>
      <label class="signal">
        <span class="cap">{t('mqttInputSignal')}</span>
        <TextInput
          value={row.signal ?? ''}
          {disabled}
          autocomplete="off"
          spellcheck={false}
          placeholder={row.topic.trim() ? `mqtt/${row.topic.trim()}` : 'mqtt/…'}
          invalid={(problem !== null && problem.startsWith('signal')) ||
            refusal?.params?.['path'] === `${i}.signal`}
          oninput={(e) => update(i, { signal: e.currentTarget.value })}
          data-testid="mqtt-input-signal"
        />
      </label>
      <label class="short">
        <span class="cap">{t('mqttInputUnit')}</span>
        <TextInput
          value={row.unit ?? ''}
          {disabled}
          autocomplete="off"
          spellcheck={false}
          placeholder="°C"
          oninput={(e) => update(i, { unit: e.currentTarget.value })}
          data-testid="mqtt-input-unit"
        />
      </label>
      <label class="short">
        <span class="cap">{t('mqttInputMin')}</span>
        <TextInput
          value={formatInputNumber(row.minimum, locale)}
          {disabled}
          inputmode="decimal"
          autocomplete="off"
          invalid={problem === 'range' || refusal?.code === 'input_bounds'}
          onchange={(e) => number(i, 'minimum', e.currentTarget.value)}
          data-testid="mqtt-input-min"
        />
      </label>
      <label class="short">
        <span class="cap">{t('mqttInputMax')}</span>
        <TextInput
          value={formatInputNumber(row.maximum, locale)}
          {disabled}
          inputmode="decimal"
          autocomplete="off"
          invalid={problem === 'range' || refusal?.code === 'input_bounds'}
          onchange={(e) => number(i, 'maximum', e.currentTarget.value)}
          data-testid="mqtt-input-max"
        />
      </label>
      <Button
        variant="icon"
        class="remove"
        {disabled}
        aria-label={t('mqttInputRemove', {
          topic: row.topic.trim() || t('mqttInputRow', { n: i + 1 }),
        })}
        title={t('mqttInputRemove', { topic: row.topic.trim() || t('mqttInputRow', { n: i + 1 }) })}
        onclick={() => remove(i)}
        data-testid="mqtt-input-remove"
      >
        <Icon name="close" size={18} />
      </Button>
      <p class="caption" data-testid="mqtt-input-caption">
        {#if problem}
          <span class="error">{t(`check_mqtt_${problem}`)}</span>
        {:else if refusal}
          <span class="error" data-testid="mqtt-input-refusal"
            >{issueText(refusal, undefined, tOpt)}</span
          >
        {:else}
          <span class="muted"
            >{t('mqttInputSignalHint', { signal: inputSignal(row) })}{typeof row.minimum ===
              'number' || typeof row.maximum === 'number'
              ? ` · ${t('mqttInputRangeHint')}`
              : ''}</span
          >
        {/if}
      </p>
    </fieldset>
  {/each}
  <div>
    <Button
      type="button"
      icon="plus"
      iconSize={16}
      disabled={disabled || inputs.length >= MAX_INPUTS}
      onclick={add}
      data-testid="mqtt-input-add"
    >
      {t('mqttInputAdd')}
    </Button>
  </div>
</div>

<style>
  .inputs {
    display: flex;
    flex-direction: column;
    gap: var(--space-3);
  }
  .none {
    margin: 0;
  }
  .row {
    margin: 0;
    padding: var(--space-3);
    border: 1px solid var(--border);
    border-radius: var(--radius-sm);
    display: grid;
    grid-template-columns: repeat(3, minmax(0, 1fr)) auto;
    gap: var(--space-2) var(--space-3);
    align-items: end;
    min-width: 0;
  }
  .row.bad {
    border-color: var(--err-text);
  }
  .topic {
    grid-column: 1 / 4;
  }
  .signal {
    grid-column: 1 / -1;
  }
  label {
    display: flex;
    flex-direction: column;
    gap: var(--space-1);
    min-width: 0;
  }
  .cap {
    font-size: var(--fs-caption);
    color: var(--muted);
  }
  .row :global(.remove) {
    grid-column: 4;
    grid-row: 1;
    align-self: end;
  }
  .caption {
    grid-column: 1 / -1;
    margin: 0;
    font-size: var(--fs-caption);
    overflow-wrap: anywhere;
  }
  .error {
    color: var(--err-text);
  }
  @container main (min-width: 48rem) {
    .row {
      grid-template-columns:
        minmax(10rem, 2fr) minmax(8rem, 1.5fr) repeat(3, minmax(4.5rem, 0.7fr))
        auto;
    }
    .topic,
    .signal {
      grid-column: auto;
    }
    .row :global(.remove) {
      grid-column: auto;
      grid-row: auto;
    }
  }
</style>
