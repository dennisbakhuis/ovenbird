<!--
  Settings: overview cards with current values, then one page per section. Desktop (wide main
  container) has a section rail on the left; narrow screens get a section picker instead of a
  clipped tab row. The draft bar sits fixed at the bottom; a spacer keeps the last field
  reachable above it.
-->
<script lang="ts">
  import Card from '$ui/Card.svelte';
  import Select from '$ui/Select.svelte';
  import Button from '$ui/Button.svelte';
  import Icon from '$ui/Icon.svelte';
  import { acknowledgeReset } from '$lib/core/api';
  import { cfg } from '$lib/core/cfg.svelte';
  import type { ControlStore } from '$lib/core/control.svelte';
  import { actionKey, classifyError } from '$lib/core/control.svelte';
  import { draft } from '$lib/core/draft.svelte';
  import type { LiveStore } from '$lib/core/live.svelte';
  import { buildHash, router } from '$lib/core/router.svelte';
  import { changesIn, sectionOf, SECTIONS, type SectionId } from '$lib/core/schema';
  import { t } from '$lib/core/settings.svelte';
  import BehaviourSection from './settings/BehaviourSection.svelte';
  import CurveSection from './settings/CurveSection.svelte';
  import EmitterSection from './settings/EmitterSection.svelte';
  import Overview from './settings/Overview.svelte';
  import PumpDutySection from './settings/PumpDutySection.svelte';
  import QuietSection from './settings/QuietSection.svelte';
  import RoomSection from './settings/RoomSection.svelte';
  import StoveSection from './settings/StoveSection.svelte';
  import VersionsSection from './settings/VersionsSection.svelte';
  import WeatherSection from './settings/WeatherSection.svelte';
  import HouseSection from './settings/HouseSection.svelte';
  import HaSection from './settings/HaSection.svelte';
  import MqttSection from './settings/MqttSection.svelte';
  import DataSection from './settings/DataSection.svelte';

  let { live, ctl }: { live: LiveStore; ctl: ControlStore } = $props();

  $effect(() => {
    void cfg.loadSchema();
  });

  const section = $derived(sectionOf(router.location.sub[0]));
  const schema = $derived(cfg.schema);
  const config = $derived(ctl.config);
  const missing = $derived(cfg.schemaState === 'missing' || ctl.configMissing);
  const sectionName = (id: SectionId) => t(`section_${id}` as 'section_curve');
  const changes = (id: SectionId) =>
    changesIn(schema, draft.changes, SECTIONS.find((s) => s.id === id)?.groups ?? []);

  function pick(event: Event): void {
    const id = (event.currentTarget as HTMLSelectElement).value;
    router.navigate('settings', id === 'overview' ? [] : [id]);
  }

  let ackError = $state<string | null>(null);
  async function acknowledge(): Promise<void> {
    ackError = null;
    try {
      const done = await acknowledgeReset();
      ctl.config = done.config;
      void ctl.refresh();
    } catch (error) {
      ackError = t(actionKey(classifyError(error)));
    }
  }
</script>

