<script lang="ts">
  import Card from '$ui/Card.svelte';
  import HealthGrid from '$components/activity/HealthGrid.svelte';
  import { formatAge } from '$lib/core/format';
  import type { LiveStore } from '$lib/core/live.svelte';
  import { t } from '$lib/core/settings.svelte';
  import { SUPPORTED_API_VERSION } from '$lib/core/types';

  let { live }: { live: LiveStore } = $props();

  const health = $derived(live.health);
  const mismatch = $derived(health !== null && health.api_version !== SUPPORTED_API_VERSION);
  const notes = $derived.by((): Record<string, string> => {
    const snapshot = live.snapshot;
    if (!snapshot) return {};
    const parts = [
      snapshot.heishamon.lwt,
      snapshot.heishamon.last_heartbeat_age === null
        ? null
        : t('healthHeartbeatAge', { age: formatAge(snapshot.heishamon.last_heartbeat_age) }),
    ].filter(Boolean);
    return parts.length ? { heishamon: parts.join(' · ') } : {};
  });
</script>

<Card bare class="health-health" data-testid="health-card" aria-labelledby="health-title">
  <h2 id="health-title">{t('healthTitle')}</h2>

  {#if mismatch && health}
    <p class="mismatch" role="alert">
      {t('apiMismatch', { ui: SUPPORTED_API_VERSION, server: health.api_version })}
    </p>
  {/if}

  {#if health}
    <HealthGrid checks={health.checks} {notes} />
    <p class="facts caption">
      <span>{t('healthVersion')} {health.version}</span>
      <span>{t('healthApi')} v{health.api_version}</span>
      <span>{t('healthLive')}: {health.live ? t('yes') : t('no')}</span>
      <span>{t('healthReady')}: {health.ready ? t('yes') : t('no')}</span>
    </p>
  {:else}
    <p class="muted">{t('healthUnavailable')}</p>
  {/if}
</Card>

<style>
  :global(.health-health) {
    display: grid;
    gap: var(--space-3);
  }
  h2 {
    margin: 0;
    font-size: var(--fs-emph);
  }
  .facts {
    display: flex;
    flex-wrap: wrap;
    gap: var(--space-1) var(--space-4);
    margin: 0;
    color: var(--muted);
  }
  .mismatch {
    margin: 0;
    background: var(--warn-bg);
    color: var(--warn-text);
    padding: var(--space-3) var(--space-4);
    border-radius: var(--radius);
    font-weight: var(--fw-semibold);
  }
</style>
