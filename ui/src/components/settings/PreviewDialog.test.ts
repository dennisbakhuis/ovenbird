// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from '@testing-library/svelte';
import { afterEach, describe, expect, it, vi } from 'vitest';
import schema from '$mock/fixtures/schema.json';
import type { ConfigSchema, PreviewResult } from '$lib/core/types';
import PreviewDialog from './PreviewDialog.svelte';

const sch = schema as unknown as ConfigSchema;
const diff = [{ field: 'control_comfort_c', from: 21.0, to: 21.2, reset: false }];
const ok: PreviewResult = { valid: true, errors: [], warnings: [], effective: {} };

function mount(result: PreviewResult | null, extra: Record<string, unknown> = {}) {
  const onapply = vi.fn();
  render(PreviewDialog, {
    diff,
    schema: sch,
    result,
    loading: false,
    error: null,
    admin: true,
    onapply,
    onclose: vi.fn(),
    ...extra,
  });
  return onapply;
}

const apply = () => screen.getByTestId('preview-apply') as HTMLButtonElement;

globalThis.ResizeObserver = class {
  observe() {}
  unobserve() {}
  disconnect() {}
};

afterEach(cleanup);

describe('PreviewDialog', () => {
  it('allows applying a clean preview with the comment', async () => {
    const onapply = mount(ok);
    expect(apply().disabled).toBe(false);
    await fireEvent.input(screen.getByTestId('preview-comment'), { target: { value: ' warmer ' } });
    await fireEvent.click(apply());
    expect(onapply).toHaveBeenCalledWith('warmer', []);
  });

  it('prefills the comment with the default comment', async () => {
    const onapply = mount(ok, { defaultComment: 'Suggested by the house model (house-1)' });
    const input = screen.getByTestId('preview-comment') as HTMLInputElement;
    expect(input.value).toBe('Suggested by the house model (house-1)');
    await fireEvent.click(apply());
    expect(onapply).toHaveBeenCalledWith('Suggested by the house model (house-1)', []);
  });

  it('disables apply while errors exist', () => {
    mount({
      valid: false,
      errors: [{ field: 'control_curve', code: 'outside_envelope', message: 'x', params: {} }],
      warnings: [],
      effective: {},
    });
    expect(apply().disabled).toBe(true);
    expect(screen.getByTestId('preview-errors')).toBeTruthy();
  });

  it('disables apply for a non-admin', () => {
    mount(ok, { admin: false });
    expect(apply().disabled).toBe(true);
    expect(screen.getByTestId('preview-blocked').textContent).toMatch(/administrator/);
  });

  it('requires every warning to be acknowledged', async () => {
    const onapply = mount({
      valid: true,
      errors: [],
      warnings: [{ field: 'control_curve', code: 'curve_shift_large', message: 'm', params: {} }],
      effective: {},
    });
    expect(apply().disabled).toBe(true);
    await fireEvent.click(screen.getByTestId('ack-curve_shift_large'));
    expect(apply().disabled).toBe(false);
    await fireEvent.click(apply());
    expect(onapply).toHaveBeenCalledWith('', ['curve_shift_large']);
  });

  it('says when the replay is not exact', async () => {
    const openLoop = {
      from: '2026-11-14T12:00:00Z',
      to: '2026-11-15T12:00:00Z',
      ticks: 10,
      skipped: 0,
      identity_ok: false,
      identity_ticks: 10,
      identity_mismatches: 2,
      identity_first_mismatch: '2026-01-01T00:00:00Z',
      limitations: [],
      open_loop: true,
      series: { at: [], recorded: [], candidate: [], candidate_pre_round: [] },
      summary: {
        mean_diff_k: 0,
        min_diff_k: 0,
        max_diff_k: 0,
        changes_recorded: 1,
        changes_candidate: 1,
        writes_per_day: 1,
        budget: 150,
        share_safety_clamped: 0,
        share_feedback_limited: 0,
        ladder: {},
        binding: {},
      },
    };
    mount({ ...ok, open_loop_run: openLoop });
    expect(screen.getByTestId('preview-comfort-caveat').textContent).toMatch(/indication only/);
    const details = screen.getByTestId('preview-details') as HTMLDetailsElement;
    details.open = true;
    await fireEvent(details, new Event('toggle'));
    expect(screen.getByTestId('preview-identity').textContent).toMatch(/indication only/);
  });

  it('sums up a comfort-only change in one sentence with the rest behind Details', () => {
    mount({ ...ok, now: undefined });
    expect(screen.getByTestId('preview-comfort').textContent).toContain(
      'Slightly warmer: comfort temperature 21.0 → 21.2 °C.',
    );
    expect(screen.getByTestId('preview-details')).toBeTruthy();
  });
});
