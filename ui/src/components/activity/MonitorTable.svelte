<!--
  MonitorTable: the safety monitors, one row each. Where the backend gives a limit, the value is
  drawn against it as a bullet bar; otherwise the row shows the value and the monitor's message.

  Props: monitors (with optional limit, unit, direction).
-->
<script lang="ts">
  import { monitorBar, type MonitorWithLimit } from '$lib/activity/monitors';
  import { monitorText, serviceMessageText } from '$lib/activity/serviceText';
  import { settings, t, tc, tOpt } from '$lib/core/settings.svelte';
  import BulletBar from '$components/charts/BulletBar.svelte';
  import Pill from '$ui/Pill.svelte';
  import Why from '$ui/Why.svelte';

  let { monitors }: { monitors: MonitorWithLimit[] } = $props();

  const tone = (status: MonitorWithLimit['status']) =>
    status === 'ok'
      ? 'good'
      : status === 'active'
        ? 'bad'
        : status === 'pending'
          ? 'warn'
          : 'neutral';

  const tools = $derived({
    say: (key: string, params?: Record<string, string | number>) => tOpt(key, params),
    locale: settings.language,
  });
  const textOf = (monitor: MonitorWithLimit) => monitorText(monitor, tools);
  const serviceLine = (message: string): { label: string; text: string } => {
    if (settings.language === 'en') return { label: t('serviceMessage'), text: message };
    const translated = serviceMessageText(message, tools);
    return translated
      ? { label: t('serviceMessage'), text: translated }
      : { label: t('serviceMessageEnglish'), text: message };
  };

  const ICON = { ok: 'check', pending: 'clock', active: 'critical', unknown: 'info' } as const;
</script>

<ul class="monitors" data-testid="monitor-table">
  {#each monitors as monitor (monitor.code)}
    {@const bar = monitorBar(monitor)}
    {@const text = textOf(monitor)}
    <li data-status={monitor.status}>
      <div class="head">
        <strong>{tc('alarm_', monitor.code)}</strong>
        <Pill tone={tone(monitor.status)} icon={ICON[monitor.status]}>
          {tc('monitorStatus_', monitor.status)}
        </Pill>
      </div>
      {#if bar}
        <BulletBar
          label={tc('alarm_', monitor.code)}
          value={bar.value}
          limit={bar.limit}
          direction={bar.direction}
          unit={bar.unit}
          showLabel={false}
        />
      {/if}
      <p class="caption msg">
        {text ?? monitor.message}
        {#if text && monitor.message}
          {@const line = serviceLine(monitor.message)}
          <Why title={line.label} label={t('whyButton')} width="22rem">
            <p class="raw">{line.text}</p>
          </Why>
        {/if}
      </p>
    </li>
  {:else}
    <li class="muted">{t('monitorsEmpty')}</li>
  {/each}
</ul>

<style>
  .monitors {
    list-style: none;
    margin: 0;
    padding: 0;
    display: grid;
    gap: 0;
  }
  li {
    display: grid;
    gap: var(--space-1);
    padding: var(--space-2) 0;
    border-bottom: 1px solid var(--border);
  }
  li:last-child {
    border-bottom: none;
  }
  .head {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: var(--space-2);
  }
  .msg {
    margin: 0;
    color: var(--muted);
    overflow-wrap: anywhere;
  }
  .raw {
    margin: 0;
    overflow-wrap: anywhere;
  }
  @media (--wide) {
    .monitors {
      grid-template-columns: 1fr 1fr;
      column-gap: var(--space-5);
    }
  }
</style>
