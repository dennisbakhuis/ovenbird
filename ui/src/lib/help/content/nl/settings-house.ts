import type { HelpTopic } from '$lib/help/types';

export const topic: HelpTopic = {
  id: 'settings/house',
  title: 'Huis',
  lead: 'Het verwarmde vloeroppervlak van je huis. Daarmee wordt het geleerde warmteverlies watt per m² en een indicatieve klasse op de pagina Huis.',
  art: 'settings',
  sections: [
    {
      id: 'area',
      kind: 'do',
      title: 'Vul het vloeroppervlak in',
      body: 'Vul het verwarmde vloeroppervlak in m² in: de ruimtes die de warmtepomp verwarmt. Een ruwe schatting is prima: 10 % ernaast verschuift de score 10 %. Laat het leeg om alleen het [[ua|warmteverlies]] in W/K te zien.',
      steps: [
        'Typ het oppervlak bij **Verwarmd vloeroppervlak**.',
        'Kies **Bekijken en toepassen** in de balk onderaan.',
      ],
      target: 'settings/house.area',
    },
    {
      id: 'effect',
      kind: 'know',
      title: 'Wat het verandert',
      body: 'Alleen de score op de pagina [Huis](#/house). De regeling gebruikt het vloeroppervlak niet: stooklijn, ruimtecorrectie en grenzen blijven zoals ze zijn. De score wordt meteen opnieuw berekend; de learner hoeft niet opnieuw te draaien.',
    },
    {
      id: 'indicative',
      kind: 'know',
      title: 'Alleen een indicatie',
      body: 'De klasse is berekend bij 20 °C binnen en −10 °C buiten uit je eigen metingen. Het is **niet het officiële energielabel**, dat anders wordt bepaald.',
    },
  ],
  questions: [
    {
      id: 'which',
      q: 'Welk oppervlak gebruik ik?',
      a: 'Het verwarmde vloeroppervlak: elke verdieping waar de verwarming komt, gemeten binnen de muren. Laat een onverwarmde zolder, garage of schuur weg.',
    },
    {
      id: 'empty',
      q: 'De pagina Huis toont nog geen klasse. Waarom?',
      a: 'Voor de klasse is ook een betrouwbaar model nodig. Zolang het model nog koude dagen nodig heeft, staat op de pagina hoeveel.',
    },
  ],
  related: ['house', 'settings'],
};
