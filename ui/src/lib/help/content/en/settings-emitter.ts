import type { HelpTopic } from '$lib/help/types';

export const topic: HelpTopic = {
  id: 'settings/emitter',
  title: 'Emitter',
  lead: 'Tell ovenbird how your house gives off heat: floor heating, radiators or both. That choice sets the preset curve, the safety limits and the tuning.',
  art: 'settings',
  sections: [
    {
      id: 'choose',
      kind: 'do',
      title: 'Choose the emitter',
      body: 'Each card shows the preset curve and its maximum supply temperature; **in use** marks the current [[emitter]].\n\nPick what is really installed. **Floor heating in screed** and **Mixed** allow 40 °C at most, **Radiators** 55 °C. Choosing Radiators for a floor would allow water hotter than a screed floor should get.',
      target: 'settings/emitter.choose',
    },
    {
      id: 'diff',
      kind: 'see',
      title: 'What switching changes',
      body: 'Below the cards ovenbird lists what a switch would do: how many values follow the [[preset]] and would change, and under **Kept: values you set yourself** the ones that stay. **Everything this preset sets** shows the full list.',
      target: 'settings/emitter.diff',
    },
    {
      id: 'envelope',
      kind: 'know',
      title: 'Safety limits move with it',
      body: 'The emitter also sets the safety [[envelope]], the band around its preset curve that your curve must stay in, and the minimum and maximum water temperature. If you set your own curve, it may fall outside the new band after a switch; the review then shows what to fix.',
    },
    {
      id: 'apply',
      kind: 'know',
      title: 'A switch needs confirming',
      body: 'Changing the emitter changes a lot at once, so the review asks you to confirm it. It applies between two decisions like any other setting and can be rolled back on [Versions and backup](#/settings/versions).',
    },
  ],
  questions: [
    {
      id: 'both',
      q: 'I have floor heating downstairs and radiators upstairs. Which one?',
      a: '**Mixed** is meant for that: floor heating together with low-temperature radiators.',
    },
    {
      id: 'kept',
      q: 'Will my own values be replaced?',
      a: 'No. Only values that still follow the preset change. Values you set yourself stay; the list under **Kept: values you set yourself** shows them.',
    },
  ],
  related: ['settings/curve', 'settings/behaviour'],
};
