import type { HelpTopic } from '$lib/help/types';

export const topic: HelpTopic = {
  id: 'settings/quiet',
  title: 'Quiet mode',
  lead: 'Schedule when the outdoor unit runs in quiet mode, for example at night. Quieter also means less heating power while the window lasts.',
  art: 'settings',
  sections: [
    {
      id: 'windows',
      kind: 'do',
      title: 'Quiet mode windows',
      body: 'The bar shows the day from 0 to 24 hours with your windows in colour. Each window has a start, an end and a level from 1 to 3; a higher level is quieter. A window that ends before it starts runs past midnight, like 22:00 to 07:00.',
      steps: [
        '**Add window** adds a row, up to four.',
        '**From**, **Until** and **Level** set it.',
        'The cross removes a window.',
      ],
      target: 'settings/quiet.windows',
    },
    {
      id: 'timezone',
      kind: 'do',
      title: 'Time zone',
      body: 'The window times are read in this time zone. Pick yours from the list, for example Europe/Amsterdam, so 22:00 means 22:00 on your clock. Under the bar you see the time there now, such as "Now 18:27 in Europe/Amsterdam".\n\nWhen the zone differs from the one your browser uses, a warning says so, with a button **Use** and your browser’s zone to switch to it.',
      target: 'settings/quiet.timezone',
    },
    {
      id: 'cost',
      kind: 'know',
      title: 'What quiet mode costs',
      body: '[[quiet-mode]] limits the outdoor unit to lower its sound. On a cold night the pump may then deliver less heat than the curve asks for, and the house can cool a little. Choose the lowest level that is quiet enough.',
    },
    {
      id: 'who',
      kind: 'know',
      title: 'Who sets quiet mode',
      body: 'With at least one window, ovenbird sets quiet mode on the pump: the window’s level inside a window, off outside all windows. Changing it on the Panasonic remote then can count as a [[foreign-writer]] and start a hold.\n\nWithout windows, ovenbird never touches quiet mode.',
    },
  ],
  questions: [
    {
      id: 'loud',
      q: 'Why is the pump not quiet during a window?',
      a: 'Check the time zone first. Quiet mode lowers the sound but does not silence the unit; level 3 is the quietest. The **Quiet mode** signal on [Signals](#/system/signals) shows what the pump reports.',
    },
    {
      id: 'stop',
      q: 'How do I stop the schedule?',
      a: 'Remove all windows and apply. Do it outside a window, when ovenbird has switched quiet mode off: after that it no longer sets quiet mode at all.',
    },
  ],
  related: ['pump', 'settings/behaviour'],
};
