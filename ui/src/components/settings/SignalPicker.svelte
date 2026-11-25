<script lang="ts">
  import Checkbox from '$ui/Checkbox.svelte';
  import Select from '$ui/Select.svelte';
  import TextInput from '$ui/TextInput.svelte';
  import type { Availability } from '$lib/core/cfg.svelte';
  import { formatAge, formatNumber } from '$lib/core/format';
  import { settings, t, tOpt } from '$lib/core/settings.svelte';
  import { signalName } from '$lib/core/signalView';
  import type { SignalCandidate } from '$lib/core/types';
  import { onDevice } from '$lib/settings/ha';

  interface Props {
    id: string;
    candidates: SignalCandidate[] | null;
    state: Availability;
    value?: string | null;
    hideReading?: boolean;
    freshS?: number;
    values?: string[];
    multiple?: boolean;
    device?: string | null;
    disabled?: boolean;
    onchange?: (value: string | null) => void;
    onchangeMany?: (values: string[]) => void;
  }

  let {
    id,
    candidates,
    state,
    value = null,
    hideReading = false,
    freshS = 3600,
    values = [],
    multiple = false,
    device = null,
    disabled = false,
    onchange,
    onchangeMany,
  }: Props = $props();

  const locale = $derived(settings.language);
  const list = $derived(candidates ?? []);
  const selected = $derived(list.find((c) => c.signal === value));
  const known = $derived(new Set(list.map((c) => c.signal)));

  function reading(c: SignalCandidate): string {
    if (typeof c.value !== 'number') return '';
    return `${formatNumber(c.value, 1, locale)}${c.unit ? `\u202f${c.unit}` : ''}`;
  }

  const nameOf = (c: SignalCandidate): string => signalName(c.signal, c.name, tOpt);
  const idCaption = (c: SignalCandidate): string =>
    c.name && c.name.includes('/') && c.name !== c.signal ? `${c.signal} · ${c.name}` : c.signal;

  function label(c: SignalCandidate): string {
    const name = c.area ? `${nameOf(c)} · ${c.area}` : nameOf(c);
    const now = reading(c);
    return now ? `${name} — ${now}` : name;
  }

  const sameDevice = (c: SignalCandidate): boolean => onDevice(c, device);

  const fresh = (c: SignalCandidate) => c.held_s === null || c.held_s < freshS;

  function toggle(signal: string, on: boolean): void {
    const next = on ? [...values, signal] : values.filter((s) => s !== signal);
    onchangeMany?.(next);
  }
</script>

{#if candidates === null}
  <div class="fallback" data-testid="signal-fallback">
    {#if multiple}
      <TextInput
        {id}
        type="text"
        {disabled}
        value={values.join(', ')}
        onchange={(e) =>
          onchangeMany?.(
            e.currentTarget.value
              .split(',')
              .map((s) => s.trim())
              .filter(Boolean),
          )}
      />
    {:else}
      <TextInput
        {id}
        type="text"
        {disabled}
        value={value ?? ''}
        onchange={(e) => onchange?.(e.currentTarget.value.trim() || null)}
      />
    {/if}
    <p class="muted note">
      {state === 'forbidden'
        ? t('pickerForbidden')
        : state === 'missing'
          ? t('pickerMissing')
          : t('pickerUnavailable')}
    </p>
  </div>
{:else if multiple}
  <ul class="checks" {id} data-testid="signal-multi">
    {#each list as c (c.signal)}
      <li>
        <Checkbox
          class="signal-check"
          {disabled}
          checked={values.includes(c.signal)}
          onchange={(e) => toggle(c.signal, e.currentTarget.checked)}
        >
          <span class="opt">
            <span>{nameOf(c)}</span>
            {#if reading(c) || c.held_s !== null || c.area}
              <span class="muted small"
                >{reading(c)}{#if c.held_s !== null}
                  · {formatAge(c.held_s)}{/if}{#if c.area}
                  · {c.area}{/if}</span
              >
            {/if}
            {#if sameDevice(c)}
              <span class="small same" data-testid="signal-same-device"
                >{t('pickerSameDevice')}</span
              >
            {/if}
          </span>
        </Checkbox>
      </li>
    {/each}
    {#each values.filter((s) => !known.has(s)) as orphan (orphan)}
      <li>
        <Checkbox
          class="signal-check"
          {disabled}
          checked
          onchange={(e) => toggle(orphan, e.currentTarget.checked)}
        >
          <span>{orphan} <em class="muted">({t('pickerUnlisted')})</em></span>
        </Checkbox>
      </li>
    {/each}
    {#if list.length === 0 && values.length === 0}
      <li class="muted">{t('pickerNone')}</li>
    {/if}
  </ul>
{:else}
  <Select
    {id}
    {disabled}
    value={value ?? ''}
    onchange={(e) => onchange?.(e.currentTarget.value || null)}
    data-testid="signal-select"
  >
    <option value="">{t('pickerNone')}</option>
    {#each list as c (c.signal)}
      <option value={c.signal}>{label(c)}</option>
    {/each}
    {#if value && !selected}
      <option {value}>{value} ({t('pickerUnlisted')})</option>
    {/if}
  </Select>
  {#if value && !selected}
    <p class="note warn" role="status" data-testid="signal-unknown">
      {t('pickerUnknownWarn', { signal: value })}
    </p>
  {/if}
  {#if selected}
    <p class="live" data-testid="signal-live">
      {#if !hideReading}<span class="fresh" class:old={!fresh(selected)} aria-hidden="true"
        ></span>{/if}
      {#if !hideReading && reading(selected)}<strong>{reading(selected)}</strong>{/if}
      {#if !hideReading && selected.held_s !== null && selected.held_s !== undefined}
        <span class="muted">· {t('pickerHeld', { age: formatAge(selected.held_s) })}</span>
      {/if}
      <span class="muted id" data-testid="signal-id"
        >{t('pickerSignalId', { id: idCaption(selected) })}</span
      >
    </p>
  {/if}
{/if}

<style>
  .checks {
    list-style: none;
    margin: 0;
    padding: 0;
    display: flex;
    flex-direction: column;
    gap: var(--space-1);
  }
  .checks :global(.signal-check) {
    display: flex;
    align-items: center;
    gap: 0.6rem;
    min-height: 44px;
    overflow-wrap: anywhere;
  }
  .note,
  .live {
    margin: var(--space-1) 0 0;
    font-size: var(--fs-caption);
  }
  .live {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 0.1rem 0.4rem;
  }
  .live .id {
    overflow-wrap: anywhere;
  }
  @media (--narrow) {
    .live .id {
      display: none;
    }
  }
  .fresh {
    width: 8px;
    height: 8px;
    border-radius: 50%;
    background: var(--cat-normal);
  }
  .fresh.old {
    background: var(--cat-limited);
  }
  .warn {
    color: var(--status-limited);
    font-weight: var(--fw-semibold);
  }
  .opt {
    display: flex;
    flex-direction: column;
    min-width: 0;
  }
  .small {
    font-size: var(--fs-caption);
  }
  .same {
    color: var(--accent);
    font-weight: var(--fw-semibold);
  }
</style>
