<!--
  MqttConnectionCard: the broker HeishaMon publishes to. The status line says whether ovenbird
  is connected, to which broker and base, and how many HeishaMon messages arrived. "Test
  connection" checks the typed (unsaved) values with a subscribe-only session; "Save connection"
  is only possible for exactly the values of the last successful test. After saving, the service
  watches the new broker for 60 s and goes back to the previous one without HeishaMon data; the
  card polls the outcome every 2 s. The password is write-only. Fields set by the deployment are
  locked; while commands to the pump are on, the broker can be tested but not changed.
-->
<script lang="ts">
  import { poll } from '$lib/core/poll.svelte';
  import ActionRow from '$ui/ActionRow.svelte';
  import Button from '$ui/Button.svelte';
  import Card from '$ui/Card.svelte';
  import Details from '$ui/Details.svelte';
  import InlineMessage from '$ui/InlineMessage.svelte';
  import Pill from '$ui/Pill.svelte';
  import SectionHeader from '$ui/SectionHeader.svelte';
  import Switch from '$ui/Switch.svelte';
  import TextInput from '$ui/TextInput.svelte';
  import {
    ApiError,
    failureKind,
    fetchMqttStatus,
    saveMqttConnection,
    testMqttConnection,
  } from '$lib/core/api';
  import { actionKey } from '$lib/core/control.svelte';
  import { formatClock, formatNumber } from '$lib/core/format';
  import { settings, t, tOpt } from '$lib/core/settings.svelte';
  import type {
    ConfigDoc,
    ConfigSchema,
    MqttStatus,
    MqttTestResult,
    ValidationIssue,
  } from '$lib/core/types';
  import { issueText } from '$lib/settings/issues';
  import {
    dropsPassword,
    MQTT_FIELDS,
    MQTT_KEYS,
    mqttBody,
    mqttFormOf,
    mqttLocked,
    mqttPasswordSet,
    mqttProblems,
    mqttSaveBlock,
    mqttVerdict,
    type MqttForm,
    type MqttKey,
    type MqttTested,
  } from '$lib/settings/mqtt';

  interface Props {
    config: ConfigDoc;
    schema: ConfigSchema;
    onsaved?: (config: ConfigDoc) => void;
    onsettled?: () => void;
    pollMs?: number;
  }

  let { config, schema, onsaved, onsettled, pollMs = 2000 }: Props = $props();

  const locale = $derived(settings.language);
  const saved = $derived(mqttFormOf(config));
  const locked = $derived(mqttLocked(config));
  const passwordSet = $derived(mqttPasswordSet(config));
  const editable = $derived(MQTT_KEYS.filter((key) => !locked.has(key)));

  let form = $state<MqttForm>(mqttFormOf(null));
  let edited = $state(false);
  let status = $state<MqttStatus | null>(null);
  let statusState = $state<'loading' | 'ok' | 'missing' | 'failed'>('loading');
  let testing = $state(false);
  let saving = $state(false);
  let tested = $state<MqttTested | null>(null);
  let result = $state<MqttTestResult | null>(null);
  let failure = $state<string | null>(null);
  let issues = $state<ValidationIssue[]>([]);

  $effect(() => {
    if (!edited) form = { ...saved };
  });

  const body = $derived(mqttBody(form, saved, locked));
  const problems = $derived(mqttProblems(form, locked));
  const invalid = $derived(Object.keys(problems).length > 0);
  const block = $derived(mqttSaveBlock({ body, tested, status, allLocked: editable.length === 0 }));
  const canSave = $derived(block === null && !saving && !testing && !invalid);
  const verdict = $derived(result ? mqttVerdict(result) : null);
  const applyState = $derived(status?.apply.state ?? 'idle');
  const dropping = $derived(dropsPassword(body, passwordSet));

  async function load(): Promise<void> {
    try {
      const next = await fetchMqttStatus();
      const before = status?.apply.state;
      status = next;
      statusState = next ? 'ok' : 'missing';
      if (before === 'applying' && next && next.apply.state !== 'applying') onsettled?.();
    } catch {
      statusState = 'failed';
    }
  }

  $effect(() => {
    void load();
  });

  $effect(() => {
    if (applyState !== 'applying') return;
    return poll(() => load(), { intervalMs: pollMs, immediate: false });
  });

  function edit(key: MqttKey, value: string | boolean): void {
    form = { ...form, [key]: value };
    edited = true;
  }

  function reset(): void {
    failure = null;
    issues = [];
  }

  function refusal(error: unknown): void {
    if (error instanceof ApiError && (error.status === 409 || error.status === 422)) {
      issues = (error.body as { errors?: ValidationIssue[] } | null)?.errors ?? [];
      const code = issues.length === 1 && issues[0]?.field === null ? issues[0].code : null;
      const known = code ? tOpt(`mqttRefused_${code}`) : undefined;
      if (known) {
        failure = known;
        issues = [];
      } else failure = t('previewRefused');
    } else failure = t(actionKey(failureKind(error)));
  }

  async function test(): Promise<void> {
    reset();
    result = null;
    testing = true;
    const sent = { ...body };
    try {
      result = await testMqttConnection(sent);
      tested = { body: sent, ok: result.ok };
    } catch (error) {
      tested = { body: sent, ok: false };
      refusal(error);
    } finally {
      testing = false;
    }
  }

  async function save(): Promise<void> {
    reset();
    saving = true;
    try {
      const done = await saveMqttConnection({ ...body });
      status = done.mqtt;
      tested = null;
      result = null;
      edited = false;
      onsaved?.(done.config);
    } catch (error) {
      refusal(error);
    } finally {
      saving = false;
    }
  }

  function issueLine(issue: ValidationIssue): string {
    const label = issue.field ? (tOpt(`cfg.${issue.field}.label`) ?? issue.field) : '';
    const text = issueText(issue, undefined, tOpt);
    const detail = issue.code === 'invalid' && issue.message ? ` (${issue.message})` : '';
    return label ? `${label}: ${text}${detail}` : `${text}${detail}`;
  }

  function lockedText(key: MqttKey): string {
    const id = MQTT_FIELDS[key];
    const env = schema.fields[id]?.env ?? id;
    return t('mqttLocked', { env: config.fields[id]?.source === 'file' ? t('source_file') : env });
  }

  function hint(key: MqttKey): string {
    if (locked.has(key)) return lockedText(key);
    if (key === 'password') {
      const stored = passwordSet ? t('mqttPasswordStored') : t('mqttPasswordNone');
      return dropping ? `${stored} ${t('mqttPasswordDrops')}` : stored;
    }
    return tOpt(`cfg.${MQTT_FIELDS[key]}.help`) ?? '';
  }

  const PLACEHOLDER: Partial<Record<MqttKey, () => string>> = {
    host: () => '192.0.2.20',
    port: () => '1883',
    base: () => 'panasonic_heat_pump',
    username: () => t('mqttPasswordPlaceholder'),
    password: () => (passwordSet ? '••••••••' : t('mqttPasswordPlaceholder')),
    ca_file: () => t('mqttCaPlaceholder'),
    client_id: () => t('mqttClientPlaceholder'),
  };
