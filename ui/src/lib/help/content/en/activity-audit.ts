import type { HelpTopic } from '$lib/help/types';

export const topic: HelpTopic = {
  id: 'activity/audit',
  title: 'Activity: audit',
  lead: 'The audit trail records who did what: settings applied or rolled back, pauses and resumes, released holds and pump settings written.',
  art: 'activity',
  sections: [
    {
      id: 'trail',
      kind: 'see',
      title: 'Audit trail',
      body: 'The chosen time range, newest first. Each row shows the time, who did it (user and address), the action and its details, such as the version with the changed values or the reason given.',
      target: 'activity/audit.trail',
    },
    {
      id: 'actions',
      kind: 'know',
      title: 'What is recorded',
      body: 'Settings applied, rolled back or reset, and a reset acknowledged; **Paused** and **Resumed (Auto)**; **Hold released**; **Pump setting written**; and **Request refused**, for example after a wrong password. Simply looking at pages is not recorded.',
    },
    {
      id: 'kept',
      kind: 'know',
      title: 'Rows are never changed',
      body: 'Rows are only ever added, never edited or deleted. Only an administrator can read the [[audit]] trail. Settings versions with their comments are on [Versions and backup](#/settings/versions).',
    },
  ],
  questions: [
    {
      id: 'refused',
      q: 'What does “Request refused” mean?',
      a: 'Someone or something called the service with a wrong password or without permission. Once is usually a typo; many in a row are worth a look.',
    },
    {
      id: 'how-far',
      q: 'How far back does it go?',
      a: 'As far as the time range above the timeline: the last 24 hours unless you pick **7 d** or **Custom**. It shows up to 200 events.',
    },
  ],
  related: ['settings/versions', 'activity'],
};
