import type { HelpTopic } from '$lib/help/types';

export const topic: HelpTopic = {
  id: 'system/trial',
  title: 'System: trial and go-live',
  lead: 'What is still needed before ovenbird takes over from your old controller, how the trial compares with before, and how to hand control back.',
  art: 'system',
  sections: [
    {
      id: 'checklist',
      kind: 'see',
      title: 'Go-live checklist',
      body: 'Each item is worked out from live facts every time you open the page: days in [[shadow|Shadow]], the [[divergence]] with the other controller, the fallback rule on the HeishaMon, notifications, a rehearsed hand-back, open alarms, the room value and the pump state recorded at go-live. **Done**, **Check** or **Missing** says where it stands; the arrow opens the page with the facts. A newer service splits the list: **Before go-live** is what ready means; **In the first trial week** (the fallback rule seen acting, a real rehearsal) can only be done once ovenbird controls.',
      target: 'system/trial.checklist',
    },
    {
      id: 'criteria',
      kind: 'see',
      title: 'Trial against before',
      body: 'The trial period (from go-live, at most 30 days) next to the same length just before it. The room may differ at most half a degree on average, the share of runs under 20 minutes may not grow, the pump may report no errors and the writes stay within the daily budget. Rows marked **Info** are for comparison only. The line below says whether this is a trial at all: without a go-live the numbers compare the other controller with itself, and the criteria are only judged after 7 days of trial.',
      target: 'system/trial.criteria',
    },
    {
      id: 'runs',
      kind: 'see',
      title: 'Run lengths',
      body: 'How long the compressor ran each time over the last 7 days. Short runs (under 20 minutes, in amber) wear the pump and cost efficiency; see [[short-cycling]]. A run cut off by missing data is left out.',
      target: 'system/trial.runs',
    },
    {
      id: 'release',
      kind: 'do',
      title: 'Release control',
      body: '[[release-control|Release control]] hands the pump back: ovenbird pauses and writes back the water temperature, pump duty and quiet level it found at go-live, checks each one and stays paused. Nothing else is touched.',
      steps: [
        'Choose **Rehearse** for a drill, or **Release control now** to hand over for real.',
        'For a real release, type the word shown to confirm.',
        'Watch each setting come back and the time against the 5-minute target.',
        'Follow the next steps to switch your previous controller back on.',
      ],
      target: 'system/trial.release',
    },
    {
      id: 'safe',
      kind: 'know',
      title: 'Nothing happens by itself',
      body: 'The page never starts a release on its own, and only an administrator can start one. A rehearsal is a real hand-back recorded as a drill: afterwards ovenbird is paused until you choose **Resume** in the mode menu.',
    },
  ],
  questions: [
    {
      id: 'rehearse',
      q: 'Why should I rehearse the hand-back?',
      a: 'The cut-over needs proof that you can give control back within 5 minutes. A rehearsal records how long it took and whether every value came back; the checklist turns **Done** when it did.',
    },
    {
      id: 'no-snapshot',
      q: 'It says no pump state is recorded. What now?',
      a: 'ovenbird records it the moment it first goes live in Auto, before it sends anything. In Shadow an administrator can **Capture pump state now** and then **Rehearse without sending**: a plan of what a hand-back would send, with nothing sent or paused. That is the checklist item Hand-back planned.',
    },
    {
      id: 'after-release',
      q: 'After a release, who controls the pump?',
      a: 'Nobody, until you switch your old controller back on. The pump keeps the values ovenbird restored. Check its first write on [Compare](#/system/shadow).',
    },
  ],
  related: ['system/shadow', 'system', 'activity'],
};
