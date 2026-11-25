import type { HelpTopic } from '$lib/help/types';

export const topic: HelpTopic = {
  id: 'settings/quiet',
  title: 'Stille modus',
  lead: 'Plan wanneer de buitenunit in stille modus draait, bijvoorbeeld ’s nachts. Stiller betekent ook minder verwarmingsvermogen zolang het tijdvak duurt.',
  art: 'settings',
  sections: [
    {
      id: 'windows',
      kind: 'do',
      title: 'Tijdvakken stille modus',
      body: 'De balk toont de dag van 0 tot 24 uur met je tijdvakken in kleur. Elk tijdvak heeft een begin, een eind en een niveau van 1 tot 3; een hoger niveau is stiller. Een tijdvak dat eindigt voordat het begint, loopt door na middernacht, zoals 22:00 tot 07:00.',
      steps: [
        '**Tijdvak toevoegen** voegt een regel toe, tot vier stuks.',
        '**Van**, **Tot** en **Niveau** stellen hem in.',
        'Het kruisje verwijdert een tijdvak.',
      ],
      target: 'settings/quiet.windows',
    },
    {
      id: 'timezone',
      kind: 'do',
      title: 'Tijdzone',
      body: 'De tijden van de tijdvakken gelden in deze tijdzone. Kies de jouwe uit de lijst, bijvoorbeeld Europe/Amsterdam, zodat 22:00 ook 22:00 op jouw klok is. Onder de balk zie je hoe laat het daar nu is, zoals "Nu 18:27 in Europe/Amsterdam".\n\nWijkt de zone af van die van je browser, dan zegt een waarschuwing dat, met een knop **Gebruik** en de zone van je browser om daarop over te stappen.',
      target: 'settings/quiet.timezone',
    },
    {
      id: 'cost',
      kind: 'know',
      title: 'Wat stille modus kost',
      body: '[[quiet-mode|Stille modus]] begrenst de buitenunit zodat die minder geluid maakt. Op een koude nacht levert de pomp dan misschien minder warmte dan de stooklijn vraagt, en kan het huis iets afkoelen. Kies het laagste niveau dat stil genoeg is.',
    },
    {
      id: 'who',
      kind: 'know',
      title: 'Wie de stille modus instelt',
      body: 'Met minstens één tijdvak stelt ovenbird de stille modus op de pomp in: het niveau van het tijdvak binnen een tijdvak, uit daarbuiten. Verander je hem dan op de afstandsbediening van Panasonic, dan kan dat tellen als [[foreign-writer|vreemde schrijver]] en een blokkade starten.\n\nZonder tijdvakken komt ovenbird niet aan de stille modus.',
    },
  ],
  questions: [
    {
      id: 'loud',
      q: 'Waarom is de pomp niet stil tijdens een tijdvak?',
      a: 'Kijk eerst naar de tijdzone. Stille modus maakt de unit zachter, niet geluidloos; niveau 3 is het stilst. Het signaal **Stille modus** bij [Signalen](#/system/signals) toont wat de pomp meldt.',
    },
    {
      id: 'stop',
      q: 'Hoe stop ik het schema?',
      a: 'Verwijder alle tijdvakken en pas toe. Doe dat buiten een tijdvak, als ovenbird de stille modus al heeft uitgezet: daarna stelt hij de stille modus helemaal niet meer in.',
    },
  ],
  related: ['pump', 'settings/behaviour'],
};
