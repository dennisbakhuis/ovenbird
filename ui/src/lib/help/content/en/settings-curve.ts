import type { HelpTopic } from '$lib/help/types';

export const topic: HelpTopic = {
  id: 'settings/curve',
  title: 'Heating curve',
  lead: 'The heating curve gives the water temperature for each outside temperature. It is the backbone of every decision; room correction only nudges it.',
  art: 'settings',
  sections: [
    {
      id: 'readout',
      kind: 'see',
      title: 'Today on the curve',
      body: 'The line above the chart reads today’s point: at the current, smoothed outside temperature the active curve gives this water temperature, and ovenbird sent that [[setpoint]] ("would send" while it does not send). They differ when room correction, the start ramp or a limit is at work.\n\nWhile you drag a point, the line shows that point instead.',
      target: 'settings/curve.readout',
    },
    {
      id: 'chart',
      kind: 'see',
      title: 'Reading the chart',
      body: '- The dark line is the active curve; your draft is drawn over it.\n- The green band is the safety [[envelope]]. The curve must stay inside it.\n- The red dashed lines are the minimum setpoint and the maximum supply temperature.\n- The orange diamond is today; the grey bars are the setpoints of the last 7 days.\n- The blue bar under the axis is the [[forecast]] for the next 48 hours, when weather is on.',
      target: 'settings/curve.chart',
    },
    {
      id: 'edit',
      kind: 'do',
      title: 'Change the curve',
      body: 'The curve has 2 to 6 points with straight lines between them. Beyond the first and last point it stays flat.',
      steps: [
        'Drag a point in the chart, or focus it and use the arrow keys: up and down move it 1 K, with Shift 0.5 K.',
        '**Points as numbers**: use − and + for exact values.',
        '**Add point** adds one; the cross removes one.',
      ],
      target: 'settings/curve.points',
    },
    {
      id: 'rules',
      kind: 'know',
      title: 'What the checks allow',
      body: 'Outside temperatures must increase from left to right, and the water may not get warmer when it gets warmer outside. Every point must lie between the minimum setpoint and the maximum supply temperature, and inside the green band.\n\nMoving the curve more than 3 K anywhere between −15 and 20 °C is allowed, but you confirm it in the review.',
    },
    {
      id: 'filter',
      kind: 'know',
      title: 'Outside temperature filter',
      body: 'Under **Advanced: outside temperature filter** sits the smoothing of the outside temperature. The pump reports whole degrees, so the raw value jumps; the filter evens that out. A longer time reacts more slowly to the weather.\n\nThe emitter preset sets it (4 hours for Mixed). Below 30 minutes is not recommended.',
      target: 'settings/curve.filter',
    },
    {
      id: 'outside',
      kind: 'know',
      title: 'Your own outside sensor',
      body: 'The pump measures the outside temperature at its outdoor unit, where sun, wind and defrosting can skew it. Under **Outside sensor for the curve** you can pick another thermometer instead: a Home Assistant sensor or an [extra MQTT sensor](#/settings/mqtt), in °C.\n\n- **Uses it:** only the heating curve (the smoothed outside temperature, and with it the water temperature and the plan).\n- **Keeps the pump sensor:** the safety [[envelope]], the safety monitors, the measured line on [Weather](#/weather) and the trial summaries.\n- **When it goes quiet:** older than **Outside sensor counts as fresh for** (30 minutes by default), and the curve uses the pump sensor again until the chosen one reports. The warning **Outside sensor not fresh** says so, and a chip appears here.',
      target: 'settings/curve.outside',
    },
    {
      id: 'tips',
      kind: 'know',
      title: 'Small steps work best',
      body: 'Too cold or too warm in all weather? Change the comfort target in [Comfort temperature](#/settings/room) first; with a room sensor, ovenbird then adjusts the water for you.\n\nChange the curve when the problem depends on the weather, for example only when it freezes. Move one point by about 1 K and give the house a day to respond.',
    },
  ],
  questions: [
    {
      id: 'differs',
      q: 'Why is the sent setpoint not what the curve says?',
      a: 'The curve is the starting point. Room correction, the start ramp, cycling protection and the safety limits add to it, and the setpoint changes in whole degrees. [Setpoint](#/setpoint) shows every part.',
    },
    {
      id: 'harm',
      q: 'Can a wrong curve harm my floor?',
      a: 'The service refuses a curve outside the green band or above the maximum supply temperature. With floor heating in screed that maximum is 40 °C.',
    },
    {
      id: 'preset',
      q: 'How do I go back to the preset curve?',
      a: 'When your curve differs from the preset, a **?** appears above the chart with **Reset to preset**. It changes your draft; review and apply as usual.',
    },
  ],
  related: ['settings/room', 'settings/emitter', 'setpoint'],
};
