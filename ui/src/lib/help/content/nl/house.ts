import type { HelpTopic } from '$lib/help/types';

export const topic: HelpTopic = {
  id: 'house',
  title: 'Huis',
  lead: 'Wat ovenbird uit zijn eigen geschiedenis over je huis leerde: warmteverlies, hoe langzaam het afkoelt, een indicatieve isolatiescore en een voorstel voor je stooklijn.',
  art: 'home',
  sections: [
    {
      id: 'score',
      kind: 'see',
      title: 'Isolatiescore',
      body: 'Het grote getal is het [[ua|warmteverlies]] in W/K, met het bereik waarin de echte waarde ligt. Met je vloeroppervlak wordt het watt per m² bij 20 °C binnen en −10 °C buiten, en een klasse van A tot G.\n\nDe klasse is **indicatief, niet het officiële energielabel**: één kamersensor ziet ook ventilatie en de andere kamers. Zolang het model nog koude dagen nodig heeft, staat er hoeveel.',
      target: 'house.score',
    },
    {
      id: 'facts',
      kind: 'see',
      title: 'Wat het model leerde',
      body: 'De [[time-constant|tijdconstante]] zegt hoe langzaam het huis afkoelt; de [[balance-temperature|stookgrens]] boven welke buitentemperatuur het geen verwarming nodig heeft. Het zonvenster is hoeveel een zonnig uur het huis verwarmt, de interne warmte wat mensen en apparaten toevoegen. Elk met zijn bereik en één gewone zin.',
      target: 'house.facts',
    },
    {
      id: 'signature',
      kind: 'see',
      title: 'Energiesignatuur',
      body: 'De [[energy-signature|energiesignatuur]] heeft één stip per dag: de warmte die het huis nodig had tegen de buitentemperatuur van die dag. De stippellijn is de fit: steiler betekent meer warmteverlies, en bij de stookgrens komt hij op nul. Zonnige dagen liggen onder de lijn. Dagen met de houtkachel tellen niet mee. **Toon als tabel** geeft elke dag.',
      target: 'house.signature',
    },
    {
      id: 'proposal',
      kind: 'do',
      title: 'Het voorstel gebruiken',
      body: 'Het model berekent welke aanvoertemperatuur nodig is om je comforttemperatuur te houden, op elk punt van je [[heating-curve|stooklijn]], binnen je grenzen. Er verandert niets vanzelf.',
      steps: [
        'Lees de tabel: het verschil per punt en wat het begrensde.',
        'Kies **Open als concept**. Het voorstel opent op de stooklijnpagina als [[draft|concept]].',
        'Kies **Bekijken en toepassen**, bekijk de [[preview|voorvertoning]] en pas toe, of gooi het weg.',
      ],
      target: 'house.proposal',
    },
    {
      id: 'quality',
      kind: 'know',
      title: 'Hoeveel je erop kunt bouwen',
      body: 'Eens per week wordt een nieuw model gefit op de laatste geschiedenis. Het wordt alleen gebruikt als het de kamer op de laatste 14 dagen minstens zo goed voorspelde als het model dat in gebruik is. De kaart toont beide fouten, het warmteverlies van elk model tot nu toe en de gebruikte gegevens. De grenzen staan onder **Grenzen van dit model**.',
      target: 'house.quality',
    },
  ],
  questions: [
    {
      id: 'empty',
      q: 'Er staat "Nog aan het leren". Waarom?',
      a: 'Een model heeft ongeveer 30 stookdagen nodig, met genoeg koude dagen (daggemiddelde onder 5 °C) en minstens 10 K spreiding in buitentemperatuur. De kaart zegt wat nog ontbreekt. Het leerprogramma draait eens per week in een eigen, optionele container.',
    },
    {
      id: 'label',
      q: 'Is dit mijn energielabel?',
      a: 'Nee. De klasse is een indicatie uit je eigen metingen bij vaste ontwerpcondities. Het officiële energielabel wordt anders bepaald en kan afwijken.',
    },
    {
      id: 'area',
      q: 'Waar vul ik het vloeroppervlak in?',
      a: 'In [Instellingen → Huis](#/settings/house). Gebruik het verwarmde vloeroppervlak in m². Zonder dat zie je alleen het warmteverlies in W/K.',
    },
    {
      id: 'bands',
      q: 'Waar beginnen en eindigen de klassen A tot G?',
      a: 'De klasse volgt het warmteverlies per m² bij 20 °C binnen en −10 °C buiten: **A** onder 30 W/m², **B** 30 tot 45, **C** 45 tot 60, **D** 60 tot 80, **E** 80 tot 100, **F** 100 tot 125 en **G** 125 of meer. De grenzen staan ook onder de schaal op de kaart.',
    },
  ],
  related: ['settings/house', 'settings/curve', 'pump'],
  aliases: [
    'isolatie',
    'energielabel',
    'warmteverlies',
    'UA',
    'huismodel',
    'insulation',
    'klasse',
    'band',
    'W/m2',
  ],
};
