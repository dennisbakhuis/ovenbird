// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from '@testing-library/svelte';
import { afterEach, describe, expect, it, vi } from 'vitest';
import OverlayHarness from './OverlayHarness.test.svelte';

afterEach(cleanup);

describe('Overlay', () => {
  it('moves the panel to the body and focuses it', () => {
    const { container } = render(OverlayHarness);
    const dialog = screen.getByRole('dialog');
    expect(container.contains(dialog)).toBe(false);
    expect(document.body.contains(dialog)).toBe(true);
    expect(document.activeElement).toBe(dialog);
  });

  it('closes on Escape', async () => {
    const onclose = vi.fn();
    render(OverlayHarness, { onclose });
    await fireEvent.keyDown(screen.getByRole('dialog'), { key: 'Escape' });
    expect(onclose).toHaveBeenCalledOnce();
  });

  it('closes on a press outside only when asked to', async () => {
    const onclose = vi.fn();
    const { unmount } = render(OverlayHarness, { onclose });
    await fireEvent.pointerDown(screen.getByTestId('elsewhere'));
    expect(onclose).not.toHaveBeenCalled();
    unmount();
    render(OverlayHarness, { onclose, outside: true });
    await fireEvent.pointerDown(screen.getByRole('dialog'));
    expect(onclose).not.toHaveBeenCalled();
    await fireEvent.pointerDown(screen.getByTestId('elsewhere'));
    expect(onclose).toHaveBeenCalledOnce();
  });

  it('locks scrolling and traps Tab while modal, and releases on close', async () => {
    const { unmount } = render(OverlayHarness, { modal: true });
    expect(document.documentElement.style.overflow).toBe('hidden');
    expect(screen.getByRole('dialog').getAttribute('aria-modal')).toBe('true');
    screen.getByTestId('last').focus();
    const tab = new KeyboardEvent('keydown', { key: 'Tab', bubbles: true, cancelable: true });
    screen.getByTestId('last').dispatchEvent(tab);
    expect(tab.defaultPrevented).toBe(true);
    expect(document.activeElement).toBe(screen.getByTestId('first'));
    unmount();
    expect(document.documentElement.style.overflow).toBe('');
  });

  it('hands focus back to the opener', () => {
    const opener = document.createElement('button');
    document.body.append(opener);
    opener.focus();
    const { unmount } = render(OverlayHarness);
    expect(document.activeElement).not.toBe(opener);
    unmount();
    expect(document.activeElement).toBe(opener);
    opener.remove();
  });
});
