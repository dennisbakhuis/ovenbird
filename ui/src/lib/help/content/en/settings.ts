import type { HelpTopic } from '$lib/help/types';

export const topic: HelpTopic = {
  id: 'settings',
  title: 'Settings',
  lead: 'Everything ovenbird may change about your heating, in one place. Every change is checked and previewed before it applies, and every earlier version can be restored.',
  art: 'settings',
  sections: [
    {
      id: 'cards',
      kind: 'see',
      title: 'The overview cards',
      body: 'Each card shows the current value of one section: the [[heating-curve]] at three outside temperatures, your comfort temperature with the room now, pump duty, the limits, the quiet windows, wood-stove mode, the emitter, weather and the [[config-version|configuration version]].\n\nA coloured dot means the section has unsaved changes. Click a card to open it.',
      target: 'settings.cards',
    },
    {
      id: 'change',
      kind: 'do',
      title: 'Change a setting',
      body: 'Changes do not apply right away. They collect in a [[draft]] in this browser. A bar at the bottom shows how many there are and whether they pass the checks.',
      steps: [
        'Open a section: the list on the left, or the section picker at the top on a phone.',
        'Change a value. A dot marks it; the undo arrow puts it back.',
        '**Review and apply** in the bottom bar checks and saves your draft. **Discard** drops it.',
      ],
    },
    {
      id: 'preview',
      kind: 'know',
      title: 'What the review shows',
      body: 'Before anything is saved you get a [[preview]]: the decision of right now with the current settings and with yours, and a replay of the last 24 hours with yours.\n\nProblems block applying; warnings need a tick. The replay is open loop: it shows how the [[setpoint]] would have differed, not how warm the house would have been.',
    },
    {
      id: 'apply',
      kind: 'know',
      title: 'When a change takes effect',
      body: '**Apply** saves a new version. The controller picks it up between two decisions, within about a minute. What it has learned carries over, so the water temperature moves in its normal steps, never in a jump.\n\nChanged your mind? Roll back on [Versions and backup](#/settings/versions).',
    },
    {
      id: 'locked',
      kind: 'know',
      title: 'Locked settings',
      body: 'A lock means the value comes from the installation: an environment variable or the options file. You see it, but you cannot change it here. The Versions and backup card counts these settings; that section lists each one with its variable.',
      target: 'settings.locked',
    },
    {
      id: 'reset',
      kind: 'know',
      title: 'If the settings store is lost',
      body: 'When the stored settings are missing or damaged, ovenbird starts with the installation defaults in [[shadow]]: it decides but sends nothing. A yellow notice asks you to check the settings and click **Acknowledge**. Only then does it return to its normal mode.',
    },
  ],
  questions: [
    {
      id: 'safe',
      q: 'Is it safe to try a change?',
      a: 'Yes. Nothing reaches the pump until you apply. The review shows the effect first, the service enforces hard limits, and every version can be rolled back.',
    },
    {
      id: 'undo',
      q: 'How do I undo a change I already applied?',
      a: 'Open [Versions and backup](#/settings/versions) and click **Roll back to this version** on the version before it. That saves a new version with the old values.',
    },
    {
      id: 'default',
      q: 'How do I get a setting back to its default?',
      a: 'Click the **?** next to it. It shows the default or preset value and, when yours differs, a **Reset to default** or **Reset to preset** button. That changes your draft only.',
    },
    {
      id: 'busy',
      q: 'Why does it say “Too many changes in a short time”?',
      a: 'The service accepts one apply per minute and at most 30 a day. Wait a minute and try again.',
    },
  ],
  related: ['settings/curve', 'settings/room', 'settings/versions'],
};
