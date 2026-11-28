<!--
  Settings overview: one card per section with its current values (not a description) — the
  curve as a mini chart with its water temperatures, the comfort target with the room now,
  pump duty, limits, quiet windows on a 24 h bar, emitter, weather, the config version — each
  linking to its section, with a dot for unsaved changes.
-->
<script lang="ts">
  import Card from '$ui/Card.svelte';
  import Icon from '$ui/Icon.svelte';
  import type { ControlStore } from '$lib/core/control.svelte';
  import { asCurve } from '$lib/core/curve';
  import { draft } from '$lib/core/draft.svelte';
  import { asWindows, curveText, formatValue } from '$lib/core/fieldFormat';
  import { actorText } from '$lib/activity/audit';
  import { formatClock, formatDateTime, formatNumber } from '$lib/core/format';
  import { buildHash } from '$lib/core/router.svelte';
  import { changesIn, SECTIONS, type SectionId } from '$lib/core/schema';
  import { settings, t, tOpt } from '$lib/core/settings.svelte';
  import type { ConfigDoc, ConfigSchema } from '$lib/core/types';
  import MiniCurve from '$components/settings/MiniCurve.svelte';
  import QuietBar from '$components/settings/QuietBar.svelte';
  import { FEATURES } from '$lib/settings/features';
  import { haHost } from '$lib/settings/ha';
  import { asMqttInputs } from '$lib/settings/mqtt';

  interface Props {
    ctl: ControlStore;
    schema: ConfigSchema;
    config: ConfigDoc;
  }

  let { ctl, schema, config }: Props = $props();

  const locale = $derived(settings.language);
  const words = $derived({
    on: t('on'),
    off: t('off'),
    none: t('fieldNone'),
    forever: t('retentionForeverValue'),
  });
  const value = (id: string) => draft.value(id, config);
  const show = (id: string) => formatValue(schema.fields[id], value(id), locale, words);
  const num = (id: string, digits = 1) => {
    const v = value(id);
    return typeof v === 'number' ? formatNumber(v, digits, locale) : '–';
  };

  const curve = $derived(asCurve(value('control_curve')) ?? []);
  const activeCurve = $derived(asCurve(config.fields['control_curve']?.value) ?? null);
  const curveWords = $derived(curveText(curve, locale));
  const war = $derived(value('control_weather_compensation') !== false);
  const windows = $derived(asWindows(value('control_quiet_windows')) ?? []);
  const room = $derived(ctl.control?.room ?? null);
  const stove = $derived(ctl.control?.stove ?? null);
  const emitter = $derived(String(value('control_emitter') ?? ''));
  const weatherOn = $derived(value('weather_enabled') === true);
  const source = $derived(String(value('weather_location_source') ?? 'ha_zone_home'));
  const haUrl = $derived(
    typeof config.fields['ha_url']?.value === 'string' ? config.fields['ha_url'].value : null,
  );
  const broker = $derived.by(() => {
    const host = config.fields['mqtt_host']?.value;
    const port = config.fields['mqtt_port']?.value;
    return typeof host === 'string' && host ? (port ? `${host}:${String(port)}` : host) : null;
  });
  const featuresOn = $derived(
    FEATURES.filter((f) => {
      const on = value(f.switch);
      return f.threeWay ? on !== 'off' : on !== false;
    }).length,
  );
  const locked = $derived(Object.values(config.fields).filter((f) => f.locked).length);
  const changes = (id: SectionId) =>
    changesIn(schema, draft.changes, SECTIONS.find((s) => s.id === id)?.groups ?? []);
</script>

