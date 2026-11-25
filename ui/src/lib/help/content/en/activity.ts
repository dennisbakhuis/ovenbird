import type { HelpTopic } from '$lib/help/types';

export const topic: HelpTopic = {
  id: 'activity',
  title: 'Activity: alarms',
  lead: 'What needs your attention and what happened, the last 24 hours or a range you pick. Alarms appear when something is wrong or unusual, and clear by themselves.',
  art: 'activity',
  sections: [
    {
      id: 'timeline',
      kind: 'see',
      title: 'Timeline',
      body: 'One lane per kind of event: alarms and holds as bars for as long as they lasted, settings changes and commands as ticks. The timeline is the same on every tab. **Show as list** gives the events as text.',
      target: 'activity.timeline',
    },
    {
      id: 'range',
      kind: 'do',
      title: 'Time range',
      body: 'Above the timeline, pick **24 h**, **7 d** or **Custom** with **From** and **To**. The range sets the window of the timeline and of all four tabs: alarms, holds, commands and audit. So an alarm that came and went on Saturday is still there on Monday.',
      target: 'activity.range',
    },
    {
      id: 'active',
      kind: 'see',
      title: 'Active alarms',
      body: 'Every [[alarm]] that is on now, the most serious first, with since when and what the service measured. Two lines say what happens next: **ovenbird now:** what ovenbird does about it, and **You:** what you can do. The link below takes you further, such as **Show holds** or **Open System**.',
      target: 'activity.active',
    },
    {
      id: 'severity',
      kind: 'know',
      title: 'Critical, warning, info',
      body: '- **Critical**: a safety limit, such as water too hot, too little flow or a pump error. Until it clears, ovenbird only lets the water temperature go down.\n- **Warning**: something needs a look, like a silent room sensor or someone else changing the pump.\n- **Info**: good to know, no action needed, like HeishaMon restarting.',
    },
    {
      id: 'monitors',
      kind: 'see',
      title: 'Safety monitors',
      body: 'The checks that run every few seconds, in every mode. Each shows the value now against its limit (the red mark) and a status: **ok**, **pending** (seen, waiting to see if it lasts), **active**, or **unknown** when there is no recent data. **Why?** shows the service’s own message.',
      target: 'activity.monitors',
    },
    {
      id: 'journal',
      kind: 'see',
      title: 'Alarm journal',
      body: 'Every alarm in the chosen range, with when it started and how long it lasted. **active** means it is still on; **cleared** means its cause went away. You cannot dismiss an alarm: it clears only when its condition is gone.',
      target: 'activity.journal',
    },
    {
      id: 'room',
      kind: 'know',
      title: 'Room sensor and Home Assistant alarms',
      body: '- **Room sensor quiet**: an on-change sensor showed no sign of life for 8 hours.\n- **Room sensor silent**: no sign of life beyond its silence limit.\n- **Room report overdue**: a periodic sensor missed three reports.\n- **Room value implausible**: the cross-check sensor disagrees.\n- **Home Assistant link down**: no contact for 5 minutes.\n\novenbird then trusts the room value less or not at all and leans on the heating curve.',
    },
  ],
  questions: [
    {
      id: 'ack',
      q: 'Do I have to acknowledge alarms?',
      a: 'No. Alarms clear by themselves once the cause is gone. Only a lost settings store needs your **Acknowledge**, on the [Settings](#/settings) page.',
    },
    {
      id: 'foreign',
      q: '“Someone else changed the pump”: what now?',
      a: 'Something other than ovenbird wrote a pump setting: the Panasonic remote, Node-RED or another app. ovenbird pauses its commands for a while (a [[hold]]). Find out who it was; see [Holds](#/activity/holds).',
    },
    {
      id: 'critical',
      q: 'A critical alarm stays on. What can I check?',
      a: 'Look at the pump itself: an error code on the remote, closed radiator or floor valves, the water pressure. Meanwhile ovenbird only sends lower water temperatures.',
    },
    {
      id: 'csv',
      q: 'Can I download the journal as a spreadsheet?',
      a: 'Yes. **CSV** next to the alarm journal, the hold history, the command journal and the audit trail downloads the range you see. Every chart has **Show as table**, and the table has its own CSV button.',
    },
  ],
  related: ['activity/holds', 'settings/room', 'system'],
  aliases: ['csv', 'export', 'download', 'spreadsheet', 'journal'],
};
