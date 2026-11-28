import type { house as en } from '$lib/i18n/en/house';

export const house: Record<keyof typeof en, string> = {
  section_house: 'Huis',
  houseTitle: 'Huis',
  navHouse: 'Huis',
  houseLead: 'Hoeveel warmte het huis verliest en hoeveel warmte de warmtepomp erin brengt.',
  houseLoading: 'De huisgegevens worden geladen.',
  houseMissing: 'Deze ovenbird-service is te oud voor de huisgegevens.',
  houseErrorTitle: 'De huisgegevens konden niet worden geladen',
  houseErrorText: 'ovenbird kon de service niet bereiken. Elke minuut volgt een nieuwe poging.',
  houseRetry: 'Opnieuw proberen',
  houseDisabledTitle: 'Huisgegevens staan uit',
  houseDisabledText:
    'De schatting van het warmteverlies staat uit, dus ovenbird rekent haar niet uit.',
  houseDisabledLink: 'Zet de schatting aan in Instellingen',
  houseStatusProvisional: 'voorlopig',
  houseCollectingTitle: 'Warmteverlies: nog aan het verzamelen',
  houseCollectingText:
    'ovenbird heeft {need} stookdagen met een kamertemperatuur nodig voordat hij het warmteverlies kan berekenen.',
  houseCollectingProgress: '{n} van de {need} bruikbare dagen',
  houseLossReason_no_room_signal:
    'Er is geen kamertemperatuur ingesteld, dus ovenbird ziet niet hoe warm het in huis is.',
  houseLossReason_too_few_days: 'Nog te weinig bruikbare dagen.',
  houseLossReason_span_too_small:
    'De dagen tot nu toe waren allemaal ongeveer even koud, dus er is nog geen lijn te trekken.',
  houseLossReason_slope_not_positive:
    'Koudere dagen vroegen tot nu toe niet meer warmte, dus de uitkomst is nog niet bruikbaar.',
  houseLossReason_slope_implausible:
    'De uitkomst was niet geloofwaardig (boven 2000 W/K) en wordt daarom niet getoond.',
  houseLossReason_too_uncertain: 'De uitkomst is te onzeker om te tonen.',
  houseLossReason_few_days: 'Tot nu toe minder dan 30 dagen.',
  houseLossReason_narrow_span: 'De gebruikte dagen beslaan een klein temperatuurbereik.',
  houseExcludedTitle: 'Tot nu toe overgeslagen dagen',
  houseExcluded_low_coverage: 'Te weinig gegevens: {n}',
  houseExcluded_stove: 'Houtkachel aan: {n}',
  houseExcluded_no_heating: 'Nauwelijks verwarmd: {n}',
  houseExcludedNone: 'Geen',
  houseLossTitle: 'Warmteverlies nu',
  houseLossBasis: 'Bij {outside} buiten en {room} in de kamer.',
  houseLossBasisTarget: 'Bij {outside} buiten en het kamerdoel van {room}.',
  houseLossBand: 'waarschijnlijk {low} tot {high} kW',
  houseLossNoNow: 'Nog geen buitentemperatuur, dus nu geen waarde.',
  houseLossNight: 'Komende nacht, {outside}',
  houseLossNightMissing: 'Komende nacht: geen voorspelling beschikbaar',
  houseLossDesign: 'Ontwerpdag, {outside}',
  houseLossBeyond: 'doorgetrokken',
  houseLossBeyondHint:
    'Kouder dan elke gemeten dag: de lijn is doorgetrokken, dus dit is minder zeker.',
  houseHeatTitle: 'Warmte van de warmtepomp',
  houseHeatNow: 'Nu geleverd',
  houseHeatMean24: 'Gemiddeld over 24 uur',
  houseHeatHotWater: 'warm water bezig',
  houseHeatUnknown: 'onbekend',
  houseHeatCoverage: 'Gegevens over {p} % van het etmaal',
  houseSliderLabel: 'Aanvoertemperatuur',
  houseSliderValue: '{supply} aanvoer, gemiddeld {mean} in de kring',
  houseHeatIntoHouse: 'Warmte het huis in',
  houseHeatLossNow: 'Warmteverlies nu',
  houseHeatBand: 'waarschijnlijk {low} tot {high} kW',
  houseSurplus: 'Overschot van {kw} kW: er komt meer warmte binnen dan het huis verliest.',
  houseShortfall:
    'Tekort van {kw} kW: er komt minder warmte binnen dan het huis verliest, dus de kamer koelt langzaam af.',
  houseBalancedNow: 'In evenwicht: er komt net zoveel warmte binnen als er verloren gaat.',
  houseNoLossToCompare: 'Nog geen warmteverlies, dus er is niets om mee te vergelijken.',
  houseBalanceAt:
    'Het huis is in evenwicht bij ongeveer {supply} aanvoer (gemiddeld {mean} in de kring).',
  houseBalanceOutOfRange:
    'Het huis zou in evenwicht zijn bij {supply}, buiten wat de pomp toestaat ({min} tot {max}).',
  houseBalanceNone:
    'Geen evenwichtstemperatuur: het huis heeft nu geen warmte nodig, of de gegevens zijn nog niet klaar.',
  houseSteadyNote:
    'Dit is een schatting voor de eindsituatie: waar het huis bij die aanvoertemperatuur op uitkomt. Vloerverwarming heeft daar uren voor nodig.',
  houseEmitterCollecting:
    'Hoeveel warmte de pomp bij elke aanvoertemperatuur geeft, is nog niet bekend.',
  houseEmitterReason_no_room_signal: 'Er is geen kamertemperatuur ingesteld.',
  houseEmitterReason_too_few_hours: 'Tot nu toe te weinig uren met draaiende compressor.',
  houseEmitterReason_slope_not_positive: 'Warmer water gaf tot nu toe niet meer warmte.',
  houseEmitterReason_slope_implausible:
    'De uitkomst was niet geloofwaardig en wordt daarom niet getoond.',
  houseEmitterReason_too_uncertain: 'De uitkomst is te onzeker om te tonen.',
  houseEmitterReason_few_hours: 'Tot nu toe minder dan 100 draaiuren of 7 dagen.',
  houseEmitterReason_narrow_span:
    'De tot nu toe geziene watertemperaturen beslaan een klein bereik.',
  houseFitTitle: 'Hoe het warmteverlies is gemeten',
  houseFitIntro:
    'Elk punt is het gemiddelde van twee dagen: de warmte van de warmtepomp tegenover hoeveel warmer de kamer was dan buiten.',
  houseFitH: 'Warmteverlies',
  houseFitBalance: 'Evenwichtstemperatuur',
  houseFitBalanceHint: 'Boven deze buitentemperatuur heeft het huis geen verwarming nodig.',
  houseFitDays: 'Gebruikte dagen',
  houseFitExcluded: 'Overgeslagen dagen',
  houseFitLimits:
    'De zon is niet meegerekend, dus de waarde valt in de herfst te hoog uit en in een zonnige, koude winter te laag. Ze beschrijft het huis zoals de kamersensor het ziet.',
  houseFitX: 'Kamer min buiten (K)',
  houseFitY: 'Warmte (kW)',
  houseFitLine: 'Berekende lijn',
  houseMarkUsed: 'Gebruikt',
  houseMarkOutlier: 'Uitschieter, niet gebruikt',
  houseMarkNear: 'Bijna evenwicht, niet gebruikt',
  houseFitPoint: '{first} tot {last}: {kw} kW bij {dt} K',
  houseWeatherTitle: 'Warmteproductie per buitentemperatuur',
  houseWeatherHeat: 'Warmte (kW)',
  houseWeatherElectric: 'Elektriciteit (kW)',
  houseWeatherCop: 'COP',
  houseWeatherNote:
    'Per klasse van 2 K van de gemiddelde etmaaltemperatuur buiten; op de as staat de ondergrens. Lichtere balken zijn gebaseerd op minder dan 3 dagen. Deze COP is de warmte die in de kring is gemeten, gedeeld door het eigen stroomverbruik van de pomp en kan daarom afwijken van de COP elders.',
  houseWeatherBin: '{from} tot {to} °C, {days} dagen',
  houseWeatherBinFew: '{from} tot {to} °C, slechts {days} dagen',
  houseWeatherEmpty: 'Nog geen volledige dagen om te tonen.',
  houseFactsInputTitle: 'Wat je van het huis weet',
  houseFactsInputSubtitle:
    'Beginpunten voor de schatting van het warmteverlies. Alles is optioneel.',
  houseFactsSet: '{n} ingevuld',
  houseFactsInputIntro:
    'Vul in wat je weet: het is het beginpunt voor de schatting. Laat leeg wat je niet weet.',
  houseFieldsToggle: 'Instellingen tonen',
  houseSectionText: 'Dezelfde gegevens staan op de pagina Huis.',
  houseSectionLink: 'Open de pagina Huis',
  moreHouseAbout: 'Wat je van het huis weet en de schatting van het warmteverlies',
  weekHouseLink: 'Je huis',
};
