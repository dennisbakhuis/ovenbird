<!--
  Field: one schema-driven setting. Label and control on one line (stacked for wide controls and
  on phones for lists), help, default/preset and reset behind a `Why` button, a changed dot with
  an undo button, errors and warnings inline. Locked fields show a padlock and their variable.
  Numbers use the UI language's decimal separator and accept both point and comma. Retention
  fields add a "Keep forever" checkbox that stores 0.
-->
<script lang="ts" module>
  import Button from '$ui/Button.svelte';
  export interface EditorApi {
    value: unknown;
    set: (value: unknown) => void;
    disabled: boolean;
    invalid: boolean;
  }
</script>

<script lang="ts">
  import type { Snippet } from 'svelte';
  import type { Availability } from '$lib/core/cfg.svelte';
  import { type DraftStore, sameValue } from '$lib/core/draft.svelte';
  import { formatInputNumber, formatValue, parseInputNumber } from '$lib/core/fieldFormat';
  import { issueText } from '$lib/settings/issues';
  import { checkField, displayUnit, fromDisplay, toDisplay } from '$lib/core/schema';
  import { settings, t, tOpt } from '$lib/core/settings.svelte';
  import type { ConfigDoc, ConfigSchema, ConfigSignals, ValidationIssue } from '$lib/core/types';
  import Checkbox from '$ui/Checkbox.svelte';
  import Icon from '$ui/Icon.svelte';
  import InlineMessage from '$ui/InlineMessage.svelte';
  import Select from '$ui/Select.svelte';
  import Switch from '$ui/Switch.svelte';
  import TextInput from '$ui/TextInput.svelte';
  import SignalPicker from './SignalPicker.svelte';
  import { sameDeviceFirst } from '$lib/settings/ha';
  import Why from '$ui/Why.svelte';

  interface Props {
    id: string;
    schema: ConfigSchema;
    config: ConfigDoc | null;
    draft: DraftStore;
    signals?: ConfigSignals | null;
    signalsState?: Availability;
    errors?: ValidationIssue[];
    warnings?: ValidationIssue[];
    editor?: Snippet<[EditorApi]>;
    hideHelp?: boolean;
    hideLabel?: boolean;
    wide?: boolean;
    helpTarget?: string;
  }

  let {
    id,
    schema,
    config,
    draft,
    signals = null,
    signalsState = 'unknown',
    errors = [],
    warnings = [],
    editor,
    hideHelp = false,
    hideLabel = false,
    wide = false,
    helpTarget,
  }: Props = $props();

  const def = $derived(schema.fields[id]);
  const known = $derived(config?.fields[id]);
  const locale = $derived(settings.language);
  const inputId = $derived(`field-${id}`);
  const locked = $derived(known?.locked === true);
  const value = $derived(draft.value(id, config));
  const changed = $derived(draft.has(id));
  const words = $derived({
    on: t('on'),
    off: t('off'),
    none: t('fieldNone'),
    forever: t('retentionForeverValue'),
  });
  const check = $derived(def && !locked ? checkField(schema, id, value, config) : null);
  const unit = $derived(def ? displayUnit(def) : '');
  const label = $derived(tOpt(`cfg.${id}.label`) ?? id);
  const help = $derived(tOpt(`cfg.${id}.help`) ?? '');
  const defaultText = $derived(def ? formatValue(def, known?.default, locale, words) : '');
  const activeText = $derived(def ? formatValue(def, known?.value, locale, words) : '');
  const atDefault = $derived(known === undefined || sameValue(value, known.default));
  const retention = $derived(def?.type === 'retention');
  const numeric = $derived(def?.type === 'number' || def?.type === 'integer' || retention);
  const forever = $derived(retention && (value === null || value === undefined || value === 0));
  const inline = $derived(!wide && (numeric || def?.type === 'boolean'));
  const roomSignal = $derived.by(() => {
    const room = draft.value('control_room_signal', config);
    return typeof room === 'string' ? room : null;
  });
  const outsideMaxAgeS = $derived.by(() => {
    const age = draft.value('control_outside_max_age_s', config);
    return typeof age === 'number' && age > 0 ? age : undefined;
  });
  const roomDevice = $derived(
    signals?.room.find((c) => c.signal === roomSignal)?.device_id ?? null,
  );
  const candidates = $derived.by(() => {
    if (!signals) return null;
    if (
      id === 'control_room_signal' ||
      id === 'control_stove_reference_signal' ||
      id === 'control_outside_signal'
    )
      return signals.room;
    if (id === 'control_room_liveness_signals')
      return sameDeviceFirst(signals.liveness, signals.room, roomSignal);
    return signals.crosscheck;
  });

  let text = $state('');
  let focused = $state(false);

  $effect(() => {
    if (def && numeric && !focused) {
      text = typeof value === 'number' ? formatInputNumber(toDisplay(def, value), locale) : '';
    }
  });

  const describe = (
    issue: Pick<ValidationIssue, 'code' | 'message'> & Partial<Pick<ValidationIssue, 'params'>>,
  ) => issueText(issue, def, tOpt);
  const clientDescribe = (code: string) => describe({ code, message: '' });

  const clientErrors = $derived(check?.error ? [clientDescribe(check.error)] : []);
  const clientWarnings = $derived(check?.warning ? [clientDescribe(check.warning)] : []);
  const serverErrors = $derived(clientErrors.length > 0 ? [] : errors.map(describe));
  const serverWarnings = $derived(warnings.filter((e) => e.code !== check?.warning).map(describe));
  const allErrors = $derived([...new Set([...clientErrors, ...serverErrors])]);
  const allWarnings = $derived([...new Set([...clientWarnings, ...serverWarnings])]);
  const hasWhy = $derived(!hideHelp || locked || (known !== undefined && !atDefault));

  function set(next: unknown): void {
    draft.set(id, next, config);
  }

  function onNumber(event: Event): void {
    if (!def) return;
    text = (event.currentTarget as HTMLInputElement).value;
    if (text.trim() === '') {
      if (def.nullable) draft.reset(id, config);
      return;
    }
    const parsed = parseInputNumber(text);
    if (parsed !== null) set(fromDisplay(def, parsed));
  }

  function setForever(on: boolean): void {
    if (on) return set(0);
    const fallback = known?.default;
    set(typeof fallback === 'number' && fallback > 0 ? fallback : (def?.soft_min ?? 365));
  }

  const lockNote = $derived(
    known?.source === 'env'
      ? t('lockedEnv', { env: def?.env ?? id })
      : known?.source === 'file'
        ? t('lockedFile', { env: def?.env ?? id })
        : t('lockedInstall', { env: def?.env ?? id }),
  );
