import { describe, expect, it } from 'vitest';
import type { HelpModule } from './content';
import { HelpContent } from './content';
import { fixtureGlossary, fixtureTopic } from './fixtures/fixture';
import { linksIn, termsIn } from './markup';
import { HELP_TOPICS, isAppRoute, isHelpTopic, topicFile } from './resolve';
import type { GlossaryEntry, HelpTopic } from './types';

const modules = import.meta.glob<HelpModule>(['./content/*/*.ts', '!./content/**/*.test.ts'], {
  eager: true,
});

const LANGUAGES = ['en', 'nl'] as const;
const GLOSSARY_FILES = ['glossary-a', 'glossary-b'];
const TOPIC_FILES = new Set(HELP_TOPICS.map(topicFile));

interface Language {
  files: string[];
  topics: Map<string, HelpTopic>;
  glossary: Record<string, GlossaryEntry[]>;
}

function collect(language: string): Language {
  const result: Language = { files: [], topics: new Map(), glossary: {} };
  for (const [path, module] of Object.entries(modules)) {
    const match = /^\.\/content\/(\w+)\/(.+)\.ts$/.exec(path);
    if (!match || match[1] !== language) continue;
    const file = match[2]!;
    result.files.push(file);
    if (module.topic) result.topics.set(file, module.topic);
    if (module.glossary) result.glossary[file] = module.glossary;
  }
  result.files.sort();
  return result;
}

const content = { en: collect('en'), nl: collect('nl') };

function bodies(topic: HelpTopic): string[] {
  return [
    topic.lead,
    ...topic.sections.flatMap((s) => [s.title, s.body, ...(s.steps ?? [])]),
    ...(topic.questions ?? []).flatMap((q) => [q.q, q.a]),
  ];
}

function variants(without: Partial<Record<string, object>> | undefined): string[] {
  return Object.entries(without ?? {}).flatMap(([feature, text]) =>
    Object.keys(text ?? {})
      .sort()
      .map((field) => `${feature}.${field}`),
  );
}

function glossaryOf(language: Language): GlossaryEntry[] {
  return GLOSSARY_FILES.flatMap((file) => language.glossary[file] ?? []);
}

