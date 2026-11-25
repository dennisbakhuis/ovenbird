<script lang="ts">
  import Pill from '$ui/Pill.svelte';
  import Card from '$ui/Card.svelte';
  import FileButton from '$ui/FileButton.svelte';
  import Button from '$ui/Button.svelte';
  import { DOWNLOAD_PREFIX } from '$lib/core/brand';
  import Details from '$ui/Details.svelte';
  import DiffTable from '$components/settings/DiffTable.svelte';
  import Icon from '$ui/Icon.svelte';
  import Why from '$ui/Why.svelte';
  import { failureKind, fetchExport, fetchVersion, fetchVersions, isMissing } from '$lib/core/api';
  import RollbackDialog from '$components/settings/RollbackDialog.svelte';
  import { actionKey, type ControlStore } from '$lib/core/control.svelte';
  import { controlFact } from '$lib/core/mode';
  import { notSendingNote } from '$lib/core/controlText';
  import { draft, parseExport, type ImportOutcome } from '$lib/core/draft.svelte';
  import { formatValue } from '$lib/core/fieldFormat';
  import { actorText } from '$lib/activity/audit';
  import { clockNow, formatDateTime } from '$lib/core/format';
  import { router } from '$lib/core/router.svelte';
  import { settings, t, tc, tOpt } from '$lib/core/settings.svelte';
  import type { ConfigDoc, ConfigSchema, ConfigVersion } from '$lib/core/types';

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
  let versions = $state<ConfigVersion[]>([]);
  let loadState = $state<'loading' | 'ok' | 'missing' | 'failed'>('loading');
  let message = $state<{ kind: 'ok' | 'error'; text: string } | null>(null);
  let outcome = $state<ImportOutcome | null>(null);

  $effect(() => {
    void config.version;
    void (async () => {
      try {
        versions = (await fetchVersions(50)).versions;
        loadState = 'ok';
      } catch (error) {
        loadState = isMissing(error) ? 'missing' : 'failed';
      }
    })();
  });

  const lockedRows = $derived(
    Object.entries(config.fields)
      .filter(([, field]) => field.locked)
      .map(([id, field]) => ({ id, field, def: schema.fields[id] })),
  );
  const overridden = $derived(lockedRows.filter((row) => row.def?.editable !== false));
  const fixed = $derived(lockedRows.filter((row) => row.def?.editable === false));
  const fixedGroups = $derived(
    schema.groups
      .map((group) => ({
        id: group.id,
        rows: group.fields.flatMap((id) => fixed.filter((row) => row.id === id)),
      }))
      .filter((group) => group.rows.length > 0),
  );
  let rollingBack = $state<number | null>(null);

  function rolledBack(version: number): void {
    rollingBack = null;
    outcome = null;
    const note = notSendingNote(
      controlFact({ control: ctl.control, decision: ctl.decision, config: ctl.config }),
      settings.language,
      clockNow(),
    );
    message = {
      kind: 'ok',
      text: note ? `${t('rollbackDone', { version })} ${note}` : t('rollbackDone', { version }),
    };
  }

  async function loadDraft(version: number): Promise<void> {
    message = null;
    try {
      const full = await fetchVersion(version);
      outcome = draft.loadDocument(full.values ?? {}, config, schema);
      message = { kind: 'ok', text: t('versionsLoaded', { version }) };
      router.navigate('settings', []);
    } catch (error) {
      message = {
        kind: 'error',
        text: t(actionKey(failureKind(error))),
      };
    }
  }

  async function exportFile(): Promise<void> {
    message = null;
    try {
      const doc = await fetchExport();
      const url = URL.createObjectURL(
        new Blob([JSON.stringify(doc, null, 2)], { type: 'application/json' }),
      );
      const link = document.createElement('a');
      link.href = url;
      link.download = `${DOWNLOAD_PREFIX}config-v${doc.version ?? config.version}.json`;
      link.click();
      URL.revokeObjectURL(url);
    } catch (error) {
      message = {
        kind: 'error',
        text: t(actionKey(failureKind(error))),
      };
    }
  }

  async function importFile(event: Event): Promise<void> {
    const input = event.currentTarget as HTMLInputElement;
    const file = input.files?.[0];
    input.value = '';
    if (!file) return;
    const parsed = parseExport(await file.text());
    if ('error' in parsed) {
      message = {
        kind: 'error',
        text: t(parsed.error === 'not_json' ? 'importNotJson' : 'importNotExport'),
      };
      return;
    }
    outcome = draft.loadDocument(parsed.values, config, schema);
    message = { kind: 'ok', text: t('importLoaded', { n: outcome.imported.length }) };
    if (outcome.imported.length > 0) router.navigate('settings', []);
  }
</script>

