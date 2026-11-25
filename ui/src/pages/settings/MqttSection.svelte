<!--
  MQTT section: the broker connection card (test, then save; the service reverts a broker without
  HeishaMon data after 60 s) and, below it, the extra MQTT sensors. The sensors are an ordinary
  setting: they go into the draft and are applied through review, after which they appear in the
  sensor lists (room sensor, reference room, outside sensor of the curve).
-->
<script lang="ts">
  import Card from '$ui/Card.svelte';
  import SectionHeader from '$ui/SectionHeader.svelte';
  import Field from '$components/settings/Field.svelte';
  import MqttConnectionCard from '$components/settings/MqttConnectionCard.svelte';
  import MqttInputsEditor from '$components/settings/MqttInputsEditor.svelte';
  import { cfg } from '$lib/core/cfg.svelte';
  import type { ControlStore } from '$lib/core/control.svelte';
  import { draft } from '$lib/core/draft.svelte';
  import { t } from '$lib/core/settings.svelte';
  import type { ConfigDoc, ConfigSchema } from '$lib/core/types';
  import { asMqttInputs } from '$lib/settings/mqtt';

  interface Props {
    ctl: ControlStore;
    schema: ConfigSchema;
    config: ConfigDoc;
  }

  let { ctl, schema, config }: Props = $props();

  const INPUTS = 'mqtt_inputs';
  const inputs = $derived(asMqttInputs(draft.value(INPUTS, config)));
  const base = $derived(config.fields['heishamon_base']?.value);

  $effect(() => {
    void config.version;
    void cfg.loadSignals();
  });

  function saved(next: ConfigDoc): void {
    ctl.config = next;
    void ctl.refresh();
  }

  function settled(): void {
    void ctl.refresh();
    void cfg.loadSignals();
  }
</script>

<MqttConnectionCard {config} {schema} onsaved={saved} onsettled={settled} />

{#if schema.fields[INPUTS]}
  <Card bare as="div" class="mqtt-inputs-card" data-testid="mqtt-inputs-card">
    <SectionHeader title={t('mqttInputsTitle')} level={2} testid="mqtt-inputs-title" />
    <p class="muted intro">{t('mqttInputsIntro')}</p>
    <Field
      id={INPUTS}
      {schema}
      {config}
      {draft}
      wide
      hideLabel
      helpTarget="settings/mqtt.inputs"
      errors={cfg.validation?.errors.filter((e) => e.field === INPUTS) ?? []}
      warnings={cfg.validation?.warnings.filter((e) => e.field === INPUTS) ?? []}
    >
      {#snippet editor(api)}
        <MqttInputsEditor
          {inputs}
          base={typeof base === 'string' ? base : undefined}
          errors={cfg.validation?.errors.filter((e) => e.field === INPUTS) ?? []}
          disabled={api.disabled}
          onchange={(next) => api.set(next)}
        />
      {/snippet}
    </Field>
  </Card>
{/if}

<style>
  :global(.mqtt-inputs-card) {
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
  }
  .intro {
    margin: 0;
  }
</style>
