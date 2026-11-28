<!--
  BasicsStates: the cards of the House page that carry no figure: loading, request error (with a
  retry), an older service, the feature switched off (with a link to the setting) and the
  collecting state (progress towards the qualifying days and the reasons in words).

  Props: kind ('loading' | 'failed' | 'missing' | 'disabled' | 'collecting'), data (collecting),
  onretry (failed).
-->
<script lang="ts">
  import { t, tc } from '$lib/core/settings.svelte';
  import { QUALIFYING_DAYS, type InsightBasics } from '$lib/house/basics';
  import Button from '$ui/Button.svelte';
  import Card from '$ui/Card.svelte';
  import EmptyState from '$ui/EmptyState.svelte';
  import Icon from '$ui/Icon.svelte';

  type Props =
    | { kind: 'loading' | 'missing' | 'disabled' }
    | { kind: 'failed'; onretry: () => void }
    | { kind: 'collecting'; data: InsightBasics };

  let props: Props = $props();

  const fit = $derived(props.kind === 'collecting' ? props.data.heat_loss : null);
  const days = $derived(Math.min(fit?.days_used ?? 0, QUALIFYING_DAYS));
  const excluded = $derived(
    fit
      ? (['low_coverage', 'stove', 'no_heating', 'away'] as const).filter(
          (key) => fit.excluded[key] > 0,
        )
      : [],
  );
</script>

{#if props.kind === 'loading'}
  <Card title={t('houseLossTitle')} icon="home" testid="house-basics-loading" span={12}>
    <p class="muted">{t('houseLoading')}</p>
  </Card>
{:else if props.kind === 'failed'}
  <Card title={t('houseErrorTitle')} icon="warning" testid="house-basics-error" span={12}>
    <p>{t('houseErrorText')}</p>
    <Button variant="default" onclick={props.onretry} data-testid="house-basics-retry">
      {t('houseRetry')}
    </Button>
  </Card>
{:else if props.kind === 'missing'}
  <Card title={t('houseLossTitle')} icon="home" testid="house-basics-missing" span={12}>
    <p class="muted">{t('houseMissing')}</p>
  </Card>
{:else if props.kind === 'disabled'}
  <Card title={t('houseDisabledTitle')} icon="home" testid="house-disabled" span={12}>
    <EmptyState art="home" size="small">
      <p>{t('houseDisabledText')}</p>
      {#snippet action()}
        <Button variant="primary" href="#/settings/house" data-testid="house-disabled-link">
          {t('houseDisabledLink')}
          <Icon name="arrowRight" size={16} />
        </Button>
      {/snippet}
    </EmptyState>
  </Card>
{:else if fit}
  <Card
    title={t('houseCollectingTitle')}
    icon="clock"
    testid="house-collecting"
    help="house.basics"
    span={12}
  >
    <p>{t('houseCollectingText', { need: QUALIFYING_DAYS })}</p>
    <div class="progress" data-testid="house-collecting-progress">
      <progress max={QUALIFYING_DAYS} value={days} aria-label={t('houseCollectingTitle')}
      ></progress>
      <strong>{t('houseCollectingProgress', { n: days, need: QUALIFYING_DAYS })}</strong>
    </div>
    {#if fit.reasons.length > 0}
      <ul class="reasons" data-testid="house-collecting-reasons">
        {#each fit.reasons as reason (reason)}<li>{tc('houseLossReason_', reason)}</li>{/each}
      </ul>
    {/if}
    {#if excluded.length > 0}
      <p class="muted" data-testid="house-collecting-excluded">
        {t('houseExcludedTitle')}:
        {excluded.map((key) => t(`houseExcluded_${key}`, { n: fit.excluded[key] })).join('; ')}
      </p>
    {/if}
  </Card>
{/if}

<style>
  .progress {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: var(--space-2) var(--space-3);
    margin: var(--space-2) 0;
  }
  progress {
    flex: 1 1 10rem;
    max-width: 24rem;
    accent-color: var(--accent);
  }
  .reasons {
    margin: 0 0 var(--space-2);
    padding-left: 1.1rem;
  }
</style>
