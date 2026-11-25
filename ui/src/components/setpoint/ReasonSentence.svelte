<!--
  ReasonSentence: the decision in one plain-language sentence. With `detailed` a "Why?" button
  opens the rest: the binding constraint and the controller's own note split
  into clauses.

  Props: decision; detailed (default false).
-->
<script lang="ts">
  import { explain, numberFormats } from '$lib/setpoint/explain';
  import { settings, t, tOpt } from '$lib/core/settings.svelte';
  import type { Decision } from '$lib/core/types';
  import NoteClauses from './NoteClauses.svelte';
  import Why from '$ui/Why.svelte';

  let { decision, detailed = false }: { decision: Decision; detailed?: boolean } = $props();

  const explanation = $derived(explain(decision.record, tOpt, numberFormats(settings.language)));
</script>

<div class="reason" data-testid="reason-sentence">
  <p class="headline">
    {explanation.headline}
    {#if detailed}
      <Why title={t('setpointWhyTitle')} label={t('whyButton')} testid="reason-why" width="26rem">
        <div class="why">
          {#if explanation.constraint}
            <p data-testid="binding-sentence">
              <strong>{t('bindingHeading')}</strong>
              {explanation.constraint}
            </p>
          {/if}
          <h3>{t('serverNote')}</h3>
          <NoteClauses note={decision.note} />
        </div>
      </Why>
    {/if}
  </p>
</div>

<style>
  p {
    margin: 0;
  }
  .headline {
    font-size: var(--fs-emph);
    font-weight: var(--fw-semibold);
    line-height: var(--lh-body);
  }
  .headline :global(.why-trigger) {
    vertical-align: baseline;
    font-weight: var(--fw-regular);
  }
  .why {
    display: grid;
    gap: var(--space-2);
    font-weight: var(--fw-regular);
  }
  h3 {
    margin: var(--space-2) 0 0;
    font-size: var(--fs-caption);
    color: var(--muted);
    text-transform: uppercase;
    letter-spacing: 0.04em;
  }
</style>