{#if message}
  <p
    class="msg {message.kind}"
    role={message.kind === 'error' ? 'alert' : 'status'}
    data-testid="versions-message"
  >
    {message.text}
    {#if outcome && (outcome.locked.length > 0 || outcome.unknown.length > 0)}
      {t('importSkipped', { locked: outcome.locked.length, unknown: outcome.unknown.length })}
    {/if}
  </p>
{/if}

<Card bare data-testid="export-import" data-help="settings/versions.export">
  <h3>
    {t('exportImportTitle')}
    <Why title={t('exportImportTitle')} testid="export-why"><p>{t('exportImportHelp')}</p></Why>
  </h3>
  <div class="row">
    <Button onclick={exportFile} data-testid="export-button"
      ><Icon name="download" size={18} />{t('exportButton')}</Button
    >
    <FileButton
      accept="application/json,.json"
      icon="upload"
      onchange={importFile}
      testid="import-input">{t('importButton')}</FileButton
    >
  </div>
</Card>

<Card
  bare
  class="versions-section-spaced"
  data-testid="versions-list"
  data-help="settings/versions.list"
>
  <h3>{t('versionsTitle')}</h3>
  {#if loadState === 'missing'}
    <p class="muted" data-testid="unavailable">{t('unavailable')}</p>
  {:else if loadState === 'failed'}
    <p class="muted">{t('actionFailed')}</p>
  {:else if loadState === 'loading'}
    <p class="muted">{t('loading')}</p>
  {:else}
    <ul class="versions">
      {#each versions as v (v.version)}
        <li data-testid="version-{v.version}">
          <div class="head">
            <strong class="num">v{v.version}</strong>
            {#if v.version === config.version}<Pill tone="ok">{t('versionsCurrent')}</Pill>{/if}
            <span class="muted meta"
              >{formatDateTime(v.created_at, locale)} · {actorText(v.actor)} · {tc(
                'origin_',
                v.origin,
              )}</span
            >
            {#if v.version !== config.version && ctl.admin !== false}
              <span class="actions">
                <Button
                  size="sm"
                  onclick={() => (rollingBack = v.version)}
                  data-testid="rollback-{v.version}"
                >
                  <Icon name="undo" size={16} />{t('versionsRollback')}
                </Button>
                <Button
                  size="sm"
                  onclick={() => loadDraft(v.version)}
                  data-testid="load-draft-{v.version}"
                >
                  <Icon name="edit" size={16} />{t('versionsLoadDraft')}
                </Button>
              </span>
            {/if}
          </div>
          {#if v.comment}<p class="comment">“{v.comment}”</p>{/if}
          {#if v.changed.length > 0}
            <Details
              summary={v.changed.map((c) => tOpt(`cfg.${c.field}.label`) ?? c.field).join(', ')}
              meta={v.changed.length}
              testid="version-changes-{v.version}"
            >
              <DiffTable
                entries={v.changed.map((c) => ({ ...c, reset: c.to === null }))}
                {schema}
              />
            </Details>
          {/if}
        </li>
      {/each}
    </ul>
  {/if}
</Card>

{#snippet lockedTable(rows: typeof lockedRows)}
  <table class="table-cards">
    <thead>
      <tr>
        <th>{t('diffSetting')}</th>
        <th>{t('colValue')}</th>
        <th>{t('lockedSource')}</th>
        <th>{t('lockedVariable')}</th>
      </tr>
    </thead>
    <tbody>
      {#each rows as row (row.id)}
        <tr>
          <td data-label={t('diffSetting')}>{tOpt(`cfg.${row.id}.label`) ?? row.id}</td>
          <td data-label={t('colValue')} class="num"
            >{formatValue(row.def, row.field.value, locale, words)}</td
          >
          <td data-label={t('lockedSource')}>{tc('source_', row.field.source)}</td>
          <td data-label={t('lockedVariable')}><code>{row.def?.env ?? row.id}</code></td>
        </tr>
      {/each}
    </tbody>
  </table>
{/snippet}

<Card
  bare
  class="versions-section-spaced"
  data-testid="locked-table"
  data-help="settings/versions.locked"
>
  <h3>
    {t('overriddenTitle')}
    <Why title={t('overriddenTitle')} testid="overridden-why"><p>{t('overriddenHelp')}</p></Why>
  </h3>
  {#if overridden.length > 0}
    {@render lockedTable(overridden)}
  {:else}
    <p class="muted">{t('overriddenNone')}</p>
  {/if}
  <div class="fixed">
    <Details
      summary={t('lockedTitle')}
      meta={fixed.length}
      id="settings-fixed"
      testid="fixed-table"
    >
      <p class="muted caption">{t('lockedHelp')}</p>
      {#each fixedGroups as group (group.id)}
        <h4>{tc('group_', group.id)}</h4>
        {@render lockedTable(group.rows)}
      {/each}
    </Details>
  </div>
</Card>

{#if rollingBack !== null}
  <RollbackDialog
    version={rollingBack}
    {ctl}
    {schema}
    {config}
    ondone={rolledBack}
    onclose={() => (rollingBack = null)}
  />
{/if}

<style>
  :global(.versions-section-spaced) {
    margin-top: 0;
  }
  .meta {
    font-size: var(--fs-caption);
  }
  h3 {
    display: flex;
    align-items: center;
    gap: var(--space-1);
    margin: 0 0 var(--space-2);
    font-size: var(--fs-emph);
  }
  .row {
    display: flex;
    flex-wrap: wrap;
    gap: var(--space-3);
  }
  .versions {
    list-style: none;
    margin: 0;
    padding: 0;
  }
  .versions li {
    padding: var(--space-2) 0;
    border-bottom: 1px solid var(--border);
  }
  .head {
    display: flex;
    flex-wrap: wrap;
    gap: var(--space-1) var(--space-3);
    align-items: center;
  }
  .comment {
    margin: var(--space-1) 0;
  }
  .msg {
    padding: var(--space-2) var(--space-3);
    border-radius: var(--radius-control);
  }
  .msg.ok {
    background: color-mix(in srgb, var(--ok) 15%, var(--surface));
  }
  .msg.error {
    background: var(--err-bg);
    color: var(--err-text);
  }
  .actions {
    display: flex;
    flex-wrap: wrap;
    gap: var(--space-2);
    margin-left: auto;
  }
  .comment {
    color: var(--muted);
    font-style: italic;
  }
  h4 {
    margin: var(--space-4) 0 var(--space-1);
    font-size: var(--fs-xl);
  }
  .fixed {
    margin-top: var(--space-4);
  }
</style>
