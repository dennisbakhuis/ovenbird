import type { HelpTopic } from '$lib/help/types';

export const topic: HelpTopic = {
  id: 'more',
  title: 'More',
  lead: 'The pages that do not fit in the bottom bar: settings, activity, system and signals, each with a one-line status.',
  art: 'welcome',
  sections: [
    {
      id: 'links',
      kind: 'see',
      title: 'The pages',
      body: '- **Settings**: the configuration version and any unsaved changes.\n- **Activity**: alarms and a hold, with a badge that counts the alarms.\n- **System**: the control mode and whether HeishaMon is online.\n- **Signals**: how many live values arrive.',
      target: 'more.links',
    },
    {
      id: 'badge',
      kind: 'know',
      title: 'The badge colour',
      body: 'The badge takes the colour of the most serious alarm: red for critical, amber for a warning, blue for information only. No badge: no alarms.',
    },
    {
      id: 'help',
      kind: 'know',
      title: 'Help on every page',
      body: 'The **?** at the top opens help for the page you are on; on a keyboard, press **?**. **Show me** points at the part of the page a section is about.',
    },
  ],
  questions: [
    {
      id: 'desktop',
      q: 'Where are these pages on a computer?',
      a: 'On a wide screen Settings sits in the top bar, and Activity and System are the icons at the top right. Signals is a tab of System.',
    },
    {
      id: 'badge-stays',
      q: 'How do I make the badge go away?',
      a: 'Alarms clear by themselves when their cause is gone. [Activity](#/activity) shows what is still on and why.',
    },
  ],
  related: ['activity', 'system', 'settings'],
};
