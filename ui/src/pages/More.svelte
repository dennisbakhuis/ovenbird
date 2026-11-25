<script lang="ts">
  import Pill from '$ui/Pill.svelte';
  import Card from '$ui/Card.svelte';
  import Icon from '$ui/Icon.svelte';
  import type { ControlStore } from '$lib/core/control.svelte';
  import { draft } from '$lib/core/draft.svelte';
  import { formatDateTime, formatNumber } from '$lib/core/format';
  import { fetchHouse, type HouseResult } from '$lib/house/house';
  import type { MessageKey } from '$lib/i18n';
  import type { IconName } from '$lib/core/icons';
  import type { LiveStore } from '$lib/core/live.svelte';
  import { modeView } from '$lib/core/mode';
  import { settings, t, tc } from '$lib/core/settings.svelte';

  let { live, ctl }: { live: LiveStore; ctl: ControlStore } = $props();

  interface Entry {
    href: string;
    icon: IconName;
    title: string;
    line: string;
    badge?: number;
    badgeTone?: 'stopped' | 'limited' | 'manual';
    testid: string;
  }

  const alarms = $derived(ctl.control?.alarms ?? []);
  const hold = $derived(ctl.control?.adapter ?? null);
  const version = $derived(
    ctl.config?.applied_version ?? ctl.control?.config_version ?? live.configVersion,
  );
  const view = $derived(modeView(ctl.control, ctl.decision, ctl.config));

  const activityLine = $derived.by(() => {
    const parts: string[] = [];
    if (alarms.length === 1) parts.push(t('stripAlarmOne'));
    else if (alarms.length > 1) parts.push(t('stripAlarms', { n: alarms.length }));
    if (hold?.hold) {
      parts.push(
        hold.hold_until
          ? t('moreActivityHold', {
              time: formatDateTime(hold.hold_until, settings.language, live.clock),
            })
          : t('stripHold', { reason: tc('holdWhy_', hold.hold) }),
      );
    }
    return parts.length ? parts.join(' · ') : t('moreActivityNone');
  });

  const settingsLine = $derived(
    [
      version === null || version === undefined ? t('moreSettingsAbout') : null,
      version === null || version === undefined ? null : t('moreSettingsLine', { version }),
      draft.count === 0
        ? null
        : draft.count === 1
          ? t('stripDraftOne')
          : t('stripDraftMany', { n: draft.count }),
    ]
      .filter(Boolean)
      .join(' · '),
  );

  const systemLine = $derived(
    t('moreSystemLine', {
      mode: t(`modeShort_${view.key}` as MessageKey),
      state:
        live.snapshot === null
          ? '–'
          : live.snapshot.heishamon.alive
            ? t('heishamonOnline')
            : t('heishamonOffline'),
    }),
  );

  const signalCount = $derived(Object.keys(live.snapshot?.signals ?? {}).length);

  let house = $state<HouseResult | null>(null);
  $effect(() => {
    const controller = new AbortController();
    fetchHouse(controller.signal)
      .then((result) => (house = result))
      .catch(() => (house = null));
    return () => controller.abort();
  });
  const houseLine = $derived.by(() => {
    if (house?.kind === 'learning') return t('moreHouseLearning');
    if (house?.kind !== 'ready') return t('moreHouseAbout');
    const ua = formatNumber(house.data.ua.w_per_k, 0, settings.language);
    const score = house.data.score;
    if (score.state === 'ready' && score.band) return t('moreHouseBand', { band: score.band, ua });
    if (score.state === 'learning') return t('moreHouseLearning');
    return t('moreHouseUa', { ua });
  });

  const entries = $derived<Entry[]>([
    {
      href: '#/settings',
      icon: 'settings',
      title: t('navSettings'),
      line: settingsLine,
      testid: 'more-settings',
    },
    {
      href: '#/activity',
      icon: 'bell',
      title: t('navActivity'),
      line: activityLine,
      badge: alarms.length,
      badgeTone: alarms.some((a) => a.severity === 'critical')
        ? 'stopped'
        : alarms.some((a) => a.severity === 'warning')
          ? 'limited'
          : 'manual',
      testid: 'more-activity',
    },
    {
      href: '#/system',
      icon: 'cpu',
      title: t('navSystem'),
      line: systemLine,
      testid: 'more-system',
    },
    {
      href: '#/house',
      icon: 'home',
      title: t('navHouse'),
      line: houseLine,
      testid: 'more-house',
    },
    {
      href: '#/system/signals',
      icon: 'chart',
      title: t('navSignals'),
      line: signalCount ? t('moreSignalsCount', { n: signalCount }) : t('moreSignalsAbout'),
      testid: 'more-signals',
    },
  ]);
</script>

<h1>{t('moreTitle')}</h1>
<ul class="links" data-testid="more-links" data-help="more.links">
  {#each entries as entry (entry.href)}
    <li>
      <Card bare as="a" class="more-link" href={entry.href} data-testid={entry.testid}>
        <span class="glyph"><Icon name={entry.icon} size={22} /></span>
        <span class="text">
          <span class="title">{entry.title}</span>
          <span class="line">{entry.line}</span>
        </span>
        {#if entry.badge}
          <Pill tone={entry.badgeTone} class="more-badge">{entry.badge}</Pill>
        {/if}
        <Icon name="chevronRight" size={18} class="go" />
      </Card>
    </li>
  {/each}
</ul>

<style>
  .links {
    list-style: none;
    margin: 0;
    padding: 0;
    display: grid;
    gap: var(--space-3);
    grid-template-columns: repeat(auto-fill, minmax(min(100%, 20rem), 1fr));
  }
  :global(.more-link) {
    display: flex;
    align-items: center;
    gap: var(--space-3);
    min-height: 4.25rem;
    text-decoration: none;
    color: var(--text);
  }
  :global(.more-link:hover) {
    border-color: var(--accent);
  }
  .glyph {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 2.5rem;
    height: 2.5rem;
    border-radius: var(--radius);
    background: var(--surface-2);
    color: var(--accent);
    flex: none;
  }
  .text {
    display: flex;
    flex-direction: column;
    gap: 0.1rem;
    flex: 1;
    min-width: 0;
  }
  .title {
    font-weight: var(--fw-semibold);
    font-size: var(--fs-emph);
  }
  .line {
    color: var(--muted);
    font-size: var(--fs-body);
  }
  :global(.more-badge) {
    min-width: 1.5rem;
    padding: 0.05rem 0.45rem;
    border-radius: var(--radius-pill);
    font-weight: var(--fw-bold);
    font-size: var(--fs-caption);
    text-align: center;
  }
  :global(.more-link) :global(.go) {
    color: var(--muted);
  }
</style>
