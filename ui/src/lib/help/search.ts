import { plainText } from './markup';
import type { GlossaryEntry, HelpTopic, HelpTopicId } from './types';

export type HelpHit =
  | { kind: 'topic'; topic: HelpTopicId; title: string; snippet: string; score: number }
  | {
      kind: 'section';
      topic: HelpTopicId;
      section: string;
      title: string;
      context: string;
      snippet: string;
      score: number;
    }
  | {
      kind: 'question';
      topic: HelpTopicId;
      question: string;
      title: string;
      context: string;
      snippet: string;
      score: number;
    }
  | { kind: 'term'; term: string; title: string; snippet: string; score: number };

/**
 * Lower-case text without accents, so "een" finds "één".
 */
export function fold(text: string): string {
  return text.normalize('NFD').replace(/\p{M}/gu, '').toLowerCase();
}

function words(query: string): string[] {
  return fold(query)
    .split(/[^\p{L}\p{N}-]+/u)
    .filter((word) => word.length > 0);
}

interface Field {
  text: string;
  weight: number;
}

const ALIAS_WEIGHT = 6;

const isWordChar = (char: string | undefined) => char !== undefined && /[\p{L}\p{N}]/u.test(char);

/**
 * How well a token occurs in a text: 3 as a whole word, 2 at the start of a word, 1 inside a
 * word, 0 not at all. Every occurrence counts, so "WAR" in "warning … WAR" is a whole word.
 */
export function matchQuality(text: string, token: string): number {
  let best = 0;
  for (let at = text.indexOf(token); at >= 0 && best < 3; at = text.indexOf(token, at + 1)) {
    const start = !isWordChar(text[at - 1]);
    const end = !isWordChar(text[at + token.length]);
    best = Math.max(best, start ? (end ? 3 : 2) : 1);
  }
  return best;
}

function score(tokens: string[], fields: Field[]): number {
  let total = 0;
  for (const token of tokens) {
    let best = 0;
    for (const field of fields) {
      const quality = matchQuality(fold(field.text), token);
      if (quality > 0) best = Math.max(best, field.weight * quality);
    }
    if (best === 0) return 0;
    total += best;
  }
  return total;
}

function aliasField(aliases: string[] | undefined): Field[] {
  return aliases?.length ? [{ text: aliases.join(' · '), weight: ALIAS_WEIGHT }] : [];
}

function snippet(text: string, tokens: string[], length = 110): string {
  const folded = fold(text);
  const at = Math.min(
    ...tokens.map((token) => folded.indexOf(token)).filter((index) => index >= 0),
    text.length,
  );
  const start = at > 40 ? text.lastIndexOf(' ', at - 30) + 1 : 0;
  const piece = text.slice(start, start + length).trim();
  return `${start > 0 ? '…' : ''}${piece}${start + length < text.length ? '…' : ''}`;
}

/**
 * Search topics, their sections and questions, and the glossary, including their aliases;
 * every word of the query must occur. A whole word counts more than the start of a word, and
 * that more than a piece inside a word. Best matches first, at most `limit`.
 */
export function searchHelp(
  query: string,
  topics: HelpTopic[],
  glossary: GlossaryEntry[],
  limit = 12,
): HelpHit[] {
  const tokens = words(query);
  if (tokens.length === 0) return [];
  const hits: HelpHit[] = [];
  for (const topic of topics) {
    const topicScore = score(tokens, [
      { text: topic.title, weight: 6 },
      { text: topic.lead, weight: 3 },
      ...aliasField(topic.aliases),
    ]);
    if (topicScore > 0)
      hits.push({
        kind: 'topic',
        topic: topic.id,
        title: topic.title,
        snippet: topic.lead,
        score: topicScore + 1,
      });
    for (const section of topic.sections) {
      const body = [plainText(section.body), ...(section.steps ?? []).map(plainText)].join(' ');
      const value = score(tokens, [
        { text: section.title, weight: 5 },
        { text: body, weight: 2 },
      ]);
      if (value > 0)
        hits.push({
          kind: 'section',
          topic: topic.id,
          section: section.id,
          title: section.title,
          context: topic.title,
          snippet: snippet(body, tokens),
          score: value,
        });
    }
    for (const question of topic.questions ?? []) {
      const answer = plainText(question.a);
      const value = score(tokens, [
        { text: question.q, weight: 4 },
        { text: answer, weight: 1 },
      ]);
      if (value > 0)
        hits.push({
          kind: 'question',
          topic: topic.id,
          question: question.id,
          title: question.q,
          context: topic.title,
          snippet: snippet(answer, tokens),
          score: value,
        });
    }
  }
  for (const entry of glossary) {
    const value = score(tokens, [
      { text: entry.term, weight: 6 },
      { text: entry.short, weight: 2 },
      { text: plainText(entry.body ?? ''), weight: 1 },
      ...aliasField(entry.aliases),
    ]);
    if (value > 0)
      hits.push({
        kind: 'term',
        term: entry.id,
        title: entry.term,
        snippet: plainText(entry.short),
        score: value + 0.5,
      });
  }
  return hits.sort((a, b) => b.score - a.score).slice(0, limit);
}
