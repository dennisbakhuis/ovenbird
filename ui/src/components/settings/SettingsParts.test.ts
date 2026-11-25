// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from '@testing-library/svelte';
import { afterEach, describe, expect, it, vi } from 'vitest';
import config from '$mock/fixtures/config.json';
import schema from '$mock/fixtures/schema.json';
import MiniCurve from './MiniCurve.svelte';
import QuietBar from './QuietBar.svelte';
import type { ConfigDoc, ConfigSchema, RoomStatus } from '$lib/core/types';
import DiffTable from './DiffTable.svelte';
import PresetDiff from './PresetDiff.svelte';
import RoomStatusCard from './RoomStatusCard.svelte';
import SignalPicker from './SignalPicker.svelte';
import Stepper from '$ui/Stepper.svelte';

const doc = config as unknown as ConfigDoc;
const sch = schema as unknown as ConfigSchema;

globalThis.ResizeObserver = class {
  observe() {}
  unobserve() {}
  disconnect() {}
};

afterEach(cleanup);

describe('Stepper', () => {
  it('steps by the step, by the fine step with Shift, and accepts a comma', async () => {
    const onchange = vi.fn();
    render(Stepper, { value: 34, step: 1, fineStep: 0.5, label: 'Water', onchange, testid: 's' });
    await fireEvent.click(screen.getByTestId('s-inc'));
    expect(onchange).toHaveBeenLastCalledWith(35);
    await fireEvent.click(screen.getByTestId('s-dec'), { shiftKey: true });
    expect(onchange).toHaveBeenLastCalledWith(33.5);
    const input = screen.getByLabelText('Water') as HTMLInputElement;
    input.value = '31,5';
    await fireEvent.change(input);
    expect(onchange).toHaveBeenLastCalledWith(31.5);
    await fireEvent.keyDown(input, { key: 'ArrowUp' });
    expect(onchange).toHaveBeenLastCalledWith(35);
  });

  it('clamps to its range and disables the end buttons', async () => {
    const onchange = vi.fn();
    render(Stepper, {
      value: 40,
      step: 1,
      min: 20,
      max: 40,
      label: 'Water',
      onchange,
      testid: 's',
    });
    expect((screen.getByTestId('s-inc') as HTMLButtonElement).disabled).toBe(true);
    const input = screen.getByLabelText('Water') as HTMLInputElement;
    input.value = '55';
    await fireEvent.change(input);
    expect(onchange).toHaveBeenLastCalledWith(40);
  });
});

describe('DiffTable', () => {
  it('draws a curve change and writes numbers as from → to with the difference', () => {
    render(DiffTable, {
      schema: sch,
      entries: [
        {
          field: 'control_curve',
          from: [
            [-10, 39],
            [0, 34],
            [15, 25],
          ],
          to: [
            [-10, 39],
            [0, 36],
            [15, 25],
          ],
        },
        { field: 'control_comfort_c', from: 21.0, to: 21.6 },
        { field: 'control_dwell_s', from: 900, to: 1200, reset: true },
      ],
    });
    const curve = screen.getByTestId('diff-row-control_curve').querySelector('svg[role="img"]');
    expect(curve?.getAttribute('aria-label')).toMatch(/largest change \+2 K at 0 °C/);
    const comfort = screen.getByTestId('diff-row-control_comfort_c').textContent ?? '';
    expect(comfort).toContain('21 °C');
    expect(comfort).toContain('21.6 °C');
    expect(comfort).toContain('+0.6');
    expect(comfort).toContain('K');
    const dwell = screen.getByTestId('diff-row-control_dwell_s').textContent ?? '';
    expect(dwell).toContain('+5');
    expect(dwell).toContain('min');
    expect(dwell).toContain('back to preset');
  });

  it('draws quiet windows as two bars', () => {
    render(DiffTable, {
      schema: sch,
      entries: [
        {
          field: 'control_quiet_windows',
          from: [],
          to: [{ start: '22:00', end: '07:00', level: 2 }],
        },
      ],
    });
    const bars = screen.getAllByRole('img');
    expect(bars).toHaveLength(2);
    expect(bars[1]?.getAttribute('aria-label')).toContain('22:00–07:00');
  });
});

