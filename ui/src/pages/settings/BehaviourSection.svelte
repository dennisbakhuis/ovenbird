<!--
  Behaviour section: the setpoint limits in view; dead band and wait time, the start ramp and
  cycling protection collapsed by topic.
-->
<script lang="ts">
  import Card from '$ui/Card.svelte';
  import FieldGroup from '$components/settings/FieldGroup.svelte';
  import type { ConfigDoc, ConfigSchema } from '$lib/core/types';

  interface Props {
    schema: ConfigSchema;
    config: ConfigDoc;
  }

  let { schema, config }: Props = $props();
</script>

<Card bare as="div">
  <FieldGroup
    {schema}
    {config}
    groups={['limits', 'behaviour', 'ramp', 'cycling']}
    helpTarget={{
      limits: 'settings/behaviour.limits',
      behaviour: 'settings/behaviour.deadband',
      ramp: 'settings/behaviour.ramp',
      cycling: 'settings/behaviour.cycling',
    }}
  />
</Card>
