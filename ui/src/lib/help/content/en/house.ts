import type { HelpTopic } from '$lib/help/types';

export const topic: HelpTopic = {
  id: 'house',
  title: 'House',
  lead: 'What ovenbird learned about your house from its own history: heat loss, how slowly it cools, an indicative insulation score and a suggestion for your curve.',
  art: 'home',
  sections: [
    {
      id: 'score',
      kind: 'see',
      title: 'Insulation score',
      body: 'The big number is the [[ua|heat loss]] in W/K, with the range the true value lies in. With your floor area it becomes watts per m² at 20 °C inside and −10 °C outside, and a band from A to G.\n\nThe band is **indicative, not the official energielabel**: one room sensor sees ventilation and the other rooms too. While the model still needs cold days, the card says how many.',
      target: 'house.score',
    },
    {
      id: 'facts',
      kind: 'see',
      title: 'What the model learned',
      body: 'The [[time-constant]] says how slowly the house cools; the [[balance-temperature]] above which outside temperature it needs no heating. The solar aperture is how much a sunny hour warms the house, the internal gains what people and appliances add. Each comes with its range and one plain sentence.',
      target: 'house.facts',
    },
    {
      id: 'signature',
      kind: 'see',
      title: 'Energy signature',
      body: "The [[energy-signature|energy signature]] has one dot per day: the heat the house needed against that day's outside temperature. The dashed line is the fit: steeper means more heat loss, and it reaches zero at the balance temperature. Sunny days sit below the line. Days with a wood-stove fire are left out. **Show as table** lists every day.",
      target: 'house.signature',
    },
    {
      id: 'proposal',
      kind: 'do',
      title: 'Use the curve suggestion',
      body: 'The model works out the water temperature it needs to hold your comfort temperature at each point of your [[heating-curve|heating curve]], within your limits. Nothing changes by itself.',
      steps: [
        'Read the table: the change per point and what limited it.',
        'Press **Open as draft**. The suggestion opens on the curve page as a [[draft]].',
        'Press **Review and apply**, look at the [[preview]] and apply it, or discard it.',
      ],
      target: 'house.proposal',
    },
    {
      id: 'quality',
      kind: 'know',
      title: 'How far to trust it',
      body: 'Once a week a new model is fitted on the latest history. It is only used when it predicted the room on the last 14 days at least as well as the model in use. The card shows both errors, the heat loss of every model so far and the data it used. Its limits are listed under **Limits of this model**.',
      target: 'house.quality',
    },
  ],
  questions: [
    {
      id: 'empty',
      q: 'The page says "Still learning". Why?',
      a: 'A model needs about 30 days of heating with enough cold days (daily mean below 5 °C) and a spread of at least 10 K in outside temperature. The card says what is still missing. The learner runs once a week in its own optional container.',
    },
    {
      id: 'label',
      q: 'Is this my energielabel?',
      a: 'No. The band is an indication from your own measurements at fixed design conditions. The official energielabel is assessed differently and can differ.',
    },
    {
      id: 'area',
      q: 'Where do I enter the floor area?',
      a: 'In [Settings → House](#/settings/house). Use the heated floor area in m². Without it you see the heat loss in W/K only.',
    },
    {
      id: 'bands',
      q: 'Where do the bands A to G start and end?',
      a: 'The band follows the heat loss per m² at 20 °C inside and −10 °C outside: **A** below 30 W/m², **B** 30 to 45, **C** 45 to 60, **D** 60 to 80, **E** 80 to 100, **F** 100 to 125 and **G** 125 or more. The limits also stand under the scale on the card.',
    },
  ],
  related: ['settings/house', 'settings/curve', 'pump'],
  aliases: [
    'insulation',
    'energielabel',
    'heat loss',
    'UA',
    'house model',
    'isolatie',
    'band',
    'bands A to G',
    'W/m2',
  ],
};
