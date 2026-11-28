<script lang="ts">
  import Button from '$ui/Button.svelte';
  import type { Component } from 'svelte';
  import Banner from '$ui/Banner.svelte';
  import ControlLine from '$components/shell/ControlLine.svelte';
  import HelpButton from '$components/help/HelpButton.svelte';
  import Icon from '$ui/Icon.svelte';
  import Segmented from '$ui/Segmented.svelte';
  import Logo from '$components/brand/Logo.svelte';
  import VersionLink from '$components/shell/VersionLink.svelte';
  import StatusStrip from '$components/shell/StatusStrip.svelte';
  import Why from '$ui/Why.svelte';
  import { cfg } from '$lib/core/cfg.svelte';
  import { recover, retrying } from '$lib/core/chunks';
  import { draft } from '$lib/core/draft.svelte';
  import { help } from '$lib/help/store.svelte';
  import type { ControlStore } from '$lib/core/control.svelte';
  import { LANGUAGES, type LanguagePreference, type MessageKey } from '$lib/i18n';
  import { isSimulation } from '$lib/core/mode';
  import { notifyHealth } from '$lib/notify/notifyHealth.svelte';
  import type { IconName } from '$lib/core/icons';
  import type { LiveStore } from '$lib/core/live.svelte';
  import { router, type Route } from '$lib/core/router.svelte';
  import { settings, t } from '$lib/core/settings.svelte';
  import { THEME_PREFERENCES } from '$lib/core/theme';
  import Home from './pages/Home.svelte';

  let { live, ctl }: { live: LiveStore; ctl: ControlStore } = $props();

  type NavRoute = Exclude<Route, 'dev-charts'>;

  const NAV: Record<NavRoute, { key: MessageKey; icon: IconName }> = {
    home: { key: 'navHome', icon: 'home' },
    setpoint: { key: 'navSetpoint', icon: 'target' },
    weather: { key: 'navWeather', icon: 'weather' },
    pump: { key: 'navPump', icon: 'pump' },
    settings: { key: 'navSettings', icon: 'settings' },
    activity: { key: 'navActivity', icon: 'bell' },
    system: { key: 'navSystem', icon: 'cpu' },
    more: { key: 'navMore', icon: 'more' },
    house: { key: 'navHouse', icon: 'house' },
  };

  const LANGUAGE_OPTIONS: LanguagePreference[] = ['auto', ...LANGUAGES];
  const TOP: NavRoute[] = ['home', 'setpoint', 'weather', 'pump', 'house'];
  const BOTTOM: NavRoute[] = ['home', 'setpoint', 'weather', 'pump', 'more'];
  const MORE_GROUP: Route[] = ['more', 'settings', 'activity', 'system', 'house'];
  const isCurrent = (route: Route, bottom = false) =>
    bottom && route === 'more' ? MORE_GROUP.includes(router.route) : router.route === route;

  const galleries: Record<string, () => Promise<{ default: Component }>> =
    import.meta.env.MODE === 'mock'
      ? import.meta.glob<{ default: Component }>('./components/charts/*Gallery.svelte')
      : {};
  const loadGallery = Object.values(galleries)[0];
  const devCharts = loadGallery !== undefined;

  type Loader = () => Promise<{ default: Component<{ live: LiveStore; ctl: ControlStore }> }>;
  const once = (load: Loader): Loader => retrying(load);
  const lazy = {
    setpoint: once(() => import('./pages/Setpoint.svelte')),
    weather: once(() => import('./pages/Weather.svelte')),
    pump: once(() => import('./pages/Pump.svelte')),
    settings: once(() => import('./pages/Settings.svelte')),
    activity: once(() => import('./pages/Activity.svelte')),
    system: once(() => import('./pages/System.svelte')),
    more: once(() => import('./pages/More.svelte')),
    house: once(() => import('./pages/House.svelte')),
    draftBar: once(() => import('$components/shell/DraftBar.svelte')),
  };

  type DrawerProps = {
    store: typeof help;
  };
  const loadHelp = retrying<{ default: Component<DrawerProps> }>(
    () => import('$components/help/HelpDrawer.svelte'),
    () => {
      help.close();
      void recover();
    },
  );
  const helpDrawer = $derived(help.request.seq > 0 ? loadHelp() : null);

  $effect(() => {
    const prefetch = () =>
      [...Object.values(lazy), loadHelp].forEach((load) => void load().catch(() => {}));
    const timer = setTimeout(prefetch, 1500);
    return () => clearTimeout(timer);
  });

  $effect(() => notifyHealth.start());

  let draftSeen = $state(false);
  $effect(() => {
    if (draft.count > 0) draftSeen = true;
  });

  const alarmCount = $derived(ctl.control?.alarms.length ?? 0);
  const alarmBadgeTone = $derived(
    ctl.control?.alarms.some((a) => a.severity === 'critical')
      ? 'stopped'
      : ctl.control?.alarms.some((a) => a.severity === 'warning')
        ? 'limited'
        : 'manual',
  );
  const appVersion = $derived(live.health?.version ?? null);
  const simulation = $derived(isSimulation(ctl.config));

  let menuOpen = $state(false);
  const languageOptions = $derived(
    LANGUAGE_OPTIONS.map((option) => ({
      value: option,
      label: option === 'auto' ? t('langAuto') : t(`langName_${option}` as MessageKey),
      testid: `language-${option}`,
    })),
  );
  const themeOptions = $derived(
    THEME_PREFERENCES.map((option) => ({
      value: option,
      label: t(`theme_${option}` as MessageKey),
      testid: `theme-${option}`,
    })),
  );

  $effect(() => {
    document.documentElement.lang = settings.language;
  });

  $effect(() => {
    cfg.schedule(draft.changes);
  });

  $effect(() => {
    void live.decisionSeq;
    void ctl.refresh();
  });
