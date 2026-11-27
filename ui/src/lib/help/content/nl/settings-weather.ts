import type { HelpTopic } from '$lib/help/types';

export const topic: HelpTopic = {
  id: 'settings/weather',
  title: 'Weer',
  lead: 'Zet de verwachting van de buitentemperatuur aan en kies de plek waarvoor die geldt. Ze voedt de pagina Weer en de stooklijngrafiek; ze stuurt de verwarming niet.',
  art: 'settings',
  sections: [
    {
      id: 'privacy',
      kind: 'know',
      title: 'Je locatie gaat het huis uit',
      body: 'De verwachting komt van Open-Meteo. De service haalt haar op, niet je browser, en stuurt daarbij je locatie, afgerond op 0,01°, ongeveer 1 km. Er gaat niets weg totdat je de verwachting aanzet.',
      target: 'settings/weather.privacy',
    },
    {
      id: 'enable',
      kind: 'do',
      title: 'Weersverwachting',
      body: 'Zet haar aan om de [[forecast|verwachting]] te zien op de pagina [Weer](#/weather) en als blauwe balk in de stooklijngrafiek. Alleen het [[model-plan|modelplan]] rekent ermee, en zolang dat niet op Aan staat, verandert ze niets aan de regeling.',
      target: 'settings/weather.enable',
    },
    {
      id: 'location',
      kind: 'do',
      title: 'Locatie',
      body: '**Uit Home Assistant (zone.home)** gebruikt je thuiszone, dus je hoeft niets in te vullen. **Zelf een locatie invullen** toont velden voor breedte- en lengtegraad. **Gebruik mijn locatie** vraagt deze browser om zijn positie en vult ze in; de knop verschijnt alleen waar de browser dat toestaat.\n\nDe regel onderaan laat zien welke bron in gebruik is.',
      target: 'settings/weather.location',
    },
    {
      id: 'off',
      kind: 'know',
      title: 'Uitzetten',
      body: 'Zet **Weersverwachting** uit en pas toe. De service haalt dan niets meer op, en de verwachting verdwijnt van de pagina Weer en uit de stooklijngrafiek.',
    },
  ],
  questions: [
    {
      id: 'heating',
      q: 'Verandert de verwachting mijn verwarming?',
      a: 'Nee, niet in deze versie. ovenbird verwarmt op de gemeten buitentemperatuur. Met de verwachting zie je wat er komt en hoe goed eerdere verwachtingen klopten.',
    },
    {
      id: 'no-button',
      q: 'Waarom zie ik geen knop “Gebruik mijn locatie”?',
      a: 'Browsers delen een positie alleen via een beveiligde (https-)verbinding. Vul de coördinaten dan zelf in; twee decimalen zijn genoeg.',
    },
  ],
  related: ['weather', 'settings/curve'],
};
