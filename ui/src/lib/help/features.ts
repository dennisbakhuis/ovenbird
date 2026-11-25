import type { GlossaryEntry, HelpFeature, HelpTopic } from './types';

export type HiddenFeatures = ReadonlySet<HelpFeature>;

const NONE: HiddenFeatures = new Set();
const NO_HOT_WATER: HiddenFeatures = new Set(['hotWater']);

/**
 * The features the app hides now: hot water unless it shows.
 */
export function hiddenFeatures(hotWater: boolean): HiddenFeatures {
  return hotWater ? NONE : NO_HOT_WATER;
}

const kept = (item: { feature?: HelpFeature }, hidden: HiddenFeatures) =>
  item.feature === undefined || !hidden.has(item.feature);

function rephrase<T extends object>(
  item: T,
  without: NoInfer<Partial<Record<HelpFeature, Partial<T>>>> | undefined,
  hidden: HiddenFeatures,
): T {
  let out = item;
  for (const feature of hidden) {
    const text = without?.[feature];
    if (text) out = { ...out, ...text };
  }
  return out;
}

/**
 * A topic as shown: sections and questions about a hidden feature left out, the others in
 * their text without it.
 */
export function shownTopic(topic: HelpTopic, hidden: HiddenFeatures): HelpTopic {
  if (hidden.size === 0) return topic;
  return {
    ...topic,
    sections: topic.sections
      .filter((section) => kept(section, hidden))
      .map((section) => rephrase(section, section.without, hidden)),
    questions: topic.questions
      ?.filter((question) => kept(question, hidden))
      .map((question) => rephrase(question, question.without, hidden)),
  };
}

/**
 * The glossary as shown: entries about a hidden feature left out (also from the related terms
 * of the others), the rest in their text without it.
 */
export function shownGlossary(entries: GlossaryEntry[], hidden: HiddenFeatures): GlossaryEntry[] {
  if (hidden.size === 0) return entries;
  const left = entries.filter((entry) => kept(entry, hidden));
  const ids = new Set(left.map((entry) => entry.id));
  return left.map((entry) => {
    const shown = rephrase(entry, entry.without, hidden);
    return shown.related ? { ...shown, related: shown.related.filter((id) => ids.has(id)) } : shown;
  });
}
