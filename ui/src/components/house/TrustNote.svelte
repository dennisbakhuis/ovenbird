<!--
  TrustNote: "What the model can be trusted for", three compact rows, one per gate: heat loss
  (insulation score, curve proposal, what-if), room dynamics (cool-down prediction) and sun
  response (the controller's model plan). Each row says trusted or not yet, what it guards and,
  when it does not pass, the plain reasons from the gate's need codes. A model from an older
  version says so and that the next run checks it. GateDetails lists how every check came out.

  Props: house (HouseInsight).
-->
<script lang="ts">
  import type { HouseInsight } from '$lib/house/house';
  import { GATE_USES, gateRows } from '$lib/house/trust';
  import { t } from '$lib/core/settings.svelte';
  import Card from '$ui/Card.svelte';
  import Pill from '$ui/Pill.svelte';
  import GateReasons from './GateReasons.svelte';

  let { house }: { house: HouseInsight } = $props();

  const rows = $derived(gateRows(house.gates));
</script>

{#if rows.length > 0}
  <Card title={t('houseGatesTitle')} icon="check" testid="house-trust" help="house.trust" span={12}>
    <ul class="gates">
      {#each rows as row (row.name)}
        <li data-testid="house-gate-{row.name}" data-ok={row.ok} data-source={row.source}>
          <div class="head">
            <strong>{t(`houseGateName_${row.name}`)}</strong>
            <Pill tone={row.ok ? 'good' : 'warn'} testid="house-gate-pill-{row.name}">
              {row.ok ? t('houseGateOk') : t('houseGateNotYet')}
            </Pill>
          </div>
          <p class="caption uses">{t(GATE_USES[row.name])}</p>
          <GateReasons {house} gate={row.name} />
        </li>
      {/each}
    </ul>
  </Card>
{/if}

<style>
  .gates {
    list-style: none;
    margin: 0;
    padding: 0;
    display: grid;
    gap: var(--space-2);
  }
  .gates li {
    display: grid;
    gap: 0;
    padding-top: var(--space-2);
    border-top: 1px solid var(--border);
  }
  .gates li:first-child {
    border-top: none;
    padding-top: 0;
  }
  .head {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: var(--space-2);
  }
  .uses {
    margin: 0;
  }
</style>
