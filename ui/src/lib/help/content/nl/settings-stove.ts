import type { HelpTopic } from '$lib/help/types';

export const topic: HelpTopic = {
  id: 'settings/stove',
  title: 'Houtkachel',
  lead: 'Verwarmt een houtkachel de kamer met de sensor, dan schakelt ovenbird de verwarming terug in plaats van het hele huis af te koelen, en blijven de andere kamers warm.',
  art: 'settings',
  sections: [
    {
      id: 'what',
      kind: 'know',
      title: 'Waar het voor is',
      body: 'Een kachel in de kamer met je [[room-sensor|kamersensor]] maakt die kamer veel warmer dan de rest. De [[room-feedback|ruimtecorrectie]] zou dan de watertemperatuur voor alle kamers verlagen, en de hal en slaapkamers koelen af.\n\n[[wood-stove|Houtkachelmodus]] verlaagt in plaats daarvan de [[heating-curve|stooklijn]] met **Terugschakelen**, standaard 3 K, of met **Terug tot het minimum** helemaal tot het veiligheidsminimum. De ruimtecorrectie pauzeert en bewaart wat ze geleerd heeft. De pomp stopt nooit.',
    },
    {
      id: 'status',
      kind: 'see',
      title: 'Status',
      body: 'De labels laten zien of de houtkachelmodus nu aan staat, hoeveel er wordt teruggeschakeld, en de start- en stopdrempel als kamertemperatuur, uitgerekend vanaf je comforttemperatuur.\n\nWacht de automatische herkenning, dan zegt een regel waarom (zie **Als de herkenning wacht**).',
      target: 'settings/stove.status',
    },
    {
      id: 'detect',
      kind: 'know',
      title: 'Automatisch herkennen',
      body: 'Met **Kachel automatisch herkennen** aan start de houtkachelmodus als de kamer de comforttemperatuur plus **Starten boven comfort** (1,5 K) haalt. Met **Ook starten bij snelle stijging** start hij eerder als de kamer binnen de **Periode snelle stijging** (30 min) **Snelle stijging** (1 K) oploopt terwijl hij al boven comfort zit.\n\nAlleen een kamerwaarde die ovenbird volledig vertrouwt telt: vers, niet tegengesproken door een controlesensor en niet lang onveranderd.',
    },
    {
      id: 'exit',
      kind: 'know',
      title: 'Wanneer hij stopt',
      body: 'Hij stopt als de kamer onder de startdrempel min **Zoveel lager stoppen** (1 K) zakt, maar niet voordat de **Kortste periode** (60 min) voorbij is. Hij stopt uiterlijk na de **Langste periode** (8 uur), en meteen als de kamerwaarde niet meer te vertrouwen is.\n\nMet de hand gestart stopt hij op het gekozen moment; is de kamer dan nog warm, dan neemt de automatische herkenning het over.',
    },
    {
      id: 'settings',
      kind: 'do',
      title: 'De instellingen',
      body: 'Zet eerst **Houtkachelmodus** aan; zonder dat verandert er niets en verschijnt **Kachel aan…** niet. De andere velden stellen de drempels hierboven in.\n\n**Referentieruimte** is optioneel: een sensor in een andere ruimte, zoals de hal. Zakt die onder **Referentieruimte minstens**, dan wordt het terugschakelen kleiner, tot niets bij **Referentieband** daaronder. Zo betaalt de hal niet voor een warme woonkamer.',
      target: 'settings/stove.settings',
    },
    {
      id: 'manual',
      kind: 'do',
      title: 'Met de hand starten en stoppen',
      body: 'Kachel aangestoken? Tik op **Kachel aan…** op de kamerkaart van Thuis of in het modusvenster en kies 2, 4 of 8 uur. Zolang de houtkachelmodus aan staat, zegt een balk op [Thuis](#/home) dat, met **Stoppen**.\n\nNa **Stoppen** wacht de automatische herkenning tot de kamer onder de stopdrempel is afgekoeld, zodat hij niet meteen weer start.',
    },
    {
      id: 'waiting',
      kind: 'know',
      title: 'Als de herkenning wacht',
      body: '- Na de **Langste periode**: een warme kamer alleen start pas een nieuwe periode als de kamer één keer onder de stopdrempel is geweest; een snelle stijging telt wel.\n- Na een onbetrouwbare kamerwaarde: die moet eerst weer **Wachten na onbetrouwbare kamerwaarde** (15 min) te vertrouwen zijn.\n- Na **Stoppen**: tot de kamer onder de stopdrempel is afgekoeld.\n\nMet de hand starten kan altijd.',
    },
  ],
  questions: [
    {
      id: 'pump-off',
      q: 'Zet ovenbird de pomp uit als de kachel brandt?',
      a: 'Nee. De pomp blijft draaien op een lagere watertemperatuur, dus de andere kamers krijgen warmte. Ontdooien, warm water, de zachte start en de veiligheidsgrenzen werken zoals altijd.',
      without: {
        hotWater: {
          a: 'Nee. De pomp blijft draaien op een lagere watertemperatuur, dus de andere kamers krijgen warmte. Ontdooien, de zachte start en de veiligheidsgrenzen werken zoals altijd.',
        },
      },
    },
    {
      id: 'cold-hall',
      q: 'De hal koelt af als de kachel brandt. Wat kan ik doen?',
      a: 'Kies de sensor in de hal als **Referentieruimte** en zet **Referentieruimte minstens** op de laagste temperatuur die je daar accepteert. Of maak **Terugschakelen** kleiner.',
    },
    {
      id: 'implausible',
      q: 'Waarom komt er geen alarm "kamerwaarde onwaarschijnlijk" als de kachel brandt?',
      a: 'De vergelijking met een tweede sensor staat in houtkachelmodus stil, omdat de kachelkamer dan juist warmer hoort te zijn. Daarna gaat ze weer verder.',
    },
    {
      id: 'after',
      q: 'Wat gebeurt er als het vuur uit is?',
      a: 'Zodra de kamer onder de stopdrempel is afgekoeld, gaat de ruimtecorrectie verder met de waarde van voor het vuur, niet met een waarde die door de hete kamer is weggezakt. De stooklijn is weer gewoon.',
    },
  ],
  related: ['home', 'settings/room', 'setpoint'],
  aliases: ['kachel', 'houtkachel', 'open haard', 'stove'],
};
