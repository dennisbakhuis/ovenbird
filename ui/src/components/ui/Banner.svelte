<script lang="ts" module>
  export type NoticeTone = 'ok' | 'info' | 'warn' | 'bad';

  export interface Notice {
    id: number;
    text: string;
    tone: NoticeTone;
    testid: string;
  }

  export const SUCCESS_TIMEOUT_MS = 8000;

  const notices = $state<Notice[]>([]);
  const timers: Record<number, ReturnType<typeof setTimeout>> = {};
  let nextId = 1;

  /**
   * Remove a notice by id.
   */
  export function dismiss(id: number): void {
    const timer = timers[id];
    if (timer !== undefined) clearTimeout(timer);
    delete timers[id];
    const index = notices.findIndex((notice) => notice.id === id);
    if (index >= 0) notices.splice(index, 1);
  }

  /**
   * Show a page-level notice under the header. Success and info notices go away after 8 s
   * and on the next page change; warnings and errors stay until closed. Returns the id.
   */
  export function notify(
    text: string,
    options: { tone?: NoticeTone; testid?: string; timeoutMs?: number | null } = {},
  ): number {
    const tone = options.tone ?? 'ok';
    const id = nextId;
    nextId += 1;
    notices.push({ id, text, tone, testid: options.testid ?? 'notice' });
    const timeout =
      options.timeoutMs === undefined
        ? tone === 'ok' || tone === 'info'
          ? SUCCESS_TIMEOUT_MS
          : null
        : options.timeoutMs;
    if (timeout !== null) timers[id] = setTimeout(() => dismiss(id), timeout);
    return id;
  }

  /**
   * Remove the notices that should not follow the user to another page.
   */
  export function clearTransient(): void {
    for (const notice of [...notices]) {
      if (notice.tone === 'ok' || notice.tone === 'info') dismiss(notice.id);
    }
  }

  /**
   * Current notices, newest last.
   */
  export function currentNotices(): readonly Notice[] {
    return notices;
  }
</script>

<script lang="ts">
  import type { LiveStore } from '$lib/core/live.svelte';
  import { router } from '$lib/core/router.svelte';
  import { t } from '$lib/core/settings.svelte';
  import type { IconName } from '$lib/core/icons';
  import Button from './Button.svelte';
  import Icon from './Icon.svelte';

  let { live }: { live: LiveStore } = $props();

  const heishamonDown = $derived(live.snapshot !== null && !live.snapshot.heishamon.alive);
  const ICON: Record<NoticeTone, IconName> = {
    ok: 'check',
    info: 'info',
    warn: 'warning',
    bad: 'critical',
  };

  let page = router.route + router.location.sub.join('/');
  $effect(() => {
    const next = router.route + router.location.sub.join('/');
    if (next !== page) {
      page = next;
      clearTransient();
    }
  });
</script>

<div class="banners" role="status" aria-live="polite">
  {#if !live.connected}
    <p class="banner bad" data-testid="banner-disconnected">
      <Icon name="critical" size={18} />{t('bannerDisconnected')}
    </p>
  {/if}
  {#if heishamonDown}
    <p class="banner warn" data-testid="banner-heishamon">
      <Icon name="warning" size={18} />{t('bannerHeishamon')}
    </p>
  {/if}
  {#each notices as notice (notice.id)}
    <p class="banner {notice.tone}" data-testid={notice.testid}>
      <Icon name={ICON[notice.tone]} size={18} />
      <span class="text">{notice.text}</span>
      <Button class="banner-close" onclick={() => dismiss(notice.id)} aria-label={t('close')}>
        <Icon name="close" size={18} />
      </Button>
    </p>
  {/each}
</div>

<style>
  .banners {
    position: sticky;
    top: 0;
    z-index: var(--z-menu);
  }
  .banner {
    display: flex;
    align-items: center;
    gap: var(--space-2);
    margin: 0;
    padding: var(--space-2) var(--space-4);
    font-weight: var(--fw-semibold);
  }
  .text {
    flex: 1;
    min-width: 0;
  }
  .bad {
    background: var(--err-bg);
    color: var(--err-text);
  }
  .warn {
    background: var(--warn-bg);
    color: var(--warn-text);
  }
  .ok {
    background: var(--status-ok-bg);
    color: var(--status-ok);
  }
  .info {
    background: var(--status-manual-bg);
    color: var(--status-manual);
  }
  :global(.banner-close) {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    min-width: 36px;
    min-height: 36px;
    padding: 0;
    border-color: transparent;
    background: transparent;
    color: inherit;
  }
  @media (--narrow), (pointer: coarse) {
    :global(.banner-close) {
      min-width: var(--tap);
      min-height: var(--tap);
      margin: -4px;
    }
  }
</style>
