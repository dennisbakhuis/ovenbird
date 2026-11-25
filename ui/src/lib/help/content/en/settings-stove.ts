import type { HelpTopic } from '$lib/help/types';

export const topic: HelpTopic = {
  id: 'settings/stove',
  title: 'Wood stove',
  lead: 'When a wood stove heats the room with the sensor, ovenbird backs the heating off instead of cooling the whole house, and keeps the other rooms warm.',
  art: 'settings',
  sections: [
    {
      id: 'what',
      kind: 'know',
      title: 'What it is for',
      body: 'A stove in the room with your [[room-sensor|room sensor]] makes that room far warmer than the rest. [[room-feedback|Room correction]] would then cut the water temperature for every room, and the hall and bedrooms go cold.\n\n[[wood-stove|Wood-stove mode]] instead lowers the [[heating-curve|heating curve]] by the **Back-off**, 3 K by default, or with **Back off to the minimum** down to the safety minimum. Room correction pauses and keeps what it learned. The pump never stops.',
    },
    {
      id: 'status',
      kind: 'see',
      title: 'Status',
      body: 'The chips show whether wood-stove mode is on now, the back-off in use, and the start and stop thresholds as room temperatures, worked out from your comfort temperature.\n\nWhen the automatic detection is waiting, a note says why (see **When detection waits**).',
      target: 'settings/stove.status',
    },
    {
      id: 'detect',
      kind: 'know',
      title: 'Automatic detection',
      body: 'With **Detect the stove automatically** on, wood-stove mode starts when the room reaches the comfort temperature plus **Start above comfort** (1.5 K). With **Also start on a fast rise** it starts sooner when the room rises by **Fast rise** (1 K) within the **Fast-rise window** (30 min) while already above comfort.\n\nOnly a room value ovenbird fully trusts counts: fresh, not contradicted by a cross-check sensor and not held unchanged for long.',
    },
    {
      id: 'exit',
      kind: 'know',
      title: 'When it ends',
      body: 'It ends when the room drops below the start threshold minus **Stop this much lower** (1 K), but not before the **Shortest episode** (60 min) has passed. It ends at the latest after the **Longest episode** (8 h), and at once when the room value is no longer trusted.\n\nStarted by hand, it ends at the chosen time; if the room is still warm then, the automatic detection carries on.',
    },
    {
      id: 'settings',
      kind: 'do',
      title: 'The settings',
      body: 'Switch on **Wood-stove mode** first; without it nothing changes and **Stove on…** is not offered. The other fields set the thresholds above.\n\n**Reference room** is optional: a sensor in another room, such as the hall. When it drops below **Reference room at least**, the back-off shrinks, down to nothing at **Reference band** below that. So the hall does not pay for a warm living room.',
      target: 'settings/stove.settings',
    },
    {
      id: 'manual',
      kind: 'do',
      title: 'Start and stop by hand',
      body: 'Lit the stove? Tap **Stove on…** on Home’s room card or in the mode sheet and choose 2 h, 4 h or 8 h. While wood-stove mode is on, a banner on [Home](#/home) says so, with **Stop**.\n\nAfter **Stop** the automatic detection waits until the room has cooled below the stop threshold, so it does not start again right away.',
    },
    {
      id: 'waiting',
      kind: 'know',
      title: 'When detection waits',
      body: '- After the **Longest episode**: a warm room alone starts no new episode until the room has been below the stop threshold once; a fast rise still counts.\n- After the room value lost trust: it must be trusted again for **Wait after an untrusted room value** (15 min).\n- After **Stop**: until the room has cooled below the stop threshold.\n\nStarting by hand always works.',
    },
  ],
  questions: [
    {
      id: 'pump-off',
      q: 'Does ovenbird switch the pump off while the stove burns?',
      a: 'No. The pump keeps running on a lower water temperature, so the other rooms keep getting heat. Defrosts, hot water, the start ramp and the safety limits work as always.',
      without: {
        hotWater: {
          a: 'No. The pump keeps running on a lower water temperature, so the other rooms keep getting heat. Defrosts, the start ramp and the safety limits work as always.',
        },
      },
    },
    {
      id: 'cold-hall',
      q: 'The hall gets cold while the stove burns. What can I do?',
      a: 'Choose the hall’s sensor as **Reference room** and set **Reference room at least** to the lowest temperature you accept there. Or make the **Back-off** smaller.',
    },
    {
      id: 'implausible',
      q: 'Why is there no "room value implausible" alarm while the stove burns?',
      a: 'The cross-check against a second sensor is paused in wood-stove mode, because the stove room is meant to be warmer then. It starts again afterwards.',
    },
    {
      id: 'after',
      q: 'What happens when the fire is out?',
      a: 'Once the room has cooled below the stop threshold, room correction carries on from the value it had before the fire, instead of from a value wound down by the hot room. The heating curve is back to normal.',
    },
  ],
  related: ['home', 'settings/room', 'setpoint'],
  aliases: ['stove', 'fireplace', 'kachel', 'houtkachel'],
};
