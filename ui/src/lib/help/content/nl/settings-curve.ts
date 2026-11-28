import type { HelpTopic } from '$lib/help/types';

export const topic: HelpTopic = {
  id: 'settings/curve',
  title: 'Stooklijn',
  lead: 'De stooklijn geeft bij elke buitentemperatuur een watertemperatuur. Ze is de basis van elke beslissing; de ruimtecorrectie stuurt alleen een beetje bij.',
  art: 'settings',
  sections: [
    {
      id: 'readout',
      kind: 'see',
      title: 'Vandaag op de stooklijn',
      body: 'De regel boven de grafiek leest het punt van vandaag af: bij de huidige, afgevlakte buitentemperatuur geeft de actieve stooklijn deze watertemperatuur, en ovenbird stuurde die [[setpoint|aanvoertemperatuur]] ("zou sturen" als hij niet stuurt). Ze verschillen als de ruimtecorrectie, de zachte start of een grens meedoet.\n\nTerwijl je een punt versleept, toont de regel dat punt.',
      target: 'settings/curve.readout',
    },
    {
      id: 'chart',
      kind: 'see',
      title: 'De grafiek lezen',
      body: '- De donkere lijn is de actieve stooklijn; je concept staat eroverheen.\n- De groene band is de [[envelope|veiligheidsband]]. De stooklijn moet erbinnen blijven.\n- De rode stippellijnen zijn de minimale en de maximale aanvoertemperatuur.\n- De oranje ruit is vandaag; de grijze balken zijn de aanvoertemperaturen van de laatste 7 dagen.\n- De blauwe balk onder de as is de [[forecast|verwachting]] voor de komende 48 uur, als het weer aan staat.',
      target: 'settings/curve.chart',
    },
    {
      id: 'edit',
      kind: 'do',
      title: 'De stooklijn aanpassen',
      body: 'De stooklijn heeft 2 tot 6 punten met rechte lijnen ertussen. Voorbij het eerste en het laatste punt loopt ze vlak door.',
      steps: [
        'Sleep een punt in de grafiek, of focus het en gebruik de pijltjestoetsen: omhoog en omlaag verschuiven 1 K, met Shift 0,5 K.',
        '**Punten als getallen**: gebruik − en + voor precieze waarden.',
        '**Punt toevoegen** voegt er een toe; het kruisje haalt er een weg.',
      ],
      target: 'settings/curve.points',
    },
    {
      id: 'rules',
      kind: 'know',
      title: 'Wat de controles toestaan',
      body: 'De buitentemperaturen moeten van links naar rechts oplopen, en het water mag niet warmer worden als het buiten warmer wordt. Elk punt moet tussen de minimale en de maximale aanvoertemperatuur liggen, en binnen de groene band.\n\nDe stooklijn ergens tussen −15 en 20 °C meer dan 3 K verschuiven mag, maar dat bevestig je bij het bekijken.',
    },
    {
      id: 'filter',
      kind: 'know',
      title: 'Filter op de buitentemperatuur',
      body: 'Onder **Geavanceerd: filter buitentemperatuur** zit de afvlakking van de buitentemperatuur. De warmtepomp meldt hele graden, dus de ruwe waarde springt; het filter strijkt dat glad. Een langere tijd reageert trager op het weer.\n\nDe voorinstelling van de afgifte bepaalt hem (4 uur bij Gemengd). Korter dan 30 minuten wordt afgeraden.',
      target: 'settings/curve.filter',
    },
    {
      id: 'outside',
      kind: 'know',
      title: 'Je eigen buitensensor',
      body: 'De pomp meet de buitentemperatuur bij de buitenunit, waar zon, wind en ontdooien hem kunnen vertekenen. Bij **Buitensensor voor de stooklijn** kies je in plaats daarvan een andere thermometer: een sensor uit Home Assistant of een [extra MQTT-sensor](#/settings/mqtt), in °C.\n\n- **Gebruikt hem:** alleen de stooklijn (de afgevlakte buitentemperatuur, en daarmee de aanvoertemperatuur en het plan).\n- **Houdt de pompsensor:** de [[envelope|veiligheidsband]], de veiligheidsbewaking, de gemeten lijn op [Weer](#/weather) en de samenvattingen van de proef.\n- **Als hij stilvalt:** ouder dan **Buitensensor geldt als vers tot** (standaard 30 minuten), en de stooklijn gebruikt weer de pompsensor tot de gekozen sensor meldt. De waarschuwing **Buitensensor niet vers** zegt dat, en hier verschijnt een label.',
      target: 'settings/curve.outside',
    },
    {
      id: 'tips',
      kind: 'know',
      title: 'Kleine stappen werken het best',
      body: 'Bij elk weer te koud of te warm? Pas dan eerst het comfortdoel aan bij [Comforttemperatuur](#/settings/room); met een kamersensor past ovenbird het water dan zelf aan.\n\nVerander de stooklijn als het probleem van het weer afhangt, bijvoorbeeld alleen bij vorst. Verschuif één punt ongeveer 1 K en geef het huis een dag om te reageren.',
    },
  ],
  questions: [
    {
      id: 'differs',
      q: 'Waarom is de gestuurde aanvoertemperatuur niet wat de stooklijn zegt?',
      a: 'De stooklijn is het vertrekpunt. Ruimtecorrectie, zachte start, pendelbeveiliging en de veiligheidsgrenzen tellen erbij op, en de aanvoertemperatuur verandert in hele graden. [Aanvoer](#/setpoint) laat elk deel zien.',
    },
    {
      id: 'harm',
      q: 'Kan een verkeerde stooklijn mijn vloer beschadigen?',
      a: 'De service weigert een stooklijn buiten de groene band of boven de maximale aanvoertemperatuur. Bij vloerverwarming in een dekvloer is dat maximum 40 °C.',
    },
    {
      id: 'preset',
      q: 'Hoe ga ik terug naar de stooklijn van de voorinstelling?',
      a: 'Als jouw stooklijn afwijkt van de voorinstelling, staat er een **?** boven de grafiek met **Terug naar voorinstelling**. Dat verandert je concept; bekijk en pas toe zoals altijd.',
    },
  ],
  related: ['settings/room', 'settings/emitter', 'setpoint'],
};
