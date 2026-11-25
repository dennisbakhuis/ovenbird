import type { HelpTopic } from '$lib/help/types';

export const topic: HelpTopic = {
  id: 'settings/house',
  title: 'House',
  lead: 'The heated floor area of your house. It turns the learned heat loss into watts per m² and an indicative band on the House page.',
  art: 'settings',
  sections: [
    {
      id: 'area',
      kind: 'do',
      title: 'Enter the floor area',
      body: 'Fill in the heated floor area in m², the rooms the heat pump warms. A rough figure is fine: 10 % off moves the score by 10 %. Leave it empty to see only the [[ua|heat loss]] in W/K.',
      steps: [
        'Type the area in **Heated floor area**.',
        'Press **Review and apply** in the bar at the bottom.',
      ],
      target: 'settings/house.area',
    },
    {
      id: 'effect',
      kind: 'know',
      title: 'What it changes',
      body: 'Only the score on the [House](#/house) page. Control does not use the floor area: the heating curve, room correction and limits stay as they are. The score is recomputed at once; the learner does not need to run again.',
    },
    {
      id: 'indicative',
      kind: 'know',
      title: 'Indicative only',
      body: 'The band is worked out at 20 °C inside and −10 °C outside from your own measurements. It is **not the official energielabel**, which is assessed differently.',
    },
  ],
  questions: [
    {
      id: 'which',
      q: 'Which area do I use?',
      a: 'The heated floor area: every floor the heating reaches, measured inside the walls. Leave out an unheated attic, garage or shed.',
    },
    {
      id: 'empty',
      q: 'The House page still shows no band. Why?',
      a: 'The band needs a trusted model as well. While the model still needs cold days, the page says how many.',
    },
  ],
  related: ['house', 'settings'],
};
