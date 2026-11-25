<!--
  SafetyNetCard: what holds the pump safe when ovenbird stops. The envelope rule on the HeishaMon
  board (not declared / declared / proven, with the last evidence: a change of the pump's water
  target into the band that ovenbird did not send), the band at the current outside temperature,
  and ovenbird's own limits (maximum supply, minimum setpoint, band width, safety corrections).

  Props: net (SafetyNet; null when the service does not report it, undefined while loading),
  failed (the last load failed).
-->
<script lang="ts">
  import type { SafetyNet } from '$lib/system/about';
  import { formatDateTime, formatNumber } from '$lib/core/format';
  import { settings, t } from '$lib/core/settings.svelte';
  import Card from '$ui/Card.svelte';
  import Pill from '$ui/Pill.svelte';

  interface Props {
    net: SafetyNet | null | undefined;
    failed?: boolean;
  }

  let { net, failed = false }: Props = $props();

  const lang = $derived(settings.language);
  const c = (value: number | null | undefined, digits = 1) =>
    typeof value === 'number' ? `${formatNumber(value, digits, lang)} °C` : '–';
  const k = (value: number | null | undefined) =>
    typeof value === 'number' ? `${formatNumber(value, 1, lang)} K` : '–';

  const rule = $derived(net?.envelope_rule ?? null);
  const tone = $derived(
    rule?.state === 'proven' ? 'good' : rule?.state === 'declared' ? 'warn' : 'bad',
  );
  const evidence = $derived(rule?.last ?? null);
  const corrections = $derived(
    typeof net?.ovenbird_corrections?.total === 'number' ? net.ovenbird_corrections.total : null,
  );
</script>

<Card title={t('safetyNetTitle')} icon="lock" testid="safety-net-card" help="system.safety">
  {#if net === undefined}
    <p class="muted">{failed ? t('systemLoadFailed') : t('loading')}</p>
  {:else if net === null}
    <p class="muted" data-testid="safety-net-missing">{t('safetyNetMissing')}</p>
  {:else if rule}
    <p class="state" data-testid="envelope-rule" data-state={rule.state}>
      <Pill {tone} icon={rule.state === 'proven' ? 'check' : 'warning'}>
        {t(`envelopeRule_${rule.state}` as 'envelopeRule_proven')}
      </Pill>
      <span>{t(`envelopeRuleText_${rule.state}` as 'envelopeRuleText_proven')}</span>
    </p>
    {#if evidence}
      <p class="evidence" data-testid="envelope-evidence">
        {t('envelopeEvidence', {
          when: formatDateTime(evidence.at, lang),
          from: c(evidence.from_c),
          to: c(evidence.to_c),
          outside: c(evidence.outside_c),
          low: c(evidence.low_c),
          high: c(evidence.high_c),
        })}
        {#if rule.count > 1}<span class="muted">
            · {t('envelopeEvidenceCount', { n: rule.count })}</span
          >{/if}
      </p>
    {/if}
    <dl class="facts">
      {#if net.envelope_now}
        <dt>{t('envelopeBandNow')}</dt>
        <dd data-testid="envelope-band">
          {t('envelopeBandValue', {
            low: c(net.envelope_now.low_c),
            high: c(net.envelope_now.high_c),
            outside: c(net.envelope_now.outside_c),
          })}
        </dd>
      {/if}
      {#if typeof rule.adopted === 'number'}
        <dt>{t('envelopeAdopted')}</dt>
        <dd>{rule.adopted}</dd>
      {/if}
      <dt>{t('safetyMaxSupply')}</dt>
      <dd>{c(net.max_supply_c)}</dd>
      <dt>{t('safetyMinSetpoint')}</dt>
      <dd>{c(net.min_setpoint_c)}</dd>
      <dt>{t('safetyBandWidth')}</dt>
      <dd>
        {t('safetyBandWidthValue', {
          below: k(net.envelope_below_k),
          above: k(net.envelope_above_k),
        })}
      </dd>
      {#if corrections !== null}
        <dt>{t('safetyCorrections')}</dt>
        <dd>{corrections}</dd>
      {/if}
    </dl>
  {/if}
</Card>

<style>
  p {
    margin: 0;
  }
  .state {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: var(--space-2);
    margin-bottom: var(--space-2);
    font-weight: var(--fw-semibold);
  }
  .evidence {
    margin-bottom: var(--space-3);
  }
  .facts {
    display: grid;
    grid-template-columns: minmax(7rem, max-content) minmax(0, 1fr);
    gap: var(--space-1) var(--space-3);
    margin: var(--space-2) 0 0;
  }
  dt {
    color: var(--muted);
  }
  dd {
    margin: 0;
    min-width: 0;
    font-variant-numeric: tabular-nums;
  }
  @container main (max-width: 30rem) {
    .facts {
      grid-template-columns: minmax(0, 1fr);
      gap: 0;
    }
    dd {
      margin-bottom: var(--space-2);
    }
  }
</style>
