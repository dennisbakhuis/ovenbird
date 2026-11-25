<!--
  One help section: a collapsible card with the text, optional steps and a "Show me" button
  when its target is on the page.
-->
<script lang="ts">
  import Button from '$ui/Button.svelte';
  import type { HelpSection } from '$lib/help/types';
  import { parseInline } from '$lib/help/markup';
  import { t } from '$lib/core/settings.svelte';
  import Icon from '$ui/Icon.svelte';
  import HelpInline from './HelpInline.svelte';
  import HelpText from './HelpText.svelte';

  interface Props {
    section: HelpSection;
    expanded: boolean;
    flash?: boolean;
    onToggle: () => void;
    onShow?: () => void;
  }

  let { section, expanded, flash = false, onToggle, onShow }: Props = $props();

  const uid = `help-sec-${Math.random().toString(36).slice(2, 8)}`;
</script>

<section
  class="sec"
  class:open={expanded}
  class:flash
  data-section={section.id}
  data-testid="help-section"
>
  <h4>
    <Button
      class="sect-toggle"
      aria-expanded={expanded}
      aria-controls={uid}
      onclick={onToggle}
      data-testid="help-section-toggle"
    >
      <span>{section.title}</span>
      <Icon name="chevronDown" size={18} class="chev" />
    </Button>
  </h4>
  <div class="body" id={uid} hidden={!expanded}>
    <HelpText body={section.body} />
    {#if section.steps?.length}
      <ol class="steps" aria-label={t('helpSteps')}>
        {#each section.steps as step, index (index)}<li>
            <HelpInline nodes={parseInline(step)} />
          </li>{/each}
      </ol>
    {/if}
    {#if onShow}
      <Button
        class="sect-show"
        onclick={onShow}
        data-testid="help-show-me"
        data-target={section.target}
      >
        <Icon name="eye" size={16} />{t('helpShowMe')}
      </Button>
    {/if}
  </div>
</section>

<style>
  .sec {
    border: 1px solid var(--border);
    border-radius: var(--radius);
    background: var(--surface);
    transition: box-shadow var(--dur-slow) ease;
  }
  .sec + :global(.sec) {
    margin-top: var(--space-2);
  }
  .sec.flash {
    box-shadow: 0 0 0 3px color-mix(in srgb, var(--accent) 45%, transparent);
  }
  h4 {
    margin: 0;
    font-size: var(--fs-body);
  }
  :global(.sect-toggle) {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: var(--space-2);
    width: 100%;
    min-height: var(--tap);
    padding: var(--space-2) var(--space-3);
    border: none;
    border-radius: var(--radius);
    background: none;
    color: var(--text);
    font: inherit;
    font-weight: var(--fw-bold);
    text-align: left;
    cursor: pointer;
  }
  :global(.sect-toggle):hover {
    color: var(--accent);
  }
  :global(.sect-toggle) :global(.chev) {
    flex: none;
    color: var(--muted);
    transition: transform var(--dur-fast) ease;
  }
  .open :global(.sect-toggle) :global(.chev) {
    transform: rotate(180deg);
  }
  .body {
    padding: 0 var(--space-3) var(--space-3);
    line-height: var(--lh-body);
  }
  .steps {
    margin: var(--space-2) 0 0;
    padding-left: 1.4rem;
  }
  .steps li + li {
    margin-top: 0.2rem;
  }
  :global(.sect-show) {
    display: inline-flex;
    align-items: center;
    gap: 0.4rem;
    margin-top: var(--space-3);
    min-height: 36px;
    padding: 0 0.8rem;
    border: 1px solid var(--accent);
    border-radius: var(--radius-pill);
    background: transparent;
    color: var(--accent);
    font-weight: var(--fw-bold);
  }
  :global(.sect-show):hover {
    background: var(--status-manual-bg);
  }
  @media (--narrow), (pointer: coarse) {
    :global(.sect-show) {
      min-height: var(--tap);
    }
  }
</style>
