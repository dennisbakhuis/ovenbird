<!--
  ComfortSheet: the comfort temperature one tap from Home. A large stepper in 0.1 °C steps; "Review
  change" puts the new value into the settings draft and opens the usual review (validate,
  preview, apply). Cancel leaves the draft as it was.

  Props: ctl (ControlStore), room (°C now | null), onclose.
-->
<script lang="ts">
  import Button from '$ui/Button.svelte';
  import { cfg } from '$lib/core/cfg.svelte';
  import type { ControlStore } from '$lib/core/control.svelte';
  import { draft } from '$lib/core/draft.svelte';
  import { formatNumber } from '$lib/core/format';
  import { reviewRequest } from '$lib/core/reviewRequest.svelte';
  import { settings, t } from '$lib/core/settings.svelte';
  import Modal from '$ui/Modal.svelte';
  import Stepper from '$ui/Stepper.svelte';

  let {
    ctl,
    room = null,
    onclose,
  }: { ctl: ControlStore; room?: number | null; onclose: () => void } = $props();

  const FIELD = 'control_comfort_c';
  $effect(() => {
    void cfg.loadSchema();
  });

  const def = $derived(cfg.schema?.fields[FIELD]);
  const active = $derived.by(() => {
    const value = ctl.config?.fields[FIELD]?.value;
    return typeof value === 'number' ? value : null;
  });
  const start = $derived.by(() => {
    const value = draft.value(FIELD, ctl.config);
    return typeof value === 'number' ? value : (active ?? 21);
  });
  let picked = $state<number | null>(null);
  const value = $derived(picked ?? start);
  const changed = $derived(active === null || Math.abs(value - active) > 1e-9);
  const locale = $derived(settings.language);

  function review(): void {
    draft.set(FIELD, value, ctl.config);
    reviewRequest.pending = true;
    onclose();
  }
</script>

<Modal title={t('comfortSheetTitle')} {onclose} testid="comfort-sheet">
  <p class="lead">{t('comfortSheetLead')}</p>
  <div class="stepper">
    <Stepper
      id="comfort-sheet-value"
      {value}
      step={def?.step ?? 0.1}
      min={def?.min ?? 5}
      max={def?.max ?? 30}
      label={t('comfortSheetTitle')}
      unit="°C"
      size="lg"
      onchange={(next) => (picked = next)}
      testid="comfort-sheet-stepper"
    />
  </div>
  <p class="caption" data-testid="comfort-sheet-now">
    {active !== null
      ? t('comfortSheetNow', { value: formatNumber(active, 1, locale) })
      : ''}{room !== null
      ? ` · ${t('comfortSheetRoom', { value: formatNumber(room, 1, locale) })}`
      : ''}
  </p>
  {#snippet footer()}
    <Button onclick={onclose}>{t('cancel')}</Button>
    <Button
      type="button"
      variant="primary"
      disabled={!changed}
      onclick={review}
      data-testid="comfort-sheet-review"
    >
      {t('comfortSheetReview')}
    </Button>
  {/snippet}
</Modal>

<style>
  .lead {
    margin: 0 0 var(--space-3);
  }
  .stepper {
    display: flex;
    justify-content: center;
    margin: var(--space-3) 0;
  }
  .caption {
    margin: 0;
    text-align: center;
    color: var(--muted);
  }
</style>
