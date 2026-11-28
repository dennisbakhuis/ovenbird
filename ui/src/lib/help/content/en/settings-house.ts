import type { HelpTopic } from '$lib/help/types';

export const topic: HelpTopic = {
  id: 'settings/house',
  title: 'House',
  lead: 'Facts about your house: build period, heated floor area, volume, windows and occupants. They are the starting points for the heat-loss estimate on the House page.',
  art: 'settings',
  sections: [
    {
      id: 'area',
      kind: 'do',
      title: 'Enter the floor area',
      body: 'Fill in the heated floor area in m², the rooms the heat pump warms. A rough figure is fine.',
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
      body: 'Nothing in the control: the heating curve, room correction and limits stay as they are. The facts are stored and shown on the [House](#/house) page.',
    },
    {
      id: 'facts',
      kind: 'know',
      title: 'Facts about the house',
      body: 'Build period, occupants, volume, window area and orientation are **starting points**. They are all optional, and leaving one empty is better than guessing.',
      target: 'settings/house.facts',
    },
  ],
  questions: [
    {
      id: 'which',
      q: 'Which area do I use?',
      a: 'The heated floor area: every floor the heating reaches, measured inside the walls. Leave out an unheated attic, garage or shed.',
    },
  ],
  related: ['house', 'settings'],
};
