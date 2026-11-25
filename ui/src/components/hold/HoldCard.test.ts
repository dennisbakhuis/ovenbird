// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/svelte';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { initialState, makeControl } from '$mock/decisions';
import HoldCard from './HoldCard.svelte';

const NOW = Date.parse('2026-11-15T12:00:00Z');

afterEach(cleanup);

function adapterWithHold() {
  return makeControl(NOW, initialState()).adapter;
}

describe('HoldCard', () => {
  it('shows the hold, its end time and the release button', () => {
    render(HoldCard, { adapter: adapterWithHold(), admin: true, onrelease: vi.fn() });
    expect(screen.getByText('Someone else changed the pump')).toBeTruthy();
    expect(screen.getByText(/ovenbird sends again at/)).toBeTruthy();
    expect(screen.getByText('2 holds in the last 12 h.')).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Release hold' })).toBeTruthy();
  });

  it('releases through a confirmation step with the typed reason', async () => {
    const onrelease = vi.fn().mockResolvedValue(null);
    render(HoldCard, { adapter: adapterWithHold(), admin: null, onrelease });
    await fireEvent.click(screen.getByRole('button', { name: 'Release hold' }));
    expect(onrelease).not.toHaveBeenCalled();
    await fireEvent.input(screen.getByLabelText('Reason (optional)'), {
      target: { value: 'checked the remote' },
    });
    await fireEvent.click(screen.getByRole('button', { name: 'Release now' }));
    await waitFor(() => expect(onrelease).toHaveBeenCalledWith('checked the remote'));
    await waitFor(() => expect(screen.queryByRole('button', { name: 'Release now' })).toBeNull());
  });

  it('can be cancelled without releasing', async () => {
    const onrelease = vi.fn();
    render(HoldCard, { adapter: adapterWithHold(), admin: true, onrelease });
    await fireEvent.click(screen.getByRole('button', { name: 'Release hold' }));
    await fireEvent.click(screen.getByRole('button', { name: 'Cancel' }));
    expect(onrelease).not.toHaveBeenCalled();
    expect(screen.getByRole('button', { name: 'Release hold' })).toBeTruthy();
  });

  it('is disabled with an explanation for a non-admin', () => {
    render(HoldCard, { adapter: adapterWithHold(), admin: false, onrelease: vi.fn() });
    const button = screen.getByRole('button', { name: 'Release hold' }) as HTMLButtonElement;
    expect(button.disabled).toBe(true);
    expect(screen.getByTestId('hold-not-admin').textContent).toMatch(/administrator/);
  });

  it('keeps the form open and shows an error when the release is refused', async () => {
    const onrelease = vi.fn().mockResolvedValue('forbidden');
    render(HoldCard, { adapter: adapterWithHold(), admin: null, onrelease });
    await fireEvent.click(screen.getByRole('button', { name: 'Release hold' }));
    await fireEvent.click(screen.getByRole('button', { name: 'Release now' }));
    const alert = await screen.findByRole('alert');
    expect(alert.textContent).toMatch(/administrator/);
    expect(screen.getByRole('button', { name: 'Release now' })).toBeTruthy();
  });

  it('says there is no hold when the adapter reports none', () => {
    const adapter = adapterWithHold();
    if (adapter) adapter.hold = null;
    render(HoldCard, { adapter, admin: true, onrelease: vi.fn() });
    expect(screen.getByTestId('no-hold')).toBeTruthy();
    expect(screen.queryByRole('button', { name: 'Release hold' })).toBeNull();
  });

  it('says commands are not published when there is no adapter', () => {
    render(HoldCard, { adapter: null, admin: true, onrelease: vi.fn() });
    expect(screen.getByText(/not being published/)).toBeTruthy();
  });

  it('shows a latched hold without an end time', () => {
    const adapter = adapterWithHold();
    if (adapter) {
      adapter.hold_latched = true;
      adapter.hold_until = null;
    }
    render(HoldCard, { adapter, admin: true, onrelease: vi.fn() });
    expect(screen.getByText(/waits until an administrator releases it/)).toBeTruthy();
  });
});

describe('HoldCard forensics', () => {
  const detail = {
    setting: 'water_setpoint',
    register: 'setcurves_target_high',
    ovenbird_value: 33,
    seen_value: 31,
    seen_since: '2026-11-15T11:30:00Z',
    pump_keeps: 31,
    at_hold_end: 'write_again',
    controller_wants: 33,
  };

  it('says what ovenbird set, what the pump reports and what happens next', () => {
    render(HoldCard, { adapter: adapterWithHold(), admin: true, onrelease: vi.fn(), detail });
    const facts = screen.getByTestId('hold-forensics');
    expect(facts.textContent).toContain('setcurves_target_high');
    expect(screen.getByTestId('hold-ovenbird').textContent).toBe('33 °C');
    expect(screen.getByTestId('hold-keeps').textContent).toBe('31 °C');
    expect(screen.getByTestId('hold-end').textContent).toMatch(/writes its own value again/);
  });

  it('shows nothing extra for an older service without detail', () => {
    render(HoldCard, { adapter: adapterWithHold(), admin: true, onrelease: vi.fn(), detail: {} });
    expect(screen.queryByTestId('hold-forensics')).toBeNull();
  });
});
