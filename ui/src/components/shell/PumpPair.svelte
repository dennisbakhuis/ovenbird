<!--
  PumpPair: what ovenbird would send next to what the pump has, at equal weight, for every state
  in which ovenbird does not send ("would send 29 °C · pump has 31 °C").

  Props: wouldSend, pumpHas (°C | null), testid.
-->
<script lang="ts">
  import { celsius } from '$lib/core/controlText';
  import { settings, t } from '$lib/core/settings.svelte';

  let {
    wouldSend,
    pumpHas,
    testid = 'pump-pair',
  }: { wouldSend: number | null; pumpHas: number | null; testid?: string } = $props();

  const show = (value: number | null) => (value === null ? '–' : celsius(value, settings.language));
</script>

<span class="pair" data-testid={testid}>
  <span class="half" data-testid="{testid}-would">
    <span class="label">{t('controlWouldSend')}</span>
    <strong>{show(wouldSend)}</strong>
  </span>
  <span class="half" data-testid="{testid}-has">
    <span class="label">{t('controlPumpHas')}</span>
    <strong>{show(pumpHas)}</strong>
  </span>
</span>

<style>
  .pair {
    display: inline-flex;
    flex-wrap: wrap;
    align-items: baseline;
    gap: 0 var(--space-3);
  }
  .half {
    display: inline-flex;
    align-items: baseline;
    gap: 0.3rem;
    white-space: nowrap;
  }
  .label {
    color: inherit;
  }
  strong {
    font-variant-numeric: tabular-nums;
  }
</style>
