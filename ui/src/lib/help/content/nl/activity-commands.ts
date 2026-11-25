import type { HelpTopic } from '$lib/help/types';

export const topic: HelpTopic = {
  id: 'activity/commands',
  title: 'Activiteit: opdrachten',
  lead: 'Elke opdracht die ovenbird in de gekozen periode naar de pomp stuurde of besloot niet te sturen, en hoeveel van het schrijfbudget van vandaag op is.',
  art: 'activity',
  sections: [
    {
      id: 'budget',
      kind: 'see',
      title: 'Opdrachtbudget vandaag',
      body: 'Elke schrijfactie naar de pomp telt. De balk laat zien hoeveel schrijfacties vandaag gebruikt zijn; het laatste stuk blijft in reserve voor veiligheidscorrecties. De labels onder **Sinds de start van de service** tellen wat er met de opdrachten gebeurde sinds de service voor het laatst startte: verstuurd, bevestigd, vreemde schrijfacties enzovoort. **Mislukt** en **Opnieuw geprobeerd** staan er altijd, ook bij 0. Het budget begint om middernacht UTC opnieuw.',
      target: 'activity/commands.budget',
    },
    {
      id: 'journal',
      kind: 'see',
      title: 'Opdrachtenjournaal',
      body: 'Eén regel per opdracht: de tijd, wat ze instelde (aanvoertemperatuur, max. pompvermogen of stille modus) met de waarde, de status en een korte uitleg. Klik op een regel om elke stap te zien, met elke poging. **Toon nog** laat oudere regels zien.',
      target: 'activity/commands.journal',
    },
    {
      id: 'status',
      kind: 'know',
      title: 'Wat de statussen betekenen',
      body: '- **bevestigd**: de pomp meldt de nieuwe waarde.\n- **mislukt**: na een paar pogingen niet bevestigd; dat start een blokkade.\n- **geweigerd**: versturen mocht niet, bijvoorbeeld in Schaduw of tijdens een blokkade.\n- **vervallen**: niet meer nodig, of ingehaald door ontdooien, tapwater of een blokkade.\n- **in wachtrij**, **verstuurd**, **opnieuw**: nog onderweg.',
      without: {
        hotWater: {
          body: '- **bevestigd**: de pomp meldt de nieuwe waarde.\n- **mislukt**: na een paar pogingen niet bevestigd; dat start een blokkade.\n- **geweigerd**: versturen mocht niet, bijvoorbeeld in Schaduw of tijdens een blokkade.\n- **vervallen**: niet meer nodig, of ingehaald door ontdooien, een pomp die elders bezig is of een blokkade.\n- **in wachtrij**, **verstuurd**, **opnieuw**: nog onderweg.',
        },
      },
    },
    {
      id: 'own',
      kind: 'know',
      title: 'Je eigen pompinstellingen',
      body: 'Instellingen die je op de pagina [Pomp](#/pump) verandert, gaan dezelfde weg en tellen mee voor hetzelfde budget. Hun uitleg noemt wie ze deed.',
    },
  ],
  questions: [
    {
      id: 'few',
      q: 'Waarom zijn er zo weinig opdrachten?',
      a: 'ovenbird schrijft alleen als de watertemperatuur minstens de [[dead-band|dode band]] moet veranderen, en wacht tussen wijzigingen. De meeste minuten hoeft er niets heen.',
    },
    {
      id: 'used-up',
      q: 'Wat gebeurt er als het budget op is?',
      a: 'Er komt een alarm en die dag gaat er niets meer heen, behalve veiligheidscorrecties. De pomp houdt zijn laatste waarden.',
    },
  ],
  related: ['activity/holds', 'settings/behaviour'],
};
