// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from '@testing-library/svelte';
import { afterEach, describe, expect, it } from 'vitest';
import config from '$mock/fixtures/config.json';
import schema from '$mock/fixtures/schema.json';
import { DraftStore } from '$lib/core/draft.svelte';
import type { ConfigDoc, ConfigSchema } from '$lib/core/types';
import Field from './Field.svelte';

const doc = config as unknown as ConfigDoc;
const sch = schema as unknown as ConfigSchema;
const store = () =>
  new DraftStore({ getItem: () => null, setItem: () => {}, removeItem: () => {} });

afterEach(cleanup);

describe('Field', () => {
  it('shows a locked field read-only and names its variable', () => {
    const locked: ConfigDoc = {
      ...doc,
      fields: {
        ...doc.fields,
        control_min_setpoint_c: {
          value: 25,
          source: 'env',
          locked: true,
          stored: null,
          default: 20,
        },
      },
    };
    render(Field, { id: 'control_min_setpoint_c', schema: sch, config: locked, draft: store() });
    const input = screen.getByLabelText('Minimum water setpoint') as HTMLInputElement;
    expect(input.disabled).toBe(true);
    expect(screen.getByTestId('locked-note').textContent).toContain(
      'OVENBIRD_CONTROL_MIN_SETPOINT_C',
    );
  });

  it('edits a number into the draft and offers reset to the default', async () => {
    const draft = store();
    render(Field, { id: 'control_comfort_c', schema: sch, config: doc, draft });
    const input = screen.getByLabelText('Comfort target') as HTMLInputElement;
    await fireEvent.input(input, { target: { value: '22.5' } });
    expect(draft.changes['control_comfort_c']).toBe(22.5);
    expect(screen.getByTestId('changed-chip')).toBeTruthy();
    await fireEvent.click(screen.getByTestId('why-control_comfort_c-button'));
    await fireEvent.click(screen.getByTestId('reset-control_comfort_c'));
    expect(draft.changes['control_comfort_c']).toBeNull();
  });

  it('accepts a decimal comma and undoes a change', async () => {
    const draft = store();
    render(Field, { id: 'control_comfort_c', schema: sch, config: doc, draft });
    await fireEvent.input(screen.getByLabelText('Comfort target'), { target: { value: '22,4' } });
    expect(draft.changes['control_comfort_c']).toBe(22.4);
    await fireEvent.click(screen.getByTestId('undo-control_comfort_c'));
    expect(draft.has('control_comfort_c')).toBe(false);
  });

  it('resets a preset-derived advanced value and shows the preset', async () => {
    const draft = store();
    draft.set('control_dwell_s', 1500, doc);
    render(Field, { id: 'control_dwell_s', schema: sch, config: doc, draft });
    expect((screen.getByLabelText('Wait time between changes') as HTMLInputElement).value).toBe(
      '25',
    );
    expect(screen.queryByText(/Preset: 15 min/)).toBeNull();
    await fireEvent.click(screen.getByTestId('why-control_dwell_s-button'));
    expect(screen.getByText(/Preset: 15 min/)).toBeTruthy();
    await fireEvent.click(screen.getByTestId('reset-control_dwell_s'));
    expect(draft.has('control_dwell_s')).toBe(false);
  });

  it('shows a soft warning without blocking and a hard error', async () => {
    const draft = store();
    render(Field, { id: 'control_comfort_c', schema: sch, config: doc, draft });
    const input = screen.getByLabelText('Comfort target');
    await fireEvent.input(input, { target: { value: '26' } });
    expect(screen.getByTestId('soft-warning').textContent).toMatch(/usual range/);
    await fireEvent.input(input, { target: { value: '40' } });
    expect(screen.getByRole('alert').textContent).toMatch(/at most 30/);
  });

  it('shows server-side issues', () => {
    render(Field, {
      id: 'control_comfort_c',
      schema: sch,
      config: doc,
      draft: store(),
      errors: [
        { field: 'control_comfort_c', code: 'whatever', message: 'server says no', params: {} },
      ],
    });
    expect(screen.getByRole('alert').textContent).toContain('server says no');
  });

  it('edits a retention in days and keeps it forever with 0', async () => {
    const draft = store();
    render(Field, { id: 'history_raw_days', schema: sch, config: doc, draft });
    const days = screen.getByLabelText('Keep raw history') as HTMLInputElement;
    expect(days.value).toBe('14');
    await fireEvent.input(days, { target: { value: '30' } });
    expect(draft.changes['history_raw_days']).toBe(30);
    const forever = screen.getByTestId('forever-history_raw_days') as HTMLInputElement;
    expect(forever.checked).toBe(false);
    await fireEvent.click(forever);
    expect(draft.changes['history_raw_days']).toBe(0);
    expect(screen.queryByRole('textbox')).toBeNull();
    expect(screen.queryByTestId('soft-warning')).toBeNull();
    await fireEvent.click(screen.getByTestId('forever-history_raw_days'));
    expect(draft.has('history_raw_days')).toBe(false);
  });

  it('shows a retention kept forever by default and leaves it with the soft minimum', async () => {
    const draft = store();
    render(Field, { id: 'history_1h_days', schema: sch, config: doc, draft });
    const forever = screen.getByTestId('forever-history_1h_days') as HTMLInputElement;
    expect(forever.checked).toBe(true);
    await fireEvent.click(forever);
    expect(draft.changes['history_1h_days']).toBe(365);
  });

  it('warns below the soft minimum of a retention', async () => {
    const draft = store();
    render(Field, { id: 'history_1m_days', schema: sch, config: doc, draft });
    await fireEvent.input(screen.getByLabelText('Keep 1-minute history'), {
      target: { value: '3' },
    });
    expect(screen.getByTestId('soft-warning')).toBeTruthy();
  });
});
