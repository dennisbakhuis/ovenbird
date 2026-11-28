import type { HelpTopic } from '$lib/help/types';

export const topic: HelpTopic = {
  id: 'house',
  title: 'Huis',
  lead: 'Hoeveel warmte je huis bij het huidige weer verliest, hoeveel warmte de warmtepomp er bij een bepaalde aanvoertemperatuur in brengt, en wat je van het huis weet.',
  art: 'home',
  sections: [
    {
      id: 'basics',
      kind: 'know',
      title: 'Warmteverlies en warmte van de pomp',
      body: 'ovenbird meet uit de geschiedenis van de warmtepomp hoeveel warmte je huis verliest per graad verschil tussen de kamer en buiten. Daaruit volgt het warmteverlies nu, vannacht en op een ontwerpdag van -10 °C, en de warmte die de pomp bij een gekozen aanvoertemperatuur levert. Het zijn schattingen: de zon is niet meegerekend, en de warmte van de pomp is de eindsituatie, waar vloerverwarming uren voor nodig heeft. Niets hiervan verandert hoe de warmtepomp wordt geregeld.',
      target: 'house.basics',
    },
    {
      id: 'inputs',
      kind: 'do',
      title: 'Vertel wat je van het huis weet',
      body: 'Bouwperiode, vloeroppervlak, aantal bewoners, volume en ramen zijn **beginpunten** voor de schatting. Vul in wat je weet en laat leeg wat je niet weet: een leeg veld is beter dan een gok.\n\nWijzigingen gaan via de balk onderaan, net als elke andere instelling.',
      steps: [
        'Open **Wat je van het huis weet**.',
        'Vul een paar velden in.',
        'Kies **Bekijken en toepassen** in de balk onderaan.',
      ],
      target: 'house.inputs',
    },
  ],
  questions: [
    {
      id: 'area',
      q: 'Waar vul ik het vloeroppervlak in?',
      a: 'Op deze pagina onder **Wat je van het huis weet**, of bij [Instellingen → Huis](#/settings/house). Gebruik het verwarmde vloeroppervlak in m², binnen de muren gemeten.',
    },
    {
      id: 'controls',
      q: 'Gebruikt ovenbird dit om de warmtepomp te regelen?',
      a: 'Nee. De gegevens worden alleen bewaard. Stooklijn, ruimtecorrectie en grenzen gebruiken ze niet.',
    },
  ],
  related: ['settings/house', 'settings/curve', 'pump'],
  aliases: [
    'warmteverlies',
    'huisgegevens',
    'vloeroppervlak',
    'bouwperiode',
    'build period',
    'heat loss',
  ],
};
