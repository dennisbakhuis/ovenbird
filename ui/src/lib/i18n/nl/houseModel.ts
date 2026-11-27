export const houseModel = {
  'houseTab_what-if': 'Wat als',
  houseAnd: 'en',

  houseSchemTitle: 'Het huis op dit moment',
  houseSrcModel: 'Geleerd uit metingen',
  houseSrcEstimate: 'Schatting uit je antwoorden, niet gemeten',
  houseSrcLearning: 'Nog aan het leren',
  houseSchemAsOf: 'Stand: {time}',
  houseError_house_model_missing:
    'Vul een paar gegevens over het huis in, dan laat dit plaatje zien waar de warmte heen gaat.',
  houseError_house_series_missing:
    'Nog geen voorspelling van de kamer: het model heeft de kamer nog niet voorspeld.',
  houseNote_dhw_active: 'De warmtepomp maakt nu warm water; dat vermogen gaat niet naar het huis.',
  busy_houseNote_dhw_active:
    'De warmtepomp is nu met iets anders bezig; dat vermogen gaat niet naar het huis.',
  houseNote_defrost:
    'De warmtepomp is nu aan het ontdooien; zijn vermogen gaat nu niet naar het huis.',
  houseNote_room_unknown: 'De kamertemperatuur is nu niet bekend.',
  houseNote_outside_unknown: 'De buitentemperatuur is nu niet bekend.',
  houseNote_heat_unknown: 'Het vermogen van de warmtepomp is nu niet bekend.',
  houseNote_stove_tail:
    'De houtkachel heeft de afgelopen 12 uur gebrand. Het huis geeft die warmte nog af, dus hoeveel warmte het opslaat is niet bekend.',
  houseSchemFactsLink: 'Gegevens invullen',
  houseSchemFailed: 'De warmtebalans kon niet worden geladen.',

  houseNodeOutside: 'Buiten',
  houseNodeEnvelope: 'Muren, dak, ramen',
  houseNodeRoom: 'Kamer',
  houseNodeMass: 'Warmteopslag',
  houseNodeMassSub: 'Vloer en huis',
  houseNodeCapacity: 'vloer en huis, samen {value} kWh per K',
  houseNodePump: 'Warmtepomp',
  houseNodePumpSub: 'Waterkring',
  houseNodeSun: 'Zon',
  houseNodePeople: 'Vrije warmte',
  houseNodeStove: 'Houtkachel',
  houseFlowLoss: 'Verlies',
  houseFlowUnknown: 'onbekend',
  houseFlowNotMeasured: 'warmte niet gemeten',
  houseStorage_storing: 'slaat {value} op',
  houseStorage_giving: 'geeft {value} terug',
  houseStorage_steady: 'stabiel',
  houseStorage_unknown: 'onbekend',
  houseSun: '{value} W/m²',

  houseBalSentence: '{head}; {list}, {tail}.',
  houseBalLoss: 'Op dit moment verliest het huis ongeveer {loss} naar buiten',
  houseBalLossUnknown: 'Op dit moment is het warmteverlies naar buiten niet bekend',
  houseBalPump: 'de warmtepomp levert {value}',
  houseBalPumpNegative: 'de warmtepomp onttrekt ongeveer {value} aan het huis (ontdooien)',
  houseBalPumpUnknown: 'het vermogen van de warmtepomp is niet bekend',
  houseBalSun: 'de zon levert ongeveer {value}',
  houseBalSunUnknown: 'de bijdrage van de zon is niet bekend',
  houseBalInternal: 'mensen en apparaten leveren ongeveer {value} vrije warmte',
  houseBalTailStoring: 'dus het gebouw slaat ongeveer {value} op',
  houseBalTailGiving: 'dus het gebouw geeft ongeveer {value} terug',
  houseBalTailSteady: 'dus het gebouw slaat bijna niets op en geeft bijna niets terug',
  houseBalTailUnknown: 'dus hoeveel warmte het gebouw opslaat is niet bekend',
  houseBalTailStoveTail:
    'maar de houtkachel heeft de afgelopen 12 uur gebrand en het gebouw geeft die warmte nog af, dus hoeveel het opslaat is niet bekend',
  houseBalTailStove:
    'maar de houtkachel brandt ook, dus hoeveel warmte het gebouw opslaat is niet bekend',

  houseToldTitle: 'Wat je hebt opgegeven en wat is gemeten',
  houseToldRow: 'Opgegeven ≈ {told} · gemeten {measured} (90\u00a0%\u2011bereik {lo}–{hi})',
  houseToldRowPlain: 'Opgegeven ≈ {told} · gemeten {measured}',
  houseToldDiffers: 'De metingen wijken af van je antwoorden; het model volgt de metingen.',
  houseTold_ua: 'Warmteverlies',
  houseTold_solar: 'Zonvenster',
  houseTold_gains: 'Netto vrije warmte',
  houseSettingsChanged:
    'Je hebt de huisinstellingen gewijzigd. Daarom heeft dit model het overgenomen, ook al voorspelde het iets slechter: {challenger} K tegen {champion} K voor het vorige model.',
  houseSettingsChangedPlain:
    'Je hebt de huisinstellingen gewijzigd. Daarom heeft dit model het van het vorige overgenomen.',

  housePredTitle: 'Gemeten en voorspelde kamertemperatuur',
  housePredMeasured: 'Gemeten',
  housePredPredicted: 'Voorspeld, 24 uur vooruit',
  housePredRange: 'Getoonde periode',
  housePredDays: '{n} d',
  housePredSummary:
    'In de laatste {days} dagen zat de voorspelling meestal {typical} K ernaast, hooguit {largest} K (rond {when}).',
  housePredTypical: 'Op testdagen zit het model er meestal {typical} °C naast.',
  housePredTypicalCold:
    'Op testdagen zit het model er meestal {typical} °C naast en voorspelt het gemiddeld {lean} °C te koud.',
  housePredTypicalWarm:
    'Op testdagen zit het model er meestal {typical} °C naast en voorspelt het gemiddeld {lean} °C te warm.',
  housePredTypicalLevel:
    'Op testdagen zit het model er meestal {typical} °C naast, zonder vaste neiging naar te koud of te warm.',
  housePredLargest: 'Het grootste verschil in deze periode was {largest} K, rond {when}.',
  housePredUnseen: 'testdagen vanaf hier',
  housePredEventsTitle:
    'Niet meegeteld in de vergelijking (daar en in de 24 uur erna staat geen voorspelling)',
  housePredEventStove: 'Houtkachel {from} tot {to}, nawarmte tot {tail}',
  housePredEventDay: 'Weggelaten dag: {day}',
  housePredLegendStove: 'Houtkachel: gearceerd, nawarmte lichter',
  housePredLegendDay: 'Weggelaten dag: gestippeld',
  housePredNone: 'Er zijn nog geen gemeten en voorspelde waarden om te vergelijken.',
  housePredLoading: 'De kamertemperaturen worden geladen.',

  houseTrendTime: 'Tijdconstante',
  houseTrendHeat: 'Warmteverlies',
  houseTrendTimeSummary: 'De tijdconstante van {n} modellen ging van {first} naar {last} uur.',
  houseTrendUnitH: 'u',

  houseWiTitle: 'Wat als',
  houseWiLead:
    'Probeer ander weer en zie wat de warmtepomp dan moet doen. Hier verandert geen enkele instelling.',
  houseWiInputs: 'Omstandigheden',
  houseWiOutside: 'Buitentemperatuur',
  houseWiComfort: 'Comforttemperatuur',
  houseWiSun: 'Zonneschijn',
  houseWiSunExact: 'Zonneschijn (W/m²)',
  houseWiSun_0: 'Geen',
  houseWiSun_150: 'Heiig',
  houseWiSun_500: 'Fel',
  houseWiStove: 'Houtkachel',
  houseWiStove_0: 'Uit',
  houseWiStove_2000: 'Laag · 2 kW',
  houseWiStove_5000: 'Hoog · 5 kW',
  houseWiResults: 'Wat het huis nodig heeft',
  houseWiUpdating: 'Bijwerken…',
  houseWiDemand: 'De warmtepomp moet ongeveer {value} leveren.',
  houseWiFree: 'Het huis verliest {loss}; zon, mensen en apparaten leveren al {free}.',
  houseWiWater:
    'Daarvoor is ongeveer {supply} °C aanvoerwater nodig (gemiddeld {mean} °C in de verwarmingskring). Je stooklijn geeft bij deze buitentemperatuur {curve} °C, het model heeft {supply} °C nodig.',
  houseWiLimitMax:
    'Je maximale aanvoertemperatuur van {max} °C begrenst dit: de warmtepomp kan geen warmer water leveren, dus de kamer kan onder {comfort} °C blijven.',
  houseWiLimitNone:
    'Bij {outside} °C buiten is met deze zon geen verwarming nodig: de vrije warmte dekt het verlies.',
  houseWiBalance: 'Met deze zon is boven {value} °C buiten geen verwarming nodig.',
  houseWiDriftTitle: 'Met de verwarming uit',
  houseWiDriftCools: 'Met de verwarming uit koelt de kamer in {hours} uur af tot {end} °C.',
  houseWiDriftHolds: 'Met de verwarming uit blijft de kamer {hours} uur lang rond {end} °C.',
  houseWiDriftTau: 'Het huis koelt af met een tijdconstante van ongeveer {tau} uur.',
  houseWiDriftAria:
    'Kamertemperatuur over {hours} uur met de verwarming uit, van {start} °C naar {end} °C.',
  houseWiSourceModel: 'Uit het geleerde model.',
  houseWiSourceEstimate: 'Schatting uit je antwoorden, niet gemeten.',
  houseWiNotCredible:
    'De controle op het warmteverlies is nog niet gehaald, dus zie de warmtevraag en de watertemperatuur als een ruwe schatting.',
  houseWiNoModel:
    'Het huismodel heeft nog geen gegevens om mee te rekenen. Vul eerst een paar gegevens in op het tabblad Overzicht.',
  houseWiAbsent: 'Deze service biedt Wat als nog niet aan.',
  houseWiFailed: 'De berekening is niet gelukt. Controleer de waarden en probeer het opnieuw.',
  houseWiFactsLink: 'Open het tabblad Overzicht',
};
