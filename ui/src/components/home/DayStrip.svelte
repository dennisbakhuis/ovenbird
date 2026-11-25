<!--
  DayStrip: the last 24 hours of pump activity as state lanes (compressor, defrost, hot water,
  quiet). Replaces the four run numbers of v1.

  Props: lanes (LaneSpec[]), from, to (ms), loading, failed.
-->
<script lang="ts">
  import { t } from '$lib/core/settings.svelte';
  import StateStrip from '$components/charts/StateStrip.svelte';
  import type { LaneSpec } from '$components/charts/types';
  import Card from '$ui/Card.svelte';

  interface Props {
    lanes: LaneSpec[];
    from: number;
    to: number;
    loading: boolean;
    failed: boolean;
  }

  let { lanes, from, to, loading, failed }: Props = $props();
</script>

<Card title={t('stripTitle')} icon="clock" span={12} testid="day-strip" help="home.day">
  {#if lanes.length > 0 && !failed}
    <StateStrip {from} {to} {lanes} now={to} title={t('stripTitle')} />
  {:else if failed}
    <p class="muted">{t('chartError')}</p>
  {:else if loading}
    <p class="muted">{t('chartLoading')}</p>
  {/if}
</Card>
