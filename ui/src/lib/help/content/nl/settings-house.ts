import type { HelpTopic } from '$lib/help/types';

export const topic: HelpTopic = {
  id: 'settings/house',
  title: 'Huis',
  lead: 'Gegevens over je huis: bouwperiode, verwarmd vloeroppervlak, volume, ramen en bewoners. Ze zijn de beginpunten voor de schatting van het warmteverlies op de pagina Huis.',
  art: 'settings',
  sections: [
    {
      id: 'area',
      kind: 'do',
      title: 'Vloeroppervlak invullen',
      body: 'Vul het verwarmde vloeroppervlak in m² in: de ruimtes die de warmtepomp verwarmt. Een ruwe schatting is goed genoeg.',
      steps: [
        'Typ de oppervlakte in **Verwarmd vloeroppervlak**.',
        'Kies **Bekijken en toepassen** in de balk onderaan.',
      ],
      target: 'settings/house.area',
    },
    {
      id: 'effect',
      kind: 'know',
      title: 'Wat het verandert',
      body: 'Niets aan de regeling: stooklijn, ruimtecorrectie en grenzen blijven zoals ze zijn. De gegevens worden bewaard en staan op de pagina [Huis](#/house).',
    },
    {
      id: 'facts',
      kind: 'know',
      title: 'Gegevens over het huis',
      body: 'Bouwperiode, bewoners, volume, raamoppervlak en richting zijn **beginpunten**. Alles is optioneel, en een veld leeg laten is beter dan gokken.',
      target: 'settings/house.facts',
    },
  ],
  questions: [
    {
      id: 'which',
      q: 'Welke oppervlakte gebruik ik?',
      a: 'Het verwarmde vloeroppervlak: elke verdieping die de verwarming bereikt, binnen de muren gemeten. Laat een onverwarmde zolder, garage of schuur weg.',
    },
  ],
  related: ['house', 'settings'],
};
