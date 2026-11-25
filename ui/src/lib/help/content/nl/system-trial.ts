import type { HelpTopic } from '$lib/help/types';

export const topic: HelpTopic = {
  id: 'system/trial',
  title: 'Systeem: proef en overstap',
  lead: 'Wat er nog nodig is voordat ovenbird het overneemt van je oude regeling, hoe de proef zich verhoudt tot daarvoor, en hoe je de regeling teruggeeft.',
  art: 'system',
  sections: [
    {
      id: 'checklist',
      kind: 'see',
      title: 'Checklist voor de overstap',
      body: 'Elk punt wordt uit actuele gegevens berekend als je de pagina opent: dagen in [[shadow|Schaduw]], de [[divergence|afwijking]] met de andere regeling, de vangnetregel op de HeishaMon, meldingen, geoefend teruggeven, open alarmen, de kamerwaarde en de pompstand bij de overstap. **Klaar**, **Nakijken** of **Ontbreekt** zegt hoe het ervoor staat; de pijl opent de pagina met de gegevens. Een nieuwere service splitst de lijst: **Voor de overstap** is wat klaar betekent; **In de eerste proefweek** (de vangnetregel aan het werk gezien, een echte oefening) kan pas als ovenbird regelt.',
      target: 'system/trial.checklist',
    },
    {
      id: 'criteria',
      kind: 'see',
      title: 'Proef tegenover daarvoor',
      body: 'De proefperiode (vanaf de overstap, hooguit 30 dagen) naast even lang daarvoor. De kamer mag gemiddeld hooguit een halve graad verschillen, het aandeel runs korter dan 20 minuten mag niet groeien, de pomp mag geen storingen melden en de schrijfacties blijven binnen het dagbudget. Rijen met **Info** zijn alleen ter vergelijking. De regel eronder zegt of het wel een proef is: zonder overstap vergelijken de cijfers de andere regeling met zichzelf, en de criteria worden pas na 7 dagen proef beoordeeld.',
      target: 'system/trial.criteria',
    },
    {
      id: 'runs',
      kind: 'see',
      title: 'Runlengtes',
      body: 'Hoe lang de compressor telkens draaide in de laatste 7 dagen. Korte runs (korter dan 20 minuten, in oranje) slijten de pomp en kosten rendement; zie [[short-cycling|pendelen]]. Een run die door ontbrekende gegevens is afgekapt, telt niet mee.',
      target: 'system/trial.runs',
    },
    {
      id: 'release',
      kind: 'do',
      title: 'Regeling teruggeven',
      body: '[[release-control|Regeling teruggeven]] geeft de pomp terug: ovenbird pauzeert en zet de watertemperatuur, pompsnelheid en het fluisterniveau terug die hij bij de overstap aantrof, controleert ze en blijft gepauzeerd. Verder wordt niets aangeraakt.',
      steps: [
        'Kies **Oefenen** voor een oefening, of **Regeling nu teruggeven** om echt over te dragen.',
        'Typ bij echt teruggeven het getoonde woord om te bevestigen.',
        'Kijk hoe elke instelling terugkomt en hoe de tijd zich verhoudt tot het doel van 5 minuten.',
        'Volg de volgende stappen om je vorige regeling weer aan te zetten.',
      ],
      target: 'system/trial.release',
    },
    {
      id: 'safe',
      kind: 'know',
      title: 'Er gebeurt niets vanzelf',
      body: 'De pagina start nooit zelf een teruggave, en alleen een beheerder kan er een starten. Een oefening is een echte teruggave die als oefening wordt vastgelegd: daarna blijft ovenbird gepauzeerd tot je **Hervatten** kiest in het standmenu.',
    },
  ],
  questions: [
    {
      id: 'rehearse',
      q: 'Waarom zou ik het teruggeven oefenen?',
      a: 'Voor de overstap moet vaststaan dat je de regeling binnen 5 minuten kunt teruggeven. Een oefening legt vast hoe lang het duurde en of elke waarde terugkwam; het punt op de checklist wordt **Klaar** als dat lukte.',
    },
    {
      id: 'no-snapshot',
      q: 'Er staat dat er geen pompstand is vastgelegd. Wat nu?',
      a: 'ovenbird legt hem vast op het moment dat hij voor het eerst live gaat in Automatisch, voordat hij iets stuurt. In Schaduw kan een beheerder **Pompstand nu vastleggen** en dan **Oefenen zonder versturen**: een plan van wat teruggeven zou versturen, zonder iets te versturen of te pauzeren. Dat is het checklistpunt Teruggeven gepland.',
    },
    {
      id: 'after-release',
      q: 'Wie regelt de pomp na het teruggeven?',
      a: 'Niemand, tot je je oude regeling weer aanzet. De pomp houdt de waarden die ovenbird heeft teruggezet. Controleer de eerste schrijfactie ervan bij [Vergelijken](#/system/shadow).',
    },
  ],
  related: ['system/shadow', 'system', 'activity'],
};