<ul class="overview" data-testid="settings-overview" data-help="settings.cards">
  {#each SECTIONS as s (s.id)}
    {@const n = changes(s.id)}
    <li class:wide={s.id === 'curve'}>
      <Card
        bare
        as="a"
        class="overview-link"
        href={buildHash('settings', [s.id])}
        data-testid="section-{s.id}"
        data-help={s.id === 'versions' ? 'settings.locked' : undefined}
      >
        <span class="head">
          <Icon name={s.icon} size={18} />
          <span class="name">{t(`section_${s.id}` as 'section_curve')}</span>
          {#if n > 0}
            <span class="dot" title={t('sectionChanges', { n })}
              ><span class="visually-hidden">{t('sectionChanges', { n })}</span></span
            >
          {/if}
          <Icon name="chevronRight" size={18} class="go" />
        </span>

        {#if s.id === 'features'}
          <span class="big" data-testid="overview-features"
            >{t('overviewFeaturesOn', { n: featuresOn, total: FEATURES.length })}</span
          >
          <span class="line">{t('overviewFeaturesLine')}</span>
        {:else if s.id === 'curve' && !war}
          <span class="big" data-testid="overview-fixed"
            >{num('control_fixed_water_c')}<span class="unit">&#8239;°C</span></span
          >
          <span class="line">{t('overviewFixed')}</span>
        {:else if s.id === 'curve'}
          <span class="curve">
            <span class="values">
              <span class="big">{curveWords.water}<span class="unit">&#8239;°C</span></span>
              <span class="caption">{t('overviewCurveAt', { outside: curveWords.outside })}</span>
            </span>
            <span class="mini"
              ><MiniCurve {curve} before={n > 0 ? activeCurve : null} height={76} /></span
            >
          </span>
        {:else if s.id === 'room'}
          <span class="big">{num('control_comfort_c')}<span class="unit">&#8239;°C</span></span>
          <span class="line">
            <span class="fresh" class:old={room !== null && !room.fresh} aria-hidden="true"></span>
            {room && room.value !== null
              ? t('overviewComfortDetail', {
                  value: formatNumber(room.value, 1, locale),
                  state: show('control_feedback_enabled'),
                })
              : `${t('overviewRoomNone')} · ${t('overviewFeedback', { state: show('control_feedback_enabled') })}`}
          </span>
        {:else if s.id === 'pump-duty'}
          <span class="big word">{show('control_pump_duty')}</span>
          {#if value('control_pump_duty') === true}
            <span class="line"
              >{t('overviewDuty', {
                heat: num('control_pump_duty_heat', 0),
                idle: num('control_pump_duty_idle', 0),
              })}</span
            >
          {/if}
        {:else if s.id === 'stove'}
          <span class="big word" data-testid="overview-stove">{show('control_stove_enabled')}</span>
          {#if value('control_stove_enabled') === true}
            <span class="line"
              >{stove?.active && stove.since
                ? t('overviewStoveActive', { time: formatClock(stove.since, locale) })
                : t(
                    value('control_stove_auto') === false
                      ? 'overviewStoveManual'
                      : 'overviewStoveAuto',
                    { k: num('control_stove_backoff_k') },
                  )}</span
            >
          {/if}
        {:else if s.id === 'behaviour'}
          <span class="big"
            >{num('control_min_setpoint_c', 0)}–{num('control_max_supply_c', 0)}<span class="unit"
              >&#8239;°C</span
            ></span
          >
          <span class="line"
            >{t('overviewBehaviour', {
              deadband: show('control_deadband_k'),
              dwell: show('control_dwell_s'),
            })}</span
          >
        {:else if s.id === 'quiet'}
          <QuietBar {windows} ticks={false} height={14} />
          <span class="line"
            >{windows.length === 0
              ? t('quietNone')
              : windows
                  .map((w) => t('quietWindowText', { start: w.start, end: w.end, level: w.level }))
                  .join(' · ')}</span
          >
        {:else if s.id === 'emitter'}
          <span class="emph">{tOpt(`cfg.control_emitter.opt.${emitter}`) ?? emitter}</span>
          <span class="line"
            >{t('overviewMaxSupply', { value: num('control_max_supply_c', 0) })}</span
          >
        {:else if s.id === 'weather'}
          <span class="big word">{weatherOn ? t('on') : t('off')}</span>
          <span class="line">{tOpt(`weatherSource_${source}`) ?? source}</span>
        {:else if s.id === 'ha'}
          <span class="emph" data-testid="overview-ha">{haHost(haUrl) ?? t('haStatusNotSet')}</span>
          <span class="line">{t('cfg.ha_url.label')}</span>
        {:else if s.id === 'mqtt'}
          <span class="emph" data-testid="overview-mqtt">{broker ?? '–'}</span>
          <span class="line"
            >{t('overviewMqttInputs', { n: asMqttInputs(value('mqtt_inputs')).length })}</span
          >
        {:else if s.id === 'data'}
          <span class="emph" data-testid="overview-data">{show('history_raw_days')}</span>
          <span class="line">{t('cfg.history_raw_days.label')}</span>
        {:else if s.id === 'house'}
          <span class="big" data-testid="overview-house"
            >{value('house_floor_area_m2') === null || value('house_floor_area_m2') === undefined
              ? '–'
              : num('house_floor_area_m2', 0)}<span class="unit">&#8239;m²</span></span
          >
          <span class="line">{t('cfg.house_floor_area_m2.label')}</span>
        {:else}
          <span class="big">v{config.version}</span>
          <span class="line"
            >{config.updated_at ? formatDateTime(config.updated_at, locale) : '–'}{config.updated_by
              ? ` · ${actorText(config.updated_by)}`
              : ''} · {t('overviewLocked', { n: locked })}</span
          >
        {/if}
      </Card>
    </li>
  {/each}
</ul>

<style>
  .overview {
    list-style: none;
    margin: 0;
    padding: 0;
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(min(15rem, 45%), 1fr));
    gap: var(--space-3);
  }
  .overview li {
    min-width: 0;
    display: flex;
  }
  .overview li.wide {
    grid-column: span 2;
  }
  :global(.overview-link) {
    flex: 1;
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
    min-height: 6.5rem;
    text-decoration: none;
    color: var(--text);
  }
  :global(.overview-link:hover) {
    border-color: var(--accent);
  }
  :global(.overview-link):hover .name {
    color: var(--accent);
  }
  .head {
    display: flex;
    align-items: center;
    gap: 0.4rem;
    color: var(--muted);
  }
  .name {
    font-weight: var(--fw-semibold);
    color: var(--text);
  }
  .head :global(.go) {
    margin-left: auto;
  }
  .dot {
    width: 9px;
    height: 9px;
    border-radius: 50%;
    background: var(--accent);
  }
  .big {
    font-size: var(--fs-value);
    font-weight: var(--fw-bold);
    line-height: var(--lh-tight);
    font-variant-numeric: tabular-nums;
  }
  .big.word::first-letter {
    text-transform: uppercase;
  }
  .big .unit {
    font-size: var(--fs-body);
  }
  .emph {
    font-size: var(--fs-emph);
    font-weight: var(--fw-semibold);
  }
  .line {
    display: block;
    color: var(--muted);
    font-size: var(--fs-caption);
  }
  .fresh {
    display: inline-block;
    margin-right: var(--space-1);
    vertical-align: 0.05em;
    width: 8px;
    height: 8px;
    border-radius: 50%;
    background: var(--cat-normal);
  }
  .fresh.old {
    background: var(--cat-limited);
  }
  .curve {
    display: grid;
    grid-template-columns: auto minmax(0, 1fr);
    gap: var(--space-4);
    align-items: center;
  }
  .values {
    display: flex;
    flex-direction: column;
    gap: 0.15rem;
  }
  .mini {
    min-width: 0;
    max-width: 22rem;
  }
  @container main (max-width: 34rem) {
    .overview li.wide {
      grid-column: 1 / -1;
    }
    :global(.overview-link) {
      min-height: 0;
    }
    .emph {
      font-size: var(--fs-body);
    }
  }
</style>
