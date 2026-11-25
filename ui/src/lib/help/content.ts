import type { Language } from '$lib/i18n';
import { HELP_TOPICS, topicFile } from './resolve';
import type { GlossaryEntry, HelpTopic, HelpTopicId } from './types';

export interface HelpModule {
  topic?: HelpTopic;
  glossary?: GlossaryEntry[];
}

type Loader = () => Promise<HelpModule>;

const modules = import.meta.glob<HelpModule>(['./content/*/*.ts', '!./content/**/*.test.ts']);

/**
 * Lazy help content for one language, from a map of `content/<language>/<file>.ts` loaders.
 */
export class HelpContent {
  #loaders: Record<string, Loader>;
  #topics = new Map<string, Promise<HelpTopic | null>>();
  #glossary = new Map<Language, Promise<GlossaryEntry[]>>();

  constructor(loaders: Record<string, Loader>) {
    this.#loaders = loaders;
  }

  #loader(language: Language, file: string): Loader | undefined {
    return this.#loaders[`./content/${language}/${file}.ts`];
  }

  /** Whether a topic has a content file in this language. */
  has(language: Language, id: HelpTopicId): boolean {
    return this.#loader(language, topicFile(id)) !== undefined;
  }

  /** The topic, or null when it has no content in this language. */
  topic(language: Language, id: HelpTopicId): Promise<HelpTopic | null> {
    const key = `${language}:${id}`;
    let pending = this.#topics.get(key);
    if (!pending) {
      const load = this.#loader(language, topicFile(id));
      pending = load
        ? load().then(
            (module) => module.topic ?? null,
            () => null,
          )
        : Promise.resolve(null);
      this.#topics.set(key, pending);
    }
    return pending;
  }

  /** Every topic that exists in this language, in page order. */
  async topics(language: Language): Promise<HelpTopic[]> {
    const all = await Promise.all(HELP_TOPICS.map((id) => this.topic(language, id)));
    return all.filter((topic): topic is HelpTopic => topic !== null);
  }

  /** The glossary of this language (both halves), sorted by term. */
  glossary(language: Language): Promise<GlossaryEntry[]> {
    let pending = this.#glossary.get(language);
    if (!pending) {
      const parts = ['glossary-a', 'glossary-b'].map((file) => this.#loader(language, file));
      pending = Promise.all(
        parts.map((load) =>
          load
            ? load().then(
                (module) => module.glossary ?? [],
                () => [],
              )
            : [],
        ),
      ).then((halves) =>
        halves
          .flat()
          .sort((a, b) => a.term.localeCompare(b.term, language, { sensitivity: 'base' })),
      );
      this.#glossary.set(language, pending);
    }
    return pending;
  }
}

/** The app's help content. */
export const helpContent = new HelpContent(modules);
