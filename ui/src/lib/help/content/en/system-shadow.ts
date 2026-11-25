import type { HelpTopic } from '$lib/help/types';

export const topic: HelpTopic = {
  id: 'system/shadow',
  title: 'System: compare with the other controller',
  lead: 'While ovenbird only watches, this page sets what it would send next to what the pump really runs on, so you can judge every difference.',
  art: 'system',
  sections: [
    {
      id: 'range',
      kind: 'do',
      title: 'Choose a period',
      body: 'Pick **24 h**, **7 days**, **14 days** or **Custom**. Custom takes a start and an end, at most 31 days apart. The 24 h view follows new decisions by itself; the longer ones load once.',
      target: 'system/shadow.range',
    },
    {
      id: 'summary',
      kind: 'see',
      title: 'The figures',
      body: '**Compared** is the share of the period with both values; the rest are gaps. Then the mean and the largest difference, the time more than 1 K apart and the number of episodes. The line below says which way ovenbird leans: cooler or warmer than the pump.',
      target: 'system/shadow.summary',
    },
    {
      id: 'chart',
      kind: 'see',
      title: 'The chart',
      body: 'The solid line is what ovenbird would send, the dashed line what the pump has. The shaded area between them is the [[divergence]]. The lane below shows who wrote the pump: ovenbird, another controller, or no data. A gap is drawn as a gap and never counts as agreement.',
      target: 'system/shadow.chart',
    },
    {
      id: 'episodes',
      kind: 'see',
      title: 'Episodes',
      body: 'An episode is a stretch in which the two stay more than 1 K apart. Each one shows when and how long, which way ovenbird would have differed, both values at the largest difference and ovenbird’s reason. An explained episode, such as a night reduction of the other controller, is fine: an administrator can **Mark as explained…** with a short note, and the go-live checklist then stops counting it.',
      target: 'system/shadow.episodes',
    },
    {
      id: 'days',
      kind: 'see',
      title: 'Per day',
      body: 'One row per day in the service’s time zone: the compared share, the mean and largest difference, the time over 1 K and the episodes that started that day. A day at the edge of the period says how many hours of it are in.',
      target: 'system/shadow.days',
    },
    {
      id: 'why',
      kind: 'know',
      title: 'Why compare',
      body: 'Before ovenbird may drive the pump, it watches in [[shadow]] next to your current controller for at least 14 days. No unexplained divergence in that time is one of the go-live checks on the [Trial](#/system/trial) page.',
    },
  ],
  questions: [
    {
      id: 'value',
      q: 'Which pump value is compared?',
      a: 'The water temperature the pump reports as its target (Z1_Water_Target_Temp), whoever wrote it: Node-RED, the remote or the envelope rule on HeishaMon.',
    },
    {
      id: 'difference',
      q: 'There is a difference of 2 K. Is that wrong?',
      a: 'Not by itself. Read ovenbird’s reason on the episode, and see the full explanation of that moment on the [Setpoint](#/setpoint) page. A difference you can explain is fine.',
    },
    {
      id: 'empty',
      q: 'The page says there is nothing to compare.',
      a: 'ovenbird has not yet watched long enough in this period, or the pump’s value was missing. Choose a longer period or come back later.',
    },
  ],
  related: ['system/trial', 'setpoint', 'system'],
  aliases: ['baseline', 'Node-RED', 'divergence', 'compare', 'comparison'],
};
