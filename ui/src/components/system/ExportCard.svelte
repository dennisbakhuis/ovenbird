<!--
  Export: choose a range, signals, resolution, layout and format; the card estimates the size
  from the stored point counts before anything is downloaded. Series and journals are direct
  links, so the browser streams them to disk however large they are; the archive (admin) is
  fetched so a refusal can be shown.
-->
<script lang="ts">
  import ActionRow from '$ui/ActionRow.svelte';
  import Button from '$ui/Button.svelte';
  import Card from '$ui/Card.svelte';
  import Checkbox from '$ui/Checkbox.svelte';
  import Icon from '$ui/Icon.svelte';
  import InlineMessage from '$ui/InlineMessage.svelte';
  import Segmented from '$ui/Segmented.svelte';
  import TextInput from '$ui/TextInput.svelte';
  import { DOWNLOAD_PREFIX } from '$lib/core/brand';
  import { formatNumber } from '$lib/core/format';
  import { settings, t } from '$lib/core/settings.svelte';
  import type { StoredSignal } from '$lib/core/types';
  import {
    JOURNALS,
    STEPS,
    downloadArchive,
    estimateSeries,
    formatBytes,
    journalUrl,
    presetWindow,
    seriesUrl,
    signalsSpan,
    type ArchiveFailure,
    type ExportFormat,
    type ExportLayout,
    type ExportStep,
    type RangePreset,
  } from '$lib/system/data';

  interface Props {
    signals: StoredSignal[] | null;
    phase: 'loading' | 'failed' | 'ok';
    now: number;
  }

  let { signals, phase, now }: Props = $props();

  const PRESETS: RangePreset[] = ['1d', '7d', '30d', 'all', 'custom'];
  const DAY_MS = 86_400_000;

  let preset = $state<RangePreset>('7d');
  let fromDay = $state('');
  let toDay = $state('');
  let step = $state<ExportStep>('900');
  let layout = $state<ExportLayout>('long');
  let format = $state<ExportFormat>('csv');
  let filter = $state('');
  let unchosen = $state<string[]>([]);
  let archiveBusy = $state(false);
  let archiveError = $state<ArchiveFailure | null>(null);

  const lang = $derived(settings.language);
  const all = $derived(signals ?? []);
  const chosen = $derived(all.filter((signal) => !unchosen.includes(signal.id)));
  const shown = $derived(
    filter.trim() === ''
      ? all
      : all.filter((signal) => signal.id.toLowerCase().includes(filter.trim().toLowerCase())),
  );

  const isoDay = (ms: number) => new Date(ms).toISOString().slice(0, 10);
  const localDay = (day: string) => (day ? new Date(`${day}T00:00`).getTime() : NaN);

  const range = $derived.by((): { from: Date | null; to: Date | null } => {
    if (preset === 'custom') {
      const start = localDay(fromDay);
      const end = localDay(toDay);
      return {
        from: Number.isNaN(start) ? null : new Date(start),
        to: Number.isNaN(end) ? null : new Date(end + DAY_MS),
      };
    }
    if (preset === 'all') return { from: null, to: null };
    return presetWindow(preset, now);
  });
  const rangeInvalid = $derived(
    range.from !== null && range.to !== null && range.to.getTime() <= range.from.getTime(),
  );

  const estimate = $derived.by(() => {
    const span = signalsSpan(chosen, step);
    if (!span) return { rows: 0, bytes: 0 };
    const from = range.from?.getTime() ?? span.first;
    const to = range.to?.getTime() ?? span.last + 1;
    return estimateSeries(chosen, step, layout, format, from, to);
  });

  const seriesHref = $derived(
    seriesUrl({
      signals: unchosen.length === 0 ? 'all' : chosen.map((signal) => signal.id),
      from: range.from,
      to: range.to,
      step,
      layout,
      format,
    }),
  );
  const seriesReady = $derived(chosen.length > 0 && !rangeInvalid);

  function toggle(id: string, on: boolean): void {
    unchosen = on ? unchosen.filter((item) => item !== id) : [...unchosen, id];
  }

  function choosePreset(next: RangePreset): void {
    if (next === 'custom' && !fromDay) {
      fromDay = isoDay(now - 7 * DAY_MS);
      toDay = isoDay(now);
    }
    preset = next;
  }

  async function archive(): Promise<void> {
    archiveBusy = true;
    archiveError = await downloadArchive(`${DOWNLOAD_PREFIX}archive.zip`);
    archiveBusy = false;
  }

  const ARCHIVE_TEXT: Record<ArchiveFailure, string> = {
    forbidden: 'exportArchiveForbidden',
    space: 'exportArchiveSpace',
    busy: 'exportArchiveBusy',
    missing: 'exportMissing',
    failed: 'actionFailed',
  };
