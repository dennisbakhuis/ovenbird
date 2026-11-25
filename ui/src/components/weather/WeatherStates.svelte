<!--
  Non-data states of the weather page.
  Props: kind ('disabled' | 'starting' | 'stale'), reason/provider (disabled), age (stale, seconds).
  The disabled state explains the opt-in and links to Settings → Weather.
-->
<script lang="ts">
  import { formatAge } from '$lib/core/format';
  import { t } from '$lib/core/settings.svelte';
  import Button from '$ui/Button.svelte';
  import Card from '$ui/Card.svelte';
  import EmptyState from '$ui/EmptyState.svelte';
  import Icon from '$ui/Icon.svelte';
  import Why from '$ui/Why.svelte';

  type Props =
    | { kind: 'disabled'; reason: string; provider: string }
    | { kind: 'starting' }
    | { kind: 'stale'; age: number | null };

  let props: Props = $props();
</script>

{#if props.kind === 'disabled'}
  <Card title={t('weatherDisabledTitle')} icon="weather" testid="weather-disabled">
    <EmptyState art="weatherOff">
      <p>{t('weatherDisabledBody')}</p>
      <p class="muted">{t('weatherDisabledWhat')}</p>
      <p class="caption">
        {t('weatherDisabledProvider', { provider: props.provider })}
      </p>
      {#snippet action()}
        <Button variant="primary" href="#/settings/weather" data-testid="weather-enable-link">
          {t('weatherDisabledAction')}
          <Icon name="arrowRight" size={16} />
        </Button>
      {/snippet}
    </EmptyState>
  </Card>
{:else if props.kind === 'starting'}
  <Card title={t('weatherStartingTitle')} icon="clock" testid="weather-starting">
    <p>{t('weatherStartingBody')}</p>
    <p>
      <a class="hit" href="#/settings/weather">{t('weatherSettingsLink')}</a>
    </p>
  </Card>
{:else}
  <div class="stale" role="status" data-testid="weather-stale">
    <Icon name="warning" size={20} />
    <strong>{t('weatherStaleTitle')}</strong>
    <Why title={t('weatherStaleTitle')} testid="weather-stale-why">
      <p>{t('weatherStaleBody', { age: props.age === null ? '–' : formatAge(props.age) })}</p>
    </Why>
  </div>
{/if}

<style>
  .stale {
    display: flex;
    gap: var(--space-3);
    align-items: center;
    padding: var(--space-1) var(--space-3);
    border-radius: var(--radius);
    border: 1px solid var(--status-warn);
    background: var(--status-warn-bg);
  }
  .stale p {
    margin: 0;
    font-size: var(--fs-caption);
  }
  .stale :global(svg) {
    flex: none;
    color: var(--status-warn);
  }
  p {
    margin: 0;
  }
</style>
