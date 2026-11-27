<!--
  GateReasons: why one of the model's three gates does not pass, one plain sentence per need code
  (and, for the heat-loss gate while it misses heating weather, a small progress display from the
  excitation counts). Nothing for a gate that passes.

  Props: house (HouseInsight), gate (heat_loss, dynamics or sun), progress (also show the progress
  bars), progressOnly (show only the progress bars, for a place where the reasons stand right
  above).
  A11y: every progress bar is a role="progressbar" with its sentence as the label; the numbers
  are printed, colour is not needed.
-->
<script lang="ts">
  import { formatNumber } from '$lib/core/format';
  import type { GateName, HouseInsight } from '$lib/house/house';
  import { excitationProgress, gateReasons, progressShare } from '$lib/house/trust';
  import { settings, t } from '$lib/core/settings.svelte';

  interface Props {
    house: HouseInsight;
    gate: GateName;
    progress?: boolean;
    progressOnly?: boolean;
    limit?: number;
  }

  let { house, gate, progress = false, progressOnly = false, limit = 99 }: Props = $props();

  const lang = $derived(settings.language);
  const num = (value: number, digits = 1) => formatNumber(value, digits, lang);
  const model = $derived(house.gates?.[gate]);
  const reasons = $derived(gateReasons(model, t, num, house));
  const bars = $derived(
    (progress || progressOnly) &&
      gate === 'heat_loss' &&
      model?.needed.some((code) => code.startsWith('more_'))
      ? excitationProgress(house.excitation)
      : [],
  );
</script>

{#if reasons.length > 0}
  <div class="reasons" data-testid="house-gate-reasons-{gate}">
    {#if !progressOnly}
      {#each reasons.slice(0, limit) as reason, i (i)}
        <p data-testid="house-gate-need-{model?.needed[i] ?? 'plain'}">{reason}</p>
      {/each}
    {/if}
    {#if bars.length > 0}
      <ul class="progress" aria-label={t('houseProgressLabel')} data-testid="house-trust-progress">
        {#each bars as item (item.kind)}
          {@const label = t(`houseProgress_${item.kind}`, {
            have: num(item.have, item.kind === 'heating_days' ? 0 : 1),
            need: num(item.need, item.kind === 'heating_days' ? 0 : 1),
          })}
          <li>
            <span class="caption">{label}</span>
            <span
              class="bar"
              role="progressbar"
              aria-label={label}
              aria-valuemin="0"
              aria-valuemax={item.need}
              aria-valuenow={item.have}
              data-testid="house-trust-bar-{item.kind}"
            >
              <span class="fill" style:width="{progressShare(item) * 100}%"></span>
            </span>
          </li>
        {/each}
      </ul>
    {/if}
  </div>
{/if}

<style>
  .reasons {
    display: grid;
    gap: var(--space-2);
  }
  p {
    margin: 0;
  }
  .progress {
    list-style: none;
    margin: 0;
    padding: 0;
    display: grid;
    gap: var(--space-2);
  }
  .progress li {
    display: grid;
    gap: var(--space-1);
  }
  .bar {
    display: block;
    height: 0.5rem;
    border-radius: var(--radius-pill);
    background: var(--surface-2);
    border: 1px solid var(--border);
    overflow: hidden;
  }
  .fill {
    display: block;
    height: 100%;
    background: var(--accent);
  }
</style>
