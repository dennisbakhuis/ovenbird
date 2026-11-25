import type { GlossaryEntry } from '$lib/help/types';

export const glossary: GlossaryEntry[] = [
  {
    id: 'room-feedback',
    term: 'Room correction',
    short:
      'How ovenbird adjusts the water temperature when the room is warmer or colder than your comfort target.',
    body: 'Too cold: it adds a little to the heating curve; too warm: it takes a little off, within a limit (3 K by default). One part reacts at once; another part, the integrator, builds up slowly over hours to remove a lasting difference. Without a trusted room value it pauses, and a warming correction fades out over 24 hours. Its settings are part of [Comfort temperature](#/settings/room). Node-RED calls it RTC.',
    related: ['comfort-band', 'room-sensor', 'heating-curve'],
    aliases: ['RTC', 'room temperature correction', 'room feedback', 'kamercorrectie'],
  },
  {
    id: 'comfort-band',
    term: 'Comfort band',
    short:
      'The range around your comfort target in which the room counts as comfortable: half a degree either side.',
    body: 'Drawn as the green part of the room bar. Room correction still aims at the target itself.',
    related: ['room-feedback'],
  },
  {
    id: 'room-sensor',
    term: 'Room sensor',
    short: 'The thermometer that tells ovenbird how warm the room is.',
    body: 'A **periodic** sensor reports on a schedule. An **on change** sensor only reports when the value moves; ovenbird then holds its last value while the device shows other signs of life, such as its humidity. A held value can be checked against a second sensor and slowly loses its power to cool the water, so a dead sensor cannot leave the house cold.',
    related: ['room-feedback', 'stale', 'signal'],
  },
  {
    id: 'stale',
    term: 'Stale',
    short: 'A value too old to trust. ovenbird does not control on stale values.',
    body: 'Every signal has a maximum age. For the room sensor it depends on its type: a few report intervals for a periodic sensor, the silence limit for an on-change sensor.',
    related: ['signal', 'room-sensor'],
  },
  {
    id: 'hold',
    term: 'Hold',
    short:
      'A period in which ovenbird waits: it sends no commands to the pump, while it keeps deciding.',
    body: 'It starts when someone else changes a pump setting or a command is not confirmed. The pump keeps its own value meanwhile. By default the first lasts 1 hour and the second 4 hours; the third within 12 hours waits until an administrator releases it. The screen says "ovenbird is waiting until 18:25". See [Holds](#/activity/holds).',
    related: ['foreign-writer', 'alarm'],
  },
  {
    id: 'foreign-writer',
    term: 'Foreign writer',
    short:
      'Anything other than ovenbird that changes a pump setting: the Panasonic remote, Node-RED or another app.',
    body: 'ovenbird notices because the pump reports another value than the one it sent. It raises an alarm and holds rather than fight over the pump. In Shadow another controller is expected, so it raises nothing.',
    related: ['hold'],
  },
  {
    id: 'wood-stove',
    term: 'Wood-stove mode',
    short:
      'While a wood stove heats the room with the sensor, ovenbird lowers the heating curve by a fixed back-off instead of cooling the whole house.',
    body: 'It starts by itself when the room gets 1.5 K above the comfort temperature or rises fast, or by hand with **Stove on…** on Home. Room correction pauses and keeps its value; the pump keeps running, so the other rooms stay warm. It ends when the room has cooled again, after 8 hours at the latest. See [Wood stove](#/settings/stove).',
    related: ['room-feedback', 'heating-curve', 'room-sensor'],
    aliases: ['stove', 'fireplace', 'kachel', 'houtkachel', 'open haard'],
  },
  {
    id: 'auto-mode',
    term: 'Auto',
    short:
      'The mode in which ovenbird reads the pump, decides every minute and sends the water setpoint.',
    body: 'Only possible when the installation allows it. **Pause** on [System](#/system) stops sending until you resume.',
    related: ['shadow', 'decision'],
  },
  {
    id: 'shadow',
    term: 'Shadow',
    short: 'ovenbird reads and decides every minute, but never sends anything to the pump.',
    body: 'Used to watch ovenbird before it takes over, while it is paused, and after the settings store was lost. The pump keeps heating on its own settings.',
    related: ['auto-mode', 'decision'],
    aliases: ['shadow mode', 'watch only', 'reads and decides'],
  },
  {
    id: 'envelope',
    term: 'Safety envelope',
    short:
      'A band around the emitter’s preset heating curve that every curve and every setpoint must stay within.',
    body: 'By default 6 K below and 5 K above the preset curve, together with the minimum and maximum water temperature. ovenbird clamps every setpoint to it, and the curve editor draws it in green. A matching rule on HeishaMon itself, to keep the pump inside the band when ovenbird is down, is planned but not part of this version: if ovenbird stops, the pump keeps the last setpoint it received.',
    related: ['emitter', 'heating-curve', 'setpoint'],
    aliases: ['fallback', 'safety', 'safety band'],
  },
  {
    id: 'emitter',
    term: 'Emitter',
    short: 'How heat leaves the water into your rooms: floor heating, radiators or both.',
    body: 'The choice sets the preset curve, the safety limits and the tuning. See [Emitter](#/settings/emitter).',
    related: ['preset', 'envelope'],
  },
  {
    id: 'preset',
    term: 'Preset',
    short: 'The starting values that come with an emitter type.',
    body: 'A setting you have not changed follows the preset, and moves with it when you switch emitter. A value you set yourself is kept.',
    related: ['emitter'],
  },
  {
    id: 'config-version',
    term: 'Configuration version',
    short: 'The number of a saved set of settings. Every apply or rollback makes a new one.',
    body: 'The mode sheet behind the mode chip shows the version in use, for example Settings v12. [Versions and backup](#/settings/versions) lists them all.',
    related: ['draft', 'audit'],
  },
  {
    id: 'control-state',
    term: 'Who controls the pump',
    short:
      'One sentence in the status bar: ovenbird controls the pump, only watches, waits, is paused, may not send, or is off.',
    body: 'It follows what ovenbird actually does, not only the mode: in Auto during a [[hold]] it says "ovenbird is waiting". Whenever ovenbird does not send, a line under the status bar shows **would send** (ovenbird’s value) next to **pump has** (what the pump runs on). The mode chip is green only while ovenbird sends.',
    related: ['auto-mode', 'shadow', 'hold'],
  },
  {
    id: 'cooling-authority',
    term: 'Trust in the room value',
    short:
      'How much ovenbird still lets the room value lower the water temperature, from 100 % to 0 %. Technical name: cooling authority.',
    body: 'A sensor that reports only on change can hold one value for a long time. The longer it is unchanged, the less ovenbird trusts it to cool the house down; at 0 % it ignores it for cooling. A room value the cross-check sensor disagrees with is not trusted at all.',
    related: ['room-sensor', 'room-feedback'],
  },
  {
    id: 'simulation',
    term: 'Simulation',
    short:
      'An installation that runs against a simulated heat pump, often on a faster clock. The top bar shows SIMULATION.',
    body: 'Nothing reaches a real pump. When the service clock differs from your device by more than 5 minutes, the service’s date and time show under the status bar, so the times on the page make sense.',
    related: ['heishamon'],
  },
  {
    id: 'draft',
    term: 'Draft',
    short:
      'Your unsaved changes to the settings. They stay in this browser until you apply or discard them.',
    related: ['preview', 'config-version'],
  },
  {
    id: 'preview',
    term: 'Preview',
    short:
      'The check before applying: the effect right now, and a replay of the last 24 hours with your settings.',
    body: 'The replay feeds the recorded inputs to the controller with your settings. It is open loop: the house did what it did under the old settings, so the replay shows how the setpoint would have differed, not how warm it would have been. A replay check first reproduces the recorded decisions; when that fails, the result is only an indication.',
    related: ['draft', 'decision'],
  },
  {
    id: 'audit',
    term: 'Audit trail',
    short:
      'The record of who did what: settings applied, pauses, released holds, pump settings and refused requests.',
    body: 'Rows are only added, never changed. See [Audit](#/activity/audit).',
    related: ['config-version'],
  },
  {
    id: 'alarm',
    term: 'Alarm',
    short: 'A message from ovenbird’s checks that something is wrong or unusual.',
    body: 'Three levels: **critical** (a safety limit; ovenbird then only lowers the water temperature), **warning** (needs a look) and **info**. An alarm clears by itself when its cause is gone. See [Activity](#/activity). ovenbird sends no notifications yet: alarms show only in the app.',
    related: ['hold'],
    aliases: ['fault', 'error', 'notification', 'storing'],
  },
  {
    id: 'signal',
    term: 'Signal',
    short:
      'One live value ovenbird receives, such as the outside temperature or the room humidity, with its age.',
    body: 'All signals are on [Signals](#/system/signals).',
    related: ['stale', 'heishamon'],
  },
  {
    id: 'heishamon',
    term: 'HeishaMon',
    short:
      'The small board on the Panasonic heat pump that reports its values and passes on commands, over MQTT.',
    related: ['mqtt', 'signal'],
  },
  {
    id: 'mqtt',
    term: 'MQTT',
    short:
      'The messaging system that HeishaMon and ovenbird use to exchange values and commands, through a broker.',
    related: ['heishamon'],
  },
  {
    id: 'ha-link',
    term: 'Home Assistant link',
    short:
      'ovenbird’s read-only connection to Home Assistant, for the room sensor and other values.',
    body: 'When it is down for 5 minutes an alarm is raised, and room values from Home Assistant are trusted for a shorter time.',
    related: ['room-sensor', 'signal'],
  },
  {
    id: 'decision',
    term: 'Decision',
    short:
      'What ovenbird works out every minute: the water setpoint, the parts it is made of, and why.',
    body: 'Each decision is stored with its inputs, so [Setpoint](#/setpoint) can show why the temperature is what it is.',
    related: ['setpoint', 'auto-mode', 'shadow'],
  },
  {
    id: 'divergence',
    term: 'Divergence',
    short:
      'The difference between the water temperature ovenbird would set and the one the pump actually runs on.',
    body: "While ovenbird only watches next to another controller, such as Node-RED, it compares the two every minute. A difference above 1 K that lasts is an **episode**; each one shows ovenbird's reason, so you can judge whether it is explained. See [Compare](#/system/shadow).",
    related: ['shadow', 'release-control'],
    aliases: ['shadow', 'shadow mode', 'afwijking', 'comparison', 'baseline'],
  },
  {
    id: 'release-control',
    term: 'Release control',
    short:
      'Handing the pump back: ovenbird stops, restores the pump settings it found at go-live and pauses.',
    body: "At go-live ovenbird records the pump's water temperature, pump duty and quiet level. Release control writes back every value that differs, checks each one and then stays paused, so another controller can take over. A **rehearsal** does the same as a drill. The target is under 5 minutes. See [Trial](#/system/trial).",
    related: ['divergence', 'shadow', 'auto-mode'],
    aliases: ['hand back', 'rollback', 'release', 'teruggeven', 'fallback'],
  },
];
