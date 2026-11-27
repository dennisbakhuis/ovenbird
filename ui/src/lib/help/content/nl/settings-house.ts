import type { HelpTopic } from '$lib/help/types';

export const topic: HelpTopic = {
  id: 'settings/house',
  title: 'Huis',
  lead: 'Gegevens over je huis, te beginnen met het verwarmde vloeroppervlak: daarmee wordt het geleerde warmteverlies omgerekend naar watt per m² en een indicatieve klasse op de pagina Huis. Verder: grenzen voor wat er wordt geleerd, de instellingen voor het leren en het gebruik van het model door de regelaar.',
  art: 'settings',
  sections: [
    {
      id: 'area',
      kind: 'do',
      title: 'Vul het vloeroppervlak in',
      body: 'Vul het verwarmde vloeroppervlak in m² in: de ruimtes die de warmtepomp verwarmt. Een ruwe schatting is prima: zit je er 10 % naast, dan verschuift de score ook 10 %. Laat het leeg om alleen het [[ua|warmteverlies]] in W/K te zien.',
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
      body: 'Alleen de score op de pagina [Huis](#/house). De regeling gebruikt het vloeroppervlak niet: stooklijn, ruimtecorrectie en grenzen blijven zoals ze zijn. De score wordt meteen opnieuw berekend; het leerprogramma hoeft niet opnieuw te draaien.',
    },
    {
      id: 'indicative',
      kind: 'know',
      title: 'Alleen een indicatie',
      body: 'De klasse is uit je eigen metingen berekend, bij 20 °C binnen en −10 °C buiten. Het is **niet het officiële energielabel**; dat wordt anders bepaald.',
    },
    {
      id: 'facts',
      kind: 'know',
      title: 'Gegevens over het huis',
      body: 'Bouwperiode, bewoners, volume, raamoppervlak en richting zijn **beginpunten**. Het leerprogramma begint ermee; zeggen de metingen iets anders, dan gaan de metingen voor. Alles is optioneel, en iets leeg laten is beter dan gokken. Je vindt ze ook op de pagina [Huis](#/house), waar je ze kunt invullen terwijl het model nog leert.',
      target: 'settings/house.facts',
    },
    {
      id: 'bounds',
      kind: 'do',
      title: 'Geleerde waarden vastzetten of begrenzen',
      body: 'Onder **Geleerde waarden vastzetten of begrenzen** kun je het warmteverlies, de tijdconstante, het zonvenster en de netto vrije warmte een minimum, een maximum of beide geven. **Zijn minimum en maximum gelijk, dan zet je de waarde vast**: je gaat dan boven de metingen. Dat is goed als je het beter weet, bijvoorbeeld met een warmteverlies uit een energieadvies. Een minimum boven het maximum wordt geweigerd. Alles geldt vanaf de volgende leerronde.',
      steps: [
        'Open **Geleerde waarden vastzetten of begrenzen** en vul minimum en maximum in.',
        'Kies **Bekijken en toepassen** in de balk onderaan.',
      ],
      target: 'settings/house.bounds',
    },
    {
      id: 'model-plan',
      kind: 'know',
      title: 'Gebruik van het model door de regelaar',
      body: 'De schakelaar **Gebruik van het huismodel door de regelaar** staat op Uit, Schaduw of Aan, en vier getallen begrenzen hem: de grootste verschuiving omlaag (standaard 0,5 K), de grootste verschuiving omhoog (0,3 K), het aantal uren vooruitkijken (6) en de grootste toegestane modelfout. **Schaduw** rekent en legt vast, maar verandert niets; **Aan** is voorlopig vergrendeld en wordt geweigerd tot een beoordeling en een periode in Schaduw klaar zijn. Zie [[model-plan|modelplan]] en de kaart op de pagina [Huis](#/house).',
      target: 'settings/house.plan',
    },
    {
      id: 'learning',
      kind: 'know',
      title: 'Instellingen voor het leren',
      body: 'Het aantal dagen om van te leren (21 tot 90, standaard 60) moet minstens 8 groter zijn dan het aantal testdagen (7 tot 21, standaard 14). De marge zegt hoeveel slechter dan het model in gebruik een nieuw model de kamer mag voorspellen om toch gekozen te worden: 0 betekent minstens even goed. **Weggelaten dagen** slaat het leerprogramma over: vakantie, de hele dag de ramen open, bezoek. Was het huis de volgende ochtend nog niet terug op temperatuur, laat die dag dan ook weg. Je kunt ze ook kiezen op de pagina Huis, in de grafiek met de kamerfout per dag.',
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
      a: 'Voor de klasse is ook een betrouwbaar model nodig. Zolang het model nog niet wordt vertrouwd, zegt de pagina waarom.',
    },
  ],
  related: ['house', 'settings'],
};
