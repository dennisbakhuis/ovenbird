import type { HelpTopic } from '$lib/help/types';

export const topic: HelpTopic = {
  id: 'pump',
  title: 'Pump',
  lead: 'The heat pump up close: the water loop right now, how it ran today and this week, and the three pump settings you can change yourself.',
  art: 'pump',
  sections: [
    {
      id: 'loop',
      kind: 'see',
      title: 'Water loop',
      body: 'Left is the outdoor unit: its state, the [[compressor]] speed in Hz, electricity in, heat out and the [[cop|COP]]. Water leaves at the [[outlet]] temperature, gives off its heat in your floor or radiators and comes back at the [[inlet]] temperature.\n\nIn the middle: the [[flow]], the [[delta-t|ΔT]] next to the value it is set to, and the [[pump-duty|pump duty]] against its maximum.',
      target: 'pump.loop',
    },
    {
      id: 'day',
      kind: 'see',
      title: 'Last 24 hours',
      body: 'The lanes show when the compressor ran, [[defrost|defrosted]], heated [[dhw|hot water]] and ran in [[quiet-mode|quiet mode]].\n\nThe figures below count from midnight in the service’s time zone (named in the heading when it is not yours), the same day as on Home: starts, average and longest run, defrosts, electricity, heat and COP. A run that was already going at midnight is not a start today. Fewer, longer runs are better (see [[short-cycling|short cycling]]).',
      without: {
        hotWater: {
          body: 'The lanes show when the compressor ran, [[defrost|defrosted]] and ran in [[quiet-mode|quiet mode]]. When the pump was busy elsewhere, a lane for that shows too.\n\nThe figures below count from midnight in the service’s time zone (named in the heading when it is not yours), the same day as on Home: starts, average and longest run, defrosts, electricity, heat and COP. A run that was already going at midnight is not a start today. Fewer, longer runs are better (see [[short-cycling|short cycling]]).',
        },
      },
      target: 'pump.day',
    },
    {
      id: 'flow',
      kind: 'see',
      title: 'Water temperatures and flow',
      body: 'Three panels over the last 24 hours: ΔT with its set value, flow, and pump duty with its maximum. Shaded stretches are defrosts.\n\nDuring a defrost the pump reverses to melt the ice: outlet and inlet swap roles and it runs its own pump duty, often above the maximum. That is why ΔT and duty jump out of their normal range there.',
      target: 'pump.flow',
    },
    {
      id: 'cop',
      kind: 'see',
      title: 'COP against outside temperature',
      body: 'Each dot is one hour of the last 7 days in which the pump drew power: the outside temperature against the COP of that hour. The dashed line is the trend.\n\nExpect the dots to rise to the right: the warmer it is outside, the less effort it takes to get heat out of the air. Dots that sit low are often hours with a defrost.',
      target: 'pump.cop',
    },
    {
      id: 'daily',
      kind: 'see',
      title: 'Daily figures',
      body: 'One bar per day for the last **7 days** or **30 days**: electricity, heat delivered, COP, compressor starts, running time, defrosts, and how much the room was below the [[comfort-band|comfort band]] (in [[degree-hours|K·h]]).\n\nThe light bar is today, still running. An empty bar means no data that day. The figures use the pump’s own estimates of power and heat.',
      target: 'pump.daily',
    },
    {
      id: 'settings',
      kind: 'do',
      title: 'Change a pump setting',
      body: 'You can change three settings: **Heating delta-T** (3–10 K), **Pump flow-rate mode** ([[flow-mode|Delta-T or Maximum flow]]) and **Heating off above outdoor temperature** (see [[heating-off-temperature|heating-off temperature]]). ovenbird checks afterwards that the pump took the new value.',
      steps: [
        'Choose **Change** next to the setting.',
        'Enter the new value under **New value**.',
        'Type the value again to confirm, then choose **Send to pump**.',
      ],
      target: 'pump.settings',
    },
    {
      id: 'when-not',
      kind: 'know',
      title: 'When a change is refused',
      body: 'Only an administrator can change pump settings, and only while ovenbird is in [[auto-mode|Auto]]. A change is refused during a defrost, a hot-water run or a [[hold]], or while another change is on its way. Each setting can change once per 10 minutes and six times a day, to spare the pump.\n\nEverything under **Read-only details** belongs to ovenbird, the pump itself or the installer, so it is shown but not changed here.',
      without: {
        hotWater: {
          body: 'Only an administrator can change pump settings, and only while ovenbird is in [[auto-mode|Auto]]. A change is refused during a defrost, while the pump is busy elsewhere, during a [[hold]] or while another change is on its way. Each setting can change once per 10 minutes and six times a day, to spare the pump.\n\nEverything under **Read-only details** belongs to ovenbird, the pump itself or the installer, so it is shown but not changed here.',
        },
      },
    },
  ],
  questions: [
    {
      id: 'duty-defrost',
      q: 'Why does the pump duty jump above its maximum during a defrost?',
      a: 'During a defrost the pump drives its own circulation pump and ignores the maximum. ovenbird knows this: it sends no pump-duty command during a defrost and picks up where it was afterwards.',
    },
    {
      id: 'delta-small',
      q: 'Should I make the delta-T smaller or larger?',
      a: 'A smaller delta-T means more flow and water that returns warmer; a larger one less flow and more cooling per litre. There is no single right value. Change it by 1 K at a time and watch the room, the starts and the COP for a few days before the next step.',
    },
    {
      id: 'idle-delta',
      q: 'Why is ΔT almost zero while the pump is idle?',
      a: 'With the compressor off, no heat is added, so the water leaves at about the temperature it came back with. The circulation pump may keep running at a low pump duty.',
    },
    {
      id: 'no-change-button',
      q: 'Why can’t I change anything?',
      a: 'A line at the top of the card says why, for example [[shadow|Shadow]], a hold or a defrost. When you are not signed in as an administrator, the settings show but cannot be changed.',
    },
  ],
  related: ['home', 'settings/pump-duty', 'settings/quiet', 'activity/commands'],
};
