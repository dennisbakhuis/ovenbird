<!--
  FeatureCard: one switchable feature in Settings → Features. Name, a sentence on what it does,
  its switch (the day shift gets off / shadow / on), the state pill from `GET control/features`,
  for an experimental feature (`spec.ack`) the checkbox with which the owner accepts that it is
  experimental (`on` is offered only once it is ticked, and an "Experimental" pill shows while it
  is on), then the feature's settings: basic ones in
  view, advanced ones in a closed block, expert ones read-only with the hint that the
  installation fixes them. A feature with a detailed editor in another section shows its switch
  and a link there instead of repeating the settings.

  Props: spec (FeatureSpec), schema, config, entry (the service's state of the feature, if
  loaded), dayshift (the day shift's status, for the link to what it is doing).
-->
<script lang="ts">
  import Card from '$ui/Card.svelte';
  import Checkbox from '$ui/Checkbox.svelte';
  import Details from '$ui/Details.svelte';
  import Icon from '$ui/Icon.svelte';
  import Pill from '$ui/Pill.svelte';
  import Segmented from '$ui/Segmented.svelte';
  import Field from './Field.svelte';
  import { cfg } from '$lib/core/cfg.svelte';
  import { draft } from '$lib/core/draft.svelte';
  import { formatValue } from '$lib/core/fieldFormat';
  import { buildHash } from '$lib/core/router.svelte';
  import { settings, t, tOpt } from '$lib/core/settings.svelte';
  import { featureFields, stateTone, type FeatureSpec } from '$lib/settings/features';
  import type { ConfigDoc, ConfigSchema, DayShift, FeatureEntry } from '$lib/core/types';

  interface Props {
    spec: FeatureSpec;
    schema: ConfigSchema;
    config: ConfigDoc;
    entry?: FeatureEntry;
    dayshift?: DayShift | null;
  }

  let { spec, schema, config, entry, dayshift = null }: Props = $props();

  const fields = $derived(featureFields(schema, spec));
  const name = $derived(t(`feature_${spec.id}` as 'feature_stove'));
  const issues = (id: string) => ({
    errors: cfg.validation?.errors.filter((e) => e.field === id) ?? [],
    warnings: cfg.validation?.warnings.filter((e) => e.field === id) ?? [],
  });
  const changedAdvanced = $derived(fields.advanced.filter((id) => draft.has(id)).length);
  const words = $derived({
    on: t('on'),
    off: t('off'),
    none: t('fieldNone'),
  });
  const notWorking = $derived(entry?.enabled === true && entry.state === 'off');
  const mode = $derived(String(draft.value(spec.switch, config) ?? 'off'));
  const acked = $derived(spec.ack === undefined || draft.value(spec.ack, config) === true);
  const ackLocked = $derived(spec.ack !== undefined && config.fields[spec.ack]?.locked === true);
  const onBlocked = $derived(!acked && mode !== 'on');
  const experimental = $derived(mode === 'on' && (entry?.experimental ?? spec.ack !== undefined));
  const modeOptions = $derived(
    (schema.fields[spec.switch]?.options ?? ['off', 'shadow', 'on']).map((value) => ({
      value,
      label: tOpt(`cfg.${spec.switch}.opt.${value}`) ?? value,
      disabled: value === 'on' && onBlocked,
      testid: `dayshift-mode-${value}`,
    })),
  );
  function acknowledge(checked: boolean): void {
    if (spec.ack) draft.set(spec.ack, checked, config);
  }
</script>

<Card
  bare
  as="section"
  class="feature"
  testid="feature-{spec.id}"
  data-state={entry?.state}
  aria-label={name}
>
  <header>
    <h3><Icon name={spec.icon} size={18} /><span>{name}</span></h3>
    <span class="pills">
      {#if experimental}
        <Pill tone="warn" testid="feature-experimental-{spec.id}">{t('featureExperimental')}</Pill>
      {/if}
      {#if entry}
        <Pill tone={stateTone(entry.state)} testid="feature-state-{spec.id}">
          {t(`featureState_${entry.state}` as 'featureState_off')}
        </Pill>
      {/if}
    </span>
  </header>
  <p class="what muted">{t(`featureHelp_${spec.id}` as 'featureHelp_stove')}</p>

  <div class="switch" data-testid="feature-switch-{spec.id}">
    {#if spec.threeWay}
      <Field id={spec.switch} {schema} {config} {draft} hideLabel hideHelp {...issues(spec.switch)}>
        {#snippet editor(api)}
          <Segmented
            label={name}
            options={modeOptions}
            value={String(api.value ?? 'off')}
            onchange={(next) => api.set(next)}
            semantics="radio"
            appearance="joined"
            disabled={api.disabled}
            testid="dayshift-mode"
          />
        {/snippet}
      </Field>
    {:else}
      <Field
        id={spec.switch}
        {schema}
        {config}
        {draft}
        hideLabel
        hideHelp
        {...issues(spec.switch)}
      />
    {/if}
  </div>
  {#if spec.ack}
    <div class="ack" data-testid="feature-ack-{spec.id}">
      <Checkbox
        checked={acked}
        disabled={ackLocked}
        label={t(`featureAck_${spec.id}` as 'featureAck_dayshift')}
        data-testid="feature-ack-input-{spec.id}"
        onchange={(e) => acknowledge(e.currentTarget.checked)}
      />
      {#if onBlocked}
        <p class="why" data-testid="feature-ack-why-{spec.id}">
          <Icon name="info" size={16} />{t('featureAckWhy')}
        </p>
      {/if}
    </div>
  {/if}
  {#if spec.threeWay && dayshift && dayshift.mode !== 'off'}
    <a class="editor" href={buildHash('setpoint')} data-testid="dayshift-see-now">
      {t('dayshiftSeeNow')}
      <Icon name="chevronRight" size={16} />
    </a>
  {/if}
  {#if notWorking}
    <p class="muted" data-testid="feature-not-working-{spec.id}">{t('featureNotWorking')}</p>
  {/if}

  {#if fields.basic.length > 0}
    <div class="fields">
      {#each fields.basic as id (id)}
        <Field {id} {schema} {config} {draft} {...issues(id)} />
      {/each}
    </div>
  {/if}

  {#if fields.advanced.length > 0}
    <Details
      summary={t('featureMore')}
      meta={changedAdvanced > 0
        ? t('groupChanged', { n: changedAdvanced })
        : fields.advanced.length}
      id="settings.feature.{spec.id}"
      testid="feature-more-{spec.id}"
    >
      <div class="fields">
        {#each fields.advanced as id (id)}
          <Field {id} {schema} {config} {draft} {...issues(id)} />
        {/each}
      </div>
    </Details>
  {/if}

  {#if fields.expert.length > 0}
    <Details
      summary={t('featureFixed')}
      meta={fields.expert.length}
      id="settings.feature.{spec.id}.fixed"
      testid="feature-fixed-{spec.id}"
    >
      <p class="muted hint" data-testid="feature-fixed-hint-{spec.id}">{t('featureFixedHint')}</p>
      <dl class="fixed">
        {#each fields.expert as id (id)}
          <div data-testid="fixed-{id}">
            <dt><Icon name="lock" size={14} />{tOpt(`cfg.${id}.label`) ?? id}</dt>
            <dd>
              {formatValue(schema.fields[id], config.fields[id]?.value, settings.language, words)}
            </dd>
          </div>
        {/each}
      </dl>
    </Details>
  {/if}

  {#if spec.editor}
    <a
      class="editor"
      href={buildHash('settings', [spec.editor])}
      data-testid="feature-link-{spec.id}"
    >
      {t('featureEditor', { section: t(`section_${spec.editor}` as 'section_curve') })}
      <Icon name="chevronRight" size={16} />
    </a>
  {/if}
</Card>

<style>
  :global(.feature) {
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
  }
  header {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    justify-content: space-between;
    gap: var(--space-1) var(--space-2);
  }
  h3 {
    display: inline-flex;
    align-items: center;
    gap: var(--space-1);
    margin: 0;
    font-size: var(--fs-emph);
  }
  h3 :global(.icon) {
    color: var(--muted);
  }
  .what {
    margin: 0;
  }
  .switch :global(.field) {
    padding: 0;
    border: none;
  }
  .switch :global(.field.inline) {
    grid-template-columns: auto auto;
    justify-content: start;
  }
  .switch :global(.field.inline .control) {
    justify-self: start;
  }
  .fields {
    display: flex;
    flex-direction: column;
    min-width: 0;
  }
  .pills {
    display: inline-flex;
    flex-wrap: wrap;
    gap: var(--space-1);
  }
  .ack {
    display: flex;
    flex-direction: column;
    gap: var(--space-1);
  }
  .why {
    display: flex;
    align-items: flex-start;
    gap: var(--space-1);
    margin: 0;
    color: var(--muted);
    font-size: var(--fs-caption);
  }
  .why :global(.icon) {
    flex: none;
    margin-top: var(--space-1);
  }
  .hint {
    margin: 0 0 var(--space-2);
    font-size: var(--fs-caption);
  }
  .fixed {
    display: flex;
    flex-direction: column;
    gap: var(--space-1);
    margin: 0;
  }
  .fixed div {
    display: flex;
    justify-content: space-between;
    gap: var(--space-3);
  }
  .fixed dt {
    display: inline-flex;
    align-items: center;
    gap: var(--space-1);
    color: var(--muted);
  }
  .fixed dd {
    margin: 0;
    font-variant-numeric: tabular-nums;
    text-align: right;
  }
  .editor {
    display: inline-flex;
    align-items: center;
    gap: var(--space-1);
    align-self: flex-start;
    min-height: var(--control-h);
    font-weight: var(--fw-medium);
  }
</style>
