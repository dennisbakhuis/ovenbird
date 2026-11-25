<!--
  Home Assistant section: the connection card (address, write-only token, test and save) and a
  pointer to where the sensors are chosen. The service reads exactly the HA entities the
  settings use, plus any listed in OVENBIRD_HA_ENTITIES.
-->
<script lang="ts">
  import Card from '$ui/Card.svelte';
  import Icon from '$ui/Icon.svelte';
  import HaConnectionCard from '$components/settings/HaConnectionCard.svelte';
  import { cfg } from '$lib/core/cfg.svelte';
  import type { ControlStore } from '$lib/core/control.svelte';
  import type { LiveStore } from '$lib/core/live.svelte';
  import { buildHash } from '$lib/core/router.svelte';
  import { t } from '$lib/core/settings.svelte';
  import type { ConfigDoc, ConfigSchema } from '$lib/core/types';

  interface Props {
    live: LiveStore;
    ctl: ControlStore;
    schema: ConfigSchema;
    config: ConfigDoc;
  }

  let { live, ctl, schema, config }: Props = $props();

  const linkUp = $derived(live.snapshot?.links?.ha ?? null);
  const extra = $derived.by(() => {
    const value = config.fields['ha_entities']?.value;
    return Array.isArray(value) ? value.map(String) : [];
  });

  function saved(next: ConfigDoc): void {
    ctl.config = next;
    void ctl.refresh();
    void cfg.loadSignals();
  }
</script>

<HaConnectionCard {config} {schema} {linkUp} onsaved={saved} />

<Card bare as="div" class="ha-sensors" data-testid="ha-sensors" data-help="settings/ha.sensors">
  <p class="muted">{t('haSensorsHint')}</p>
  <a href={buildHash('settings', ['room'])} data-testid="ha-sensors-link"
    >{t('haSensorsLink')}<Icon name="chevronRight" size={16} /></a
  >
  {#if extra.length > 0}
    <p class="muted small" data-testid="ha-extra">
      {t('haExtraEntities', { list: extra.join(', ') })}
    </p>
  {/if}
</Card>

<style>
  :global(.ha-sensors) {
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
  }
  p {
    margin: 0;
  }
  a {
    display: inline-flex;
    align-items: center;
    gap: var(--space-1);
    font-weight: var(--fw-medium);
  }
  .small {
    font-size: var(--fs-caption);
  }
</style>