describe('help content files', () => {
  it('has the same files in EN and NL', () => {
    expect(content.nl.files).toEqual(content.en.files);
  });

  it.each(LANGUAGES)('names every %s file after a topic or a glossary half', (language) => {
    for (const file of content[language].files) {
      const known = TOPIC_FILES.has(file) || GLOSSARY_FILES.includes(file);
      expect(known, file).toBe(true);
      if (GLOSSARY_FILES.includes(file))
        expect(Array.isArray(content[language].glossary[file]), file).toBe(true);
      else expect(topicFile(content[language].topics.get(file)?.id ?? 'home'), file).toBe(file);
    }
  });

  it.each(LANGUAGES)('keeps %s topics well formed', (language) => {
    for (const [file, topic] of content[language].topics) {
      expect(topic.title.trim(), file).not.toBe('');
      expect(topic.lead.trim(), file).not.toBe('');
      const ids = topic.sections.map((s) => s.id);
      expect(new Set(ids).size, `${file} section ids`).toBe(ids.length);
      const questions = (topic.questions ?? []).map((q) => q.id);
      expect(new Set(questions).size, `${file} question ids`).toBe(questions.length);
      for (const section of topic.sections) {
        expect(['see', 'do', 'know'], `${file}.${section.id}`).toContain(section.kind);
        expect(section.body.trim(), `${file}.${section.id}`).not.toBe('');
        if (section.target)
          expect(section.target.startsWith(`${topic.id}.`), section.target).toBe(true);
      }
      for (const id of topic.related ?? []) {
        expect(isHelpTopic(id), `${file} related ${id}`).toBe(true);
        expect(id, `${file} relates to itself`).not.toBe(topic.id);
      }
    }
  });

  it('has the same topics, sections, kinds, targets and questions in EN and NL', () => {
    const shape = (topic: HelpTopic) => ({
      id: topic.id,
      art: topic.art,
      sections: topic.sections.map((s) => ({
        id: s.id,
        kind: s.kind,
        target: s.target ?? null,
        steps: s.steps?.length ?? 0,
        feature: s.feature ?? null,
        without: variants(s.without),
      })),
      questions: (topic.questions ?? []).map((q) => ({
        id: q.id,
        feature: q.feature ?? null,
        without: variants(q.without),
      })),
      related: topic.related ?? [],
    });
    for (const [file, topic] of content.en.topics) {
      const nl = content.nl.topics.get(file);
      expect(nl, file).toBeDefined();
      if (nl) expect(shape(nl), file).toEqual(shape(topic));
    }
  });

  it.each(LANGUAGES)('has unique %s glossary ids across both halves', (language) => {
    const ids = glossaryOf(content[language]).map((entry) => entry.id);
    expect(ids.filter((id, index) => ids.indexOf(id) !== index)).toEqual([]);
  });

  it('has the same glossary ids in EN and NL, in the same halves', () => {
    for (const file of GLOSSARY_FILES) {
      const ids = (language: Language) =>
        (language.glossary[file] ?? []).map((entry) => entry.id).sort();
      expect(ids(content.nl), file).toEqual(ids(content.en));
    }
  });

  it('tags and rephrases the same glossary entries for a hidden feature in EN and NL', () => {
    const shape = (language: Language) =>
      glossaryOf(language)
        .map((entry) => ({
          id: entry.id,
          feature: entry.feature ?? null,
          without: variants(entry.without),
        }))
        .sort((a, b) => a.id.localeCompare(b.id));
    expect(shape(content.nl)).toEqual(shape(content.en));
  });

  it.each(LANGUAGES)('resolves every %s glossary link and in-app link', (language) => {
    const entries = glossaryOf(content[language]);
    const known = new Set(entries.map((entry) => entry.id));
    const texts: [string, string][] = [];
    for (const [file, topic] of content[language].topics)
      for (const text of bodies(topic)) texts.push([file, text]);
    for (const entry of entries) {
      texts.push([`glossary ${entry.id}`, entry.short]);
      if (entry.body) texts.push([`glossary ${entry.id}`, entry.body]);
      for (const id of entry.related ?? [])
        expect(known.has(id), `glossary ${entry.id} related ${id}`).toBe(true);
    }
    const missing = texts.flatMap(([where, text]) =>
      termsIn(text)
        .filter((id) => !known.has(id))
        .map((id) => `${where}: [[${id}]]`),
    );
    expect(missing).toEqual([]);
    const broken = texts.flatMap(([where, text]) =>
      linksIn(text)
        .filter((href) => !isAppRoute(href))
        .map((href) => `${where}: ${href}`),
    );
    expect(broken).toEqual([]);
  });
});

describe('HelpContent', () => {
  const loaders = {
    './content/en/pump.ts': async () => ({ topic: fixtureTopic }),
    './content/en/glossary-a.ts': async () => ({ glossary: [fixtureGlossary[1]!] }),
    './content/en/glossary-b.ts': async () => ({ glossary: [fixtureGlossary[0]!] }),
    './content/nl/broken.ts': async () => Promise.reject(new Error('offline')),
  };
  const store = new HelpContent(loaders);

  it('knows which topics exist and loads them lazily', async () => {
    expect(store.has('en', 'pump')).toBe(true);
    expect(store.has('nl', 'pump')).toBe(false);
    expect(await store.topic('en', 'pump')).toBe(fixtureTopic);
    expect(await store.topic('nl', 'pump')).toBeNull();
    expect((await store.topics('en')).map((topic) => topic.id)).toEqual(['pump']);
  });

  it('merges and sorts both glossary halves', async () => {
    expect((await store.glossary('en')).map((entry) => entry.id)).toEqual(['delta-t', 'outlet']);
    expect(await store.glossary('nl')).toEqual([]);
  });
});
