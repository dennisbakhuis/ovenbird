import type { HelpTopic } from '$lib/help/types';

export const topic: HelpTopic = {
  id: 'settings/behaviour',
  title: 'Behaviour',
  lead: 'How far and how often ovenbird may move the water temperature, and how it treats the compressor at start-up and against short runs.',
  art: 'settings',
  sections: [
    {
      id: 'limits',
      kind: 'do',
      title: 'Setpoint limits',
      body: '**Minimum water setpoint** and **Maximum supply temperature** are the floor and ceiling of every [[setpoint]] ovenbird sends. You can only lower the maximum here; raising it above the emitter’s default needs the installation. A lock means the value comes from the installation.',
      target: 'settings/behaviour.limits',
    },
    {
      id: 'deadband',
      kind: 'know',
      title: 'Dead band and wait time',
      body: 'The [[dead-band]] is how far the calculated temperature must drift before the setpoint changes, at least 1 K. **Wait time between changes** is the least time between two changes ([[dwell]]).\n\nLarger values mean fewer, calmer changes and fewer writes to the pump; smaller ones follow more closely. A wait below 10 minutes is not recommended.',
      target: 'settings/behaviour.deadband',
    },
    {
      id: 'ramp',
      kind: 'know',
      title: 'Start ramp',
      body: 'With the [[start-ramp]] on, ovenbird holds the setpoint below the curve right after the compressor starts and then releases it slowly: a soft start that suits floor heating. Hold time, depth and release speed shape it; the depth never reaches below the safety band.\n\nThe floor and mixed presets switch it on; Radiators switches it off.',
      target: 'settings/behaviour.ramp',
    },
    {
      id: 'cycling',
      kind: 'know',
      title: 'Cycling protection',
      body: 'Keeps the setpoint high enough early in a run so the pump does not stop and restart soon after ([[short-cycling]]). **Cycling protection window** is the minimum run it tries to secure, 30 minutes for floor heating.\n\nSwitching it off raises a warning you must confirm.',
      target: 'settings/behaviour.cycling',
    },
    {
      id: 'safe',
      kind: 'know',
      title: 'Before you change these',
      body: 'The emitter preset sets all of these, and they suit most houses. The **?** of each field shows the preset value and a **Reset to preset** button. The review shows how many setpoint changes a day your version would make, against the daily write budget.',
    },
  ],
  questions: [
    {
      id: 'exact',
      q: 'Why does ovenbird not follow the curve exactly?',
      a: 'Every change is a write to the pump. The dead band and the wait time keep that to a sensible number a day, and the setpoint changes in whole degrees.',
    },
    {
      id: 'budget',
      q: 'What is the daily write budget?',
      a: 'A cap on commands to the pump per day, 150 by default with 10 kept for safety. [Commands](#/activity/commands) shows how much is used today.',
    },
  ],
  related: ['settings/curve', 'activity/commands', 'setpoint'],
};
