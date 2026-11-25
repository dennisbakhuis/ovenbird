// @vitest-environment jsdom
import { cleanup, render, screen } from '@testing-library/svelte';
import { afterEach, describe, expect, it } from 'vitest';
import InlineMessageHarness from './InlineMessageHarness.test.svelte';

afterEach(cleanup);

describe('InlineMessage', () => {
  it('announces errors', () => {
    render(InlineMessageHarness, { tone: 'error' });
    expect(screen.getByRole('alert').textContent).toContain('Saved?');
  });

  it('keeps warnings, confirmations and notes quiet', () => {
    for (const tone of ['warn', 'ok', 'info'] as const) {
      render(InlineMessageHarness, { tone });
      expect(screen.queryByRole('alert')).toBeNull();
      cleanup();
    }
  });
});
