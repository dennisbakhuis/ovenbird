<!--
  AboutCard: "About this installation" from `system/about`: version, service time and time zone,
  uptime and starts, then (in a Details) the control loop, connections, setpoint register,
  simulation and clock speed. "Download diagnostics" (admin) saves the redacted bundle for an
  issue report.

  Props: about (SystemAbout; null when the service does not offer it, undefined while loading),
  failed (the last load failed).
-->
<script lang="ts">
  import ActionRow from '$ui/ActionRow.svelte';
  import Button from '$ui/Button.svelte';
  import { DOWNLOAD_PREFIX } from '$lib/core/brand';
  import type { SystemAbout } from '$lib/system/about';
  import type { FailureKind } from '$lib/core/api';
  import { downloadFrom } from '$lib/core/download';
  import { formatDateTime, formatDuration, formatNumber } from '$lib/core/format';
  import { settings, t } from '$lib/core/settings.svelte';
  import Card from '$ui/Card.svelte';
  import Details from '$ui/Details.svelte';
  import Icon from '$ui/Icon.svelte';

  interface Props {
    about: SystemAbout | null | undefined;
    failed?: boolean;
  }

  let { about, failed = false }: Props = $props();

  const lang = $derived(settings.language);
  const when = (iso: string | null | undefined) => (iso ? formatDateTime(iso, lang) : '–');
  const yesNo = (value: boolean | null | undefined) =>
    value === null || value === undefined ? '–' : value ? t('yes') : t('no');

  let busy = $state(false);
  let failure = $state<FailureKind | null>(null);

  async function download(): Promise<void> {
    busy = true;
    failure = await downloadFrom(
      'api/v1/diagnostics?format=json',
      `${DOWNLOAD_PREFIX}diagnostics.json`,
    );
    busy = false;
  }

  const failureText = $derived(
    failure === null
      ? null
      : failure === 'forbidden' || failure === 'unauthorized'
        ? t('diagnosticsForbidden')
        : failure === 'missing'
          ? t('diagnosticsMissing')
          : t('actionFailed'),
  );

  const failing = $derived(Object.keys(about?.failing_components ?? {}));
</script>

<Card title={t('aboutTitle')} icon="info" testid="about-card" help="system.about">
  {#if about === undefined}
    <p class="muted">{failed ? t('systemLoadFailed') : t('loading')}</p>
  {:else if about === null}
    <p class="muted" data-testid="about-missing">{t('aboutMissing')}</p>
  {:else}
    <dl class="facts" data-testid="about-facts">
      <dt>{t('aboutVersion')}</dt>
      <dd>{about.version} <span class="muted">· API v{about.api_version}</span></dd>
      <dt>{t('aboutServiceTime')}</dt>
      <dd>{when(about.service_time)} <span class="muted">· {about.timezone}</span></dd>
      <dt>{t('aboutUptime')}</dt>
      <dd>
        {formatDuration(about.uptime_s, lang)}
        <span class="muted">· {t('aboutSince', { when: when(about.started_at) })}</span>
      </dd>
      {#if failing.length > 0}
        <dt>{t('aboutFailing')}</dt>
        <dd class="err-text">{failing.join(', ')}</dd>
      {/if}
    </dl>
    <Details summary={t('aboutMore')} id="system-about" testid="about-details">
      <dl class="facts">
        <dt>{t('aboutStarts')}</dt>
        <dd>
          {about.service_starts ?? '–'}
          {#if about.previous_start}<span class="muted">
              · {t('aboutPreviousStart', { when: when(about.previous_start) })}</span
            >{/if}
        </dd>
        <dt>{t('aboutRestored')}</dt>
        <dd>{yesNo(about.restored_state)}</dd>
        <dt>{t('aboutRegister')}</dt>
        <dd><code>{about.setpoint_register ?? '–'}</code></dd>
        <dt>{t('aboutInterval')}</dt>
        <dd>{formatDuration(about.control_interval_s, lang)}</dd>
        {#if about.control}
          <dt>{t('aboutTicks')}</dt>
          <dd>
            {formatNumber(about.control.ticks, 0, lang)}
            <span class="muted"
              >· {t('aboutLastTick', { when: when(about.control.last_tick_at) })}</span
            >
          </dd>
          <dt>{t('aboutPublishing')}</dt>
          <dd>{yesNo(about.control.publishing)}</dd>
        {/if}
        <dt>{t('aboutMqtt')}</dt>
        <dd>
          {#if about.connections.mqtt}
            {about.connections.mqtt.connected ? t('aboutConnected') : t('aboutDisconnected')}
            <span class="muted">
              · <code>{about.connections.mqtt.heishamon_base}</code>
              · {about.connections.mqtt.tls ? 'TLS' : t('aboutNoTls')}
              · {about.connections.mqtt.heishamon_alive
                ? t('heishamonOnline')
                : t('heishamonOffline')}</span
            >
          {:else}
            –
          {/if}
        </dd>
        <dt>{t('aboutHa')}</dt>
        <dd>
          {#if about.connections.ha?.configured}
            {about.connections.ha.connected ? t('aboutConnected') : t('aboutDisconnected')}
          {:else}
            {t('aboutNotConfigured')}
          {/if}
        </dd>
        <dt>{t('aboutToken')}</dt>
        <dd>{about.connections.integration_token ? t('aboutTokenSet') : t('aboutTokenUnset')}</dd>
        <dt>{t('aboutSimulation')}</dt>
        <dd>
          {about.simulation
            ? t('aboutSimulationOn', { speed: formatNumber(about.clock_speed, 0, lang) })
            : t('no')}
        </dd>
      </dl>
    </Details>
  {/if}
  <ActionRow center loose class="about-actions">
    <Button onclick={download} disabled={busy} data-testid="diagnostics-download">
      <Icon name="download" size={16} />{t('diagnosticsDownload')}
    </Button>
    <span class="caption muted">{t('diagnosticsHint')}</span>
  </ActionRow>
  {#if failureText}<p class="err-text" role="alert" data-testid="diagnostics-error">
      {failureText}
    </p>{/if}
</Card>

<style>
  p {
    margin: 0;
  }
  .facts {
    display: grid;
    grid-template-columns: minmax(7rem, max-content) minmax(0, 1fr);
    gap: var(--space-1) var(--space-3);
    margin: 0 0 var(--space-2);
  }
  dt {
    color: var(--muted);
  }
  dd {
    margin: 0;
    min-width: 0;
    overflow-wrap: anywhere;
  }
  .err-text {
    color: var(--err-text);
  }
  :global(.about-actions) {
    margin-top: var(--space-3);
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
