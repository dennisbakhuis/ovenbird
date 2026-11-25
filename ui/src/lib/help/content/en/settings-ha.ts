import type { HelpTopic } from '$lib/help/types';

export const topic: HelpTopic = {
  id: 'settings/ha',
  title: 'Home Assistant',
  lead: 'Where ovenbird reads your room sensors: the address of Home Assistant and an access token. ovenbird only reads from Home Assistant; it never changes anything there.',
  art: 'settings',
  sections: [
    {
      id: 'connection',
      kind: 'do',
      title: 'Connect Home Assistant',
      body: 'Use the address you open Home Assistant with: directly on your network, such as `http://192.0.2.10:8123`, or your https address behind a reverse proxy. Plain http is fine on your own network.',
      steps: [
        'In Home Assistant, open your profile, then **Security**, and create a **Long-lived access token**.',
        'Enter the address and paste the token.',
        'Press **Test connection**. It checks that Home Assistant answers, that the token is accepted and that the sensors you use exist.',
        'Press **Save connection**. ovenbird connects right away; no restart is needed.',
      ],
      target: 'settings/ha.connection',
    },
    {
      id: 'token',
      kind: 'know',
      title: 'The token stays secret',
      body: 'The token is stored on the ovenbird server and never shown again: the page only says that one is stored. Exports, diagnostics and the audit log leave it out. To change it, paste a new one and save.',
    },
    {
      id: 'sensors',
      kind: 'know',
      title: 'Choosing sensors',
      body: 'Pick the room sensor in [Comfort temperature](#/settings/room) and the reference room in [Wood stove](#/settings/stove). ovenbird reads exactly the sensors you choose there. A thermostat can be the room sensor too: its measured room temperature is used.',
      target: 'settings/ha.sensors',
    },
    {
      id: 'units',
      kind: 'know',
      title: 'Units',
      body: 'Temperatures in °F or K are converted to °C when they arrive. A room sensor without a unit is only trusted when Home Assistant uses the metric system; otherwise ovenbird ignores its value, raises an alarm and runs on the heating curve.',
    },
    {
      id: 'locked',
      kind: 'know',
      title: 'Set by the installation',
      body: 'When the address or token comes from an environment variable or the options file, it is locked here and wins over a saved one. You can still test it.',
    },
  ],
  questions: [
    {
      id: 'fails',
      q: 'The test says Home Assistant cannot be reached. What now?',
      a: 'Open the same address in a browser on the ovenbird machine’s network. Check the port (usually 8123) and that you use https only when Home Assistant or your proxy offers it. A redirect counts as a failure: use the final address.',
    },
    {
      id: 'rejected',
      q: 'The token is rejected.',
      a: 'Create a new long-lived access token in your Home Assistant profile and paste it in full; tokens are long. An expired or deleted token is rejected too.',
    },
  ],
  related: ['settings', 'settings/room', 'system/signals'],
};
