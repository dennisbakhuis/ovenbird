import type { GlossaryEntry, HelpTopic } from '$lib/help/types';

/** A small made-up topic for the help unit and component tests; not real help content. */
export const fixtureTopic: HelpTopic = {
  id: 'pump',
  title: 'Fixture pump',
  lead: 'A made-up topic that exercises every part of the markup.',
  art: 'pump',
  sections: [
    {
      id: 'flow',
      kind: 'see',
      title: 'Water flow',
      body: 'The **flow** line shows the [[delta-t|difference]] between [[outlet]] and inlet.\n\n- one\n- two',
      target: 'pump.flow',
    },
    {
      id: 'speed',
      kind: 'do',
      title: 'Change the speed',
      body: 'Open [the settings](#/settings/pump-duty) to change the pump speed.',
      steps: ['Press **Edit**.', 'Pick a speed.'],
      target: 'pump.speed',
    },
    {
      id: 'defrost',
      kind: 'know',
      title: 'Defrost',
      body: 'Sometimes the pump defrosts. Één keer per uur is normaal.',
    },
  ],
  questions: [{ id: 'noisy', q: 'Why is it noisy?', a: 'Because the [[outlet]] is hot.' }],
  related: ['settings/pump-duty', 'home'],
};

export const fixtureGlossary: GlossaryEntry[] = [
  { id: 'delta-t', term: 'Delta-T', short: 'The difference between outlet and inlet water.' },
  {
    id: 'outlet',
    term: 'Outlet',
    short: 'Water leaving the pump.',
    body: 'The outlet is the warm side.',
    related: ['delta-t'],
  },
];