</script>

<a class="skip" href="#main">{t('skipToContent')}</a>
<Banner {live} />

<div class="topbar-box">
  <div class="topbar" class:framed={settings.framed} data-testid="topbar">
    <div class="brand-box">
      <a class="brand" href="#/home" aria-label={t('appName')}>
        <Logo size={34} wordmark />
      </a>
      <VersionLink version={appVersion} testid="app-version" />
    </div>

    <nav class="top" aria-label={t('navMain')} data-testid="top-nav">
      <ul>
        {#each TOP as route (route)}
          <li>
            <a
              href="#/{route}"
              aria-current={isCurrent(route) ? 'page' : undefined}
              title={t(NAV[route].key)}
            >
              <Icon name={NAV[route].icon} size={18} />
              <span class="nav-label">{t(NAV[route].key)}</span>
            </a>
          </li>
        {/each}
      </ul>
    </nav>

    <div class="strip-slot">
      <StatusStrip {live} {ctl} />
    </div>

    <div class="tools">
      {#if simulation}
        <span class="sim" title={t('simBadgeTitle')} data-testid="sim-badge">
          <span class="sim-long">{t('simBadge')}</span>
          <span class="sim-short" aria-hidden="true">{t('simBadgeShort')}</span>
        </span>
      {/if}
      <a
        class="tool desk"
        href="#/settings"
        aria-current={isCurrent('settings') ? 'page' : undefined}
        aria-label={t('navSettings')}
        title={t('navSettings')}
        data-testid="nav-settings"
      >
        <Icon name="settings" size={20} />
      </a>
      <a
        class="tool desk"
        href="#/activity"
        aria-current={isCurrent('activity') ? 'page' : undefined}
        aria-label={alarmCount ? t('navActivityAlarms', { n: alarmCount }) : t('navActivity')}
        title={t('navActivity')}
        data-testid="nav-activity"
      >
        <Icon name="bell" size={20} />
        {#if alarmCount}<span class="badge {alarmBadgeTone}" aria-hidden="true">{alarmCount}</span
          >{/if}
      </a>
      <a
        class="tool desk"
        href="#/system"
        aria-current={isCurrent('system') ? 'page' : undefined}
        aria-label={t('navSystem')}
        title={t('navSystem')}
        data-testid="nav-system"
      >
        <Icon name="cpu" size={20} />
      </a>
      <HelpButton />
      <Why
        title={t('menuLabel')}
        bind:open={menuOpen}
        align="end"
        width="19rem"
        triggerClass="tool"
        testid="settings-menu"
      >
        {#snippet trigger()}
          <Icon name="gear" size={20} />
        {/snippet}
        <fieldset class="choice">
          <legend><Icon name="globe" size={16} />{t('language')}</legend>
          <Segmented
            options={languageOptions}
            value={settings.preference}
            onchange={(option) => settings.setPreference(option)}
            semantics="radio"
            appearance="joined"
            name="ovenbird-language"
            label={t('language')}
            tint
            fill
          />
          {#if settings.preference === 'auto'}
            <p class="hint">
              {t('langBrowser', {
                language: t(`langName_${settings.browserLanguage}` as MessageKey),
              })}
            </p>
          {/if}
        </fieldset>
        <fieldset class="choice">
          <legend><Icon name="contrast" size={16} />{t('menuTheme')}</legend>
          <Segmented
            options={themeOptions}
            value={settings.theme}
            onchange={(option) => settings.setTheme(option)}
            semantics="radio"
            appearance="joined"
            name="ovenbird-theme"
            label={t('menuTheme')}
            tint
            fill
          />
        </fieldset>
        {#if appVersion}<p class="hint">{t('menuVersion', { version: appVersion })}</p>{/if}
      </Why>
    </div>
  </div>
</div>

<ControlLine {live} {ctl} />

{#if help.request.seq > 0 && helpDrawer}
  {#await helpDrawer then drawer}
    <drawer.default store={help} />
  {/await}
{/if}

{#if draftSeen}
  {#await lazy.draftBar() then bar}<bar.default {live} {ctl} />{/await}
{/if}

{#snippet failed()}
  <div class="load-failed" role="alert" data-testid="page-load-failed">
    <p>{t('pageLoadFailed')}</p>
    <Button onclick={() => location.reload()}>{t('pageReload')}</Button>
  </div>
{/snippet}

<main id="main" tabindex="-1" class:framed={settings.framed}>
  {#if router.route === 'home'}
    <Home {live} {ctl} />
  {:else if router.route === 'setpoint'}
    {#await lazy.setpoint() then page}<page.default
        {live}
        {ctl}
      />{:catch}{@render failed()}{/await}
  {:else if router.route === 'weather'}
    {#await lazy.weather() then page}<page.default {live} {ctl} />{:catch}{@render failed()}{/await}
  {:else if router.route === 'settings'}
    {#await lazy.settings() then page}<page.default
        {live}
        {ctl}
      />{:catch}{@render failed()}{/await}
  {:else if router.route === 'pump'}
    {#await lazy.pump() then page}<page.default {live} {ctl} />{:catch}{@render failed()}{/await}
  {:else if router.route === 'more'}
    {#await lazy.more() then page}<page.default {live} {ctl} />{:catch}{@render failed()}{/await}
  {:else if router.route === 'activity'}
    {#await lazy.activity() then page}<page.default
        {live}
        {ctl}
      />{:catch}{@render failed()}{/await}
  {:else if router.route === 'system'}
    {#await lazy.system() then page}<page.default {live} {ctl} />{:catch}{@render failed()}{/await}
  {:else if router.route === 'house'}
    {#await lazy.house() then page}<page.default {live} {ctl} />{:catch}{@render failed()}{/await}
  {:else if devCharts && loadGallery}
    {#await loadGallery() then gallery}
      <gallery.default />
    {/await}
  {:else}
    <Home {live} {ctl} />
  {/if}
</main>

<nav class="bottom" aria-label={t('navBottom')} data-testid="bottom-nav">
  <ul>
    {#each BOTTOM as route (route)}
      <li>
        <a
          href="#/{route}"
          aria-current={isCurrent(route, true) ? 'page' : undefined}
          aria-label={route === 'more' && alarmCount
            ? t('navMoreAlarms', { n: alarmCount })
            : undefined}
        >
          <span class="glyph">
            <Icon name={NAV[route].icon} size={24} />
            {#if route === 'more' && alarmCount}
              <span class="badge {alarmBadgeTone}" aria-hidden="true">{alarmCount}</span>
            {/if}
          </span>
          <span class="label">{t(NAV[route].key)}</span>
        </a>
      </li>
    {/each}
  </ul>
</nav>

<style>
  .skip {
    position: absolute;
    left: -999px;
    top: 0;
    display: inline-flex;
    align-items: center;
    min-height: var(--tap);
    background: var(--surface);
    padding: var(--space-2) var(--space-4);
    z-index: var(--z-toast);
  }
  .skip:focus {
    left: 0;
  }
  .load-failed {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: var(--space-3);
    margin: var(--space-4) 0;
    padding: var(--space-4);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    background: var(--surface);
  }

  .load-failed p {
    margin: 0;
    flex: 1 1 16rem;
  }

  .topbar-box {
    container: topbar / inline-size;
  }
  .topbar {
    display: grid;
    grid-template-columns: auto minmax(0, 1fr) auto;
    grid-template-areas:
      'brand nav tools'
      'strip strip strip';
    align-items: center;
    column-gap: var(--space-4);
    background: var(--surface);
    border-bottom: 1px solid var(--border);
    padding: 0 var(--space-4);
  }
  .brand-box {
    grid-area: brand;
    display: inline-flex;
    align-items: center;
    gap: var(--space-2);
  }
  .brand {
    display: inline-flex;
    align-items: center;
    gap: 0.45rem;
    min-height: 52px;
    color: var(--text);
    text-decoration: none;
    font-weight: var(--fw-bold);
    font-size: var(--fs-title);
    letter-spacing: -0.01em;
  }
  nav.top {
    grid-area: nav;
    min-width: 0;
  }
  nav ul {
    display: flex;
    gap: 0.15rem;
    list-style: none;
    margin: 0;
    padding: 0;
  }
  nav.top ul {
    overflow-x: auto;
    scrollbar-width: none;
  }
  nav.top a {
    display: inline-flex;
    align-items: center;
    gap: 0.4rem;
    min-height: var(--control-h);
    padding: 0 0.7rem;
    border-radius: var(--radius-control);
    color: var(--muted);
    text-decoration: none;
    font-weight: var(--fw-semibold);
    white-space: nowrap;
  }
  nav.top a[aria-current='page'] {
    background: var(--status-manual-bg);
    color: var(--status-manual);
  }
  nav.top a:not([aria-current]):hover {
    background: var(--surface-2);
    color: var(--text);
  }
  .strip-slot {
    grid-area: strip;
    min-width: 0;
    padding: var(--space-2) 0;
    border-top: 1px solid var(--border);
  }
  .tools {
    grid-area: tools;
    display: flex;
    align-items: center;
    gap: 0.15rem;
  }
  .tools :global(.tool) {
    position: relative;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 40px;
    height: var(--control-h);
    min-height: 0;
    padding: 0;
    border: 1px solid transparent;
    border-radius: var(--radius-control);
    background: transparent;
    color: var(--muted);
  }
  .tools :global(.tool:hover),
  .tools :global(.tool[aria-expanded='true']) {
    background: var(--surface-2);
    color: var(--text);
    border-color: transparent;
  }
  .tools :global(.tool[aria-current='page']) {
    background: var(--status-manual-bg);
    color: var(--status-manual);
  }
  .sim {
    display: inline-flex;
    align-items: center;
    min-height: 28px;
    margin-right: var(--space-2);
    padding: 0 0.55rem;
    border: 1.5px solid var(--status-frozen);
    border-radius: var(--radius-sm);
    background: var(--status-frozen-bg);
    color: var(--status-frozen);
    font-size: var(--fs-caption);
    font-weight: var(--fw-extrabold);
    letter-spacing: 0.08em;
    text-transform: uppercase;
    white-space: nowrap;
  }
  .sim-short {
    display: none;
  }
  .badge {
    position: absolute;
    top: 2px;
    right: 0;
    min-width: 1.05rem;
    height: 1.05rem;
    padding: 0 var(--space-1);
    border-radius: var(--radius-pill);
    font-size: var(--fs-3xs);
    font-weight: var(--fw-bold);
    line-height: 1.05rem;
    text-align: center;
    border: 1.5px solid var(--surface);
    box-sizing: content-box;
  }
  .badge.stopped {
    background: var(--cat-stopped);
    color: var(--on-solid);
  }
  .badge.limited {
    background: var(--status-limited-bg);
    color: var(--status-limited);
    border-color: var(--cat-limited);
  }
  .badge.manual {
    background: var(--status-manual-bg);
    color: var(--status-manual);
  }
  .choice {
    border: none;
    margin: 0 0 var(--space-3);
    padding: 0;
    min-width: 0;
  }
  legend {
    display: inline-flex;
    align-items: center;
    gap: 0.35rem;
    padding: 0;
    margin-bottom: var(--space-2);
    color: var(--muted);
    font-weight: var(--fw-semibold);
    font-size: var(--fs-caption);
  }
  .hint {
    margin: var(--space-2) 0 0;
    color: var(--muted);
    font-size: var(--fs-caption);
  }
  main {
    container: main / inline-size;
    max-width: var(--page-max);
    margin: 0 auto;
    padding: var(--space-4) var(--space-5) var(--space-6);
  }
  main.framed {
    max-width: none;
    padding: var(--space-3) var(--space-4) var(--space-5);
  }
  main:focus {
    outline: none;
  }
  nav.bottom {
    display: none;
  }

  :global(html[data-framed]) .brand-box {
    display: none;
  }
  .topbar.framed {
    grid-template-columns: minmax(0, auto) minmax(0, 1fr) auto;
    grid-template-areas: 'nav strip tools';
    padding: 0 var(--space-3);
  }
  .topbar.framed .strip-slot {
    border-top: none;
    padding: 0;
  }

  @container topbar (max-width: 80rem) {
    .topbar.framed {
      grid-template-columns: minmax(0, 1fr) auto;
      grid-template-areas:
        'nav tools'
        'strip strip';
    }
    .topbar.framed .strip-slot {
      padding: var(--space-2) 0;
      border-top: 1px solid var(--border);
    }
  }

  @container topbar (max-width: 55rem) {
    nav.top a:not([aria-current]) {
      padding: 0 0.6rem;
    }
    nav.top a:not([aria-current]) .nav-label {
      position: absolute;
      width: 1px;
      height: 1px;
      overflow: hidden;
      clip-path: inset(50%);
      white-space: nowrap;
    }
  }

  @container topbar (max-width: 46rem) {
    nav.top a:not([aria-current]) {
      padding: 0 var(--space-2);
    }
    .brand-box :global(.slot) {
      display: none;
    }
  }

  @media (--narrow) {
    .topbar,
    .topbar.framed {
      grid-template-columns: minmax(0, 1fr) auto;
      grid-template-areas: 'strip tools';
      padding: 0 var(--space-2) 0 var(--space-3);
      column-gap: var(--space-2);
    }
    .brand-box,
    nav.top,
    .tools .desk {
      display: none;
    }
    .strip-slot,
    .topbar.framed .strip-slot {
      border-top: none;
      padding: var(--space-1) 0;
    }
    .tools :global(.tool) {
      width: var(--tap);
      height: var(--tap);
    }
    .sim {
      margin-right: 0;
      padding: 0 0.35rem;
    }
    .sim-long {
      display: none;
    }
    .sim-short {
      display: inline;
    }
    main,
    main.framed {
      padding: var(--space-3) var(--space-3) calc(4.75rem + env(safe-area-inset-bottom));
    }
    nav.bottom {
      display: block;
      position: fixed;
      left: 0;
      right: 0;
      bottom: 0;
      z-index: var(--z-nav);
      background: var(--surface);
      border-top: 1px solid var(--border);
      padding-bottom: env(safe-area-inset-bottom);
    }
    nav.bottom ul {
      gap: 0;
    }
    nav.bottom li {
      flex: 1;
      min-width: 0;
    }
    nav.bottom a {
      display: flex;
      flex-direction: column;
      align-items: center;
      justify-content: center;
      gap: 0.1rem;
      min-height: 56px;
      color: var(--muted);
      text-decoration: none;
      font-size: var(--fs-caption);
      font-weight: var(--fw-medium);
    }
    nav.bottom a[aria-current='page'] {
      color: var(--accent);
      font-weight: var(--fw-bold);
    }
    nav.bottom a[aria-current='page'] .glyph {
      background: var(--status-manual-bg);
      color: var(--status-manual);
    }
    .glyph {
      position: relative;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      width: 3.25rem;
      height: 1.85rem;
      border-radius: var(--radius-pill);
    }
    .glyph .badge {
      top: -3px;
      right: 2px;
    }
    .label {
      max-width: 100%;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
  }
</style>
