<!--
  HaConnectionCard: the Home Assistant address and token. The token is write-only: the service
  only says whether one is stored, so the field stays empty and a new value replaces the stored
  one. "Test connection" checks the typed (unsaved) values read-only on the HA side; "Save"
  stores them and the service reconnects at once. Fields set by the installation are locked but
  can still be tested.
-->
<script lang="ts">
  import ActionRow from '$ui/ActionRow.svelte';
  import Button from '$ui/Button.svelte';
  import Card from '$ui/Card.svelte';
  import Icon from '$ui/Icon.svelte';
  import InlineMessage from '$ui/InlineMessage.svelte';
  import Pill from '$ui/Pill.svelte';
  import SectionHeader from '$ui/SectionHeader.svelte';
  import TextInput from '$ui/TextInput.svelte';
  import { ApiError, failureKind, saveHaConnection, testHaConnection } from '$lib/core/api';
  import { actionKey } from '$lib/core/control.svelte';
  import { formatNumber } from '$lib/core/format';
  import { settings, t, tOpt } from '$lib/core/settings.svelte';
  import type {
    ConfigDoc,
    ConfigSchema,
    HaEntityCheck,
    HaTestResult,
    ValidationIssue,
  } from '$lib/core/types';
  import { haSignals, haUrlProblem, haVerdict } from '$lib/settings/ha';
  import { issueText } from '$lib/settings/issues';

  interface Props {
    config: ConfigDoc;
    schema: ConfigSchema;
    linkUp?: boolean | null;
    onsaved?: (config: ConfigDoc) => void;
  }

  let { config, schema, linkUp = null, onsaved }: Props = $props();

  const urlField = $derived(config.fields['ha_url']);
  const tokenField = $derived(config.fields['ha_token']);
  const savedUrl = $derived(typeof urlField?.value === 'string' ? urlField.value : '');
  const tokenSet = $derived(tokenField?.value === 'set');
  const urlLocked = $derived(urlField?.locked === true);
  const tokenLocked = $derived(tokenField?.locked === true);
  const stored = $derived(urlField?.source === 'store' || tokenField?.source === 'store');
  const locale = $derived(settings.language);

  let url = $state('');
  let token = $state('');
  let edited = $state(false);
  let testing = $state(false);
  let saving = $state(false);
  let result = $state<HaTestResult | null>(null);
  let failure = $state<string | null>(null);
  let issues = $state<ValidationIssue[]>([]);
  let notice = $state<string | null>(null);

  $effect(() => {
    if (!edited) url = savedUrl;
  });

  const problem = $derived(haUrlProblem(url));
  const urlChanged = $derived(url.trim() !== savedUrl);
  const canSave = $derived(
    !saving && !problem && (urlChanged || token.trim() !== '') && !(urlLocked && tokenLocked),
  );
  const status = $derived(
    !savedUrl ? 'notSet' : linkUp === true ? 'connected' : linkUp === false ? 'down' : null,
  );
  const verdict = $derived(result ? haVerdict(result) : null);
  const entities = $derived(result?.entities ?? []);

  function reset(): void {
    failure = null;
    issues = [];
    notice = null;
  }

  async function test(): Promise<void> {
    reset();
    result = null;
    testing = true;
    try {
      const body: { url?: string; token?: string; signals: string[] } = {
        signals: haSignals(config),
      };
      if (url.trim()) body.url = url.trim();
      if (token.trim()) body.token = token.trim();
      result = await testHaConnection(body);
    } catch (error) {
      failure = t(actionKey(failureKind(error)));
    } finally {
      testing = false;
    }
  }

  async function save(remove = false): Promise<void> {
    reset();
    saving = true;
    try {
      const body: { url?: string | null; token?: string | null } = remove
        ? { url: null, token: null }
        : {};
      if (!remove && urlChanged) body.url = url.trim() || null;
      if (!remove && token.trim()) body.token = token.trim();
      const done = await saveHaConnection(body);
      token = '';
      edited = false;
      notice = remove ? t('haRemoved') : t('haSaved');
      onsaved?.(done.config);
    } catch (error) {
      if (error instanceof ApiError && error.status === 422) {
        issues = (error.body as { errors?: ValidationIssue[] } | null)?.errors ?? [];
        failure = t('previewRefused');
      } else {
        failure = t(actionKey(failureKind(error)));
      }
    } finally {
      saving = false;
    }
  }

  function entityText(item: HaEntityCheck): string {
    if (!item.found) return t('haEntityMissing');
    if (item.problem) return item.problem;
    if (item.value === null) return t('haEntityFound');
    const unit = item.unit ? `\u202f${item.unit}` : '';
    return `${t('haEntityFound')} · ${formatNumber(item.value, 1, locale)}${unit}`;
  }

  function issueLine(issue: ValidationIssue): string {
    const label = issue.field ? (tOpt(`cfg.${issue.field}.label`) ?? issue.field) : '';
    const text = issueText(issue, undefined, tOpt);
    const detail = issue.code === 'invalid' && issue.message ? ` (${issue.message})` : '';
    return label ? `${label}: ${text}${detail}` : `${text}${detail}`;
  }

  const lockedText = (id: string): string => {
    const env = schema.fields[id]?.env ?? id;
    return t('haLocked', { env: config.fields[id]?.source === 'file' ? t('source_file') : env });
  };
