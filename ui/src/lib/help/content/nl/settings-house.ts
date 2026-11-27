import type { HelpTopic } from '$lib/help/types';

export const topic: HelpTopic = {
  id: 'settings/house',
  title: 'Huis',
  lead: 'Het verwarmde vloeroppervlak van je huis. Daarmee wordt het geleerde warmteverlies watt per m² en een indicatieve klasse op de pagina Huis.',
  art: 'settings',
  sections: [
    {
      id: 'area',
      kind: 'do',
      title: 'Vul het vloeroppervlak in',
      body: 'Vul het verwarmde vloeroppervlak in m² in: de ruimtes die de warmtepomp verwarmt. Een ruwe schatting is prima: 10 % ernaast verschuift de score 10 %. Laat het leeg om alleen het [[ua|warmteverlies]] in W/K te zien.',
      steps: [
        'Typ het oppervlak bij **Verwarmd vloeroppervlak**.',
        'Kies **Bekijken en toepassen** in de balk onderaan.',
      ],
      target: 'settings/house.area',
    },
    {
      id: 'effect',
      kind: 'know',
      title: 'Wat het verandert',
      body: 'Alleen de score op de pagina [Huis](#/house). De regeling gebruikt het vloeroppervlak niet: stooklijn, ruimtecorrectie en grenzen blijven zoals ze zijn. De score wordt meteen opnieuw berekend; de learner hoeft niet opnieuw te draaien.',
    },
    {
      id: 'indicative',
      kind: 'know',
      title: 'Alleen een indicatie',
      body: 'De klasse is berekend bij 20 °C binnen en −10 °C buiten uit je eigen metingen. Het is **niet het officiële energielabel**, dat anders wordt bepaald.',
    },
    {
      id: 'facts',
      kind: 'know',
      title: 'Gegevens over het huis',
      body: 'Bouwperiode, aandeel vloerverwarming, bewoners, volume, raamoppervlak en richting zijn **beginpunten**. Het leerprogramma begint ermee; de metingen gaan voor als ze anders zeggen. Alles is optioneel, en iets leeg laten is beter dan gokken. Je vindt ze ook op de pagina [Huis](#/house), waar je ze kunt invullen terwijl het model nog leert.',
      target: 'settings/house.facts',
    },
    {
      id: 'bounds',
      kind: 'do',
      title: 'Geleerde waarden vastzetten of begrenzen',
      body: 'Onder **Geleerde waarden vastzetten of begrenzen** kun je het warmteverlies, de tijdconstante, de zonopening en de interne warmtewinst een minimum, een maximum of beide geven. **Gelijk minimum en maximum zetten de waarde vast**: jij gaat boven de metingen, wat goed is als je het beter weet, bijvoorbeeld met een warmteverlies uit een energieadvies. Een minimum boven het maximum wordt geweigerd. De volgende leerronde past het toe.',
      steps: [
        'Open **Geleerde waarden vastzetten of begrenzen** en vul minimum en maximum in.',
        'Kies **Bekijken en toepassen** in de balk onderaan.',
      ],
      target: 'settings/house.bounds',
    },
    {
      id: 'learning',
      kind: 'know',
      title: 'Instellingen voor het leren',
      body: 'Dagen om van te leren (21 tot 90, standaard 60) moeten minstens 8 meer zijn dan de dagen voor de test (7 tot 21, standaard 14). De marge zegt hoeveel slechter dan het model in gebruik een nieuw model de kamer mag voorspellen om toch gekozen te worden: 0 betekent minstens even goed. **Overgeslagen dagen** slaat het leerprogramma over: een vakantie, de hele dag open ramen, bezoek. Je kunt ze ook kiezen op de pagina Huis, in de grafiek met de kamerafwijking per dag.',
      target: 'settings/house.learning',
    },
  ],
  questions: [
    {
      id: 'which',
      q: 'Welk oppervlak gebruik ik?',
      a: 'Het verwarmde vloeroppervlak: elke verdieping waar de verwarming komt, gemeten binnen de muren. Laat een onverwarmde zolder, garage of schuur weg.',
    },
    {
      id: 'empty',
      q: 'De pagina Huis toont nog geen klasse. Waarom?',
      a: 'Voor de klasse is ook een betrouwbaar model nodig. Zolang het model nog koude dagen nodig heeft, staat op de pagina hoeveel.',
    },
  ],
  related: ['house', 'settings'],
};
