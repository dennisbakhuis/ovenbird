import type { HelpTopic } from '$lib/help/types';

export const topic: HelpTopic = {
  id: 'weather',
  title: 'Weer',
  lead: 'De buitentemperatuur zoals de pomp die meet, de weersverwachting, en de watertemperatuur die de stooklijn de komende dagen zal vragen.',
  art: 'weather',
  sections: [
    {
      id: 'now',
      kind: 'see',
      title: 'Nu',
      body: '**Nu … buiten** is wat de pomp meet, in hele graden. **gefilterd** is de afgevlakte waarde die de [[heating-curve|stooklijn]] echt gebruikt (zie [[filtered-outside|gefilterde buitentemperatuur]]). **verwachting** is wat de [[forecast|weersverwachting]] voor dit moment geeft.\n\nRechts: het bereik van de verwachting voor de komende 48 uur, en de watertemperatuur die de stooklijn in die tijd zou vragen.',
      target: 'weather.now',
    },
    {
      id: 'chart',
      kind: 'see',
      title: 'Buiten: gemeten en verwacht',
      body: 'Links van **nu** is het verleden: **Gemeten** (in stapjes van een hele graad), **Gefilterd**, en gestippeld **Verwachting −24 u**, wat een dag eerder werd voorspeld. Rechts van nu staat de nieuwste **Verwachting**.\n\nDe panelen eronder tonen **Stooklijnwater**, zon, bewolking en wind op dezelfde tijdlijn; nachten zijn grijs. De bronregel noemt de aanbieder en wanneer de verwachting is uitgegeven.',
      target: 'weather.chart',
    },
    {
      id: 'days',
      kind: 'see',
      title: 'Komende dagen',
      body: 'Eén kaart per dag: de lucht, de hoogste en laagste temperatuur, bewolking, uren zon, wind en het bereik van het **Stooklijnwater** voor die dag. Een sterretje (*) betekent dat alleen de resterende uren van die dag meetellen.',
      target: 'weather.days',
    },
    {
      id: 'error',
      kind: 'see',
      title: 'Fout van de verwachting per voorspeltijd',
      body: 'Hoe goed de verwachting hier de laatste 14 dagen was, vergeleken met wat de pomp mat. **6 uur vooruit** en **24 uur vooruit** zijn de [[lead-time|voorspeltijden]].\n\nDe balken tonen de [[mae|MAE]], de typische grootte van de fout. **Afwijking** is de gemiddelde fout: +0,8 K betekent dat de verwachting gemiddeld 0,8 K te warm was. **Verwachtingen** is het aantal vergeleken uren.',
      target: 'weather.error',
    },
    {
      id: 'display-only',
      kind: 'know',
      title: 'De verwachting stuurt nog niet',
      body: 'Voorlopig is de verwachting alleen om naar te kijken. ovenbird regelt op de gemeten buitentemperatuur; de verwachting is geen invoer van de regelaar.\n\n**Stooklijnwater** is alleen de stooklijn, vóór [[room-feedback|ruimtecorrectie]], grenzen en afronden, dus de echte aanvoertemperatuur kan een paar graden afwijken. ovenbird bewaart elke verwachting zoals ze is uitgegeven, zodat de kwaliteit eerlijk te beoordelen is voordat ze ooit meestuurt.',
    },
    {
      id: 'privacy',
      kind: 'do',
      title: 'De verwachting aan- of uitzetten',
      body: 'De verwachting is opt-in. Staat ze aan, dan gaat alleen je locatie, afgerond op ongeveer 1 km, één keer per uur naar de aanbieder (Open-Meteo). Staat ze uit, dan gaat er niets het huis uit.',
      steps: [
        'Open [Instellingen → Weer](#/settings/weather).',
        'Zet **Weersverwachting** aan of uit en kies de locatie.',
        'Kies **Bekijken en toepassen** en daarna **Toepassen**.',
      ],
    },
  ],
  questions: [
    {
      id: 'steps',
      q: 'Waarom loopt de gemeten temperatuur in trapjes?',
      a: 'De pomp meldt de buitentemperatuur in hele graden. Daarom vlakt ovenbird die af: anders zou elke sprong van een graad de aanvoertemperatuur laten bewegen.',
    },
    {
      id: 'filtered-lags',
      q: 'Waarom loopt de gefilterde lijn achter?',
      a: 'Het filter middelt bewust over een aantal uren. Een huis met veel massa reageert traag op het weer, dus de stooklijn hoort dat ook te doen. Een kort zonnetje of een koude windvlaag mag de watertemperatuur niet veranderen.',
    },
    {
      id: 'stale',
      q: 'Wat betekent "De verwachting is verouderd"?',
      a: 'Er kwam al meer dan 3 uur geen nieuwe verwachting binnen, bijvoorbeeld omdat internet weg was. De verwarming werkt gewoon door, want de regeling gebruikt de gemeten buitentemperatuur.',
    },
    {
      id: 'curve-differs',
      q: 'Stooklijnwater zegt 33 °C, maar de aanvoertemperatuur is 31 °C. Wie heeft gelijk?',
      a: 'Allebei. Stooklijnwater is alleen het startpunt. De pagina [Aanvoer](#/setpoint) toont de correcties daarop, zoals de ruimtecorrectie als de kamer al warm genoeg is.',
    },
  ],
  related: ['settings/weather', 'settings/curve', 'setpoint', 'home'],
};
