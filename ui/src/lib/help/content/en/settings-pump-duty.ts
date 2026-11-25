import type { HelpTopic } from '$lib/help/types';

export const topic: HelpTopic = {
  id: 'settings/pump-duty',
  title: 'Pump',
  lead: 'Which parts of the pump the app shows, and how hard the water pump inside your heat pump may run. ovenbird can set the duty higher while heating and lower while the compressor rests.',
  art: 'settings',
  aliases: ['hot water', 'DHW', 'tank', 'pump duty'],
  sections: [
    {
      id: 'hot-water',
      kind: 'do',
      title: 'Hot water',
      body: '**Hot water** says whether the app shows the pump heating a hot-water tank. **Automatic (as the pump reports)** follows what the pump says about its tank, as the line below the setting tells; **Show** and **Hide** decide for it.\n\nHidden, hot water leaves the day strips, the signals and this help. A run that still happens shows as **Pump busy elsewhere**, and ovenbird does not lower the setpoint meanwhile, as always. The setting changes nothing in how ovenbird controls the pump.',
      target: 'settings/pump-duty.hot-water',
    },
    {
      id: 'reported',
      kind: 'see',
      title: 'What the pump reports',
      body: '**Max** is the maximum [[pump-duty]] the pump has now. **Now** is the duty it actually runs at. **Range** is the band ovenbird may ever command; the installation fixes it, hence the lock.',
      target: 'settings/pump-duty.reported',
    },
    {
      id: 'settings',
      kind: 'do',
      title: 'The duty settings',
      body: '**Control pump duty** lets ovenbird set the maximum duty. **Duty while heating** applies while the [[compressor]] runs and during a hot water run. **Duty when idle** applies once the compressor has been off for the **Delay before idle duty**, 5 minutes by default.\n\nThe idle value may not be higher than the heating value, and both must lie within the range.',
      without: {
        hotWater: {
          body: '**Control pump duty** lets ovenbird set the maximum duty. **Duty while heating** applies while the [[compressor]] runs. **Duty when idle** applies once the compressor has been off for the **Delay before idle duty**, 5 minutes by default.\n\nThe idle value may not be higher than the heating value, and both must lie within the range.',
        },
      },
      target: 'settings/pump-duty.settings',
    },
    {
      id: 'defrost',
      kind: 'know',
      title: 'During a defrost',
      body: 'During a [[defrost]] the pump drives its own duty and ignores the setting. ovenbird then sends nothing for pump duty and applies its value again once the defrost is over. [Commands](#/activity/commands) shows such a command as not sent.',
    },
    {
      id: 'safe',
      kind: 'know',
      title: 'Safe values',
      body: 'ovenbird never stops the pump: water keeps circulating when idle. Too low a heating duty gives too little [[flow]]; the low flow monitor raises a critical alarm when flow drops below its minimum while the compressor runs.\n\nSwitch **Control pump duty** off to leave the duty to the pump.',
    },
  ],
  questions: [
    {
      id: 'units',
      q: 'What do the numbers mean?',
      a: 'They are the pump’s own duty scale as HeishaMon reports it, not percentages or litres. Compare them with **Now** and with the flow on the [Pump](#/pump) page.',
    },
    {
      id: 'why-idle',
      q: 'Why lower the duty when idle?',
      a: 'While the compressor rests the water only needs to keep moving, so the pump can run slower and quieter.',
    },
    {
      id: 'off',
      q: 'What happens if I switch it off?',
      a: 'ovenbird stops sending pump duty commands. The pump keeps the last maximum duty it received.',
    },
  ],
  related: ['pump', 'activity/commands'],
};
