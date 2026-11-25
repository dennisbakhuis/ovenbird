import type { HelpTopic } from '$lib/help/types';

export const topic: HelpTopic = {
  id: 'activity/commands',
  title: 'Activity: commands',
  lead: 'Every command ovenbird sent to the pump in the chosen time range, or decided not to send, and how much of today’s write budget is used.',
  art: 'activity',
  sections: [
    {
      id: 'budget',
      kind: 'see',
      title: 'Command budget today',
      body: 'Every write to the pump counts. The bar shows how many of today’s writes are used; the last part is kept in reserve for safety corrections. The chips under **Since the service started** count what happened to commands since the service last started: sent, verified, foreign writes and so on. **Failed** and **Retried** are always shown, also at 0. The budget starts again at midnight UTC.',
      target: 'activity/commands.budget',
    },
    {
      id: 'journal',
      kind: 'see',
      title: 'Command journal',
      body: 'One row per command: the time, what it set (water setpoint, max pump duty or quiet mode) with the value, its status and a short explanation. Click a row to see each step, with every attempt. **Show more** shows older rows.',
      target: 'activity/commands.journal',
    },
    {
      id: 'status',
      kind: 'know',
      title: 'What the statuses mean',
      body: '- **verified**: the pump reports the new value.\n- **failed**: not confirmed after several tries; this starts a hold.\n- **refused**: not allowed to send, for example in Shadow or during a hold.\n- **dropped**: no longer needed, or overtaken by a defrost, a hot water run or a hold.\n- **queued**, **sent**, **retry**: still on its way.',
      without: {
        hotWater: {
          body: '- **verified**: the pump reports the new value.\n- **failed**: not confirmed after several tries; this starts a hold.\n- **refused**: not allowed to send, for example in Shadow or during a hold.\n- **dropped**: no longer needed, or overtaken by a defrost, the pump being busy elsewhere or a hold.\n- **queued**, **sent**, **retry**: still on its way.',
        },
      },
    },
    {
      id: 'own',
      kind: 'know',
      title: 'Your own pump settings',
      body: 'Settings you change on the [Pump](#/pump) page go the same way and count against the same budget. Their explanation names who made them.',
    },
  ],
  questions: [
    {
      id: 'few',
      q: 'Why are there so few commands?',
      a: 'ovenbird only writes when the water temperature must change by at least the [[dead-band]], and it waits between changes. Most minutes nothing needs to be sent.',
    },
    {
      id: 'used-up',
      q: 'What happens when the budget is used up?',
      a: 'An alarm is raised and nothing more is sent that day, apart from safety corrections. The pump keeps its last values.',
    },
  ],
  related: ['activity/holds', 'settings/behaviour'],
};