describe('PresetDiff', () => {
  it('lists only what changes when switching and keeps your own values', () => {
    render(PresetDiff, { schema: sch, config: doc, current: 'mixed', chosen: 'radiators' });
    expect(screen.getByTestId('preset-summary').textContent).toMatch(/Switching changes \d+/);
    expect(screen.getByTestId('diff-row-control_curve')).toBeTruthy();
    expect(screen.queryByTestId('diff-row-control_min_setpoint_c')).toBeNull();
    expect(screen.getByTestId('preset-kept')).toBeTruthy();
  });

  it('summarises the preset in use without a table', () => {
    render(PresetDiff, { schema: sch, config: doc, current: 'mixed', chosen: 'mixed' });
    expect(screen.getByTestId('preset-summary').textContent).toMatch(/follow this preset/);
    expect(screen.queryByTestId('diff-table')).toBeNull();
  });
});

describe('RoomStatusCard', () => {
  const room: RoomStatus = {
    signal: 'room_temperature',
    profile: 'on_change',
    step_k: 0.1,
    max_age_s: null,
    report_interval_s: null,
    silence_limit_s: 86400,
    liveness: ['room_humidity'],
    crosscheck: null,
    value: 21.4,
    fresh: true,
    held_s: 7200,
    alive_s: 240,
    alive_by: 'room_humidity',
    link_up: true,
    authority: 0.8,
    plausible: true,
  };

  it('shows the room sensor as compact chips with names', () => {
    render(RoomStatusCard, {
      room,
      nameOf: (s: string) => (s === 'room_humidity' ? 'Humidity' : s),
    });
    const text = screen.getByTestId('room-status').textContent ?? '';
    expect(text).toContain('Sensor fresh');
    expect(text).toContain('21.4');
    expect(text).toContain('Humidity');
    expect(text).toContain('80');
    expect(text).toContain('plausible');
  });

  it('says when no room sensor is configured', () => {
    render(RoomStatusCard, { room: null });
    expect(screen.getByTestId('room-status').textContent).toMatch(/No room sensor/);
  });
});

describe('SignalPicker', () => {
  it('names an MQTT signal by its label and keeps the id and topic as a caption', () => {
    render(SignalPicker, {
      id: 'pick',
      state: 'ok',
      value: 'room_temperature',
      candidates: [
        {
          signal: 'room_temperature',
          name: 'climate_manager_capture/room_temp',
          unit: '°C',
          value: 21.9,
          held_s: 60,
          source: 'mqtt',
        },
      ],
    });
    const select = screen.getByTestId('signal-select') as HTMLSelectElement;
    expect(select.selectedOptions[0]?.textContent).toMatch(/^Room temperature — 21.9/);
    expect(select.textContent).not.toContain('climate_manager_capture');
    expect(screen.getByTestId('signal-id').textContent).toBe(
      'signal id room_temperature · climate_manager_capture/room_temp',
    );
    expect(screen.getByTestId('signal-live').querySelector('code')).toBeNull();
  });
});

describe('MiniCurve and QuietBar', () => {
  it('describes a single curve', () => {
    render(MiniCurve, {
      curve: [
        [-10, 39],
        [15, 25],
      ],
    });
    expect(screen.getByRole('img').getAttribute('aria-label')).toBe(
      'Heating curve 39 / 25 °C at −10 / 15 °C outside',
    );
  });

  it('describes quiet windows and draws one segment per part of the day', () => {
    const { container } = render(QuietBar, {
      windows: [{ start: '22:00', end: '07:00', level: 2 }],
    });
    expect(screen.getByRole('img').getAttribute('aria-label')).toContain('22:00–07:00 level 2');
    expect(container.querySelectorAll('.seg')).toHaveLength(2);
  });
});
