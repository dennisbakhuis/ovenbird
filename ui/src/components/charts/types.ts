import type { Point, StateSegment } from '$lib/core/chart';

export interface LineSpec {
  id: string;
  label: string;
  color: string;
  points: Point[];
  dash?: string;
  step?: boolean;
  axis?: 'left' | 'right';
  width?: number;
  unit?: string;
  digits?: number;
  hideInLegend?: boolean;
  maxGapMs?: number;
}

export interface BandSpec {
  id: string;
  label: string;
  color: string;
  upper: Point[] | number;
  lower: Point[] | number;
  opacity?: number;
  axis?: 'left' | 'right';
  hideInLegend?: boolean;
}

export interface MarkerSpec {
  t: number;
  label: string;
  color?: string;
  icon?: string;
}

export interface SpanSpec {
  from: number;
  to: number;
  label?: string;
  color?: string;
  opacity?: number;
}

export interface RuleSpec {
  value: number;
  label?: string;
  color?: string;
  dash?: string;
}

export interface LaneState {
  label: string;
  color?: string;
}

export interface LaneEvent {
  at: number;
  text: string;
}

export interface LaneSpec {
  id: string;
  label: string;
  color: string;
  segments: StateSegment[];
  icon?: string;
  states?: Record<string, LaneState>;
  events?: LaneEvent[];
}

export interface PanelSpec {
  id: string;
  label?: string;
  unit?: string;
  rightUnit?: string;
  lines?: LineSpec[];
  bands?: BandSpec[];
  rules?: RuleSpec[];
  lanes?: LaneSpec[];
  height?: number;
  min?: number;
  max?: number;
  zero?: boolean;
  snap?: number;
  digits?: number;
}

export interface BarItem {
  label: string;
  value: number | null;
  color?: string;
  note?: string;
}
