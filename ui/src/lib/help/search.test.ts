import { describe, expect, it } from 'vitest';
import type { HelpModule } from './content';
import { fixtureGlossary, fixtureTopic } from './fixtures/fixture';
import { HELP_TOPICS, topicFile } from './resolve';
import { fold, matchQuality, searchHelp, type HelpHit } from './search';
import type { GlossaryEntry, HelpTopic } from './types';

const search = (query: string) => searchHelp(query, [fixtureTopic], fixtureGlossary);

describe('help search', () => {
  it('folds case and accents', () => {
    expect(fold('Één Delta-T')).toBe('een delta-t');
  });

  it('returns nothing for an empty query', () => {
    expect(search('  ')).toEqual([]);
  });

  it('finds topics, sections, questions and terms', () => {
    expect(search('fixture')[0]).toMatchObject({ kind: 'topic', topic: 'pump' });
    expect(search('speed')[0]).toMatchObject({ kind: 'section', section: 'speed' });
    expect(search('noisy')[0]).toMatchObject({ kind: 'question', question: 'noisy' });
    expect(search('delta')[0]).toMatchObject({ kind: 'term', term: 'delta-t' });
  });

  it('matches without accents and requires every word', () => {
    expect(search('een keer').map((hit) => hit.kind)).toEqual(['section']);
    expect(search('speed banana')).toEqual([]);
  });

  it('ranks title matches above body matches', () => {
    const hits = search('outlet');
    expect(hits[0]).toMatchObject({ kind: 'term', term: 'outlet' });
    expect(hits.some((hit) => hit.kind === 'section' && hit.section === 'flow')).toBe(true);
  });

  it('searches the text of markup, not the markup', () => {
    expect(search('settings')).toEqual(
      expect.arrayContaining([expect.objectContaining({ kind: 'section', section: 'speed' })]),
    );
    expect(search('pump-duty')).toEqual([]);
  });

  it('limits the number of hits', () => {
    expect(searchHelp('e', [fixtureTopic], fixtureGlossary, 2)).toHaveLength(2);
  });

  it('rates whole words over word starts over pieces of words', () => {
    expect(matchQuality('the war is over', 'war')).toBe(3);
    expect(matchQuality('a warning', 'war')).toBe(2);
    expect(matchQuality('software', 'war')).toBe(1);
    expect(matchQuality('a warning, then war', 'war')).toBe(3);
    expect(matchQuality('wood-stove mode', 'stove')).toBe(3);
    expect(matchQuality('nothing', 'war')).toBe(0);
  });

  it('finds aliases, and a whole-word alias beats a word start in a title', () => {
    const topic: HelpTopic = {
      ...fixtureTopic,
      sections: [{ id: 'warning', kind: 'know', title: 'Warning', body: 'A warning.' }],
      questions: [],
    };
    const glossary: GlossaryEntry[] = [
      { id: 'curve', term: 'Heating curve', short: 'The curve.', aliases: ['WAR'] },
    ];
    expect(searchHelp('WAR', [topic], glossary)[0]).toMatchObject({ kind: 'term', term: 'curve' });
    const aliased: HelpTopic = { ...fixtureTopic, aliases: ['who controls'] };
    expect(searchHelp('who controls', [aliased], [])[0]).toMatchObject({
      kind: 'topic',
      topic: 'pump',
    });
  });
});

const modules = import.meta.glob<HelpModule>(['./content/*/*.ts', '!./content/**/*.test.ts'], {
  eager: true,
});

function contentOf(language: 'en' | 'nl'): { topics: HelpTopic[]; glossary: GlossaryEntry[] } {
  const module = (file: string) => modules[`./content/${language}/${file}.ts`];
  const topics = HELP_TOPICS.flatMap((id) => {
    const topic = module(topicFile(id))?.topic;
    return topic ? [topic] : [];
  });
  const glossary = ['glossary-a', 'glossary-b'].flatMap((file) => module(file)?.glossary ?? []);
  return { topics, glossary };
}

const where = (hit: HelpHit | undefined) =>
  hit === undefined ? 'nothing' : hit.kind === 'term' ? `term ${hit.term}` : `topic ${hit.topic}`;

describe.each(['en', 'nl'] as const)('help search over the %s content', (language) => {
  const { topics, glossary } = contentOf(language);
  const first = (query: string) => where(searchHelp(query, topics, glossary)[0]);

  it('puts the heating curve or the switching guide first for WAR', () => {
    expect(['term heating-curve', 'topic switching']).toContain(first('WAR'));
    expect(['term heating-curve', 'topic switching']).toContain(first('war'));
  });

  it('finds the Node-RED names', () => {
    expect(['term room-feedback', 'topic switching']).toContain(first('RTC'));
    expect(['term start-ramp', 'topic switching']).toContain(first('SoftStart'));
    expect(['term quiet-mode', 'topic switching']).toContain(first('NightReduction'));
    expect(first('Node-RED')).not.toBe('nothing');
  });

  it('finds the words owners use', () => {
    expect(first('shadow')).toBe('term shadow');
    expect(first('fallback')).not.toBe('nothing');
    expect(first('notification')).not.toBe('nothing');
    expect(['topic start', 'term control-state']).toContain(first('who controls'));
    expect(first('build period')).toBe('topic house');
    expect(first('csv')).toBe('topic activity');
  });
});

describe('help search for owners, per language', () => {
  const en = contentOf('en');
  const nl = contentOf('nl');
  const first = (language: typeof en, query: string) =>
    where(searchHelp(query, language.topics, language.glossary)[0]);

  it('finds the alarm for a Dutch "storing"', () => {
    expect(first(nl, 'storing')).toBe('term alarm');
    expect(first(nl, 'melding')).not.toBe('nothing');
    expect(['topic start', 'term control-state']).toContain(first(nl, 'wie stuurt'));
    expect(first(nl, 'schaduw')).toBe('term shadow');
    expect(first(nl, 'terugval')).not.toBe('nothing');
    expect(first(nl, 'bouwperiode')).toBe('topic house');
    expect(first(nl, 'csv')).toBe('topic activity');
  });

  it('finds the wood stove', () => {
    expect(['term wood-stove', 'topic settings/stove']).toContain(first(nl, 'houtkachel'));
    expect(['term wood-stove', 'topic settings/stove']).toContain(first(en, 'stove'));
    expect(['term wood-stove', 'topic settings/stove']).toContain(first(en, 'fireplace'));
  });
});
