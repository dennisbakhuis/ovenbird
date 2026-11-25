<!--
  The help drawer. Wide screens: a 26rem panel on the right, beside the page (no backdrop; at
  1100px and up the page makes room for it). Phones: a full-height modal sheet that collapses
  to a "Back to help" bar while "Show me" rings something on the page. It shows the topic of
  the page and tab the router is on and follows navigation. Help about a part of the installation
  the app hides (hot water) is left out or shown in its text without it.
-->
<script lang="ts">
  import TextInput from '$ui/TextInput.svelte';
  import Button from '$ui/Button.svelte';
  import { tick, untrack } from 'svelte';
  import { helpContent, type HelpContent } from '$lib/help/content';
  import { hiddenFeatures, shownGlossary, shownTopic } from '$lib/help/features';
  import { hotWater } from '$lib/core/hotWater.svelte';
  import { plainText } from '$lib/help/markup';
  import { hrefFor, topicFor } from '$lib/help/resolve';
  import { searchHelp, type HelpHit } from '$lib/help/search';
  import { HelpNav, type HelpFocus, type HelpView } from '$lib/help/nav.svelte';
  import type { HelpStore } from '$lib/help/store.svelte';
  import type { ArtName, GlossaryEntry, HelpTopic, HelpTopicId } from '$lib/help/types';
  import { router } from '$lib/core/router.svelte';
  import { WIDE_QUERY, NARROW_QUERY } from '$lib/core/breakpoints';
  import { settings, t } from '$lib/core/settings.svelte';
  import Icon from '$ui/Icon.svelte';
  import Overlay from '$ui/Overlay.svelte';
  import { provideGlossary } from './context';
  import HelpArt from './HelpArt.svelte';
  import HelpGlossary from './HelpGlossary.svelte';
  import HelpIndex from './HelpIndex.svelte';
  import HelpResults from './HelpResults.svelte';
  import HelpText from './HelpText.svelte';
  import HelpTopicBody from './HelpTopicBody.svelte';
  import Spotlight from './Spotlight.svelte';

  interface Props {
    store: HelpStore;
    content?: HelpContent;
  }

  let { store, content = helpContent }: Props = $props();

  const nav = new HelpNav();

  $effect(() => {
    const target = store.request.target;
    void store.request.seq;
    untrack(() => nav.start(target));
  });

  $effect(() => {
    const follow = () => nav.follow();
    window.addEventListener('hashchange', follow);
    return () => window.removeEventListener('hashchange', follow);
  });

  const media = (query: string) =>
    typeof window !== 'undefined' && typeof window.matchMedia === 'function'
      ? window.matchMedia(query).matches
      : false;

  const language = $derived(settings.language);
  const pageId = $derived(topicFor(router.location, (id) => content.has(language, id)));
  const topicId = $derived<HelpTopicId | null>(
    nav.view.kind === 'topic' ? nav.view.id : nav.view.kind === 'page' ? pageId : null,
  );

  let topic = $state<HelpTopic | null>(null);
  let loading = $state(true);
  let topics = $state<HelpTopic[]>([]);
  let glossary = $state<GlossaryEntry[]>([]);
  let expanded = $state<Record<string, boolean>>({});
  let query = $state('');
  let present = $state(new Set<string>());
  let phone = $state(media(NARROW_QUERY));
  let dock = $state(media(WIDE_QUERY));
  let collapsed = $state(false);
  let panel: HTMLDivElement | undefined = $state();
  let heading: HTMLHeadingElement | undefined = $state();
  let scroller: HTMLDivElement | undefined = $state();

  const hidden = $derived(hiddenFeatures(hotWater.shown));

  $effect(() => {
    const id = topicId;
    const lang = language;
    const without = hidden;
    if (!id) return;
    let current = true;
    loading = true;
    void content.topic(lang, id).then((found) => {
      if (!current) return;
      topic = found ? shownTopic(found, without) : null;
      loading = false;
    });
    return () => {
      current = false;
    };
  });

  $effect(() => {
    const lang = language;
    const without = hidden;
    let current = true;
    void Promise.all([content.topics(lang), content.glossary(lang)]).then(([all, entries]) => {
      if (!current) return;
      topics = all.map((item) => shownTopic(item, without));
      glossary = shownGlossary(entries, without);
    });
    return () => {
      current = false;
    };
  });

  const glossaryById = $derived(new Map(glossary.map((entry) => [entry.id, entry])));
  const titles = $derived(Object.fromEntries(topics.map((item) => [item.id, item.title])));
  const hits = $derived(query.trim() ? searchHelp(query, topics, glossary) : []);

  provideGlossary({
    get: (id) => glossaryById.get(id),
    more: (id) => move({ kind: 'glossary', entry: id }),
  });

  const hero = $derived.by((): { art?: ArtName; title: string; lead: string } | null => {
    const view = nav.view;
    if (view.kind === 'index')
      return { art: 'welcome', title: t('helpAllTopics'), lead: t('helpIndexLead') };
    if (view.kind === 'glossary') {
      const entry = view.entry ? glossaryById.get(view.entry) : undefined;
      return entry
        ? { title: entry.term, lead: plainText(entry.short) }
        : { title: t('helpGlossary'), lead: t('helpGlossaryLead') };
    }
    return topic ? { art: topic.art, title: topic.title, lead: topic.lead } : null;
  });

  $effect(() => {
    void nav.view;
    query = '';
    scroller?.scrollTo?.({ top: 0 });
  });

  $effect(() => {
    const phoneQuery = window.matchMedia?.(NARROW_QUERY);
    const dockQuery = window.matchMedia?.(WIDE_QUERY);
    const update = () => {
      phone = phoneQuery?.matches ?? false;
      dock = dockQuery?.matches ?? false;
    };
    phoneQuery?.addEventListener('change', update);
    dockQuery?.addEventListener('change', update);
    return () => {
      phoneQuery?.removeEventListener('change', update);
      dockQuery?.removeEventListener('change', update);
    };
  });

  $effect(() => {
    if (!store.open) collapsed = false;
  });

  $effect(() => {
    if (!phone) collapsed = false;
  });

  const modal = $derived(store.open && phone && !collapsed);

  $effect(() => {
    if (!store.open || !dock || phone) return;
    const root = document.documentElement;
    root.classList.add('help-docked');
    return () => root.classList.remove('help-docked');
  });

  $effect(() => {
    if (!store.open) return;
    let last = '';
    let frame = 0;
    const scan = () => {
      const found: string[] = [];
      for (const element of document.querySelectorAll<HTMLElement>('[data-help]')) {
        if (element.closest('[data-help-drawer]')) continue;
        const target = element.dataset['help'];
        if (target && element.getClientRects().length > 0) found.push(target);
      }
      const key = found.sort().join('|');
      if (key !== last) {
        last = key;
        present = new Set(found);
      }
    };
    const schedule = () => {
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(scan);
    };
    scan();
    const observer = new MutationObserver(schedule);
    observer.observe(document.body, {
      subtree: true,
      childList: true,
      attributes: true,
      attributeFilter: ['data-help', 'hidden'],
    });
    window.addEventListener('resize', schedule);
    return () => {
      cancelAnimationFrame(frame);
      observer.disconnect();
      window.removeEventListener('resize', schedule);
    };
  });

  let wasOpen = false;
  $effect(() => {
    const open = store.open;
    if (open && !wasOpen && !untrack(() => nav.focus))
      void tick().then(() => (heading ?? panel)?.focus({ preventScroll: true }));
    wasOpen = open;
  });

  function move(view: HelpView, focus?: Omit<HelpFocus, 'seq'>): void {
    nav.go(view, focus);
    if (!focus) void tick().then(() => heading?.focus({ preventScroll: true }));
  }

  function back(): void {
    nav.back();
    void tick().then(() => heading?.focus({ preventScroll: true }));
  }

  function showTopic(id: HelpTopicId): void {
    move(id === pageId ? { kind: 'page' } : { kind: 'topic', id });
  }

  function pick(hit: HelpHit): void {
    query = '';
    if (hit.kind === 'term') move({ kind: 'glossary', entry: hit.term });
    else if (hit.kind === 'topic') showTopic(hit.topic);
    else {
      const view =
        hit.topic === pageId
          ? ({ kind: 'page' } as const)
          : ({ kind: 'topic', id: hit.topic } as const);
      move(view, hit.kind === 'section' ? { section: hit.section } : { question: hit.question });
    }
  }

  function showMe(target: string): void {
    nav.point(target);
    if (phone) collapsed = true;
  }

  const unpoint = () => nav.unpoint();

  async function expand(): Promise<void> {
    nav.unpoint();
    collapsed = false;
    await tick();
    panel?.querySelector<HTMLElement>('[data-testid="help-show-me"]')?.focus();
  }

  function onWindowKey(event: KeyboardEvent): void {
    if (event.key !== 'Escape' || !store.open || event.defaultPrevented) return;
    if (document.querySelector('[aria-modal="true"]:not([data-help-panel])')) return;
    store.close();
  }
