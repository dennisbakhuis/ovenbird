<script lang="ts">
  import Card from '$ui/Card.svelte';
  import Select from '$ui/Select.svelte';
  import Button from '$ui/Button.svelte';
  import Field from '$components/settings/Field.svelte';
  import QuietScheduleEditor from '$components/settings/QuietScheduleEditor.svelte';
  import { cfg } from '$lib/core/cfg.svelte';
  import { draft } from '$lib/core/draft.svelte';
  import { asWindows } from '$lib/core/fieldFormat';
  import { clockNow } from '$lib/core/format';
  import { settings, t } from '$lib/core/settings.svelte';
  import { browserZone, clockIn, timeZones } from '$lib/core/timezones';
  import type { ConfigDoc, ConfigSchema } from '$lib/core/types';

  interface Props {
    schema: ConfigSchema;
    config: ConfigDoc;
  }

  let { schema, config }: Props = $props();
  const windows = $derived(asWindows(draft.value('control_quiet_windows', config)) ?? []);

  const ZONE = 'control_timezone';
  const browser = browserZone();
  const zoneValue = $derived.by(() => {
    const value = draft.value(ZONE, config);
    return typeof value === 'string' && value !== '' ? value : null;
  });
  const zone = $derived(zoneValue ?? browser ?? 'UTC');
  const zones = $derived(timeZones(zoneValue));
  let now = $state(clockNow());
  $effect(() => {
    const timer = setInterval(() => (now = clockNow()), 15_000);
    return () => clearInterval(timer);
  });
  const nowText = $derived(clockIn(now, zone, settings.language));
  const differs = $derived(browser !== null && zoneValue !== null && zoneValue !== browser);
</script>

<Card bare as="div">
  <Field
    id="control_quiet_windows"
    {schema}
    {config}
    {draft}
    wide
    helpTarget="settings/quiet.windows"
    errors={cfg.validation?.errors.filter((e) => e.field === 'control_quiet_windows') ?? []}
    warnings={cfg.validation?.warnings.filter((e) => e.field === 'control_quiet_windows') ?? []}
  >
    {#snippet editor(api)}
      <QuietScheduleEditor
        {windows}
        max={schema.fields['control_quiet_windows']?.max_items}
        disabled={api.disabled}
        onchange={(next) => api.set(next)}
      />
    {/snippet}
  </Field>
  {#if nowText}
    <p class="now" data-testid="quiet-now">{t('quietNowIn', { time: nowText, zone })}</p>
  {/if}
  <Field
    id={ZONE}
    {schema}
    {config}
    {draft}
    helpTarget="settings/quiet.timezone"
    errors={cfg.validation?.errors.filter((e) => e.field === ZONE) ?? []}
    warnings={cfg.validation?.warnings.filter((e) => e.field === ZONE) ?? []}
  >
    {#snippet editor(api)}
      <Select
        block={false}
        id="field-{ZONE}"
        value={zone}
        disabled={api.disabled}
        aria-invalid={api.invalid}
        onchange={(event) => api.set(event.currentTarget.value)}
        data-testid="quiet-timezone"
      >
        {#each zones as option (option)}<option value={option}>{option}</option>{/each}
      </Select>
    {/snippet}
  </Field>
  {#if differs && browser}
    <div class="differs" role="status" data-testid="quiet-zone-differs">
      <span>{t('quietZoneDiffers', { browser })}</span>
      <Button onclick={() => draft.set(ZONE, browser, config)} data-testid="quiet-use-browser"
        >{t('quietUseZone', { zone: browser })}</Button
      >
    </div>
  {/if}
</Card>

<style>
  .now {
    margin: var(--space-2) 0;
    color: var(--muted);
    font-size: var(--fs-body);
  }
  .differs {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: var(--space-2) var(--space-3);
    margin-top: var(--space-2);
    padding: var(--space-2) var(--space-3);
    border: 1px solid var(--status-limited);
    border-radius: var(--radius);
    background: var(--status-limited-bg);
  }
</style>
