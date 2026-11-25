<!--
  LearningCard: the House page before there is a model to show. `learning`: the learner ran but
  promoted nothing yet, with what is missing; `not_run`: the learner has not run; `missing`: this
  service does not offer the house model; `failed`: it could not be loaded.

  Props: kind, data (HouseLearning | null).
-->
<script lang="ts">
  import Card from '$ui/Card.svelte';
  import { formatDateTime } from '$lib/core/format';
  import type { HouseLearning } from '$lib/house/house';
  import { settings, t } from '$lib/core/settings.svelte';
  import EmptyState from '$ui/EmptyState.svelte';

  interface Props {
    kind: 'learning' | 'not_run' | 'missing' | 'failed';
    data?: HouseLearning | null;
  }

  let { kind, data = null }: Props = $props();

  const lang = $derived(settings.language);
  const title = $derived(
    kind === 'missing'
      ? t('houseMissingTitle')
      : kind === 'failed'
        ? t('houseFailedTitle')
        : t('houseLearningTitle'),
  );
  const text = $derived(
    kind === 'missing'
      ? t('houseMissingText')
      : kind === 'failed'
        ? t('houseFailedText')
        : kind === 'not_run'
          ? t('houseNotRunText')
          : t('houseLearningText'),
  );
  const missing = $derived(kind === 'learning' ? (data?.missing ?? []) : []);
</script>

<Card bare class="learning-card-learning" data-testid="house-{kind}" data-help="house.score">
  <EmptyState art="noData" {title} {text} testid="house-empty" />
  {#if missing.length > 0}
    <div class="missing">
      <h2>{t('houseMissingList')}</h2>
      <ul>
        {#each missing as item (item)}<li>{item}</li>{/each}
      </ul>
    </div>
  {/if}
  {#if data?.last_run?.at}
    <p class="caption">{t('houseLastRunAt', { time: formatDateTime(data.last_run.at, lang) })}</p>
  {/if}
</Card>

<style>
  :global(.learning-card-learning) {
    display: grid;
    gap: var(--space-3);
  }
  h2 {
    margin: 0 0 var(--space-1);
    font-size: var(--fs-body);
  }
  ul {
    margin: 0;
    padding-left: 1.2rem;
  }
  .caption {
    margin: 0;
  }
</style>