</script>

<Card title={t('exportTitle')} icon="download" testid="export-card" help="system/data.export">
  <InlineMessage tone="warn" icon testid="export-privacy">{t('exportPrivacy')}</InlineMessage>

  {#if phase === 'loading' && !signals}
    <p class="muted">{t('loading')}</p>
  {:else if phase === 'failed' && !signals}
    <p class="muted">{t('actionFailed')}</p>
  {:else if !signals}
    <p class="muted" data-testid="export-missing">{t('exportMissing')}</p>
  {:else}
    <fieldset class="part" data-testid="export-range">
      <legend>{t('exportRange')}</legend>
      <Segmented
        options={PRESETS.map((value) => ({
          value,
          label: t(`range_${value}` as 'range_1d'),
          testid: `range-${value}`,
        }))}
        value={preset}
        onchange={choosePreset}
        label={t('exportRange')}
        size="sm"
        wrap
      />
      {#if preset === 'custom'}
        <div class="days">
          <label>
            <span>{t('exportFrom')}</span>
            <TextInput type="date" bind:value={fromDay} block={false} data-testid="export-from" />
          </label>
          <label>
            <span>{t('exportTo')}</span>
            <TextInput type="date" bind:value={toDay} block={false} data-testid="export-to" />
          </label>
        </div>
      {/if}
    </fieldset>

    <fieldset class="part" data-testid="export-signals">
      <legend>
        {t('exportSignals')}
        <span class="caption muted" data-testid="export-chosen"
          >{t('exportChosen', { n: chosen.length, total: all.length })}</span
        >
      </legend>
      <div class="signal-tools">
        <TextInput
          type="search"
          placeholder={t('exportFilter')}
          aria-label={t('exportFilter')}
          bind:value={filter}
          data-testid="export-filter"
        />
        <Button size="sm" onclick={() => (unchosen = [])} data-testid="export-all"
          >{t('exportAll')}</Button
        >
        <Button
          size="sm"
          onclick={() => (unchosen = all.map((signal) => signal.id))}
          data-testid="export-none">{t('exportNone')}</Button
        >
      </div>
      <ul class="signals">
        {#each shown as signal (signal.id)}
          <li>
            <Checkbox
              checked={!unchosen.includes(signal.id)}
              onchange={(e) => toggle(signal.id, e.currentTarget.checked)}
              data-testid="export-signal"
              data-signal={signal.id}
            >
              <span class="signal-id">{signal.id}</span>
              {#if signal.unit}<span class="caption muted">{signal.unit}</span>{/if}
            </Checkbox>
          </li>
        {/each}
      </ul>
    </fieldset>

    <div class="choices">
      <fieldset class="part">
        <legend>{t('exportResolution')}</legend>
        <Segmented
          options={STEPS.map((value) => ({
            value,
            label: t(`step_${value}` as 'step_raw'),
            testid: `step-${value}`,
          }))}
          value={step}
          onchange={(value) => (step = value)}
          label={t('exportResolution')}
          size="sm"
        />
      </fieldset>
      <fieldset class="part">
        <legend>{t('exportLayout')}</legend>
        <Segmented
          options={[
            { value: 'long', label: t('layout_long'), testid: 'layout-long' },
            { value: 'wide', label: t('layout_wide'), testid: 'layout-wide' },
          ]}
          value={layout}
          onchange={(value) => (layout = value as ExportLayout)}
          label={t('exportLayout')}
          size="sm"
        />
      </fieldset>
      <fieldset class="part">
        <legend>{t('exportFormat')}</legend>
        <Segmented
          options={[
            { value: 'csv', label: 'CSV', testid: 'format-csv' },
            { value: 'ndjson', label: 'NDJSON', testid: 'format-ndjson' },
          ]}
          value={format}
          onchange={(value) => (format = value as ExportFormat)}
          label={t('exportFormat')}
          size="sm"
        />
      </fieldset>
    </div>
    <p class="caption muted">{t('exportLayoutHint')}</p>

    <p class="estimate" data-testid="export-estimate" aria-live="polite">
      {estimate.rows > 0
        ? t('exportEstimate', {
            rows: formatNumber(estimate.rows, 0, lang),
            size: formatBytes(estimate.bytes, lang),
          })
        : t('exportEstimateNone')}
    </p>
    <ActionRow>
      {#if seriesReady}
        <Button href={seriesHref} download data-testid="export-series">
          <Icon name="download" size={16} />{t('exportSeries')}
        </Button>
      {:else}
        <Button disabled data-testid="export-series">
          <Icon name="download" size={16} />{t('exportSeries')}
        </Button>
        {#if chosen.length === 0}<span class="caption muted">{t('exportNoSignals')}</span>{/if}
      {/if}
    </ActionRow>

    <section class="more" data-help="system/data.journals">
      <h3>{t('exportJournals')}</h3>
      <p class="caption muted">{t('exportJournalsText')}</p>
      <ActionRow>
        {#each JOURNALS as kind (kind)}
          <Button
            size="sm"
            href={rangeInvalid ? undefined : journalUrl(kind, range.from, range.to, format)}
            disabled={rangeInvalid}
            download
            data-testid="export-journal-{kind}"
          >
            <Icon name="download" size={16} />{t(`journal_${kind}` as 'journal_decisions')}
          </Button>
        {/each}
      </ActionRow>
    </section>
  {/if}

  <section class="more" data-help="system/data.archive">
    <h3>{t('exportArchive')}</h3>
    <p class="caption muted">{t('exportArchiveText')}</p>
    <ActionRow>
      <Button onclick={archive} busy={archiveBusy} data-testid="export-archive">
        <Icon name="download" size={16} />{t('exportArchiveButton')}
      </Button>
    </ActionRow>
    {#if archiveError}
      <InlineMessage tone="error" testid="export-archive-error"
        >{t(ARCHIVE_TEXT[archiveError] as 'actionFailed')}</InlineMessage
      >
    {/if}
  </section>
</Card>

<style>
  .part {
    border: 0;
    margin: var(--space-3) 0 0;
    padding: 0;
    min-width: 0;
  }
  legend {
    padding: 0;
    margin-bottom: var(--space-1);
    font-weight: var(--fw-semibold);
    display: flex;
    gap: var(--space-2);
    align-items: baseline;
  }
  .days {
    display: flex;
    flex-wrap: wrap;
    gap: var(--space-3);
    margin-top: var(--space-2);
  }
  .days label {
    display: grid;
    gap: var(--space-1);
    font-size: var(--fs-caption);
  }
  .signal-tools {
    display: flex;
    gap: var(--space-2);
    align-items: center;
  }
  .signals {
    list-style: none;
    margin: var(--space-2) 0 0;
    padding: var(--space-1) var(--space-2);
    max-height: 15rem;
    overflow-y: auto;
    border: 1px solid var(--border);
    border-radius: var(--radius);
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(min(17rem, 100%), 1fr));
    gap: 0 var(--space-3);
  }
  .signal-id {
    overflow-wrap: anywhere;
  }
  .choices {
    display: flex;
    flex-wrap: wrap;
    gap: 0 var(--space-5);
  }
  .estimate {
    margin: var(--space-3) 0 var(--space-2);
    font-variant-numeric: tabular-nums;
  }
  .more {
    margin-top: var(--space-4);
    padding-top: var(--space-3);
    border-top: 1px solid var(--border);
  }
  .more h3 {
    margin: 0 0 var(--space-1);
    font-size: var(--fs-emph);
  }
  .more p {
    margin: 0 0 var(--space-2);
  }
</style>