</script>

{#snippet text(key: Exclude<MqttKey, 'tls'>)}
  {@const problem = problems[key]}
  <div class="field" class:locked={locked.has(key)} data-testid="mqtt-{key}-row">
    <label for="mqtt-{key}-input"
      >{t(`cfg.${MQTT_FIELDS[key]}.label` as 'cfg.mqtt_host.label')}</label
    >
    <TextInput
      id="mqtt-{key}-input"
      type={key === 'password' ? 'password' : 'text'}
      inputmode={key === 'port' ? 'numeric' : undefined}
      autocomplete="off"
      spellcheck={false}
      placeholder={PLACEHOLDER[key]?.()}
      aria-describedby={problem ? `mqtt-${key}-hint mqtt-${key}-error` : `mqtt-${key}-hint`}
      invalid={Boolean(problem)}
      disabled={locked.has(key)}
      value={form[key]}
      oninput={(e) => edit(key, e.currentTarget.value)}
      data-testid="mqtt-{key}"
    />
    <p class="hint" id="mqtt-{key}-hint">{hint(key)}</p>
    {#if problem}
      <p class="error" id="mqtt-{key}-error" role="alert">{t(`mqttProblem_${problem}`)}</p>
    {/if}
  </div>
{/snippet}

<Card bare class="mqtt-card" data-testid="mqtt-card" data-help="settings/mqtt.connection">
  <SectionHeader title={t('mqttTitle')} level={2} testid="mqtt-card-title">
    {#snippet actions()}
      {#if status?.connected === true}
        <Pill tone="good" icon="check" testid="mqtt-status">{t('mqttStatusConnected')}</Pill>
      {:else if status?.connected === false}
        <Pill tone="warn" icon="warning" testid="mqtt-status">{t('mqttStatusDown')}</Pill>
      {/if}
    {/snippet}
  </SectionHeader>
  <p class="muted intro">{t('mqttIntro')}</p>
  {#if status}
    <p class="now" data-testid="mqtt-now">
      {t('mqttNow', {
        broker: `${status.host}:${status.port}`,
        base: status.base,
        n: formatNumber(status.heishamon_messages, 0, locale),
      })}
    </p>
  {:else if statusState === 'missing'}
    <InlineMessage tone="info" icon testid="mqtt-missing">{t('mqttStatusMissing')}</InlineMessage>
  {/if}
  {#if status?.commands_enabled}
    <InlineMessage tone="warn" icon size="md" testid="mqtt-commands">
      {t('mqttCommandsNotice')}
    </InlineMessage>
  {/if}

  <div class="grid">
    <div class="wide">{@render text('host')}</div>
    {@render text('port')}
    {@render text('username')}
    {@render text('password')}
    <div class="wide">{@render text('base')}</div>
  </div>

  <Details summary={t('mqttMore')} id="mqtt-more" icon="lock" testid="mqtt-more">
    <div class="grid">
      <div class="field switch-row" class:locked={locked.has('tls')} data-testid="mqtt-tls-row">
        <label for="mqtt-tls-input">{t('cfg.mqtt_tls.label')}</label>
        <Switch
          id="mqtt-tls-input"
          aria-describedby="mqtt-tls-hint"
          checked={form.tls}
          disabled={locked.has('tls')}
          state={form.tls ? t('on') : t('off')}
          onchange={(e) => edit('tls', e.currentTarget.checked)}
          data-testid="mqtt-tls"
        />
        <p class="hint" id="mqtt-tls-hint">{hint('tls')}</p>
      </div>
      {@render text('ca_file')}
      {@render text('client_id')}
    </div>
  </Details>

  <ActionRow>
    <Button
      type="button"
      icon="link"
      iconSize={16}
      busy={testing}
      disabled={invalid || saving || statusState === 'missing'}
      onclick={test}
      data-testid="mqtt-test"
    >
      {testing ? t('mqttTesting') : t('mqttTest')}
    </Button>
    <Button
      type="button"
      variant="primary"
      busy={saving}
      disabled={!canSave}
      aria-describedby={block ? 'mqtt-save-why' : undefined}
      onclick={save}
      data-testid="mqtt-save"
    >
      {saving ? t('mqttSaving') : t('mqttSave')}
    </Button>
  </ActionRow>
  {#if block && statusState !== 'missing'}
    <p class="hint why" id="mqtt-save-why" data-testid="mqtt-save-why" data-block={block}>
      {t(`mqttSaveBlock_${block}`)}
    </p>
  {/if}

  {#if failure}
    <InlineMessage tone="error" icon testid="mqtt-failure">
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
    <section class="result" data-testid="mqtt-result" data-verdict={verdict} aria-live="polite">
      <InlineMessage
        tone={verdict === 'ok' ? 'ok' : verdict === 'no_heishamon' ? 'warn' : 'error'}
        icon
        size="md"
        role="status"
        testid="mqtt-verdict"
      >
        <strong>{t(`mqttVerdict_${verdict}`)}</strong>
        {#if result.error_code}
          <span class="why-text" data-testid="mqtt-error"
            >{tOpt(`mqttTest_${result.error_code}`) ?? result.error}</span
          >
        {/if}
      </InlineMessage>
      <dl class="facts">
        <div>
          <dt>{t('mqttResultBroker')}</dt>
          <dd data-testid="mqtt-result-broker">{result.host}:{result.port}</dd>
        </div>
        <div>
          <dt>{t('mqttResultConnected')}</dt>
          <dd>{result.connected ? t('haYes') : t('haNo')}</dd>
        </div>
        <div>
          <dt>{t('mqttResultHeishamon')}</dt>
          <dd>{result.heishamon ? t('haYes') : t('haNo')}</dd>
        </div>
        {#if result.topic}
          <div>
            <dt>{t('mqttResultTopic')}</dt>
            <dd class="mono">{result.topic}</dd>
          </div>
        {/if}
        {#if result.latency_ms !== null}
          <div>
            <dt>{t('haResultLatency')}</dt>
            <dd>{t('haLatencyValue', { ms: formatNumber(result.latency_ms, 0, locale) })}</dd>
          </div>
        {/if}
      </dl>
      {#if result.error && result.error_code}
        <p class="muted small detail">{t('haDetail', { text: result.error })}</p>
      {/if}
    </section>
  {/if}

  {#if status && applyState !== 'idle'}
    <div class="apply" data-testid="mqtt-apply" data-state={applyState} aria-live="polite">
      {#if applyState === 'applying'}
        <InlineMessage tone="info" icon size="md" role="status">{t('mqttApplying')}</InlineMessage>
      {:else if applyState === 'applied'}
        <InlineMessage tone="ok" icon size="md" role="status">
          {t('mqttApplied', { time: formatClock(status.apply.at, locale) })}
        </InlineMessage>
      {:else if applyState === 'failed'}
        <InlineMessage tone="error" icon size="md" role="alert">
          {t('mqttRevertFailed', { time: formatClock(status.apply.at, locale) })}
          {#if status.apply.message}
            <span class="why-text muted small">{t('haDetail', { text: status.apply.message })}</span
            >
          {/if}
        </InlineMessage>
      {:else}
        <InlineMessage tone="warn" icon size="md" role="status">
          {t('mqttReverted', { time: formatClock(status.apply.at, locale) })}
          {#if status.apply.message}
            <span class="why-text muted small">{t('haDetail', { text: status.apply.message })}</span
            >
          {/if}
        </InlineMessage>
      {/if}
    </div>
  {/if}
</Card>

<style>
  :global(.mqtt-card) {
    display: flex;
    flex-direction: column;
    gap: var(--space-3);
  }
  .intro,
  .now {
    margin: 0;
  }
  .now {
    font-size: var(--fs-caption);
    color: var(--muted);
    overflow-wrap: anywhere;
  }
  .grid {
    display: grid;
    grid-template-columns: minmax(0, 1fr);
    gap: var(--space-3) var(--space-4);
    max-width: 44rem;
  }
  @container main (min-width: 40rem) {
    .grid {
      grid-template-columns: repeat(2, minmax(0, 1fr));
    }
    .wide {
      grid-column: 1 / -1;
    }
  }
  .wide {
    min-width: 0;
  }
  .wide .field {
    max-width: 36rem;
  }
  .field {
    display: flex;
    flex-direction: column;
    gap: var(--space-1);
    min-width: 0;
  }
  .field label {
    font-weight: var(--fw-semibold);
  }
  .switch-row {
    grid-column: 1 / -1;
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
  .result,
  .apply {
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
  }
  .why-text {
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
  .issues {
    list-style: none;
    margin: 0;
    padding: 0;
    display: flex;
    flex-direction: column;
    gap: var(--space-1);
  }
  .mono {
    font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
    font-size: var(--fs-caption);
  }
  .small {
    font-size: var(--fs-caption);
  }
  .detail {
    margin: 0;
    overflow-wrap: anywhere;
  }
</style>
