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
    {
      id: 'facts',
      kind: 'know',
      title: 'Facts about the house',
      body: 'Build period, share of floor heating, occupants, volume, window area and orientation are **starting points**. The learner begins from them; the measurements overrule them when they disagree. They are all optional, and leaving one empty is better than guessing. They are also on the [House](#/house) page, where you can fill them in while the model is still learning.',
      target: 'settings/house.facts',
    },
    {
      id: 'bounds',
      kind: 'do',
      title: 'Pin or limit what is learned',
      body: 'Under **Pin or limit what is learned** you can give the heat loss, the time constant, the solar aperture and the internal gains a minimum, a maximum or both. **Equal minimum and maximum pin the value**: you overrule the measurements, which is right when you know better, for example a heat loss from an energy audit. A minimum above its maximum is refused. The next learner run applies it.',
      steps: [
        'Open **Pin or limit what is learned** and fill in the minimum and maximum.',
        'Press **Review and apply** in the bar at the bottom.',
      ],
      target: 'settings/house.bounds',
    },
    {
      id: 'learning',
      kind: 'know',
      title: 'Learning settings',
      body: 'Days to learn from (21 to 90, 60 by default) must be at least 8 more than the days kept for testing (7 to 21, 14 by default). The tolerance says how much worse than the model in use a new model may predict the room and still be taken: 0 means at least as good. **Days left out** are skipped by the learner: a holiday, windows open all day, visitors. You can also pick them on the House page, in the chart of the room error per day.',
      target: 'settings/house.learning',
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