<div class="page">
  <h1>
    {#if section}
      <a class="crumb" href={buildHash('settings')}>{t('settingsPageTitle')}</a>
      <span class="here"
        ><Icon name="chevronRight" size={18} /><span>{sectionName(section.id)}</span></span
      >
    {:else}
      {t('settingsPageTitle')}
    {/if}
  </h1>

  {#if missing}
    <Card bare data-testid="unavailable">
      <p>{t('unavailable')}</p>
    </Card>
  {:else if !schema || !config}
    <p class="muted" data-testid="settings-loading">
      {cfg.schemaState === 'failed' ? t('settingsFailed') : t('loading')}
    </p>
  {:else}
    {#if config.reset_pending}
      <Card bare class="settings-reset" data-testid="reset-pending" role="alert">
        <p><Icon name="warning" size={18} />{t('resetPending')}</p>
        <Button type="button" variant="primary" onclick={acknowledge} data-testid="reset-ack">
          {t('resetAcknowledge')}
        </Button>
        {#if ackError}<p class="error">{ackError}</p>{/if}
      </Card>
    {/if}

    <div class="layout">
      <nav class="rail" aria-label={t('settingsTabs')} data-testid="settings-rail">
        <ul>
          <li>
            <a href={buildHash('settings')} aria-current={section ? undefined : 'page'}>
              <Icon name="settings" size={18} />
              <span class="label">{t('settingsOverview')}</span>
            </a>
          </li>
          {#each SECTIONS as s (s.id)}
            {@const n = changes(s.id)}
            <li>
              <a
                href={buildHash('settings', [s.id])}
                aria-current={section?.id === s.id ? 'page' : undefined}
                data-testid="rail-{s.id}"
              >
                <Icon name={s.icon} size={18} />
                <span class="label">{sectionName(s.id)}</span>
                {#if n > 0}<span class="count" aria-label={t('sectionChanges', { n })}>{n}</span
                  >{/if}
              </a>
            </li>
          {/each}
        </ul>
      </nav>

      <div class="content">
        {#if section}
          <label class="picker" data-testid="settings-picker">
            <span class="visually-hidden">{t('settingsPicker')}</span>
            <Icon name={section.icon} size={20} />
            <Select class="picker-select" block={false} value={section.id} onchange={pick}>
              <option value="overview">{t('settingsOverview')}</option>
              {#each SECTIONS as s (s.id)}
                {@const n = changes(s.id)}
                <option value={s.id}
                  >{sectionName(s.id)}{n > 0 ? ` · ${t('pickerChanges', { n })}` : ''}</option
                >
              {/each}
            </Select>
            <Icon name="chevronDown" size={18} />
          </label>
        {/if}

        {#if !section}
          <Overview {ctl} {schema} {config} />
        {:else if section.id === 'curve'}
          <CurveSection {live} {ctl} {schema} {config} />
        {:else if section.id === 'room'}
          <RoomSection {ctl} {schema} {config} />
        {:else if section.id === 'pump-duty'}
          <PumpDutySection {live} {schema} {config} />
        {:else if section.id === 'stove'}
          <StoveSection {ctl} {schema} {config} />
        {:else if section.id === 'behaviour'}
          <BehaviourSection {schema} {config} />
        {:else if section.id === 'quiet'}
          <QuietSection {schema} {config} />
        {:else if section.id === 'emitter'}
          <EmitterSection {schema} {config} />
        {:else if section.id === 'weather'}
          <WeatherSection {schema} {config} />
        {:else if section.id === 'house'}
          <HouseSection {schema} {config} />
        {:else if section.id === 'ha'}
          <HaSection {live} {ctl} {schema} {config} />
        {:else if section.id === 'mqtt'}
          <MqttSection {ctl} {schema} {config} />
        {:else if section.id === 'data'}
          <DataSection {schema} {config} />
        {:else}
          <VersionsSection {ctl} {schema} {config} />
        {/if}
      </div>
    </div>
  {/if}

  {#if draft.count > 0}<div class="spacer" aria-hidden="true"></div>{/if}
</div>

<style>
  h1 {
    display: flex;
    align-items: center;
    flex-wrap: wrap;
    gap: var(--space-1);
  }
  h1 :global(.icon) {
    color: var(--muted);
  }
  .here {
    display: inline-flex;
    align-items: center;
    gap: var(--space-1);
  }
  @container main (max-width: 52rem) {
    .here {
      position: absolute;
      width: 1px;
      height: 1px;
      overflow: hidden;
      clip: rect(0 0 0 0);
      white-space: nowrap;
    }
    .crumb {
      color: var(--text);
      font-weight: var(--fw-semibold);
    }
  }
  .crumb {
    display: inline-flex;
    align-items: center;
    color: var(--muted);
    text-decoration: none;
    font-weight: var(--fw-medium);
  }
  @media (--narrow), (pointer: coarse) {
    .crumb {
      min-height: var(--tap);
    }
  }
  .crumb:hover {
    color: var(--accent);
    text-decoration: underline;
  }
  .layout {
    display: grid;
    grid-template-columns: minmax(0, 1fr);
    gap: var(--space-5);
    align-items: start;
  }
  .rail {
    display: none;
  }
  .content {
    min-width: 0;
    display: flex;
    flex-direction: column;
    gap: var(--space-3);
  }
  .picker {
    position: relative;
    display: flex;
    align-items: center;
    gap: var(--space-2);
    min-height: var(--tap);
    padding: 0 var(--space-3);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    background: var(--surface);
    color: var(--muted);
  }
  .picker:focus-within {
    outline: 3px solid var(--accent);
    outline-offset: 2px;
  }
  .picker :global(.picker-select) {
    padding: 0;
    flex: 1;
    min-width: 0;
    min-height: var(--tap);
    border: none;
    background: transparent;
    color: var(--text);
    font-weight: var(--fw-semibold);
    appearance: none;
    -webkit-appearance: none;
    cursor: pointer;
  }
  .picker :global(.picker-select:focus-visible) {
    outline: none;
  }
  .picker :global(.icon:last-child) {
    pointer-events: none;
  }
  @container main (min-width: 52rem) {
    .layout {
      grid-template-columns: 13.5rem minmax(0, 1fr);
    }
    .rail {
      display: block;
      position: sticky;
      top: var(--space-4);
    }
    .picker {
      display: none;
    }
  }
  .rail ul {
    list-style: none;
    margin: 0;
    padding: 0;
    display: flex;
    flex-direction: column;
    gap: 2px;
  }
  .rail a {
    display: flex;
    align-items: center;
    gap: 0.55rem;
    min-height: var(--control-h);
    padding: 0 0.7rem;
    border-radius: var(--radius-control);
    color: var(--muted);
    text-decoration: none;
    font-weight: var(--fw-semibold);
  }
  .rail a:hover {
    background: var(--surface-2);
    color: var(--text);
  }
  .rail a[aria-current='page'] {
    background: var(--status-manual-bg);
    color: var(--status-manual);
  }
  .rail .label {
    flex: 1;
    min-width: 0;
  }
  .count {
    min-width: 1.3rem;
    padding: 0 0.35rem;
    border-radius: var(--radius-pill);
    background: var(--accent);
    color: var(--on-accent);
    font-size: var(--fs-caption);
    text-align: center;
  }
  :global(.settings-reset) {
    margin-bottom: var(--space-4);
    background: var(--warn-bg);
    color: var(--warn-text);
  }
  :global(.settings-reset) p {
    display: flex;
    gap: 0.4rem;
    margin-top: 0;
  }
  .error {
    color: var(--err-text);
  }
  .spacer {
    height: 4.5rem;
  }
</style>
