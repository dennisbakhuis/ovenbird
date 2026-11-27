<!--
  GateDetails: how every check of the three gates came out (value against limit, where the learner
  gives them), collapsed, with the 24 h skill as information only: a house held at a steady
  temperature is hard to out-predict, so it is never judged. Nothing for a model without the
  learner's gate detail.

  Props: house (HouseInsight).
-->
<script lang="ts">
  import { formatNumber } from '$lib/core/format';
  import type { GateDetails, HouseInsight } from '$lib/house/house';
  import { checkRows, gateRows } from '$lib/house/trust';
  import { settings, t, tOpt } from '$lib/core/settings.svelte';
  import Details from '$ui/Details.svelte';

  let { house }: { house: HouseInsight } = $props();

  const lang = $derived(settings.language);
  const num = (value: number, digits = 2) => formatNumber(value, digits, lang).replace('-', '−');
  const rows = $derived(gateRows(house.gates));
  const detail = $derived<GateDetails | undefined>(
    (house.revalidation?.gates ?? house.credibility?.gates) as GateDetails | undefined,
  );
  const detailRows = $derived(
    rows
      .map((row) => ({ row, checks: checkRows(detail?.[row.name]) }))
      .filter((x) => x.checks.length),
  );
  const skill24 = $derived(
    house.credibility?.gates?.dynamics?.diagnostics?.skill_24h ??
      detail?.dynamics?.diagnostics?.skill_24h ??
      null,
  );
  const valueText = (value: number | null, limit: number | null) =>
    value === null
      ? ''
      : limit === null
        ? t('houseCheckValueOnly', { value: num(value) })
        : t('houseCheckValue', { value: num(value), limit: num(limit) });
</script>

{#if detailRows.length > 0}
  <Details summary={t('houseGateDetails')} id="house-gate-details" testid="house-gate-details">
    <div class="checks">
      {#each detailRows as { row, checks } (row.name)}
        <section>
          <h3>{t(`houseGateName_${row.name}`)}</h3>
          <p class="caption">{t(`houseGateSource_${row.source}`)}</p>
          <ul>
            {#each checks as check (check.id)}
              <li data-testid="house-check-{check.id}" data-ok={check.ok}>
                <span>{tOpt(`houseCheck_${check.id}`) ?? check.id}</span>
                <span class="result"
                  >{check.ok ? t('houseCheckPass') : t('houseCheckFail')}{#if check.value !== null}
                    · {valueText(check.value, check.limit)}{/if}</span
                >
              </li>
            {/each}
          </ul>
        </section>
      {/each}
      {#if skill24 !== null}
        <p class="caption" data-testid="house-skill24">
          {t('houseSkill24', { value: num(skill24) })}
        </p>
      {/if}
    </div>
  </Details>
{/if}

<style>
  .checks {
    display: grid;
    gap: var(--space-3);
  }
  .checks h3 {
    margin: 0;
    font-size: var(--fs-body);
  }
  .checks p {
    margin: 0;
  }
  .checks ul {
    list-style: none;
    margin: 0;
    padding: 0;
    display: grid;
    gap: var(--space-1);
  }
  .checks li {
    display: flex;
    flex-wrap: wrap;
    justify-content: space-between;
    gap: 0 var(--space-3);
  }
  .result {
    color: var(--muted);
    font-variant-numeric: tabular-nums;
  }
</style>
