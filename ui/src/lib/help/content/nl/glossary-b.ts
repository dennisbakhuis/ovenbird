import type { GlossaryEntry } from '$lib/help/types';

export const glossary: GlossaryEntry[] = [
  {
    id: 'room-feedback',
    term: 'Ruimtecorrectie',
    short:
      'Hoe ovenbird de watertemperatuur bijstuurt als de kamer warmer of kouder is dan je comfortdoel.',
    body: 'Te koud: er komt iets bij de stooklijn bij; te warm: er gaat iets af, binnen een grens (standaard 3 K). Eén deel reageert meteen; een ander deel, de integrator, bouwt zich in de loop van uren op om een blijvend verschil weg te werken. Zonder betrouwbare kamerwaarde pauzeert de correctie, en een correctie die verwarmt zwakt in 24 uur af. De instellingen horen bij [Comforttemperatuur](#/settings/room). Node-RED noemt het RTC.',
    related: ['comfort-band', 'room-sensor', 'heating-curve'],
    aliases: ['RTC', 'kamercorrectie', 'ruimtetemperatuurcorrectie'],
  },
  {
    id: 'comfort-band',
    term: 'Comfortband',
    short:
      'Het gebied rond je comfortdoel waarin de kamer als comfortabel telt: een halve graad naar beide kanten.',
    body: 'Getekend als het groene deel van de kamerbalk. De ruimtecorrectie mikt nog steeds op het doel zelf.',
    related: ['room-feedback'],
  },
  {
    id: 'room-sensor',
    term: 'Kamersensor',
    short: 'De thermometer die ovenbird vertelt hoe warm de kamer is.',
    body: 'Een **periodieke** sensor meldt volgens een schema. Een sensor die **bij verandering** meldt, laat alleen iets horen als de waarde verschuift; ovenbird houdt de laatste waarde dan vast zolang het apparaat andere tekenen van leven geeft, zoals zijn luchtvochtigheid. Een vastgehouden waarde kan tegen een tweede sensor worden gecontroleerd en verliest langzaam haar invloed om het water te laten afkoelen, dus een kapotte sensor kan het huis niet koud laten.',
    related: ['room-feedback', 'stale', 'signal'],
  },
  {
    id: 'stale',
    term: 'Verouderd',
    short: 'Een waarde die te oud is om te vertrouwen. ovenbird regelt niet op verouderde waarden.',
    body: 'Elk signaal heeft een maximale leeftijd. Voor de kamersensor hangt die af van het type: een paar meldintervallen bij een periodieke sensor, de stiltegrens bij een sensor die bij verandering meldt.',
    related: ['signal', 'room-sensor'],
  },
  {
    id: 'hold',
    term: 'Blokkade',
    short:
      'Een periode waarin ovenbird wacht: hij stuurt geen opdrachten naar de pomp, maar blijft wel beslissen.',
    body: 'Ze begint als iemand anders een pompinstelling wijzigt of een opdracht niet wordt bevestigd. De pomp houdt intussen haar eigen waarde. Standaard duurt de eerste 1 uur en de tweede 4 uur; bij de derde binnen 12 uur wacht ovenbird tot een beheerder haar opheft. Op het scherm staat "ovenbird wacht tot 18:25". Zie [Blokkades](#/activity/holds).',
    related: ['foreign-writer', 'alarm'],
    aliases: ['wachten', 'hold'],
  },
  {
    id: 'foreign-writer',
    term: 'Vreemde schrijver',
    short:
      'Alles behalve ovenbird dat een pompinstelling verandert: de afstandsbediening van Panasonic, Node-RED of een andere app.',
    body: 'ovenbird merkt het doordat de pomp een andere waarde meldt dan hij stuurde. Hij geeft een alarm en wacht, in plaats van om de pomp te vechten. In Schaduw wordt een andere regelaar verwacht, dus dan meldt hij niets.',
    related: ['hold'],
  },
  {
    id: 'wood-stove',
    term: 'Houtkachelmodus',
    short:
      'Terwijl een houtkachel de kamer met de sensor verwarmt, verlaagt ovenbird de stooklijn met een vaste stap in plaats van het hele huis af te koelen.',
    body: 'Hij start vanzelf als de kamer 1,5 K boven de comforttemperatuur komt of snel opwarmt, of met de hand met **Kachel aan…** op Thuis. De ruimtecorrectie pauzeert en bewaart haar waarde; de pomp blijft draaien, dus de andere kamers blijven warm. Hij stopt als de kamer weer is afgekoeld, uiterlijk na 8 uur. Zie [Houtkachel](#/settings/stove).',
    related: ['room-feedback', 'heating-curve', 'room-sensor'],
    aliases: ['kachel', 'houtkachel', 'open haard', 'haard', 'stove'],
  },
  {
    id: 'auto-mode',
    term: 'Automatisch',
    short:
      'De modus waarin ovenbird de pomp uitleest, elke minuut beslist en de aanvoertemperatuur stuurt.',
    body: 'Alleen mogelijk als de installatie het toestaat. **Pauzeren** op [Systeem](#/system) stopt het sturen tot je hervat.',
    related: ['shadow', 'decision'],
  },
  {
    id: 'shadow',
    term: 'Schaduw',
    short: 'ovenbird leest en beslist elke minuut, maar stuurt nooit iets naar de pomp.',
    body: 'Gebruikt om ovenbird te volgen voordat hij het overneemt, als hij gepauzeerd is, en nadat de opgeslagen instellingen kwijtraakten. De pomp verwarmt verder op zijn eigen instellingen.',
    related: ['auto-mode', 'decision'],
    aliases: ['shadow', 'schaduwmodus', 'meekijken'],
  },
  {
    id: 'envelope',
    term: 'Veiligheidsband',
    short:
      'Een band rond de stooklijn van de voorinstelling waarbinnen elke stooklijn en elke aanvoertemperatuur moet blijven.',
    body: 'Standaard 6 K onder en 5 K boven de stooklijn van de voorinstelling, samen met de minimale en maximale watertemperatuur. ovenbird houdt elke aanvoertemperatuur erbinnen, en de stooklijneditor tekent de band in groen. Een bijpassende regel op HeishaMon zelf, die de pomp binnen de band houdt als ovenbird uitvalt, is gepland maar zit niet in deze versie: stopt ovenbird, dan houdt de pomp de laatste aanvoertemperatuur die ze kreeg.',
    related: ['emitter', 'heating-curve', 'setpoint'],
    aliases: ['fallback', 'terugval', 'veiligheid'],
  },
  {
    id: 'emitter',
    term: 'Afgifte',
    short: 'Hoe de warmte uit het water je kamers in gaat: vloerverwarming, radiatoren of allebei.',
    body: 'De keuze bepaalt de stooklijn van de voorinstelling, de veiligheidsgrenzen en de afstelling. Zie [Afgifte](#/settings/emitter).',
    related: ['preset', 'envelope'],
  },
  {
    id: 'preset',
    term: 'Voorinstelling',
    short: 'De beginwaarden die bij een soort afgifte horen.',
    body: 'Een instelling die je niet hebt veranderd volgt de voorinstelling, en verschuift mee als je van afgifte wisselt. Een waarde die je zelf instelde blijft staan.',
    related: ['emitter'],
  },
  {
    id: 'config-version',
    term: 'Configuratieversie',
    short:
      'Het nummer van een bewaarde set instellingen. Elke keer toepassen of terugdraaien maakt een nieuwe.',
    body: 'Het modusvenster achter de modusknop toont de versie in gebruik, bijvoorbeeld Instellingen v12. [Versies en back-up](#/settings/versions) zet ze allemaal op een rij.',
    related: ['draft', 'audit'],
  },
  {
    id: 'control-state',
    term: 'Wie stuurt de pomp',
    short:
      'Eén zin in de statusbalk: ovenbird stuurt de pomp aan, kijkt alleen mee, wacht, is gepauzeerd, mag niet sturen of staat uit.',
    body: 'De zin volgt wat ovenbird echt doet, niet alleen de modus: op Automatisch tijdens een [[hold|blokkade]] staat er "ovenbird wacht". Zolang ovenbird niet stuurt, toont een regel onder de statusbalk **zou sturen** (de waarde van ovenbird) naast **pomp heeft** (waar de pomp op draait). De modusknop is alleen groen als ovenbird stuurt.',
    related: ['auto-mode', 'shadow', 'hold'],
  },
  {
    id: 'cooling-authority',
    term: 'Vertrouwen in de kamerwaarde',
    short:
      'Hoeveel ovenbird de kamerwaarde nog de watertemperatuur laat verlagen, van 100 % tot 0 %. Technische naam: koelzeggenschap.',
    body: 'Een sensor die alleen bij verandering meldt, kan lang dezelfde waarde houden. Hoe langer ze niet verandert, hoe minder ovenbird haar vertrouwt om het huis af te koelen; bij 0 % negeert hij haar daarvoor. Een kamerwaarde waar de controlesensor het niet mee eens is, wordt helemaal niet vertrouwd.',
    related: ['room-sensor', 'room-feedback'],
  },
  {
    id: 'simulation',
    term: 'Simulatie',
    short:
      'Een installatie die tegen een gesimuleerde warmtepomp draait, vaak met een snellere klok. De bovenbalk toont SIMULATIE.',
    body: 'Er gaat niets naar een echte pomp. Wijkt de klok van de service meer dan 5 minuten af van je apparaat, dan staan de datum en tijd van de service onder de statusbalk, zodat de tijden op de pagina kloppen.',
    related: ['heishamon'],
  },
  {
    id: 'draft',
    term: 'Concept',
    short:
      'Je niet-opgeslagen wijzigingen aan de instellingen. Ze blijven in deze browser tot je ze toepast of weggooit.',
    related: ['preview', 'config-version'],
  },
  {
    id: 'preview',
    term: 'Doorrekenen',
    short:
      'De controle voor het toepassen: het effect op dit moment, en een terugblik op de afgelopen 24 uur met jouw instellingen.',
    body: 'De terugblik geeft de vastgelegde gegevens met jouw instellingen aan de regelaar. Het is een open lus: het huis deed wat het deed onder de oude instellingen, dus de terugblik laat zien hoe de aanvoertemperatuur was afgeweken, niet hoe warm het was geweest. Eerst speelt een controle de vastgelegde beslissingen na; lukt dat niet, dan is de uitkomst alleen een indicatie.',
    related: ['draft', 'decision'],
  },
  {
    id: 'audit',
    term: 'Logboek',
    short:
      'Het overzicht van wie wat deed: instellingen toegepast, pauzes, opgeheven blokkades, pompinstellingen en geweigerde verzoeken.',
    body: 'Er komen alleen regels bij; ze veranderen nooit. Zie [Logboek](#/activity/audit).',
    related: ['config-version'],
  },
  {
    id: 'alarm',
    term: 'Alarm',
    short: 'Een melding van de controles van ovenbird dat er iets mis of ongewoon is.',
    body: 'Drie niveaus: **kritiek** (een veiligheidsgrens; ovenbird laat de watertemperatuur dan alleen nog dalen), **waarschuwing** (even naar kijken) en **info**. Een alarm verdwijnt vanzelf als de oorzaak weg is. Zie [Activiteit](#/activity). ovenbird stuurt nog geen meldingen: alarmen zie je alleen in de app.',
    related: ['hold'],
    aliases: ['storing', 'melding', 'notificatie', 'foutmelding', 'fout'],
  },
  {
    id: 'signal',
    term: 'Signaal',
    short:
      'Eén live waarde die ovenbird binnenkrijgt, zoals de buitentemperatuur of de luchtvochtigheid in de kamer, met haar leeftijd.',
    body: 'Alle signalen staan bij [Signalen](#/system/signals).',
    related: ['stale', 'heishamon'],
  },
  {
    id: 'heishamon',
    term: 'HeishaMon',
    short:
      'Het kleine printje op de Panasonic-warmtepomp dat zijn waarden doorgeeft en opdrachten doorzet, via MQTT.',
    related: ['mqtt', 'signal'],
  },
  {
    id: 'mqtt',
    term: 'MQTT',
    short:
      'Het berichtensysteem waarmee HeishaMon en ovenbird waarden en opdrachten uitwisselen, via een broker.',
    related: ['heishamon'],
  },
  {
    id: 'ha-link',
    term: 'Koppeling met Home Assistant',
    short:
      'De verbinding van ovenbird met Home Assistant, alleen om te lezen: voor de kamersensor en andere waarden.',
    body: 'Ligt ze 5 minuten plat, dan komt er een alarm en worden kamerwaarden uit Home Assistant korter vertrouwd.',
    related: ['room-sensor', 'signal'],
  },
  {
    id: 'decision',
    term: 'Beslissing',
    short:
      'Wat ovenbird elke minuut uitrekent: de aanvoertemperatuur, de delen waaruit die bestaat, en waarom.',
    body: 'Elke beslissing wordt bewaard met haar invoer, zodat [Aanvoer](#/setpoint) kan laten zien waarom de temperatuur is wat ze is.',
    related: ['setpoint', 'auto-mode', 'shadow'],
  },
  {
    id: 'divergence',
    term: 'Afwijking',
    short:
      'Het verschil tussen de watertemperatuur die ovenbird zou instellen en die waar de pomp echt op draait.',
    body: 'Zolang ovenbird alleen meekijkt naast een andere regeling, zoals Node-RED, vergelijkt hij die twee elke minuut. Een verschil van meer dan 1 K dat aanhoudt is een **episode**; bij elke episode zie je de reden van ovenbird, zodat je kunt beoordelen of hij verklaard is. Zie [Vergelijken](#/system/shadow).',
    related: ['shadow', 'release-control'],
    aliases: ['shadow', 'schaduw', 'divergence', 'vergelijking', 'baseline'],
  },
  {
    id: 'release-control',
    term: 'Regeling teruggeven',
    short:
      'De pomp teruggeven: ovenbird stopt, zet de pompinstellingen terug die hij bij de overstap aantrof en pauzeert.',
    body: 'Bij de overstap legt ovenbird de watertemperatuur, de pompsnelheid en het fluisterniveau van de pomp vast. Regeling teruggeven schrijft elke waarde terug die afwijkt, controleert ze en blijft daarna gepauzeerd, zodat een andere regeling het kan overnemen. Een **oefening** doet hetzelfde als proef. Het doel is binnen 5 minuten. Zie [Proef](#/system/trial).',
    related: ['divergence', 'shadow', 'auto-mode'],
    aliases: ['release control', 'terugzetten', 'rollback', 'teruggeven', 'fallback'],
  },
];
