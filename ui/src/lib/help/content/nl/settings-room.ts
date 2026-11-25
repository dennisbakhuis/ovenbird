import type { HelpTopic } from '$lib/help/types';

export const topic: HelpTopic = {
  id: 'settings/room',
  title: 'Comforttemperatuur',
  lead: 'Stel de kamertemperatuur in die je wilt en kies de sensor die haar meet. De ruimtecorrectie stuurt de watertemperatuur dan iets omhoog of omlaag om daar te komen.',
  art: 'settings',
  sections: [
    {
      id: 'comfort',
      kind: 'do',
      title: 'Comfortdoel',
      body: 'De kamertemperatuur waar ovenbird naar streeft, 21 °C tenzij je die verandert. Met − en + verschuif je haar in stappen van 0,1 °C.\n\nErnaast zie je de kamer nu op een balk; het groene deel is de [[comfort-band|comfortband]]. Tussen 18 en 24 °C is gebruikelijk; daarbuiten bevestig je de wijziging bij het bekijken.',
      target: 'settings/room.comfort',
    },
    {
      id: 'sensor',
      kind: 'do',
      title: 'Kamersensor',
      body: 'Kies de thermometer in de kamer die het meest telt, meestal de woonkamer. De lijst toont sensoren uit Home Assistant en van de warmtepomp, met hun waarde nu.\n\nZonder sensor regelt ovenbird alleen op de stooklijn, zonder ruimtecorrectie.',
      target: 'settings/room.sensor',
    },
    {
      id: 'status',
      kind: 'see',
      title: 'Hoe ovenbird de sensor ziet',
      body: '- **Sensor actueel** of **Sensor verouderd**: of de waarde wordt vertrouwd ([[stale|verouderd]]).\n- **ongewijzigd**: hoelang de waarde niet veranderd is.\n- **in leven via**: een ander signaal van hetzelfde apparaat dat laat zien dat het nog werkt.\n- **Gezag**: hoeveel de kamer de watertemperatuur nog mag verlagen.\n- **aannemelijk**: of de controlesensor het ermee eens is.\n\nEen label verschijnt alleen als het van toepassing is.',
      target: 'settings/room.status',
    },
    {
      id: 'behaviour',
      kind: 'know',
      title: 'Gedrag van de sensor',
      body: 'Vertel ovenbird hoe je [[room-sensor|kamersensor]] meldt. Een **Periodiek** type meldt volgens een schema: vul het **Meldinterval** in. Een type **Bij verandering**, zoals veel Zigbee-sensoren op batterijen, meldt alleen als de waarde de **Stapgrootte van de sensor** verschuift, dus stilte is normaal.\n\n**Levenssignalen**, zoals de luchtvochtigheid van hetzelfde apparaat, laten zien dat het leeft. Een **Controlesensor** moet ongeveer overeenkomen, anders pauzeert de ruimtecorrectie.',
      target: 'settings/room.behaviour',
    },
    {
      id: 'correction',
      kind: 'know',
      title: 'Comforttemperatuur',
      body: 'Met **Ruimtecorrectie** aan vergelijkt ovenbird de kamer met het doel en verhoogt of verlaagt de watertemperatuur, standaard met hooguit 3 K ([[room-feedback|hoe dat werkt]]). Uit betekent alleen de stooklijn.\n\n**Meer: Ruimtecorrectie** bevat de afstelling: hoe sterk en hoe snel ze reageert, en haar grenzen. De voorinstelling van de afgifte kiest goede waarden; verander ze alleen als de kamer blijft schommelen of dagenlang naast het doel zit.',
      target: 'settings/room.correction',
    },
    {
      id: 'monitor',
      kind: 'know',
      title: 'Kamerbewaking',
      body: 'Geeft een waarschuwing als de kamer te koud blijft: standaard 1,5 K onder het doel gedurende 30 minuten. Laat de marge leeg om de bewaking uit te zetten. Ze waarschuwt alleen; ze verandert niets aan de verwarming.',
      target: 'settings/room.monitor',
    },
  ],
  questions: [
    {
      id: 'silent',
      q: 'Wat gebeurt er als de sensor niets meer meldt?',
      a: 'ovenbird stopt met corrigeren en regelt op de stooklijn. Een opgebouwde correctie die verwarmt blijft staan en zwakt in 24 uur af, zodat het huis niet ineens afkoelt. Een [alarm](#/activity) vertelt wat er aan de hand is.',
    },
    {
      id: 'on-change',
      q: 'Mijn sensor meldt alleen als de temperatuur verandert. Is dat erg?',
      a: 'Nee. Kies **Bij verandering** onder **Gedrag van de sensor** en voeg een levenssignaal van hetzelfde apparaat toe. ovenbird houdt de laatste waarde dan vast zolang het apparaat leeft, tot aan de **Stiltegrens** (standaard 24 uur). Hoe langer een waarde vastgehouden wordt, hoe minder ze het water mag laten afkoelen, dus een kapotte sensor kan het huis niet koud laten.',
    },
    {
      id: 'raise',
      q: 'Kan ik het comfortdoel veilig verhogen?',
      a: 'Ja. Het water blijft binnen de grenzen van de stooklijn en onder de maximale aanvoertemperatuur. De kamer reageert langzaam, zeker met vloerverwarming: geef het een paar uur tot een dag.',
    },
    {
      id: 'stove',
      q: 'Een houtkachel maakt deze kamer heet en de rest van het huis koud. Wat helpt?',
      a: 'Zet de [[wood-stove|houtkachelmodus]] aan bij [Houtkachel](#/settings/stove). ovenbird verlaagt de stooklijn dan met een vaste stap zolang de kachel brandt, in plaats van de ruimtecorrectie de watertemperatuur voor het hele huis te laten verlagen.',
    },
  ],
  related: ['settings/curve', 'settings/stove', 'activity', 'system/signals'],
};
