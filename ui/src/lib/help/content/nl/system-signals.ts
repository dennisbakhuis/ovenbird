import type { HelpTopic } from '$lib/help/types';

export const topic: HelpTopic = {
  id: 'system/signals',
  title: 'Systeem: signalen',
  lead: 'Elke live waarde die ovenbird van de warmtepomp en Home Assistant krijgt, per soort gegroepeerd, met hoe vers ze is.',
  art: 'system',
  sections: [
    {
      id: 'toolbar',
      kind: 'do',
      title: 'Een signaal vinden',
      body: 'Typ in **Signalen zoeken** om te filteren op naam, id, bron of waarde. **Alleen vastgehouden of verouderd** toont alleen de signalen die niet vers zijn. Het getal rechts zegt hoeveel er getoond worden.',
      target: 'system/signals.toolbar',
    },
    {
      id: 'groups',
      kind: 'see',
      title: 'Groepen en tekens',
      body: 'De signalen staan in groepen: Ruimte, Temperaturen, Pomp, Vermogen, Instellingen en Overig. Het teken ervoor toont de toestand:\n\n- een vinkje: actueel;\n- een pauzeteken: vastgehouden, een sensor die bij verandering meldt en leeft maar niet veranderd is;\n- een waarschuwingsteken: [[stale|verouderd]], met de leeftijd van de laatste melding.',
      target: 'system/signals.groups',
    },
    {
      id: 'details',
      kind: 'do',
      title: 'Beter bekijken',
      body: 'Klik op een signaal voor zijn id, zijn leeftijd, hoelang het ongewijzigd is, de maximale leeftijd voordat het als verouderd telt, wat het in leven houdt, en zijn bron. Van daaruit kun je het laatste uur als kleine grafiek tonen.',
    },
    {
      id: 'source',
      kind: 'know',
      title: 'Waar signalen vandaan komen',
      body: 'Waarden van de pomp komen van [[heishamon|HeishaMon]] via [[mqtt|MQTT]]; kamer- en andere sensoren uit Home Assistant. Elk [[signal|signaal]] heeft een maximale leeftijd; oudere waarden worden niet gebruikt om te regelen.',
    },
  ],
  questions: [
    {
      id: 'held',
      q: 'Waarom staat mijn kamersensor op vastgehouden?',
      a: 'Hij meldt alleen als de temperatuur verandert. Vastgehouden betekent dat het apparaat nog leeft, omdat er kort geleden een ander signaal van binnenkwam, dus de waarde wordt vertrouwd.',
    },
    {
      id: 'stale',
      q: 'Een waarde is verouderd. Is dat erg?',
      a: 'Bij een pompwaarde betekent het dat HeishaMon of MQTT niets meer levert; kijk bij [Systeem](#/system). Bij een sensor in Home Assistant: kijk naar de batterij of de verbinding.',
    },
  ],
  related: ['system', 'settings/room'],
};
