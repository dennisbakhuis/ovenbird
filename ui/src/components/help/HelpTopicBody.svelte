<!--
  The body of a help topic: sections grouped as What you see / What you can do / Good to know,
  common questions, related topics.
-->
<script lang="ts">
  import Button from '$ui/Button.svelte';
  import { tick } from 'svelte';
  import type { HelpFocus } from '$lib/help/nav.svelte';
  import type { HelpSectionKind, HelpTopic, HelpTopicId } from '$lib/help/types';
  import type { MessageKey } from '$lib/i18n';
  import { t } from '$lib/core/settings.svelte';
  import Icon from '$ui/Icon.svelte';
  import HelpText from './HelpText.svelte';
  import SectionCard from './SectionCard.svelte';

  interface Props {
    topic: HelpTopic;
    titles: Partial<Record<HelpTopicId, string>>;
    present: Set<string>;
    focus: HelpFocus | null;
    expanded: Record<string, boolean>;
    onShow: (target: string) => void;
    onTopic: (id: HelpTopicId) => void;
  }

  let { topic, titles, present, focus, expanded = $bindable(), onShow, onTopic }: Props = $props();

  const KINDS: HelpSectionKind[] = ['see', 'do', 'know'];
  const groups = $derived(
    KINDS.map((kind) => ({ kind, sections: topic.sections.filter((s) => s.kind === kind) })).filter(
      (group) => group.sections.length > 0,
    ),
  );

  const key = (kind: 's' | 'q', id: string) => `${topic.id}:${kind}:${id}`;
  let flash = $state<string | null>(null);
  let root: HTMLDivElement | undefined = $state();

  $effect(() => {
    const wanted = focus;
    if (!wanted) return;
    const section = topic.sections.find(
      (s) => (wanted.target !== undefined && s.target === wanted.target) || s.id === wanted.section,
    );
    const question = topic.questions?.find((q) => q.id === wanted.question);
    const id = section ? key('s', section.id) : question ? key('q', question.id) : null;
    if (!id) return;
    expanded[id] = true;
    flash = id;
    let timer = 0;
    void tick().then(() => {
      const node = [...(root?.querySelectorAll<HTMLElement>('[data-key]') ?? [])].find(
        (element) => element.dataset['key'] === id,
      );
      node?.scrollIntoView?.({ block: 'start' });
      node?.querySelector<HTMLElement>('button')?.focus({ preventScroll: true });
      timer = window.setTimeout(() => (flash = null), 1600);
    });
    return () => clearTimeout(timer);
  });

  const toggle = (id: string) => (expanded[id] = !expanded[id]);
</script>

<div class="topic" bind:this={root}>
  {#each groups as group (group.kind)}
    <section class="group" aria-labelledby="help-group-{group.kind}">
      <h3 id="help-group-{group.kind}">{t(`helpKind_${group.kind}` as MessageKey)}</h3>
      {#each group.sections as section (section.id)}
        <div data-key={key('s', section.id)}>
          <SectionCard
            {section}
            expanded={expanded[key('s', section.id)] ?? false}
            flash={flash === key('s', section.id)}
            onToggle={() => toggle(key('s', section.id))}
            onShow={section.target && present.has(section.target)
              ? () => onShow(section.target!)
              : undefined}
          />
        </div>
      {/each}
    </section>
  {/each}

  {#if topic.questions?.length}
    <section class="group" aria-labelledby="help-questions">
      <h3 id="help-questions">{t('helpQuestions')}</h3>
      <div class="questions">
        {#each topic.questions as question (question.id)}
          {@const id = key('q', question.id)}
          <div
            class="question"
            class:flash={flash === id}
            data-key={id}
            data-testid="help-question"
          >
            <Button
              class="topic-q"
              aria-expanded={expanded[id] ?? false}
              aria-controls="help-a-{question.id}"
              onclick={() => toggle(id)}
            >
              <span>{question.q}</span>
              <Icon name="chevronDown" size={18} class="chev" />
            </Button>
            <div class="a" id="help-a-{question.id}" hidden={!expanded[id]}>
              <HelpText body={question.a} />
            </div>
          </div>
        {/each}
      </div>
    </section>
  {/if}

  {#if topic.related?.length}
    <section class="group" aria-labelledby="help-related">
      <h3 id="help-related">{t('helpRelated')}</h3>
      <ul class="chips">
        {#each topic.related as id (id)}
          <li>
            <Button class="topic-chip" onclick={() => onTopic(id)} data-testid="help-related">
              {titles[id] ?? id}
              <Icon name="chevronRight" size={16} />
            </Button>
          </li>
        {/each}
      </ul>
    </section>
  {/if}
</div>

<style>
  .group {
    margin-top: var(--space-5);
  }
  .group:first-child {
    margin-top: 0;
  }
  h3 {
    margin: 0 0 var(--space-2);
    color: var(--muted);
    font-size: var(--fs-caption);
    font-weight: var(--fw-bold);
    letter-spacing: 0.06em;
    text-transform: uppercase;
  }
  [data-key] + [data-key] {
    margin-top: var(--space-2);
  }
  .questions {
    border: 1px solid var(--border);
    border-radius: var(--radius);
    overflow: hidden;
  }
  .question {
    transition: box-shadow var(--dur-slow) ease;
  }
  .question + .question {
    border-top: 1px solid var(--border);
    margin-top: 0;
  }
  .question.flash {
    box-shadow: inset 0 0 0 3px color-mix(in srgb, var(--accent) 45%, transparent);
  }
  :global(.topic-q) {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: var(--space-2);
    width: 100%;
    min-height: var(--tap);
    padding: var(--space-2) var(--space-3);
    border: none;
    border-radius: 0;
    background: var(--surface);
    color: var(--text);
    font: inherit;
    font-weight: var(--fw-semibold);
    text-align: left;
    cursor: pointer;
  }
  :global(.topic-q):hover {
    color: var(--accent);
  }
  :global(.topic-q) :global(.chev) {
    flex: none;
    color: var(--muted);
    transition: transform var(--dur-fast) ease;
  }
  :global(.topic-q[aria-expanded='true']) :global(.chev) {
    transform: rotate(180deg);
  }
  .a {
    padding: 0 var(--space-3) var(--space-3);
    line-height: var(--lh-body);
  }
  .chips {
    display: flex;
    flex-wrap: wrap;
    gap: var(--space-2);
    margin: 0;
    padding: 0;
    list-style: none;
  }
  :global(.topic-chip) {
    display: inline-flex;
    align-items: center;
    gap: 0.2rem;
    min-height: 36px;
    padding: 0 var(--space-2) 0 0.8rem;
    border: 1px solid var(--border);
    border-radius: var(--radius-pill);
    background: var(--surface);
    color: var(--text);
    font-weight: var(--fw-semibold);
  }
  :global(.topic-chip):hover {
    border-color: var(--accent);
    color: var(--accent);
  }
  @media (--narrow), (pointer: coarse) {
    :global(.topic-chip) {
      min-height: var(--tap);
    }
  }
</style>
