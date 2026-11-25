import type { HelpTopic } from '$lib/help/types';

export const topic: HelpTopic = {
  id: 'system/signals',
  title: 'System: signals',
  lead: 'Every live value ovenbird receives from the pump and Home Assistant, grouped by kind, with how fresh it is.',
  art: 'system',
  sections: [
    {
      id: 'toolbar',
      kind: 'do',
      title: 'Find a signal',
      body: 'Type in **Search signals** to filter on name, id, source or value. **Only held or stale** shows only the signals that are not fresh. The count on the right says how many are shown.',
      target: 'system/signals.toolbar',
    },
    {
      id: 'groups',
      kind: 'see',
      title: 'Groups and marks',
      body: 'Signals are grouped into Room, Temperatures, Pump, Power, Settings and Other. The mark in front shows the state:\n\n- a tick: fresh;\n- a pause sign: held, an on-change sensor that is alive but unchanged;\n- a warning sign: [[stale]], with the age of its last report.',
      target: 'system/signals.groups',
    },
    {
      id: 'details',
      kind: 'do',
      title: 'Look closer',
      body: 'Click a signal to see its id, its age, how long it has been unchanged, the maximum age before it counts as stale, what keeps it alive, and its source. From there you can show the last hour as a small chart.',
    },
    {
      id: 'source',
      kind: 'know',
      title: 'Where signals come from',
      body: 'Pump values come from [[heishamon|HeishaMon]] over [[mqtt|MQTT]]; room and other sensors from Home Assistant. Each [[signal]] has a maximum age; older values are not used for control.',
    },
  ],
  questions: [
    {
      id: 'held',
      q: 'Why is my room sensor marked as held?',
      a: 'It only reports when the temperature changes. Held means the device is still alive, because another signal from it arrived recently, so its value is trusted.',
    },
    {
      id: 'stale',
      q: 'A value is stale. Is that bad?',
      a: 'For a pump value it means HeishaMon or MQTT stopped delivering; check [System](#/system). For a sensor in Home Assistant, check its battery or connection.',
    },
  ],
  related: ['system', 'settings/room'],
};
