import type { HelpTopic } from '$lib/help/types';

export const topic: HelpTopic = {
  id: 'system/replay',
  title: 'System: replay',
  lead: 'What ovenbird would have sent over a past period with another configuration: the active one, a stored version or your current draft, next to what it recorded and what the pump actually ran on.',
  art: 'system',
  sections: [
    {
      id: 'claims',
      kind: 'know',
      title: 'No comfort or energy claims',
      body: 'A replay is open loop. The house followed the control that was recorded at the time, so the rooms, the water and the pump in the replay are the recorded ones. A replay shows which setpoints ovenbird would have sent and why; it cannot say how warm the rooms would have been or how much energy another configuration would have used.',
      target: 'system/replay.claims',
    },
    {
      id: 'period',
      kind: 'do',
      title: 'Choose a period',
      body: 'Pick **24 h**, **7 days**, **30 days** or **Custom**. The strip shows a cell per day: the fuller the cell, the more of that day’s decisions are stored. Tap a day to replay just that day. Decisions older than their retention (Settings → Data) are gone and cannot be replayed.',
      target: 'system/replay.period',
    },
    {
      id: 'config',
      kind: 'do',
      title: 'Choose a configuration',
      body: '**Active configuration** replays the configuration that runs now. **A stored version** replays an earlier or later version from Settings → Versions and backup. **The current draft** replays your unsaved changes on top of the active configuration, before you apply them.',
      target: 'system/replay.config',
    },
    {
      id: 'run',
      kind: 'do',
      title: 'Run it',
      body: 'Press **Replay**. The service steps every stored decision again; 30 days take a few seconds to a minute. You can leave the page meanwhile and come back. Starting a new replay stops the one that runs; replaying needs the operate or admin role.',
      target: 'system/replay.run',
    },
    {
      id: 'identity',
      kind: 'see',
      title: 'Exact or not',
      body: 'First each decision is stepped again with the configuration it ran with. **Exact** means every recorded setpoint came back, so the replay of another configuration starts from the same ground. **Not exact** means a few did not (for example after an update of ovenbird): read the result as an indication.',
    },
    {
      id: 'figures',
      kind: 'see',
      title: 'Figures, chart and episodes',
      body: 'The figures count how often the replayed setpoint changes, how many writes a day that would cost against the daily budget, how long it lies more than the threshold above or below the pump’s target, and which constraint held it most often. The chart lays the replay (solid), ovenbird’s recorded setpoint (dotted) and the pump’s target (dashed) over each other. An episode is a stretch in which the replay and the pump are more than the threshold apart, with the reason the replay gave.',
    },
  ],
  related: ['system/shadow', 'settings/versions', 'system/data'],
};
