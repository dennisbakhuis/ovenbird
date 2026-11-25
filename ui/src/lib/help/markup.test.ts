import { describe, expect, it } from 'vitest';
import { linksIn, parseBody, parseInline, plainText, termsIn } from './markup';

describe('help markup', () => {
  it('parses bold, terms, labelled terms and in-app links', () => {
    expect(parseInline('A **bold [[cop]]** and [[delta-t|the gap]] or [this](#/pump).')).toEqual([
      { kind: 'text', text: 'A ' },
      {
        kind: 'bold',
        children: [
          { kind: 'text', text: 'bold ' },
          { kind: 'term', id: 'cop', text: 'cop' },
        ],
      },
      { kind: 'text', text: ' and ' },
      { kind: 'term', id: 'delta-t', text: 'the gap' },
      { kind: 'text', text: ' or ' },
      { kind: 'link', text: 'this', href: '#/pump' },
      { kind: 'text', text: '.' },
    ]);
  });

  it('keeps links that are not app routes as plain text', () => {
    expect(parseInline('[evil](javascript:alert(1)) [out](https://x.y) [no](#/nowhere)')).toEqual([
      { kind: 'text', text: 'evil) out no' },
    ]);
  });

  it('never produces HTML: tags stay text', () => {
    expect(parseInline('<img src=x onerror=alert(1)>')).toEqual([
      { kind: 'text', text: '<img src=x onerror=alert(1)>' },
    ]);
  });

  it('splits paragraphs on blank lines and joins wrapped lines', () => {
    const blocks = parseBody('First line\nwraps here.\n\nSecond.');
    expect(blocks).toEqual([
      { kind: 'p', content: [{ kind: 'text', text: 'First line wraps here.' }] },
      { kind: 'p', content: [{ kind: 'text', text: 'Second.' }] },
    ]);
  });

  it('turns "- " lines into a list, with indented continuation lines', () => {
    const blocks = parseBody('Intro:\n- one\n  continued\n- **two**\nAfter.');
    expect(blocks.map((b) => b.kind)).toEqual(['p', 'list', 'p']);
    const list = blocks[1];
    expect(list?.kind === 'list' && list.items.length).toBe(2);
    expect(list?.kind === 'list' && list.items[0]).toEqual([
      { kind: 'text', text: 'one continued' },
    ]);
  });

  it('gives the plain text, the terms and the links of a body', () => {
    const body = 'See **[[cop|COP]]** and [[scop]].\n\n- [Pump](#/pump) **[x](#/home)**';
    expect(plainText(body)).toBe('See COP and scop. Pump x');
    expect(termsIn(body)).toEqual(['cop', 'scop']);
    expect(linksIn(body)).toEqual(['#/pump', '#/home']);
  });

  it('handles an empty body', () => {
    expect(parseBody('')).toEqual([]);
    expect(parseBody('\n\n  \n')).toEqual([]);
  });
});
