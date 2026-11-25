<!--
  SystemTiles: the second row of System → Overview: Notifications, Safety net and About this
  installation, loaded from `notifications/status` and `system/about` (refreshed every minute).
  An older service without these endpoints gets a calm "not offered yet" line per tile.
-->
<script lang="ts">
  import AboutCard from '$components/system/AboutCard.svelte';
  import NotificationsCard from '$components/system/NotificationsCard.svelte';
  import SafetyNetCard from '$components/system/SafetyNetCard.svelte';
  import {
    fetchAbout,
    fetchNotifications,
    sendTestNotification,
    type NotificationStatus,
    type SystemAbout,
  } from '$lib/system/about';
  import { failureKind } from '$lib/core/api';
  import type { ControlStore } from '$lib/core/control.svelte';
  import type { LiveStore } from '$lib/core/live.svelte';
  import { retryAfter, type TestFailure } from '$lib/notify/notify';
  import { notifyHealth } from '$lib/notify/notifyHealth.svelte';

  let { live }: { live: LiveStore; ctl: ControlStore } = $props();

  const REFRESH_MS = 60_000;

  let about = $state<SystemAbout | null | undefined>(undefined);
  let notifications = $state<NotificationStatus | null | undefined>(undefined);
  let aboutFailed = $state(false);
  let notifyFailed = $state(false);

  $effect(() => {
    void live.configVersion;
    const controller = new AbortController();
    let timer: number | undefined;
    const load = async () => {
      const [aboutResult, notifyResult] = await Promise.allSettled([
        fetchAbout(controller.signal),
        fetchNotifications(controller.signal),
      ]);
      if (controller.signal.aborted) return;
      if (aboutResult.status === 'fulfilled') {
        about = aboutResult.value;
        aboutFailed = false;
      } else aboutFailed = true;
      if (notifyResult.status === 'fulfilled') {
        notifications = notifyResult.value;
        notifyHealth.set(notifyResult.value);
        notifyFailed = false;
      } else notifyFailed = true;
      timer = window.setTimeout(load, REFRESH_MS);
    };
    void load();
    return () => {
      controller.abort();
      window.clearTimeout(timer);
    };
  });

  async function test(): Promise<TestFailure | null> {
    try {
      const result = await sendTestNotification();
      notifications = result.status;
      notifyHealth.set(result.status);
      return null;
    } catch (error) {
      return { kind: failureKind(error), retryS: retryAfter(error) };
    }
  }
</script>

<div class="grid tiles">
  <div class="span-6">
    <NotificationsCard status={notifications} failed={notifyFailed} ontest={test} />
  </div>
  <div class="span-6">
    <SafetyNetCard
      net={about === undefined ? undefined : (about?.safety_net ?? null)}
      failed={aboutFailed}
    />
  </div>
  <div class="span-12"><AboutCard {about} failed={aboutFailed} /></div>
</div>

<style>
  .tiles {
    margin-top: var(--space-4);
  }
</style>
