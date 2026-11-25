import type { HelpTopic } from '$lib/help/types';

export const topic: HelpTopic = {
  id: 'activity/holds',
  title: 'Activity: holds',
  lead: 'A hold means ovenbird sends no commands to the pump for a while, usually because something else changed a pump setting. It keeps deciding meanwhile.',
  art: 'activity',
  sections: [
    {
      id: 'why',
      kind: 'know',
      title: 'Why holds happen',
      body: 'ovenbird checks that the pump keeps the values it sent. When a value changes without ovenbird, a [[foreign-writer]] is at work: the Panasonic remote, Node-RED or another app. Rather than fight over the pump, ovenbird holds.\n\nA command the pump does not confirm after several tries also starts a [[hold]].',
    },
    {
      id: 'current',
      kind: 'see',
      title: 'Command hold',
      body: 'The hold now in plain words, such as **Someone else changed the pump**; when ovenbird sends again and how much time is left; and how many holds there were recently, such as "2 holds in the last 12 h". **No hold** means ovenbird may send commands.',
      target: 'activity/holds.current',
    },
    {
      id: 'escalation',
      kind: 'know',
      title: 'Holds get longer',
      body: 'Within 12 hours the first hold lasts 1 hour and the second 4 hours; the third is **latched** and lasts until an administrator releases it. These are the installation defaults. They stop ovenbird and another controller from taking turns all day.',
    },
    {
      id: 'release',
      kind: 'do',
      title: 'Release a hold',
      body: 'Found the cause, for example a setting changed on the remote? Release the hold so ovenbird takes over again. Only an administrator can.',
      steps: [
        '**Release hold** opens the form.',
        '**Reason (optional)**: note what you checked.',
        '**Release now**: ovenbird sends its values again and the count starts over.',
      ],
    },
    {
      id: 'history',
      kind: 'see',
      title: 'Hold history',
      body: 'Every hold in the chosen time range, numbered within the escalation window, with how long it lasted and how it ended: **expired**, **released** or still **active**. **Why?** shows the service’s message.',
      target: 'activity/holds.history',
    },
  ],
  questions: [
    {
      id: 'heating',
      q: 'Is the heating off during a hold?',
      a: 'No. The pump keeps heating on the values it has. ovenbird keeps deciding, so [Setpoint](#/setpoint) shows what it would send.',
    },
    {
      id: 'remote',
      q: 'I changed the temperature on the remote myself. Is that wrong?',
      a: 'It works, but ovenbird sees it as a foreign writer and holds. To change the temperature, use the comfort target in [Comfort temperature](#/settings/room) instead.',
    },
    {
      id: 'cannot',
      q: 'Why can I not release the hold?',
      a: 'Only an administrator can. A hold because of a critical alarm cannot be released here; it ends when the alarm clears.',
    },
  ],
  related: ['activity', 'activity/commands'],
};