</script>

<svelte:window onkeydown={onWindowKey} />

{#if store.open}
  <Overlay
    layer="drawer"
    {modal}
    escapePrevent
    onclose={() => store.close()}
    layerClass="help-layer"
    layerAttrs={{ 'data-help-drawer': '' }}
    class="drawer {phone ? 'sheet' : ''} {collapsed ? 'collapsed' : ''}"
    role="dialog"
    aria-label={t('helpTitle')}
    bind:element={panel}
    data-help-panel
    data-testid="help-drawer"
    data-topic={nav.view.kind === 'index' || nav.view.kind === 'glossary' ? nav.view.kind : topicId}
  >
    <header class="bar">
      {#if nav.history.length}
        <Button class="help-icon-btn help-back" onclick={back} data-testid="help-back">
          <Icon name="chevronRight" size={20} class="flip" />
          <span>{t('helpBack')}</span>
        </Button>
      {:else}
        <span class="eyebrow"><Icon name="why" size={18} />{t('helpTitle')}</span>
      {/if}
      <Button
        class="help-icon-btn help-close"
        onclick={() => store.close()}
        aria-label={t('close')}
        data-testid="help-close"
      >
        <Icon name="close" size={20} />
      </Button>
    </header>

    <div class="scroll" bind:this={scroller}>
      {#if hero?.art}<HelpArt name={hero.art} />{/if}
      <h2 tabindex="-1" bind:this={heading} class:muted={!hero && loading} data-testid="help-title">
        {hero ? hero.title : loading ? t('helpLoading') : t('helpTitle')}
      </h2>
      {#if hero}
        <div class="lead"><HelpText body={hero.lead} /></div>
        {@const goto =
          topicId && topicId !== pageId && nav.view.kind === 'topic' ? hrefFor(topicId) : null}
        {#if goto}
          <a class="goto" href={goto} data-testid="help-goto">
            {t('helpGoToPage')}<Icon name="arrowRight" size={16} />
          </a>
        {/if}
      {:else if !loading}
        <p class="lead">{t('helpMissing')}</p>
      {/if}

      <label class="search">
        <span class="visually-hidden">{t('helpSearch')}</span>
        <TextInput
          class="help-search-input"
          type="search"
          bind:value={query}
          placeholder={t('helpSearchPlaceholder')}
          autocomplete="off"
          spellcheck="false"
          data-testid="help-search"
        />
      </label>

      <div class="content">
        {#if query.trim()}
          <HelpResults {hits} query={query.trim()} onPick={pick} />
        {:else if nav.view.kind === 'index'}
          <HelpIndex
            {topics}
            current={pageId}
            onTopic={showTopic}
            onGlossary={() => move({ kind: 'glossary' })}
          />
        {:else if nav.view.kind === 'glossary'}
          <HelpGlossary
            entries={glossary}
            entry={nav.view.entry}
            onEntry={(id) => move({ kind: 'glossary', entry: id })}
          />
        {:else if topic}
          <HelpTopicBody
            {topic}
            {titles}
            {present}
            focus={nav.focus}
            bind:expanded
            onShow={showMe}
            onTopic={showTopic}
          />
        {/if}
      </div>

      {#if !query.trim()}
        <nav class="more" aria-label={t('helpTitle')}>
          {#if nav.view.kind !== 'index'}
            <Button
              class="help-link"
              onclick={() => move({ kind: 'index' })}
              data-testid="help-all-topics"
            >
              {t('helpAllTopics')}
            </Button>
          {/if}
          {#if nav.view.kind !== 'glossary' || nav.view.entry}
            <Button
              class="help-link"
              onclick={() => move({ kind: 'glossary' })}
              data-testid="help-glossary-link"
            >
              {t('helpGlossary')}
            </Button>
          {/if}
        </nav>
        {#if !phone}<p class="hint">{t('helpKeyHint')}</p>{/if}
      {/if}
    </div>

    {#snippet beside()}
      {#if collapsed}
        <div class="backbar" role="region" aria-label={t('helpTitle')} data-testid="help-backbar">
          <Button class="help-return" onclick={expand} data-testid="help-return">
            <Icon name="why" size={20} />{t('helpBackToHelp')}
          </Button>
          <Button class="help-icon-btn" onclick={() => store.close()} aria-label={t('close')}>
            <Icon name="close" size={20} />
          </Button>
        </div>
      {/if}

      {#if nav.spotlight}
        {#key nav.spotlight.seq}
          <Spotlight target={nav.spotlight.target} ondone={unpoint} />
        {/key}
      {/if}
    {/snippet}
  </Overlay>
{/if}

<style>
  :global(html.help-docked body) {
    padding-right: 26rem;
  }
  :global(.drawer) {
    position: absolute;
    top: 0;
    right: 0;
    bottom: 0;
    width: min(26rem, 100%);
    display: flex;
    flex-direction: column;
    background: var(--bg);
    color: var(--text);
    border-left: 1px solid var(--border);
    box-shadow: var(--shadow-pop);
    font-size: var(--fs-body);
    animation: slide-in 0.2s ease-out;
  }
  :global(.drawer.sheet) {
    left: 0;
    width: auto;
    border-left: none;
    box-shadow: none;
    padding-bottom: env(safe-area-inset-bottom);
    animation-name: rise-in;
  }
  :global(.drawer.collapsed) {
    display: none;
  }
  @keyframes slide-in {
    from {
      transform: translateX(1.5rem);
      opacity: 0;
    }
  }
  @keyframes rise-in {
    from {
      transform: translateY(1.5rem);
      opacity: 0;
    }
  }
  .bar {
    flex: none;
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: var(--space-2);
    min-height: 52px;
    padding: 0 var(--space-2) 0 var(--space-4);
    background: var(--surface);
    border-bottom: 1px solid var(--border);
  }
  .eyebrow {
    display: inline-flex;
    align-items: center;
    gap: 0.4rem;
    color: var(--muted);
    font-weight: var(--fw-bold);
  }
  :global(.help-icon-btn) {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    gap: var(--space-1);
    min-width: var(--tap);
    min-height: var(--tap);
    padding: 0;
    border: none;
    border-radius: var(--radius-control);
    background: transparent;
    color: var(--muted);
    font-weight: var(--fw-semibold);
  }
  :global(.help-icon-btn):hover {
    background: var(--surface-2);
    color: var(--text);
  }
  :global(.help-back) {
    margin-left: calc(-1 * var(--space-2));
    padding: 0 0.6rem 0 0.3rem;
    color: var(--accent);
  }
  :global(.help-back) :global(.flip) {
    transform: scaleX(-1);
  }
  .scroll {
    flex: 1;
    min-height: 0;
    overflow-y: auto;
    overscroll-behavior: contain;
    padding: var(--space-4) var(--space-4) var(--space-6);
  }
  h2 {
    margin: 0;
    font-family: var(--font-display);
    font-size: var(--fs-value);
    line-height: var(--lh-tight);
  }
  h2:focus {
    outline: none;
  }
  h2.muted {
    color: var(--muted);
    font-weight: var(--fw-semibold);
  }
  .lead {
    margin: var(--space-2) 0 0;
    color: var(--muted);
    font-size: var(--fs-emph);
    line-height: var(--lh-body);
  }
  .goto {
    display: inline-flex;
    align-items: center;
    gap: 0.3rem;
    margin-top: var(--space-2);
    color: var(--accent);
    font-weight: var(--fw-bold);
  }
  .search {
    display: block;
    margin: var(--space-4) 0;
  }
  .search :global(.help-search-input) {
    width: 100%;
    min-height: var(--control-h);
    padding: 0 var(--space-3);
    border: 1px solid var(--border);
    border-radius: var(--radius-pill);
    background: var(--surface);
    color: var(--text);
    font: inherit;
  }
  .search :global(.help-search-input:focus-visible) {
    outline: 3px solid var(--accent);
    outline-offset: 1px;
  }
  .visually-hidden {
    position: absolute;
    width: 1px;
    height: 1px;
    overflow: hidden;
    clip-path: inset(50%);
    white-space: nowrap;
  }
  .more {
    display: flex;
    flex-wrap: wrap;
    gap: var(--space-2) var(--space-4);
    margin-top: var(--space-5);
    padding-top: var(--space-4);
    border-top: 1px solid var(--border);
  }
  :global(.help-link) {
    min-height: 36px;
    padding: 0;
    border: none;
    background: none;
    color: var(--accent);
    font: inherit;
    font-weight: var(--fw-bold);
    cursor: pointer;
  }
  :global(.help-link):hover {
    text-decoration: underline;
  }
  .hint {
    margin: var(--space-3) 0 0;
    color: var(--muted);
    font-size: var(--fs-caption);
  }
  .backbar {
    position: absolute;
    left: var(--space-3);
    right: var(--space-3);
    bottom: calc(56px + env(safe-area-inset-bottom) + var(--space-3));
    display: flex;
    align-items: center;
    gap: var(--space-1);
    padding: var(--space-1);
    pointer-events: auto;
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: var(--radius-pill);
    box-shadow: var(--shadow-pop);
  }
  :global(.help-return) {
    flex: 1;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    gap: 0.4rem;
    min-height: var(--tap);
    border: none;
    border-radius: var(--radius-pill);
    background: var(--accent);
    color: var(--on-accent);
    font-weight: var(--fw-bold);
  }
  @media (--narrow), (pointer: coarse) {
    :global(.help-link) {
      min-height: var(--tap);
    }
    .search :global(.help-search-input) {
      min-height: var(--tap);
    }
  }
  @media (prefers-reduced-motion: reduce) {
    :global(.drawer) {
      animation: none;
    }
  }
</style>
