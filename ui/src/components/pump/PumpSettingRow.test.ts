// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/svelte';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { ApiError } from '$lib/core/api';
import { translateOptional } from '$lib/i18n';
import type { PumpRefusalCode } from '$lib/core/types';
import type { PumpSetting } from '$lib/core/types';
import PumpSettingRow from './PumpSettingRow.svelte';

const setting: PumpSetting = {
  id: 'heat_delta',
  signal: 'main/Heat_Delta',
  value: 5,
  unit: 'K',
  label: null,
  fresh: true,
  age: 12,
  command: 'SetFloorHeatDelta',
  supported: true,
  access: 'write',
  min: 3,
  max: 10,
  owner: 'operator',
  last_write: null,
};

function mount(
  onwrite = vi.fn().mockResolvedValue(undefined),
  extra: Record<string, unknown> = {},
) {
  render(PumpSettingRow, { setting, writable: true, admin: true, onwrite, ...extra });
  return onwrite;
}

async function open(value: string) {
  await fireEvent.click(screen.getByTestId('pump-edit-heat_delta'));
  await fireEvent.input(screen.getByTestId('pump-input'), { target: { value } });
}

const confirm = () => screen.getByTestId('pump-confirm') as HTMLButtonElement;

afterEach(cleanup);

describe('PumpSettingRow', () => {
  it('needs the new value typed before it sends, with expect set to the current value', async () => {
    const onwrite = mount();
    await open('4');
    expect(confirm().disabled).toBe(true);
    await fireEvent.input(screen.getByTestId('pump-confirm-input'), { target: { value: '4' } });
    expect(confirm().disabled).toBe(false);
    await fireEvent.click(confirm());
    await waitFor(() => expect(onwrite).toHaveBeenCalledWith('heat_delta', 4, 5));
    await waitFor(() => expect(screen.getByTestId('command-progress')).toBeTruthy());
  });

  it('refuses out-of-range and non-integer values client-side', async () => {
    mount();
    await open('11');
    await fireEvent.input(screen.getByTestId('pump-confirm-input'), { target: { value: '11' } });
    expect(confirm().disabled).toBe(true);
    expect(screen.getAllByRole('alert')[0]?.textContent).toMatch(/between 3 and 10/);
    await fireEvent.input(screen.getByTestId('pump-input'), { target: { value: '4.5' } });
    expect(screen.getAllByRole('alert')[0]?.textContent).toMatch(/whole number/);
  });

  it('shows the 409 and 422 refusals and keeps the dialog open', async () => {
    const conflict = new ApiError('x', 409, { detail: { code: 'value_changed', message: '' } });
    const onwrite = vi
      .fn()
      .mockRejectedValueOnce(conflict)
      .mockRejectedValueOnce(new ApiError('x', 422));
    mount(onwrite);
    await open('4');
    await fireEvent.input(screen.getByTestId('pump-confirm-input'), { target: { value: '4' } });
    await fireEvent.click(confirm());
    expect((await screen.findByTestId('pump-error')).textContent).toMatch(
      /changed in the meantime/,
    );
    await fireEvent.click(confirm());
    await waitFor(() => expect(screen.getByTestId('pump-error').textContent).toMatch(/refused/));
    expect(screen.getByTestId('pump-dialog')).toBeTruthy();
  });

  it('tracks verification from the reported last write', async () => {
    const view = render(PumpSettingRow, {
      setting,
      writable: true,
      admin: true,
      onwrite: vi.fn().mockResolvedValue(undefined),
    });
    await open('4');
    await fireEvent.input(screen.getByTestId('pump-confirm-input'), { target: { value: '4' } });
    await fireEvent.click(confirm());
    await screen.findByTestId('command-progress');
    await view.rerender({
      setting: {
        ...setting,
        value: 4,
        last_write: { at: 'x', by: 'me', from: 5, to: 4, status: 'verified' },
      },
    });
    expect(screen.getByTestId('command-progress').dataset['status']).toBe('verified');
  });

  it('disables editing for a non-admin', () => {
    mount(undefined, { admin: false });
    expect((screen.getByTestId('pump-edit-heat_delta') as HTMLButtonElement).disabled).toBe(true);
  });

  const CODES: PumpRefusalCode[] = [
    'unknown_setting',
    'bad_comment',
    'not_an_integer',
    'out_of_range',
    'expect_required',
    'not_publishing',
    'hold',
    'defrost',
    'dhw',
    'state_unknown',
    'not_fresh',
    'value_changed',
    'unchanged',
    'in_flight',
    'rate_limited',
    'day_limit',
    'write_budget',
  ];

  it.each(CODES)('shows its own text for the refusal %s', async (code) => {
    const status = code === 'out_of_range' || code === 'not_an_integer' ? 422 : 409;
    const refusal = new ApiError('x', status, { detail: { code, message: 'raw', params: {} } });
    mount(vi.fn().mockRejectedValue(refusal));
    await open('4');
    await fireEvent.input(screen.getByTestId('pump-confirm-input'), { target: { value: '4' } });
    await fireEvent.click(confirm());
    const shown = (await screen.findByTestId('pump-error')).textContent ?? '';
    expect(shown).toContain(translateOptional('en', `pumpRefusal_${code}`) ?? '');
  });

  it('adds the wait time for rate and day limits', async () => {
    const limited = new ApiError('x', 429, {
      detail: { code: 'rate_limited', message: 'raw', params: { retry_after: 120 } },
    });
    mount(vi.fn().mockRejectedValue(limited));
    await open('4');
    await fireEvent.input(screen.getByTestId('pump-confirm-input'), { target: { value: '4' } });
    await fireEvent.click(confirm());
    expect((await screen.findByTestId('pump-error')).textContent).toMatch(/2 min/);
  });

  it('falls back to a status text for an unstructured refusal', async () => {
    mount(vi.fn().mockRejectedValue(new ApiError('x', 429)));
    await open('4');
    await fireEvent.input(screen.getByTestId('pump-confirm-input'), { target: { value: '4' } });
    await fireEvent.click(confirm());
    expect((await screen.findByTestId('pump-error')).textContent).toMatch(/Too many changes/);
  });

  it('handles a last write without a status', () => {
    mount(undefined, {
      setting: {
        ...setting,
        last_write: { at: '2026-11-14T10:00:00Z', by: 'me', from: 4, to: 5, status: null },
      },
    });
    expect(screen.getByTestId('pump-last-heat_delta').textContent).toMatch(/status unknown/);
  });

  it('shows a mapped label for enum values and no raw number', () => {
    mount(undefined, {
      setting: {
        ...setting,
        id: 'pump_flowrate_mode',
        value: 1,
        label: 'max_flow',
        unit: null,
        min: 0,
        max: 1,
      },
    });
    expect(screen.getByTestId('pump-value-pump_flowrate_mode').textContent).toBe('Maximum flow');
  });

  it('shows read-only rows without a change button, with the raw signal behind the why', () => {
    mount(undefined, {
      setting: {
        id: 'quiet_mode_priority',
        signal: 'main/Quiet_Mode_Priority',
        value: 0,
        unit: null,
        label: 'sound',
        fresh: true,
        age: 40,
        supported: true,
        access: 'read',
        owner: 'operator',
      },
    });
    expect(screen.queryByTestId('pump-edit-quiet_mode_priority')).toBeNull();
    expect(screen.getByTestId('pump-value-quiet_mode_priority').textContent).toBe('Sound');
  });
});