</script>

<Card bare class="ha-card" data-testid="ha-card" data-help="settings/ha.connection">
  <SectionHeader title={t('haTitle')} level={2} testid="ha-card-title">
    {#snippet actions()}
      {#if status === 'connected'}
        <Pill tone="good" icon="check" testid="ha-status">{t('haStatusConnected')}</Pill>
      {:else if status === 'down'}
        <Pill tone="warn" icon="warning" testid="ha-status">{t('haStatusDown')}</Pill>
      {:else if status === 'notSet'}
        <Pill tone="neutral" testid="ha-status">{t('haStatusNotSet')}</Pill>
      {/if}
    {/snippet}
  </SectionHeader>
  <p class="muted intro">{t('haIntro')}</p>

  <div class="field" data-testid="ha-url-row">
    <label for="ha-url-input">{t('cfg.ha_url.label')}</label>
    <TextInput
      id="ha-url-input"
      type="url"
      inputmode="url"
      autocomplete="off"
      spellcheck={false}
      placeholder="http://homeassistant.local:8123"
      aria-describedby={problem ? 'ha-url-hint ha-url-error' : 'ha-url-hint'}
      invalid={Boolean(problem)}
      disabled={urlLocked}
      value={url}
      oninput={(e) => {
        url = e.currentTarget.value;
        edited = true;
      }}
      data-testid="ha-url"
    />
    <p class="hint" id="ha-url-hint">{urlLocked ? lockedText('ha_url') : t('haUrlHint')}</p>
    {#if problem}
      <p class="error" id="ha-url-error" role="alert">{t(`haUrl_${problem}`)}</p>
    {/if}
  </div>

  <div class="field" data-testid="ha-token-row">
    <label for="ha-token-input">{t('cfg.ha_token.label')}</label>
    <TextInput
      id="ha-token-input"
      type="password"
      autocomplete="off"
      spellcheck={false}
      placeholder={tokenSet ? '••••••••' : t('haTokenPlaceholder')}
      aria-describedby="ha-token-hint"
      disabled={tokenLocked}
      value={token}
      oninput={(e) => (token = e.currentTarget.value)}
      data-testid="ha-token"
    />
    <p class="hint" id="ha-token-hint">
      {tokenLocked
        ? lockedText('ha_token')
        : tokenSet
          ? `${t('haTokenStored')} ${t('haTokenHint')}`
          : t('haTokenHint')}
    </p>
  </div>

  <ActionRow>
    <Button
      type="button"
      icon="link"
      iconSize={16}
      busy={testing}
      disabled={!!problem}
      onclick={test}
      data-testid="ha-test"
    >
      {testing ? t('haTesting') : t('haTest')}
    </Button>
    <Button
      type="button"
      variant="primary"
      busy={saving}
      disabled={!canSave}
      onclick={() => save()}
      data-testid="ha-save"
    >
      {saving ? t('haSaving') : t('haSave')}
    </Button>
    {#if stored && !urlLocked && !tokenLocked}
      <Button
        type="button"
        variant="ghost"
        disabled={saving}
        onclick={() => save(true)}
        data-testid="ha-remove">{t('haRemove')}</Button
      >
    {/if}
  </ActionRow>

  {#if notice}
    <InlineMessage tone="ok" icon role="status" testid="ha-notice">{notice}</InlineMessage>
  {/if}
  {#if failure}
    <InlineMessage tone="error" icon testid="ha-failure">
      {failure}
      {#if issues.length > 0}
        <ul class="issues">
          {#each issues as issue (`${issue.field}-${issue.code}`)}
            <li>{issueLine(issue)}</li>
          {/each}
        </ul>
      {/if}
    </InlineMessage>
  {/if}

  {#if result && verdict}
    <section class="result" data-testid="ha-result" data-verdict={verdict} aria-live="polite">
      <InlineMessage
        tone={verdict === 'ok' ? 'ok' : verdict === 'entities' ? 'warn' : 'error'}
        icon
        size="md"
        role="status"
        testid="ha-verdict"
      >
        <strong>{t(`haVerdict_${verdict}`)}</strong>
        {#if result.error_code}
          <span class="why" data-testid="ha-error"
            >{tOpt(`haTest_${result.error_code}`) ?? result.error}</span
          >
        {/if}
      </InlineMessage>
      <dl class="facts">
        <div>
          <dt>{t('haResultReachable')}</dt>
          <dd>{result.reachable ? t('haYes') : t('haNo')}</dd>
        </div>
        {#if result.auth_ok !== null}
          <div>
            <dt>{t('haResultToken')}</dt>
            <dd>{result.auth_ok ? t('haTokenAccepted') : t('haTokenRejected')}</dd>
          </div>
        {/if}
        {#if result.ha_version}
          <div>
            <dt>{t('haResultVersion')}</dt>
            <dd data-testid="ha-version">{result.ha_version}</dd>
          </div>
        {/if}
        {#if result.latency_ms !== null}
          <div>
            <dt>{t('haResultLatency')}</dt>
            <dd>{t('haLatencyValue', { ms: formatNumber(result.latency_ms, 0, locale) })}</dd>
          </div>
        {/if}
        {#if result.temperature_unit}
          <div>
            <dt>{t('haResultUnits')}</dt>
            <dd>
              {result.metric
                ? t('haMetric', { unit: result.temperature_unit })
                : t('haNotMetric', { unit: result.temperature_unit })}
            </dd>
          </div>
        {/if}
      </dl>
      {#if entities.length > 0}
        <h3 class="sub">{t('haEntitiesTitle')}</h3>
        <ul class="entities" data-testid="ha-entities">
          {#each entities as item (item.signal)}
            <li class:bad={!item.found || item.problem !== null} data-testid="ha-entity">
              <Icon name={item.found && item.problem === null ? 'check' : 'warning'} size={16} />
              <span class="mono">{item.entity_id}</span>
              <span class="muted">{entityText(item)}</span>
            </li>
          {/each}
        </ul>
      {/if}
      {#if result.error && result.error_code}
        <p class="muted small detail">{t('haDetail', { text: result.error })}</p>
      {/if}
    </section>
  {/if}
</Card>

<style>
  :global(.ha-card) {
    display: flex;
    flex-direction: column;
    gap: var(--space-3);
  }
  .intro {
    margin: 0;
  }
  .field {
    display: flex;
    flex-direction: column;
    gap: var(--space-1);
    max-width: 36rem;
  }
  .field label {
    font-weight: var(--fw-semibold);
  }
  .hint,
  .error {
    margin: 0;
    font-size: var(--fs-caption);
  }
  .hint {
    color: var(--muted);
  }
  .error {
    color: var(--err-text);
  }
  .result {
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
  }
  .why {
    display: block;
  }
  .facts {
    margin: 0;
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(10rem, 1fr));
    gap: var(--space-1) var(--space-4);
  }
  dt {
    font-size: var(--fs-caption);
    color: var(--muted);
  }
  dd {
    margin: 0;
    overflow-wrap: anywhere;
  }
  .sub {
    margin: 0;
    font-size: var(--fs-body);
  }
  .entities,
  .issues {
    list-style: none;
    margin: 0;
    padding: 0;
    display: flex;
    flex-direction: column;
    gap: var(--space-1);
  }
  .entities li {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: var(--space-1) var(--space-2);
  }
  .entities li.bad {
    color: var(--warn-text);
  }
  .mono {
    font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
    font-size: var(--fs-caption);
    overflow-wrap: anywhere;
  }
  .small {
    font-size: var(--fs-caption);
  }
  .detail {
    margin: 0;
    overflow-wrap: anywhere;
  }
</style>
