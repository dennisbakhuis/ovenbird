const r2 = (value: number) => Math.round(value * 100) / 100;

function circle(cx: number, cy: number, r: number): string {
  return `M${cx} ${cy - r}a${r} ${r} 0 1 0 0 ${2 * r}a${r} ${r} 0 1 0 0 ${-2 * r}z`;
}

function polar(cx: number, cy: number, r: number, degrees: number): string {
  const a = (degrees * Math.PI) / 180;
  return `${r2(cx + r * Math.cos(a))} ${r2(cy + r * Math.sin(a))}`;
}

function polygon(points: string[]): string {
  return `M${points.join('L')}z`;
}

function gear(): string {
  const points: string[] = [];
  for (let i = 0; i < 8; i += 1) {
    const c = i * 45;
    points.push(
      polar(12, 12, 6.6, c - 22.5),
      polar(12, 12, 6.6, c - 13),
      polar(12, 12, 9, c - 8),
      polar(12, 12, 9, c + 8),
      polar(12, 12, 6.6, c + 13),
    );
  }
  return polygon(points) + circle(12, 12, 2.75);
}

function rays(r1: number, r2: number, count: number, offset = 0): string {
  let d = '';
  for (let i = 0; i < count; i += 1) {
    const a = offset + (i * 360) / count;
    d += `M${polar(12, 12, r1, a)}L${polar(12, 12, r2, a)}`;
  }
  return d;
}

function snowflake(): string {
  let d = '';
  for (let i = 0; i < 6; i += 1) {
    const a = i * 60 - 90;
    d += `M12 12L${polar(12, 12, 9, a)}`;
    const tip = (r: number, da: number) => polar(12, 12, r, a + da);
    d += `M${tip(7.6, -14)}L${polar(12, 12, 6.2, a)}L${tip(7.6, 14)}`;
  }
  return d;
}

function fan(): string {
  let d = circle(12, 12, 9.25) + circle(12, 12, 1.25);
  for (let i = 0; i < 3; i += 1) {
    const a = i * 120 - 90;
    d += `M${polar(12, 12, 1.6, a)}Q${polar(12, 12, 7.5, a - 28)} ${polar(12, 12, 7, a + 14)}Q${polar(12, 12, 4, a + 30)} ${polar(12, 12, 1.6, a + 40)}`;
  }
  return d;
}

function octagon(r: number): string {
  const points: string[] = [];
  for (let i = 0; i < 8; i += 1) points.push(polar(12, 12, r, i * 45 + 22.5));
  return polygon(points);
}

/**
 * Stroke paths on a 24 px grid, drawn with `currentColor` at 1.5 px.
 */
