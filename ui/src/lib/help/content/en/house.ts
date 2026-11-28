import type { HelpTopic } from '$lib/help/types';

export const topic: HelpTopic = {
  id: 'house',
  title: 'House',
  lead: 'How much heat your house loses at the current weather, how much heat the heat pump gives it at a water temperature, and what you know about the house.',
  art: 'home',
  sections: [
    {
      id: 'basics',
      kind: 'know',
      title: 'Heat loss and heat from the heat pump',
      body: 'ovenbird measures how much heat your house loses per degree of difference between the room and outside, from the history of the heat pump. From that it gives the heat loss now, tonight and on a design day of -10 °C, and the heat the pump gives at a chosen water temperature. These are estimates: the sun is not modelled, and the heat pump figure is a steady state that under-floor heating needs hours to reach. Nothing here changes how the heat pump is controlled.',
      target: 'house.basics',
    },
    {
      id: 'inputs',
      kind: 'do',
      title: 'Tell it what you know about the house',
      body: 'Build period, floor area, number of occupants, volume and windows are **starting points** for the estimate. Fill in what you know and leave out what you do not: an empty field is better than a guess.\n\nChanges go through the bar at the bottom, like any other setting.',
      steps: [
        'Open **What you know about the house**.',
        'Fill in a few fields.',
        'Press **Review and apply** in the bar at the bottom.',
      ],
      target: 'house.inputs',
    },
  ],
  questions: [
    {
      id: 'area',
      q: 'Where do I enter the floor area?',
      a: 'On this page under **What you know about the house**, or in [Settings → House](#/settings/house). Use the heated floor area in m², measured inside the walls.',
    },
    {
      id: 'controls',
      q: 'Does ovenbird use this to control the heat pump?',
      a: 'No. The facts are only stored. The heating curve, room correction and limits do not use them.',
    },
  ],
  related: ['settings/house', 'settings/curve', 'pump'],
  aliases: ['heat loss', 'house facts', 'floor area', 'build period', 'warmteverlies'],
};
