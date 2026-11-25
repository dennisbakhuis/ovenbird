import type { HelpTopic } from '$lib/help/types';

export const topic: HelpTopic = {
  id: 'settings/behaviour',
  title: 'Gedrag',
  lead: 'Hoe ver en hoe vaak ovenbird de watertemperatuur mag verschuiven, en hoe hij de compressor ontziet bij het starten en tegen korte runs.',
  art: 'settings',
  sections: [
    {
      id: 'limits',
      kind: 'do',
      title: 'Grenzen van de aanvoertemperatuur',
      body: '**Minimale aanvoertemperatuur** en **Maximale aanvoertemperatuur** zijn de onder- en bovengrens van elke [[setpoint|aanvoertemperatuur]] die ovenbird stuurt. Het maximum kun je hier alleen verlagen; hoger dan de standaard van de afgifte kan alleen via de installatie. Een slotje betekent dat de waarde uit de installatie komt.',
      target: 'settings/behaviour.limits',
    },
    {
      id: 'deadband',
      kind: 'know',
      title: 'Dode band en wachttijd',
      body: 'De [[dead-band|dode band]] is hoever de berekende temperatuur moet afwijken voordat de aanvoertemperatuur verandert, minstens 1 K. **Wachttijd tussen wijzigingen** is de kortste tijd tussen twee wijzigingen ([[dwell|wachttijd]]).\n\nGrotere waarden geven minder en rustiger wijzigingen en minder schrijfacties naar de pomp; kleinere volgen nauwer. Een wachttijd onder 10 minuten wordt afgeraden.',
      target: 'settings/behaviour.deadband',
    },
    {
      id: 'ramp',
      kind: 'know',
      title: 'Zachte start',
      body: 'Met de [[start-ramp|zachte start]] aan houdt ovenbird de aanvoertemperatuur net na het starten van de compressor onder de stooklijn en laat haar daarna langzaam los: een rustige start die past bij vloerverwarming. Aanhoudtijd, diepte en vrijgavesnelheid bepalen het verloop; de diepte komt nooit onder de veiligheidsband.\n\nDe voorinstellingen voor vloer en gemengd zetten hem aan; Radiatoren zet hem uit.',
      target: 'settings/behaviour.ramp',
    },
    {
      id: 'cycling',
      kind: 'know',
      title: 'Pendelbeveiliging',
      body: 'Houdt de aanvoertemperatuur vroeg in een run hoog genoeg, zodat de pomp niet stopt en kort daarna weer start ([[short-cycling|pendelen]]). **Venster van de pendelbeveiliging** is de kortste run die ze probeert te halen, 30 minuten bij vloerverwarming.\n\nUitzetten geeft een waarschuwing die je moet bevestigen.',
      target: 'settings/behaviour.cycling',
    },
    {
      id: 'safe',
      kind: 'know',
      title: 'Voordat je hieraan draait',
      body: 'De voorinstelling van de afgifte bepaalt al deze waarden, en die passen bij de meeste huizen. Het **?** bij elk veld toont de waarde van de voorinstelling en een knop **Terug naar voorinstelling**. Bij het bekijken zie je hoeveel wijzigingen per dag jouw versie zou geven, afgezet tegen het dagbudget voor schrijfacties.',
    },
  ],
  questions: [
    {
      id: 'exact',
      q: 'Waarom volgt ovenbird de stooklijn niet precies?',
      a: 'Elke wijziging is een schrijfactie naar de pomp. De dode band en de wachttijd houden dat op een redelijk aantal per dag, en de aanvoertemperatuur verandert in hele graden.',
    },
    {
      id: 'budget',
      q: 'Wat is het dagbudget voor schrijfacties?',
      a: 'Een maximum aantal opdrachten naar de pomp per dag, standaard 150, waarvan 10 in reserve voor de veiligheid. [Opdrachten](#/activity/commands) laat zien hoeveel er vandaag gebruikt is.',
    },
  ],
  related: ['settings/curve', 'activity/commands', 'setpoint'],
};