</script>

{#if def}
  <div
    class="field"
    class:inline
    class:changed
    class:locked
    class:invalid={allErrors.length > 0}
    data-testid="field-{id}"
    data-help={helpTarget}
  >
    <div class="head" class:hidden-label={hideLabel} class:empty={hideLabel && !changed && !hasWhy}>
      <label for={inputId}>
        {#if locked}<Icon name="lock" size={16} />{/if}
        <span>{label}</span>
      </label>
      {#if changed}
        <span class="dot" data-testid="changed-chip" title={t('fieldChanged')}>
          <span class="visually-hidden">{t('fieldChanged')}</span>
        </span>
        {#if hideLabel}<span class="changed-word" aria-hidden="true">{t('fieldChanged')}</span>{/if}
      {/if}
      {#if hasWhy}
        <Why title={label} ariaLabel={t('fieldWhy', { label })} testid="why-{id}">
          {#if help && !hideHelp}<p>{help}</p>{/if}
          {#if locked}
            <p class="lock-full">{lockNote}</p>
          {:else if known}
            <p class="preset" data-testid="field-default-{id}">
              {def.preset_default
                ? t('fieldPresetValue', { value: defaultText })
                : t('fieldDefaultValue', { value: defaultText })}
              {#if atDefault && def.preset_default}{t('fieldIsPreset')}{/if}
            </p>
            {#if !atDefault}
              <Button
                class="field-reset"
                onclick={() => draft.reset(id, config)}
                data-testid="reset-{id}"
              >
                <Icon name="undo" size={16} />
                {def.preset_default ? t('fieldResetPreset') : t('fieldResetDefault')}
              </Button>
            {/if}
          {/if}
        </Why>
      {/if}
      {#if changed}
        <Button
          variant="icon"
          size="sm"
          class="field-undo"
          onclick={() => draft.revert(id, config)}
          aria-label={t('fieldUndo', { label, value: activeText })}
          title={t('fieldUndo', { label, value: activeText })}
          data-testid="undo-{id}"
        >
          <Icon name="undo" size={18} />
          {#if hideLabel}<span>{t('fieldUndoShort')}</span>{/if}
        </Button>
      {/if}
    </div>

    <div class="control">
      {#if editor}
        {@render editor({
          value,
          set,
          disabled: locked,
          invalid: allErrors.length > 0,
        })}
      {:else if def.type === 'boolean'}
        <Switch
          id={inputId}
          checked={value === true}
          disabled={locked}
          state={value === true ? t('on') : t('off')}
          onchange={(e) => set(e.currentTarget.checked)}
        />
      {:else if retention}
        <span class="retention">
          {#if !forever}
            <TextInput
              id={inputId}
              type="text"
              inputmode="numeric"
              autocomplete="off"
              value={text}
              disabled={locked}
              invalid={allErrors.length > 0}
              framed
              {unit}
              align="end"
              width="7.5rem"
              onfocus={() => (focused = true)}
              onblur={() => (focused = false)}
              oninput={onNumber}
            />
          {/if}
          <Checkbox
            id={forever ? inputId : undefined}
            checked={forever}
            disabled={locked}
            label={t('retentionForever')}
            data-testid="forever-{id}"
            onchange={(e) => setForever(e.currentTarget.checked)}
          />
        </span>
      {:else if numeric}
        <TextInput
          id={inputId}
          type="text"
          inputmode="decimal"
          autocomplete="off"
          value={text}
          disabled={locked}
          invalid={allErrors.length > 0}
          framed
          {unit}
          align="end"
          width="9.5rem"
          onfocus={() => (focused = true)}
          onblur={() => (focused = false)}
          oninput={onNumber}
          placeholder={def.nullable && value === null
            ? def.preset_default
              ? t('fieldPreset')
              : t('fieldNotSet')
            : undefined}
        />
      {:else if def.type === 'enum'}
        <Select
          id={inputId}
          value={String(value ?? '')}
          disabled={locked}
          invalid={allErrors.length > 0}
          onchange={(e) =>
            e.currentTarget.value === '' ? draft.reset(id, config) : set(e.currentTarget.value)}
        >
          {#if def.nullable}<option value="">{t('fieldNotSet')}</option>{/if}
          {#each def.options ?? [] as option (option)}
            <option value={option}>{tOpt(`cfg.${id}.opt.${option}`) ?? option}</option>
          {/each}
        </Select>
      {:else if def.type === 'signal'}
        <SignalPicker
          id={inputId}
          {candidates}
          state={signalsState}
          value={typeof value === 'string' ? value : null}
          hideReading={id === 'control_room_signal' && value === config?.fields[id]?.value}
          freshS={id === 'control_outside_signal' ? outsideMaxAgeS : undefined}
          disabled={locked}
          onchange={(v) => (v === null ? draft.reset(id, config) : set(v))}
        />
      {:else if def.type === 'signal_list'}
        <SignalPicker
          id={inputId}
          {candidates}
          state={signalsState}
          multiple
          device={roomDevice}
          values={Array.isArray(value) ? (value as string[]) : []}
          disabled={locked}
          onchangeMany={(v) => set(v)}
        />
      {:else}
        <TextInput
          id={inputId}
          type="text"
          value={String(value ?? '')}
          disabled={locked}
          onchange={(e) => set(e.currentTarget.value)}
        />
      {/if}
    </div>

    {#if locked || allErrors.length > 0 || allWarnings.length > 0}
      <div class="notes">
        {#if locked}
          <p class="lock-note" data-testid="locked-note">
            {t('lockedShort', { env: def.env ?? id })}
          </p>
        {:else}
          {#each allErrors as message (message)}
            <InlineMessage tone="error" icon class="field-issue">{message}</InlineMessage>
          {/each}
          {#each allWarnings as message (message)}
            <InlineMessage tone="warn" icon testid="soft-warning" class="field-issue"
              >{message}</InlineMessage
            >
          {/each}
        {/if}
      </div>
    {/if}
  </div>
{/if}

<style>
  .retention {
    display: inline-flex;
    flex-wrap: wrap;
    align-items: center;
    justify-content: flex-end;
    gap: var(--space-2) var(--space-3);
  }
  :global(.field-issue) {
    margin: var(--space-1) 0 0;
  }
  .field {
    display: grid;
    grid-template-columns: minmax(0, 1fr);
    gap: var(--space-1) var(--space-4);
    padding: var(--space-3) 0;
    border-bottom: 1px solid var(--border);
    position: relative;
  }
  .field:last-child {
    border-bottom: none;
  }
  .field:first-child {
    padding-top: 0;
  }
  .head.empty {
    display: none;
  }
  .field.inline {
    grid-template-columns: minmax(0, 1fr) auto;
    align-items: center;
  }
  .head {
    display: flex;
    align-items: center;
    gap: 0.35rem;
    min-width: 0;
  }
  .head.hidden-label label {
    position: absolute;
    width: 1px;
    height: 1px;
    overflow: hidden;
    clip: rect(0 0 0 0);
  }
  .head label {
    display: inline-flex;
    align-items: center;
    gap: 0.35rem;
    font-weight: var(--fw-semibold);
    min-width: 0;
  }
  .head label :global(.icon) {
    color: var(--muted);
    flex: none;
  }
  .dot {
    width: 8px;
    height: 8px;
    border-radius: 50%;
    background: var(--accent);
    flex: none;
  }
  .changed-word {
    color: var(--accent);
    font-size: var(--fs-caption);
    font-weight: var(--fw-semibold);
  }
  .hidden-label :global(.field-undo) {
    width: auto;
    gap: var(--space-1);
    padding: 0 0.4rem;
    font-size: var(--fs-caption);
  }
  :global(.field-undo) {
    color: var(--accent);
  }
  @media (--narrow), (pointer: coarse) {
    :global(.field-undo) {
      width: var(--tap);
      height: var(--tap);
    }
  }
  .control {
    min-width: 0;
  }
  .inline .control {
    justify-self: end;
  }
  .notes {
    grid-column: 1 / -1;
    min-width: 0;
  }
  p {
    margin: var(--space-1) 0 0;
  }
  .lock-note {
    font-size: var(--fs-caption);
    color: var(--muted);
    overflow-wrap: anywhere;
  }
  .preset {
    color: var(--muted);
  }
  :global(.field-reset) {
    display: inline-flex;
    align-items: center;
    gap: 0.35rem;
    margin-top: var(--space-2);
  }
  @container main (min-width: 52rem) {
    .field.inline {
      grid-template-columns: minmax(12rem, 24rem) auto;
      justify-content: start;
    }
    .inline .control {
      justify-self: start;
    }
  }
</style>
