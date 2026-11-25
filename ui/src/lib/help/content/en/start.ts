import type { HelpTopic } from '$lib/help/types';

export const topic: HelpTopic = {
  id: 'start',
  title: 'Start here',
  lead: 'What ovenbird does with your heat pump, who is in control right now, what happens if ovenbird stops, and where to look first.',
  art: 'welcome',
  sections: [
    {
      id: 'what',
      kind: 'know',
      title: 'What ovenbird does',
      body: 'Every minute ovenbird works out one number: the water temperature for the pump, the [[setpoint]]. It starts from the [[heating-curve|heating curve]] for the outside temperature and adds [[room-feedback|room correction]] when the room is colder or warmer than your comfort temperature.\n\novenbird sends that number through [[heishamon|HeishaMon]] and checks that the pump took it. The pump itself still decides when to start and stop.',
    },
    {
      id: 'modes',
      kind: 'know',
      title: 'The modes',
      body: '- **Auto**: ovenbird reads the pump, decides and sends ([[auto-mode]]).\n- **Shadow**: it reads and decides every minute but never sends ([[shadow]]). The pump runs on its own settings or on another controller.\n- **Paused**: ovenbird sends nothing until you resume; it keeps reading and deciding.\n- **Off**: it neither decides nor sends.\n\nThe mode chip in the top bar opens the mode sheet with the details.',
    },
    {
      id: 'who',
      kind: 'see',
      title: 'Who controls the pump',
      body: 'The line under the status bar says in one sentence what ovenbird does right now, for example "ovenbird controls the pump", "ovenbird only watches; another controller writes" or "ovenbird is waiting until 18:25". It follows what really happens, not only the mode ([[control-state]]).\n\nWhenever ovenbird does not send, you see **would send** (ovenbird’s value) next to **pump has** (what the pump runs on).',
    },
    {
      id: 'stops',
      kind: 'know',
      title: 'If ovenbird stops',
      body: 'The pump keeps the last water temperature it received and keeps heating on it: it does not switch off. Only the adjusting stops: no changes for the weather or the room until ovenbird runs again.\n\nAfter a restart ovenbird sends nothing until fresh pump data has arrived, and carries on with what it had learned. A safety rule on HeishaMon itself, for when ovenbird is down, is planned but not part of this version.',
    },
    {
      id: 'first',
      kind: 'do',
      title: 'Where to look first',
      body: 'Start on [Home](#/home). The line at the top sums up the house: "The house is at temperature", "Warming up" or "Needs attention: …".\n\nWhen something is wrong, ovenbird raises an [[alarm]]. The status bar counts them, and [Activity](#/activity) lists each one, with what ovenbird does about it now and what you can do.',
    },
    {
      id: 'warmer',
      kind: 'do',
      title: 'Warmer or cooler',
      body: 'Tap the target on Home’s room card ("Target 21.0 °C") to change the comfort temperature in steps of 0.1 °C, or open [Settings → Comfort temperature](#/settings/room). A change takes effect within about a minute, and every earlier version can be restored.',
    },
  ],
  questions: [
    {
      id: 'notification',
      q: 'Will I get a notification when something is wrong?',
      a: 'Not yet. ovenbird does not send messages to your phone or to Home Assistant today. Alarms show only in the app: in the status bar, on Home and on [Activity](#/activity). Look there now and then, especially in the first weeks.',
    },
    {
      id: 'fallback',
      q: 'Is there a fallback when ovenbird or the network is down?',
      a: 'The pump keeps the last water temperature it received, so the house stays heated, only without adjustments. A rule on HeishaMon that keeps the pump inside the [[envelope|safety envelope]] while ovenbird is down is planned, not built. While ovenbird runs, every setpoint stays inside that envelope.',
    },
    {
      id: 'home-assistant',
      q: 'What happens when Home Assistant restarts?',
      a: 'ovenbird keeps running: it is a separate service that talks to the pump through HeishaMon. It reads the room sensor from Home Assistant; without it, it runs on the heating curve and lets a warming correction it built up fade out over 24 hours.',
    },
    {
      id: 'try',
      q: 'Can I try ovenbird without letting it control the pump?',
      a: 'Yes, that is what [[shadow|Shadow]] is for. ovenbird decides every minute next to your current controller, such as Node-RED, without writing anything. [Setpoint](#/setpoint) shows what it would send next to what the pump has.',
    },
  ],
  related: ['switching', 'home', 'activity', 'system'],
  aliases: ['who controls', 'notification', 'notifications', 'getting started', 'overview'],
};
