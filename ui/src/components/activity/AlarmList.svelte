<!--
  AlarmList: active alarms, most severe first, each with a severity icon, how long it has been
  active, two lines "ovenbird now: …" (what ovenbird does about it) and "You: …" (what you can
  do), and a link to where it can be looked into.

  Props: alarms, compact (one line per alarm without message and action; for Home).
-->
<script lang="ts">
  import { formatDateTime } from '$lib/core/format';
  import type { IconName } from '$lib/core/icons';
  import { ACTION_HREF, alarmAction, type MonitorWithLimit } from '$lib/activity/monitors';
  import { monitorText, serviceMessageText } from '$lib/activity/serviceText';
  import { settings, t, tc, tOpt } from '$lib/core/settings.svelte';
  import type { Alarm, Severity } from '$lib/core/types';
  import Icon from '$ui/Icon.svelte';
  import Why from '$ui/Why.svelte';

  let {
    alarms,
    compact = false,
    monitors = [],
  }: { alarms: Alarm[]; compact?: boolean; monitors?: MonitorWithLimit[] } = $props();

  const ORDER: Record<Severity, number> = { critical: 0, warning: 1, info: 2 };
  const ICON: Record<Severity, IconName> = {
    critical: 'critical',
    warning: 'warning',
    info: 'info',
  };

  function textOf(alarm: Alarm): string | null {
    const monitor = monitors.find((item) => item.code === alarm.code);
    const composed = monitor
      ? monitorText(monitor, { say: (key, params) => tOpt(key, params), locale: settings.language })
      : null;
    if (composed || settings.language === 'en') return composed;
    return (
      tOpt(`alarmText_${alarm.code}`) ??
      serviceMessageText(alarm.message, {
        say: (key, params) => tOpt(key, params),
        locale: settings.language,
      })
    );
  }

  function serviceLine(message: string): { label: string; text: string } {
    if (settings.language === 'en') return { label: t('serviceMessage'), text: message };
    const translated = serviceMessageText(message, {
      say: (key, params) => tOpt(key, params),
      locale: settings.language,
    });
    return translated
      ? { label: t('serviceMessage'), text: translated }
      : { label: t('serviceMessageEnglish'), text: message };
  }

  const sorted = $derived(
    [...alarms].sort(
      (a, b) => ORDER[a.severity] - ORDER[b.severity] || a.since.localeCompare(b.since),
    ),
  );
</script>

{#if alarms.length === 0}
  <p class="muted none" data-testid="no-alarms">
    <Icon name="check" size={16} />
    {t('alarmsNone')}
  </p>
{:else}
  <ul class="alarms" class:compact data-testid="alarm-list">
    {#each sorted as alarm (alarm.code)}
      {@const action = compact ? null : alarmAction(alarm.code)}
      <li class="sev-{alarm.severity}">
        <span class="mark"><Icon name={ICON[alarm.severity]} size={compact ? 16 : 20} /></span>
        <div class="body">
          <div class="line">
            <strong>{tc('alarm_', alarm.code)}</strong>
            <span class="visually-hidden">({tc('severity_', alarm.severity)})</span>
            <span class="caption">
              {t('alarmSince', { when: formatDateTime(alarm.since, settings.language) })}
            </span>
          </div>
          {#if !compact}
            {@const text = textOf(alarm)}
            {@const hint = tOpt(`alarmWhy_${alarm.code}`)}
            <p class="muted msg">
              {text ?? alarm.message}
              {#if (text && alarm.message) || hint}
                <Why title={t('alarmWhyTitle')} label={t('whyButton')} width="24rem">
                  {#if hint}<p class="raw">{hint}</p>{/if}
                  {#if text && alarm.message}
                    {@const line = serviceLine(alarm.message)}
                    <p class="raw" data-testid="alarm-service-{alarm.code}">
                      <strong>{line.label}:</strong>
                      {line.text}
                    </p>
                  {/if}
                </Why>
              {/if}
            </p>
            {@const now = tOpt(`alarmNow_${alarm.code}`)}
            {@const you = tOpt(`alarmYou_${alarm.code}`)}
            {#if now || you}
              <dl class="advice" data-testid="alarm-advice-{alarm.code}">
                {#if now}<div>
                    <dt>{t('alarmNowLabel')}</dt>
                    <dd>{now}</dd>
                  </div>{/if}
                {#if you}<div>
                    <dt>{t('alarmYouLabel')}</dt>
                    <dd>{you}</dd>
                  </div>{/if}
              </dl>
            {/if}
            {#if action}
              <a class="act hit" href={ACTION_HREF[action]}>
                {t(`alarmAction_${action}` as 'alarmAction_holds')}
                <Icon name="chevronRight" size={14} />
              </a>
            {/if}
          {/if}
        </div>
      </li>
    {/each}
  </ul>
{/if}

<style>
  .none {
    display: flex;
    align-items: center;
    gap: var(--space-2);
    margin: 0;
    color: var(--status-ok);
  }
  .alarms {
    list-style: none;
    margin: 0;
    padding: 0;
  }
  li {
    display: flex;
    gap: var(--space-3);
    align-items: flex-start;
    padding: var(--space-3) 0 var(--space-3) var(--space-3);
    border-bottom: 1px solid var(--border);
    border-left: 3px solid var(--status-manual);
    margin-bottom: -1px;
  }
  .compact li {
    padding: var(--space-2) 0 var(--space-2) var(--space-2);
    align-items: center;
  }
  li:last-child {
    border-bottom: none;
  }
  .sev-critical {
    border-left-color: var(--status-stopped);
  }
  .sev-critical .mark {
    color: var(--status-stopped);
  }
  .sev-warning {
    border-left-color: var(--status-limited);
  }
  .sev-warning .mark {
    color: var(--status-limited);
  }
  .sev-info .mark {
    color: var(--status-manual);
  }
  .body {
    min-width: 0;
    flex: 1;
  }
  .advice {
    display: grid;
    gap: 0.15rem;
    margin: var(--space-1) 0 0;
    font-size: var(--fs-body);
  }
  .advice div {
    display: block;
  }
  .advice dt {
    display: inline;
    font-weight: var(--fw-semibold);
  }
  .advice dd {
    display: inline;
    margin: 0 0 0 0.3rem;
  }
  .line {
    display: flex;
    flex-wrap: wrap;
    align-items: baseline;
    gap: 0 var(--space-3);
  }
  .msg {
    margin: 2px 0 0;
    font-size: var(--fs-body);
    overflow-wrap: anywhere;
  }
  .raw {
    margin: 0 0 var(--space-2);
    overflow-wrap: anywhere;
  }
  .act {
    display: inline-flex;
    align-items: center;
    margin-top: var(--space-1);
    font-size: var(--fs-body);
    font-weight: var(--fw-medium);
  }
</style>
