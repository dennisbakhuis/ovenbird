<!--
  "All help topics": the guides first ("Start here", "Coming from another controller"), then every page
  with its tabs or sections underneath, the current one marked.
-->
<script lang="ts">
  import Button from '$ui/Button.svelte';
  import { isPageTopic, pageTopic } from '$lib/help/resolve';
  import type { HelpTopic, HelpTopicId } from '$lib/help/types';
  import { t } from '$lib/core/settings.svelte';
  import Icon from '$ui/Icon.svelte';

  interface Props {
    topics: HelpTopic[];
    current: HelpTopicId;
    onTopic: (id: HelpTopicId) => void;
    onGlossary: () => void;
  }

  let { topics, current, onTopic, onGlossary }: Props = $props();

  const guides = $derived(topics.filter((topic) => !isPageTopic(topic.id)));

  const pages = $derived(
    topics
      .filter((topic) => isPageTopic(topic.id) && pageTopic(topic.id) === topic.id)
      .map((page) => ({
        page,
        children: topics.filter((topic) => topic.id !== page.id && pageTopic(topic.id) === page.id),
      })),
  );
</script>

<ul class="index" data-testid="help-index">
  {#each guides as guide (guide.id)}
    <li>
      <Button
        class="help-index-entry help-index-page"
        data-topic={guide.id}
        onclick={() => onTopic(guide.id)}
      >
        <span class="name">{guide.title}</span>
        <Icon name="chevronRight" size={16} />
      </Button>
    </li>
  {/each}
  {#each pages as { page, children } (page.id)}
    <li>
      <Button
        class="help-index-entry help-index-page"
        data-topic={page.id}
        aria-current={page.id === current ? 'true' : undefined}
        onclick={() => onTopic(page.id)}
      >
        <span class="name">{page.title}</span>
        {#if page.id === current}<span class="here">{t('helpThisPage')}</span>{/if}
        <Icon name="chevronRight" size={16} />
      </Button>
      {#if children.length}
        <ul>
          {#each children as child (child.id)}
            <li>
              <Button
                class="help-index-entry"
                aria-current={child.id === current ? 'true' : undefined}
                onclick={() => onTopic(child.id)}
              >
                <span class="name">{child.title}</span>
                {#if child.id === current}<span class="here">{t('helpThisPage')}</span>{/if}
                <Icon name="chevronRight" size={16} />
              </Button>
            </li>
          {/each}
        </ul>
      {/if}
    </li>
  {/each}
  <li>
    <Button class="help-index-entry help-index-page" onclick={onGlossary}>
      <span class="name">{t('helpGlossary')}</span>
      <Icon name="chevronRight" size={16} />
    </Button>
  </li>
</ul>

<style>
  ul {
    margin: 0;
    padding: 0;
    list-style: none;
  }
  .index > li + li {
    margin-top: var(--space-1);
  }
  .index ul {
    margin: 0 0 var(--space-2) var(--space-3);
    padding-left: var(--space-2);
    border-left: 2px solid var(--border);
  }
  :global(.help-index-entry) {
    display: flex;
    align-items: center;
    gap: var(--space-2);
    width: 100%;
    min-height: var(--control-h);
    padding: 0 var(--space-2);
    border: none;
    border-radius: var(--radius-sm);
    background: none;
    color: var(--text);
    font: inherit;
    text-align: left;
    cursor: pointer;
  }
  :global(.help-index-entry.help-index-page) {
    font-weight: var(--fw-bold);
  }
  :global(.help-index-entry):hover {
    background: var(--surface-2);
  }
  :global(.help-index-entry[aria-current='true']) {
    background: var(--status-manual-bg);
    color: var(--status-manual);
  }
  .name {
    flex: 1;
    min-width: 0;
  }
  .here {
    font-size: var(--fs-caption);
    font-weight: var(--fw-semibold);
  }
  :global(.help-index-entry) :global(svg) {
    flex: none;
    color: var(--muted);
  }
  @media (--narrow), (pointer: coarse) {
    :global(.help-index-entry) {
      min-height: var(--tap);
    }
  }
</style>
