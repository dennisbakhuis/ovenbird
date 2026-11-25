import type { GlossaryEntry } from '$lib/help/types';

export const glossary: GlossaryEntry[] = [
  {
    id: 'heating-curve',
    term: 'Stooklijn',
    short:
      'De regel die bij elke buitentemperatuur een watertemperatuur geeft: hoe kouder het buiten is, hoe warmer het water.',
    body: 'Ook wel weersafhankelijke regeling of WAR genoemd. Het is het startpunt van elke aanvoertemperatuur; ovenbird zet er correcties bovenop. Je past hem aan bij [Instellingen → Stooklijn](#/settings/curve), met 2 tot 6 punten. Daar kun je de weersafhankelijke regeling ook uitzetten; ovenbird gebruikt dan één vaste watertemperatuur. Ruimtecorrectie is een aparte schakelaar.',
    related: ['setpoint', 'filtered-outside', 'room-feedback'],
    aliases: ['WAR', 'weersafhankelijk', 'weersafhankelijke regeling', 'heating curve'],
  },
  {
    id: 'setpoint',
    term: 'Aanvoertemperatuur (setpoint)',
    short: 'De watertemperatuur die ovenbird aan de pomp vraagt, in hele graden.',
    body: 'Ook wel het waterdoel genoemd. ovenbird rekent hem elke minuut uit, uit de stooklijn plus correcties, en stuurt hem alleen als de wijziging de moeite waard is. De pomp beslist daarna zelf wanneer ze start en stopt om hem te halen.',
    related: ['heating-curve', 'dead-band', 'dwell', 'decision'],
  },
  {
    id: 'outlet',
    term: 'Aanvoer',
    short:
      'De temperatuur van het water dat de warmtepomp verlaat, op weg naar je vloer of radiatoren.',
    body: 'De pomp probeert de aanvoer op de ingestelde aanvoertemperatuur te brengen.',
    related: ['inlet', 'delta-t', 'setpoint'],
  },
  {
    id: 'inlet',
    term: 'Retour',
    short:
      'De temperatuur van het water dat terugkomt bij de warmtepomp, nadat het zijn warmte heeft afgegeven.',
    related: ['outlet', 'delta-t'],
  },
  {
    id: 'delta-t',
    term: 'Delta-T (ΔT)',
    short:
      'Het verschil tussen aanvoer en retour: hoeveel het water afkoelt op zijn weg door het huis.',
    body: 'In de doorstromingsmodus Delta-T past de pomp het debiet aan om dit verschil dicht bij de instelling **Delta-T bij verwarmen** (3–10 K) te houden. Een kleinere delta-T betekent meer debiet. Met de compressor uit is de ΔT bijna nul.',
    related: ['outlet', 'inlet', 'flow', 'flow-mode'],
  },
  {
    id: 'flow',
    term: 'Debiet',
    short: 'Hoeveel water er door de verwarming stroomt, in liter per minuut.',
    body: 'Te weinig debiet is een risico voor de warmtepomp. Daarom geeft ovenbird een alarm als het te laag wordt terwijl de compressor draait. Houd minstens één verwarmingsgroep altijd open.',
    related: ['delta-t', 'pump-duty'],
  },
  {
    id: 'cop',
    term: 'COP',
    short:
      'Geleverde warmte gedeeld door gebruikte stroom. Een COP van 4 betekent 4 kWh warmte voor 1 kWh stroom.',
    body: 'De COP is hoger als het buiten milder is en als het water niet zo warm hoeft. Ontdooien en korte runs drukken hem. ovenbird berekent hem uit de eigen schattingen van de pomp voor stroom en warmte, dus zie hem als een goede indicatie, niet als een meterstand.',
    related: ['defrost', 'short-cycling'],
  },
  {
    id: 'compressor',
    term: 'Compressor',
    short: 'Het hart van de warmtepomp: hij pompt warmte uit de buitenlucht naar het water.',
    body: 'Het toerental staat in Hz: hoger betekent meer warmte en meer stroom. Staat hij stil (0 Hz), dan staat de pomp stand-by.',
    related: ['short-cycling', 'cop'],
  },
  {
    id: 'defrost',
    term: 'Ontdooien',
    short:
      'Een paar minuten waarin de pomp ijs van haar buitenunit smelt, met warmte uit het water.',
    body: 'IJs ontstaat bij koud, vochtig weer. Tijdens het ontdooien koelt het water even af en stuurt de pomp haar circulatiepomp zelf aan. ovenbird zet dan de ruimtecorrectie stil en verlaagt de aanvoertemperatuur niet, zodat de dip geen overreactie geeft.',
    related: ['pump-duty', 'cop', 'dhw'],
  },
  {
    id: 'dhw',
    term: 'Warm water',
    feature: 'hotWater',
    short: 'De pomp verwarmt het boilervat voor warm tapwater in plaats van het huis.',
    body: 'Een driewegklep stuurt het warme water dan naar het vat. ovenbird regelt het warm tapwater nooit. Zolang een warmwaterrun duurt, behandelt ovenbird die als ontdooien: de ruimtecorrectie staat stil en de aanvoertemperatuur gaat niet omlaag.',
    related: ['defrost'],
  },
  {
    id: 'pump-duty',
    term: 'Pompvermogen',
    short:
      'De snelheid van de circulatiepomp die het water door de verwarming stuwt, als een getal van de pomp.',
    body: 'De instelling **Maximaal pompvermogen** begrenst het. ovenbird kan een maximum aanhouden terwijl de compressor draait en een lager maximum in rust, voor minder stroom en geluid (zie [Instellingen → Pomp](#/settings/pump-duty)). Tijdens ontdooien negeert de pomp het maximum, dus dan stuurt ovenbird niets.',
    related: ['flow', 'defrost'],
  },
  {
    id: 'quiet-mode',
    term: 'Stille modus',
    short:
      'Een stand van de pomp die compressor en ventilator afremt, zodat de buitenunit minder geluid maakt.',
    body: "Ook wel fluistermodus genoemd. Er zijn niveaus 1 tot 3; een hoger niveau is stiller maar geeft ook minder warmte. ovenbird kan hem op vaste tijden aanzetten, bijvoorbeeld 's nachts (zie [Instellingen → Stille modus](#/settings/quiet)). Het gaat om geluid, niet om nachtverlaging zoals NightReduction in Node-RED: die heeft ovenbird nog niet.",
    related: ['compressor'],
    aliases: ['NightReduction', 'nachtverlaging', 'fluistermodus'],
  },
  {
    id: 'heating-off-temperature',
    term: 'Verwarming uit boven buitentemperatuur',
    short:
      'Boven deze buitentemperatuur stopt de pomp zelf met verwarmen, wat ovenbird ook vraagt.',
    body: 'Een zomerschakelaar in de pomp, in te stellen van 10 tot 35 °C op de pagina [Pomp](#/pump). ovenbird toont een info-alarm zolang het buiten zo warm is. Te laag ingesteld blijft het huis op milde dagen misschien koud.',
    related: ['setpoint'],
  },
  {
    id: 'flow-mode',
    term: 'Doorstromingsmodus van de pomp',
    short:
      'Hoe de pomp haar debiet kiest: Delta-T houdt de ingestelde ΔT aan, Maximaal debiet pompt altijd zo hard als mag.',
    body: 'Delta-T is de gebruikelijke keuze. Sommige oudere pompmodellen negeren deze instelling.',
    related: ['delta-t', 'flow'],
  },
  {
    id: 'start-ramp',
    term: 'Zachte start',
    short:
      'Na een compressorstart houdt ovenbird de aanvoertemperatuur iets onder de stooklijn en laat hem langzaam oplopen.',
    body: 'Een pomp die start tegen een hoge aanvoertemperatuur draait hard, schiet door en stopt misschien snel weer. Een rustige start geeft langere, kalmere runs. Je zet hem uit bij [Instellingen → Gedrag](#/settings/behaviour).',
    related: ['short-cycling', 'setpoint'],
    aliases: ['SoftStart', 'soft start', 'softstart'],
  },
  {
    id: 'short-cycling',
    term: 'Pendelen',
    short: 'De compressor start en stopt vaak, met korte runs ertussen.',
    body: 'Elke start kost rendement en slijtage. De **Pendelbeveiliging** van ovenbird houdt de aanvoertemperatuur vroeg in een run hoog genoeg, zodat de pomp niet te snel haar eigen stoppunt bereikt. Minder, langere runs zijn beter.',
    related: ['compressor', 'start-ramp'],
  },
  {
    id: 'dead-band',
    term: 'Dode band',
    short:
      'De kleinste wijziging die de moeite waard is: de aanvoertemperatuur verandert pas als de berekende waarde minstens zoveel verschilt (1 K of meer).',
    body: 'Zo springt de aanvoertemperatuur niet heen en weer bij kleine veranderingen.',
    related: ['dwell', 'setpoint'],
  },
  {
    id: 'dwell',
    term: 'Wachttijd',
    short: 'De minimale tijd tussen twee wijzigingen van de aanvoertemperatuur.',
    body: 'Hij houdt de pomp rustig en beschermt het aantal schrijfacties per dag. Je stelt hem in bij [Instellingen → Gedrag](#/settings/behaviour); een wijziging die nodig is wacht tot de tijd voorbij is.',
    related: ['dead-band', 'setpoint'],
  },
  {
    id: 'filtered-outside',
    term: 'Gefilterde buitentemperatuur',
    short: 'De buitentemperatuur afgevlakt over een aantal uren. Dit is wat de stooklijn gebruikt.',
    body: 'De pomp meldt de buitentemperatuur in hele graden en die kan snel schommelen. Het huis reageert traag, dus ovenbird vlakt hem eerst af.',
    related: ['heating-curve'],
  },
  {
    id: 'forecast',
    term: 'Weersverwachting',
    short:
      'De verwachte buitentemperatuur, zon, bewolking en wind voor de komende dagen, van een online aanbieder.',
    body: 'Opt-in: alleen je locatie, afgerond op ongeveer 1 km, wordt verstuurd. Voorlopig is ze er om te bekijken; ovenbird stuurt er nog niet op.',
    related: ['lead-time', 'forecast-bias', 'mae'],
  },
  {
    id: 'lead-time',
    term: 'Voorspeltijd',
    short:
      'Hoe ver vooruit een verwachting is gemaakt. Een verwachting voor 18:00 die om 12:00 is uitgegeven heeft een voorspeltijd van 6 uur.',
    body: 'Verwachtingen worden minder nauwkeurig naarmate ze verder vooruit kijken, daarom wordt de fout per voorspeltijd beoordeeld.',
    related: ['forecast', 'mae'],
  },
  {
    id: 'forecast-bias',
    term: 'Afwijking (bias)',
    short:
      'De gemiddelde fout van de verwachting. Positief betekent gemiddeld te warm voorspeld, negatief te koud.',
    related: ['mae', 'lead-time'],
  },
  {
    id: 'mae',
    term: 'MAE',
    short:
      'Gemiddelde absolute fout: hoeveel de verwachting er meestal naast zat, te warm of te koud.',
    body: 'Een MAE van 1,4 K betekent dat de verwachting meestal 1,4 graad afweek.',
    related: ['forecast-bias', 'lead-time'],
  },
  {
    id: 'degree-hours',
    term: 'Graaduren',
    short:
      'Hoe ver en hoe lang de kamer onder de comfortband zat: 2 uur lang 1 K te koud is 2 graaduur.',
    body: 'Nul betekent dat de kamer de hele dag comfortabel bleef.',
    related: ['comfort-band'],
  },
  {
    id: 'ua',
    term: 'Warmteverlies (UA)',
    short:
      'Hoeveel watt het huis verliest voor elke graad dat het binnen warmer is dan buiten, in W/K.',
    body: 'Een huis met een UA van 300 W/K verliest bij 20 °C binnen en 0 °C buiten ongeveer 6 kW. ovenbird leert het uit je eigen geschiedenis; met één kamersensor is het een **schijnbaar** getal: ventilatie en de andere kamers zitten er ook in. Je ziet het met een bereik: de echte waarde ligt daar met 90 % zekerheid in. Gedeeld door het vloeroppervlak geeft het de [indicatieve isolatiescore](#/house).',
    related: ['balance-temperature', 'time-constant', 'energy-signature'],
    aliases: ['UA', 'warmteverliescoëfficiënt', 'HLC', 'isolatie', 'heat loss'],
  },
  {
    id: 'balance-temperature',
    term: 'Stookgrens',
    short:
      'De buitentemperatuur waarboven het huis geen verwarming nodig heeft: zon, mensen en apparaten houden het warm.',
    body: 'Daaronder groeit de warmte die de pomp moet leveren met elke graad dat het kouder wordt. ovenbird leest hem af uit de [[energy-signature]]: waar de lijn door de dagpunten op nul warmte uitkomt.',
    related: ['energy-signature', 'ua'],
    aliases: ['balanstemperatuur', 'balance temperature', 'basistemperatuur'],
  },
  {
    id: 'time-constant',
    term: 'Tijdconstante',
    short:
      'Hoe langzaam het huis afkoelt: de uren waarin het zonder verwarming ongeveer twee derde van een temperatuurverschil verliest.',
    body: 'Een zwaar, goed geïsoleerd huis heeft een lange tijdconstante (vaak 100 uur of meer): een nacht zonder verwarming kost weinig. Een licht huis koelt snel af. Daarom kan ovenbird de watertemperatuur een tijdje verlagen zonder dat de kamer het meteen merkt.',
    related: ['ua'],
    aliases: ['tau', 'thermische massa', 'time constant'],
  },
  {
    id: 'energy-signature',
    term: 'Energiesignatuur',
    short:
      'Een grafiek van de warmte die het huis per dag nodig had, tegen de buitentemperatuur van die dag.',
    body: 'Hoe kouder de dag, hoe meer warmte. De helling van de lijn door de punten is het [[ua|warmteverlies]]; waar hij op nul uitkomt ligt de [[balance-temperature]]. Zonnige dagen liggen onder de lijn. Dagen met de houtkachel tellen niet mee.',
    related: ['ua', 'balance-temperature'],
    aliases: ['energy signature', 'warmtesignatuur'],
  },
];
