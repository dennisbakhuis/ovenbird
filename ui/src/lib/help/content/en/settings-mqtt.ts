import type { HelpTopic } from '$lib/help/types';

export const topic: HelpTopic = {
  id: 'settings/mqtt',
  title: 'MQTT',
  lead: 'Where ovenbird reads the heat pump: the [[mqtt|MQTT]] broker [[heishamon|HeishaMon]] publishes to, and extra sensors that publish to MQTT.',
  art: 'settings',
  sections: [
    {
      id: 'connection',
      kind: 'do',
      title: 'Change the broker',
      body: 'The status line says whether ovenbird is connected, to which broker and base topic, and how many HeishaMon messages arrived since it connected.',
      steps: [
        'Enter the broker’s address and port, and a user name and password when the broker asks for them.',
        'Check the **HeishaMon base**: the topic base set in HeishaMon’s MQTT settings, usually `panasonic_heat_pump`.',
        'Press **Test connection**. ovenbird connects with a separate, read-only session and waits up to 30 seconds for a live HeishaMon value under that base (a retained value alone does not count: it may come from a board that is long gone). Nothing is sent.',
        'Press **Save connection**. It is only possible for exactly the values of the last successful test, within 10 minutes; change anything and you test again.',
      ],
      target: 'settings/mqtt.connection',
    },
    {
      id: 'revert',
      kind: 'know',
      title: 'Back to the old broker after 60 seconds',
      body: 'After saving, ovenbird switches at once and watches the new broker for 60 seconds. As soon as it is connected and live HeishaMon data arrives, the change stands. Without data in that time it goes back to the previous broker by itself and raises the warning **Broker change reverted**, so a typo never leaves the pump unread. A restart during those 60 seconds does not end the watch: it runs again after the start. Should going back fail, the card says so and the critical alarm **Broker change stuck** asks you to set a working broker. The card shows the outcome; the audit log records both steps.',
    },
    {
      id: 'password',
      kind: 'know',
      title: 'The password stays secret',
      body: 'The password is stored on the ovenbird server and never shown again: the card only says whether one is stored. Leave the field empty to keep it. A new broker or port, switching TLS off or another CA file without a password drops the stored one, so it is never sent to another broker. A password set by the deployment cannot follow such a change at all: change the broker in the deployment then.',
    },
    {
      id: 'locked',
      kind: 'know',
      title: 'Set by the deployment',
      body: 'A field that comes from an environment variable or the options file is locked here and shows its variable. Change it in the deployment and restart. You can still test the rest.',
    },
    {
      id: 'commands',
      kind: 'know',
      title: 'While commands are on',
      body: 'While ovenbird sends commands to the pump, the command link keeps the broker it started with. The broker can then be tested here but not changed: change it in the deployment and restart.',
    },
    {
      id: 'inputs',
      kind: 'do',
      title: 'Extra MQTT sensors',
      body: 'A thermometer that publishes to MQTT can be a sensor too: add its topic under **Extra MQTT sensors**. The signal name is optional (otherwise `mqtt/<topic>`); give the unit, such as °C, and optionally a range outside which values are ignored. These are ordinary settings: review and apply them like any other change. Afterwards they appear in the sensor lists, for example as the room sensor or as the outside sensor of the [heating curve](#/settings/curve).',
      target: 'settings/mqtt.inputs',
    },
  ],
  questions: [
    {
      id: 'no-heishamon',
      q: 'The test connects, but finds no HeishaMon data.',
      a: 'The broker works, but nothing arrives under that base topic. Compare the base with the MQTT topic base in HeishaMon’s settings, and check that HeishaMon publishes to this broker.',
    },
    {
      id: 'reverted',
      q: 'My change was reverted. What now?',
      a: 'The new broker brought no HeishaMon data within 60 seconds, so ovenbird is back on the previous one and keeps working. Test the new settings again; the warning clears with the next successful test or change.',
    },
  ],
  related: ['settings/ha', 'settings/curve', 'system/signals'],
};
