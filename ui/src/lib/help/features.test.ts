import { describe, expect, it } from 'vitest';
import type { HelpModule } from './content';
import { hiddenFeatures, shownGlossary, shownTopic } from './features';
import { plainText, termsIn } from './markup';
import type { GlossaryEntry, HelpTopic } from './types';

const modules = import.meta.glob<HelpModule>(['./content/*/*.ts', '!./content/**/*.test.ts'], {
  eager: true,
});

const topic: HelpTopic = {
  id: 'pump',
  title: 'Pump',
  lead: 'The pump.',
  art: 'pump',
  sections: [
    { id: 'tank', kind: 'know', title: 'Tank', body: 'About the tank.', feature: 'hotWater' },
    {
      id: 'lanes',
      kind: 'see',
      title: 'Lanes',
      body: 'Compressor, defrost and hot water.',
      without: { hotWater: { body: 'Compressor and defrost.' } },
    },
    { id: 'plain', kind: 'see', title: 'Plain', body: 'Nothing about it.' },
  ],
  questions: [
    { id: 'tank', q: 'Is the tank hot?', a: 'Yes.', feature: 'hotWater' },
    {
      id: 'runs',
      q: 'Why does it stop for hot water?',
      a: 'It is busy.',
      without: { hotWater: { q: 'Why does it stop?' } },
    },
  ],
};

const glossary: GlossaryEntry[] = [
  { id: 'defrost', term: 'Defrost', short: 'Ice.', related: ['dhw', 'flow'] },
  { id: 'dhw', term: 'Hot water', short: 'The tank.', feature: 'hotWater' },
  {
    id: 'flow',
    term: 'Flow',
    short: 'Water moving, also to the tank.',
    without: { hotWater: { short: 'Water moving.' } },
  },
];

describe('help features', () => {
  it('hides hot water only when it does not show', () => {
    expect([...hiddenFeatures(true)]).toEqual([]);
    expect([...hiddenFeatures(false)]).toEqual(['hotWater']);
  });

  it('keeps everything as written while nothing is hidden', () => {
    expect(shownTopic(topic, hiddenFeatures(true))).toBe(topic);
    expect(shownGlossary(glossary, hiddenFeatures(true))).toBe(glossary);
  });

  it('leaves out what is about a hidden feature and rephrases what mentions it', () => {
    const shown = shownTopic(topic, hiddenFeatures(false));
    expect(shown.sections.map((s) => [s.id, s.body])).toEqual([
      ['lanes', 'Compressor and defrost.'],
      ['plain', 'Nothing about it.'],
    ]);
    expect(shown.questions?.map((q) => [q.id, q.q, q.a])).toEqual([
      ['runs', 'Why does it stop?', 'It is busy.'],
    ]);
  });

  it('drops a hidden glossary entry, also from the related terms of the others', () => {
    const shown = shownGlossary(glossary, hiddenFeatures(false));
    expect(shown.map((entry) => entry.id)).toEqual(['defrost', 'flow']);
    expect(shown[0]?.related).toEqual(['flow']);
    expect(shown[1]?.short).toBe('Water moving.');
  });
});

const WORDS: Record<string, RegExp> = {
  en: /hot[- ]?water|\bDHW\b|\btanks?\b/i,
  nl: /tapwater|warm ?water|boiler/i,
};

/** Phrases that use the words in another sense: water warming the floor, not a tank. */
const ALLOWED: Record<string, string[]> = { en: [], nl: ['vol warm water'] };

/** The section that explains the setting itself stays, so hot water can be switched back on. */
const SETTING = 'settings/pump-duty#hot-water';

function texts(language: string): { where: string; text: string }[] {
  const out: { where: string; text: string }[] = [];
  const hidden = hiddenFeatures(false);
  for (const [path, module] of Object.entries(modules)) {
    if (!path.startsWith(`./content/${language}/`)) continue;
    if (module.topic) {
      const shown = shownTopic(module.topic, hidden);
      out.push({ where: `${shown.id} lead`, text: shown.lead });
      for (const s of shown.sections)
        for (const text of [s.title, s.body, ...(s.steps ?? [])])
          out.push({ where: `${shown.id}#${s.id}`, text });
      for (const q of shown.questions ?? [])
        for (const text of [q.q, q.a]) out.push({ where: `${shown.id}?${q.id}`, text });
    }
    for (const entry of shownGlossary(module.glossary ?? [], hidden))
      for (const text of [entry.term, entry.short, entry.body ?? ''])
        out.push({ where: `glossary ${entry.id}`, text });
  }
  return out;
}

describe.each(['en', 'nl'])('%s help with hot water hidden', (language) => {
  const shown = texts(language);

  it('does not mention hot water outside the setting that hides it', () => {
    const mentions = shown
      .filter(({ where }) => where !== SETTING)
      .filter(({ text }) => {
        let rest = plainText(text);
        for (const phrase of ALLOWED[language] ?? []) rest = rest.split(phrase).join('');
        return WORDS[language]!.test(rest);
      })
      .map(({ where }) => where);
    expect(mentions).toEqual([]);
  });

  it('links no glossary entry that is left out', () => {
    const links = shown
      .filter(({ where }) => where !== SETTING)
      .filter(({ text }) => termsIn(text).includes('dhw'))
      .map(({ where }) => where);
    expect(links).toEqual([]);
  });

  it('keeps the section about the setting', () => {
    expect(shown.some(({ where }) => where === SETTING)).toBe(true);
  });
});
