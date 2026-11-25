import type { HelpTopic } from '$lib/help/types';

export const topic: HelpTopic = {
  id: 'switching',
  title: 'Coming from another controller',
  lead: 'Used a Node-RED flow or another controller for your heat pump before? Here is where the usual settings live in ovenbird, and what ovenbird does differently.',
  art: 'welcome',
  sections: [
    {
      id: 'mapping',
      kind: 'know',
      title: 'Where your settings went',
      body: '- **WAR** (weather-dependent curve) → [Heating curve](#/settings/curve), with its own on/off switch\n- **RTC** (room temperature correction) → room correction, in [Comfort temperature](#/settings/room), switched on or off separately\n- **SoftStart** → **Start ramp**, in [Behaviour](#/settings/behaviour)\n- **HEAT_SP_lower_limit** → **Minimum water setpoint**, in [Behaviour](#/settings/behaviour)\n- **NightReduction** → no night setback yet; [Quiet mode](#/settings/quiet) is about noise only\n- **Pump duty** → [Pump](#/settings/pump-duty)\n\nThere is no import: enter your values by hand.',
    },
    {
      id: 'curve',
      kind: 'do',
      title: 'Copy the curve',
      body: 'WAR gives a water temperature for a few outside temperatures. Enter the same points in the [[heating-curve|heating curve]] editor, which takes 2 to 6 points, and the same room target under [Comfort temperature](#/settings/room).\n\nThe target applies to the sensor that measures it. If your previous controller read another room input than the sensor you choose here, the same number can feel a little warmer or cooler.',
    },
    {
      id: 'night',
      kind: 'know',
      title: 'Night setback',
      body: 'ovenbird has no night setback today. [[quiet-mode|Quiet mode]] makes the outdoor unit quieter in the windows you set; it does not lower the temperature on purpose, although with less power the house can cool a little. Lowering the room at night is left to a planner that comes later.',
    },
    {
      id: 'different',
      kind: 'know',
      title: 'What ovenbird does differently',
      body: '- One [[setpoint]] built from named parts, explained for every [[decision]] on [Setpoint](#/setpoint).\n- A [[envelope|safety envelope]] that no setpoint can leave.\n- A [[dead-band|dead band]] and a [[dwell|wait time]], so it does not write for every small change.\n- Every command is checked against what the pump reports.\n- When someone else writes, it [[hold|holds]] instead of fighting.\n- [[wood-stove|Wood-stove mode]] for a stove in the sensor’s room.',
    },
    {
      id: 'side-by-side',
      kind: 'do',
      title: 'Run it next to Node-RED first',
      body: 'In [[shadow|Shadow]] ovenbird reads and decides every minute but never writes, so Node-RED keeps control. Node-RED is then the expected writer: no alarm, no hold. Compare **would send** with **pump has** on [Setpoint](#/setpoint).\n\nBefore ovenbird controls in Auto, stop Node-RED from writing to the pump. Otherwise ovenbird sees a [[foreign-writer|foreign writer]] and waits.',
    },
  ],
  questions: [
    {
      id: 'import',
      q: 'Can ovenbird import the settings of my previous controller?',
      a: 'Not yet. Enter your values by hand: the WAR points in [Heating curve](#/settings/curve), your room target in [Comfort temperature](#/settings/room), the pump duty values in [Pump](#/settings/pump-duty).',
    },
    {
      id: 'both',
      q: 'Can Node-RED and ovenbird both control the pump?',
      a: 'No, only one may write. In Shadow ovenbird only watches, so Node-RED can keep control. In Auto ovenbird [[hold|holds]] its commands when it sees another writer; after three holds within 12 hours it waits until you release it on [Holds](#/activity/holds).',
    },
    {
      id: 'timing',
      q: 'My previous controller looked every few minutes. Does ovenbird write more often?',
      a: 'ovenbird decides every minute, but sends only whole degrees, only when the change reaches the dead band and not before the wait time has passed. Most minutes nothing is sent. Every write counts against a daily budget.',
    },
    {
      id: 'defrost-duty',
      q: 'Why does ovenbird send no pump duty during a defrost?',
      a: 'During a defrost the pump sets its own duty and ignores the setting. ovenbird therefore sends nothing then and applies its value again afterwards.',
    },
  ],
  related: ['start', 'settings/curve', 'settings/room', 'settings/behaviour'],
  aliases: ['Node-RED', 'WAR', 'RTC', 'SoftStart', 'NightReduction', 'import', 'migrate'],
};
