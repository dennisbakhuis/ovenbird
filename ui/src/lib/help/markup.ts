import { isAppRoute } from './resolve';

export type Inline =
  | { kind: 'text'; text: string }
  | { kind: 'bold'; children: Inline[] }
  | { kind: 'term'; id: string; text: string }
  | { kind: 'link'; text: string; href: string };

export type Block = { kind: 'p'; content: Inline[] } | { kind: 'list'; items: Inline[][] };

const TOKEN = /\*\*(.+?)\*\*|\[\[([^\]|]+?)(?:\|([^\]]+?))?\]\]|\[([^\]]+?)\]\(([^)\s]*)\)/g;

/**
 * Parse one line of help markup into inline nodes: `**bold**`, `[[term]]`,
 * `[[term|text]]` and `[text](#/route)`. A link that is not an in-app route stays text.
 */
export function parseInline(text: string, nested = false): Inline[] {
  const out: Inline[] = [];
  const push = (node: Inline) => {
    const last = out[out.length - 1];
    if (node.kind === 'text' && last?.kind === 'text') last.text += node.text;
    else if (node.kind !== 'text' || node.text) out.push(node);
  };
  let at = 0;
  for (const match of text.matchAll(TOKEN)) {
    const [whole, bold, termId, termText, linkText, href] = match;
    push({ kind: 'text', text: text.slice(at, match.index) });
    at = match.index + whole.length;
    if (bold !== undefined) {
      if (nested) push({ kind: 'text', text: bold });
      else push({ kind: 'bold', children: parseInline(bold, true) });
    } else if (termId !== undefined) {
      const id = termId.trim();
      push({ kind: 'term', id, text: (termText ?? id).trim() });
    } else if (linkText !== undefined && href !== undefined) {
      push(
        isAppRoute(href)
          ? { kind: 'link', text: linkText, href }
          : { kind: 'text', text: linkText },
      );
    }
  }
  push({ kind: 'text', text: text.slice(at) });
  return out;
}

/**
 * Parse a help body into blocks: paragraphs separated by blank lines, and lists of lines
 * that start with "- ". Indented lines continue the list item above them.
 */
export function parseBody(body: string): Block[] {
  const blocks: Block[] = [];
  for (const chunk of body.replace(/\r\n?/g, '\n').split(/\n[ \t]*\n/)) {
    let paragraph: string[] = [];
    let items: string[] = [];
    const flushParagraph = () => {
      const text = paragraph.join(' ').trim();
      if (text) blocks.push({ kind: 'p', content: parseInline(text) });
      paragraph = [];
    };
    const flushList = () => {
      if (items.length)
        blocks.push({ kind: 'list', items: items.map((item) => parseInline(item)) });
      items = [];
    };
    for (const raw of chunk.split('\n')) {
      const line = raw.trim();
      if (!line) continue;
      if (line.startsWith('- ')) {
        flushParagraph();
        items.push(line.slice(2).trim());
      } else if (items.length && /^\s/.test(raw)) {
        items[items.length - 1] += ` ${line}`;
      } else {
        flushList();
        paragraph.push(line);
      }
    }
    flushParagraph();
    flushList();
  }
  return blocks;
}

function inlineText(nodes: Inline[]): string {
  return nodes
    .map((node) => (node.kind === 'bold' ? inlineText(node.children) : node.text))
    .join('');
}

/**
 * The plain text of a help body, for search and length checks.
 */
export function plainText(body: string): string {
  return parseBody(body)
    .map((block) =>
      block.kind === 'p' ? inlineText(block.content) : block.items.map(inlineText).join(' '),
    )
    .join(' ');
}

function collect<T>(body: string, pick: (node: Inline) => T | undefined): T[] {
  const found: T[] = [];
  const walk = (nodes: Inline[]) => {
    for (const node of nodes) {
      const value = pick(node);
      if (value !== undefined) found.push(value);
      if (node.kind === 'bold') walk(node.children);
    }
  };
  for (const block of parseBody(body)) {
    if (block.kind === 'p') walk(block.content);
    else block.items.forEach(walk);
  }
  return found;
}

/**
 * The glossary ids a body links to.
 */
export function termsIn(body: string): string[] {
  return collect(body, (node) => (node.kind === 'term' ? node.id : undefined));
}

/**
 * Every `[text](href)` target written in a body, valid or not.
 */
export function linksIn(body: string): string[] {
  return [...body.matchAll(/(?<!\[)\[[^[\]]+?\]\(([^)\s]*)\)/g)].map((match) => match[1] ?? '');
}