export const ICONS = {
  home: 'M3.5 11 12 4l8.5 7M5.5 9.5V20h13V9.5M10 20v-5.5h4V20',
  house:
    'M2.5 12 12 3.5l9.5 8.5M16 7.2V4.5h2.5v5.3M5.5 10.5v10h13v-10M9 13.5h2.5V16H9zM14 20.5V16.5h2.5v4',
  target: circle(12, 12, 8.5) + circle(12, 12, 4.5) + 'M12 2.5v3M12 18.5v3M2.5 12h3M18.5 12h3',
  weather:
    'M8.5 3v1.5M3.5 8.5H5M5 5l1 1M12 5l-1 1' +
    'M5.4 11.3A3.5 3.5 0 1 1 11.9 7' +
    'M8 20a3.5 3.5 0 0 1-.3-7 5 5 0 0 1 9.4-1.3A4.2 4.2 0 0 1 17.3 20z',
  settings:
    'M4 6.5h8.5M16.5 6.5H20M4 12h2.5M10.5 12H20M4 17.5h10.5M18.5 17.5H20' +
    circle(14.5, 6.5, 2) +
    circle(8.5, 12, 2) +
    circle(16.5, 17.5, 2),
  pump:
    'M3.5 5.5h17v12h-17zM6 17.5V20M18 17.5V20M16.5 9h1.5M16.5 11.5h1.5M16.5 14h1.5' +
    circle(9.5, 11.5, 3.75) +
    'M9.5 7.75v7.5M5.75 11.5h7.5',
  bell: 'M6 16.5V11a6 6 0 0 1 12 0v5.5l1.5 2h-15zM10 20.5a2 2 0 0 0 4 0',
  cpu: 'M7 7h10v10H7zM10 10h4v4h-4zM10 4v3M14 4v3M10 17v3M14 17v3M4 10h3M4 14h3M17 10h3M17 14h3',
  more: '',
  gear: gear(),
  fan: fan(),
  snowflake: snowflake(),
  tap: 'M3.5 8.5v5M3.5 11h8.5a3 3 0 0 1 3 3v1M9 11V7.5M6.5 7.5h5M15 17.5c-.9 1.1-1.4 1.9-1.4 2.5a1.4 1.4 0 0 0 2.8 0c0-.6-.5-1.4-1.4-2.5z',
  moon: 'M19.5 14.5A8 8 0 0 1 9.5 4.5a8 8 0 1 0 10 10z',
  ramp: 'M3.5 19.5h4.5l8-12.5h4.5M17.5 4.5 20.5 7l-3 2.5',
  pause: 'M9 5.5v13M15 5.5v13',
  play: 'M8 5.5v13l10-6.5z',
  lock: 'M6 11h12v9H6zM8.5 11V8a3.5 3.5 0 0 1 7 0v3M12 14.5v2',
  info: circle(12, 12, 9) + 'M12 11v5.5',
  warning: 'M12 4 21 19.5H3zM12 9.5v4.25',
  critical: octagon(9.5) + 'M12 7.75v5.25',
  check: circle(12, 12, 9) + 'M8 12.5l2.75 2.75L16 9.5',
  why: circle(12, 12, 9) + 'M9.75 9.5a2.25 2.25 0 1 1 3.15 2.06c-.55.27-.9.82-.9 1.44v.5',
  edit: 'M15 5l4 4L9 19H5v-4zM13 7l4 4',
  undo: 'M9 14 4.5 9.5 9 5M5 9.5h9a5 5 0 0 1 0 10h-3',
  download: 'M12 4v11M7.5 10.5 12 15l4.5-4.5M5 19.5h14',
  upload: 'M12 15V4M7.5 8.5 12 4l4.5 4.5M5 19.5h14',
  external: 'M14 4.5h5.5V10M19.5 4.5l-8 8M17 14v5.5H4.5V7H10',
  chevronDown: 'M6 9.5l6 6 6-6',
  chevronRight: 'M9.5 6l6 6-6 6',
  arrowRight: 'M4.5 12h15M14 6.5l5.5 5.5-5.5 5.5',
  close: 'M6 6l12 12M18 6 6 18',
  bolt: 'M13 3 5.5 13.5H12l-1 7.5 7.5-10.5H12z',
  flame:
    'M12 21a6 6 0 0 0 6-6c0-3.6-2.5-5.6-3.6-8.6-.6 2-1.7 3.1-2.9 3.4C11.7 7.4 10.5 5 8.6 3.5 8.7 7.6 6 10.2 6 15a6 6 0 0 0 6 6z',
  thermometer: 'M10 13.6V5a2 2 0 0 1 4 0v8.6a4 4 0 1 1-4 0zM12 9.5v6.5',
  droplet: 'M12 3.5s-6 6.6-6 10.5a6 6 0 0 0 12 0c0-3.9-6-10.5-6-10.5z',
  clock: circle(12, 12, 9) + 'M12 7.5V12l3 2',
  hand: 'M8.5 12.5V6a1.5 1.5 0 0 1 3 0v5M11.5 11V4.5a1.5 1.5 0 0 1 3 0V11M14.5 11V6.5a1.5 1.5 0 0 1 3 0V14a7 7 0 0 1-7 7h-.5a6 6 0 0 1-4.9-2.6l-2.3-3.4a1.5 1.5 0 0 1 2.5-1.7l1.7 2.2',
  power: 'M12 3.5v8M7.2 6.5a7.5 7.5 0 1 0 9.6 0',
  eye:
    'M2.5 12s3.5-6.5 9.5-6.5S21.5 12 21.5 12s-3.5 6.5-9.5 6.5S2.5 12 2.5 12z' + circle(12, 12, 3),
  sun: circle(12, 12, 4) + rays(6.5, 9, 8),
  cloud: 'M7 19a4.2 4.2 0 0 1-.6-8.35 5.6 5.6 0 0 1 10.8-1.3A4.8 4.8 0 0 1 17 19z',
  wind: 'M3.5 9h11a2.5 2.5 0 1 0-2.5-2.5M3.5 15h14a2.5 2.5 0 1 1-2.5 2.5M3.5 12h7',
  chart: 'M4 4.5V20h16M7.5 15l3.5-4.5 3 2.5 5-6.5',
  globe:
    circle(12, 12, 9) +
    'M3 12h18M12 3c2.4 2.6 3.6 5.6 3.6 9s-1.2 6.4-3.6 9c-2.4-2.6-3.6-5.6-3.6-9S9.6 5.6 12 3z',
  contrast: circle(12, 12, 9),
  plus: 'M12 5v14M5 12h14',
  minus: 'M5 12h14',
  trendUp: 'M4 16.5l6-6 4 4 6-6.5M15 8h5v5',
  trendDown: 'M4 7.5l6 6 4-4 6 6.5M15 16h5v-5',
  trendFlat: 'M4 12h15.5M15 7.5l4.5 4.5-4.5 4.5',
  link: 'M10 14a4 4 0 0 0 5.7 0l3-3a4 4 0 0 0-5.7-5.7l-1 1M14 10a4 4 0 0 0-5.7 0l-3 3a4 4 0 0 0 5.7 5.7l1-1',
} as const;

export type IconName = keyof typeof ICONS;

/**
 * Filled shapes drawn under the stroke for glyphs that need solid parts.
 */
export const FILLS: Partial<Record<IconName, string>> = {
  more: circle(5, 12, 1.6) + circle(12, 12, 1.6) + circle(19, 12, 1.6),
  contrast: 'M12 3a9 9 0 0 1 0 18z',
  info: circle(12, 7.75, 1.1),
  warning: circle(12, 16.75, 1.1),
  critical: circle(12, 15.75, 1.1),
  why: circle(12, 16.5, 1.1),
};

export const ICON_NAMES = Object.keys(ICONS) as IconName[];
