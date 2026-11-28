import type { features as en } from '$lib/i18n/en/features';

export const features: Record<keyof typeof en, string> = {
  section_features: 'Functies',
  overviewFeaturesOn: '{n} van {total} aan',
  overviewFeaturesLine: 'Zet elke functie aan of uit',
  settingsFeaturesIntro:
    'Elke functie heeft een eigen schakelaar. Zet uit wat je niet wilt. Het label laat zien wat elke functie nu doet.',
  featuresLegend:
    'Uit: uitgeschakeld. Schaduw: aan, maar het legt alleen vast wat het zou doen. Aan: ingeschakeld. Nu actief: werkt op dit moment.',
  featuresNoStatus: 'De actuele stand van de functies is nu niet beschikbaar.',
  feature_weather_compensation: 'Weersafhankelijke regeling',
  feature_room_feedback: 'Ruimtecorrectie',
  feature_slow_start: 'Zachte start',
  feature_minimum_run: 'Pendelbeveiliging',
  feature_pump_duty: 'Pomptoerental',
  feature_quiet: 'Stille modus',
  feature_stove: 'Houtkachelmodus',
  feature_dayshift: 'Zonnige dagverschuiving',
  feature_summer: 'Zomerstand',
  feature_away: 'Afwezig',
  feature_boost: 'Boost',
  feature_starts_alarm: 'Startenalarm',
  feature_house_basics: 'Huisgegevens',
  featureHelp_weather_compensation:
    'Bepaalt de watertemperatuur uit de buitentemperatuur, langs je stooklijn. Uit gebruikt het één vaste watertemperatuur.',
  featureHelp_room_feedback:
    'Zet de watertemperatuur iets hoger of lager tot de kamer je kamerdoel haalt.',
  featureHelp_slow_start:
    'Houdt het water na een start van de compressor even iets onder de stooklijn en laat het langzaam stijgen, zodat het niet doorschiet.',
  featureHelp_minimum_run:
    'Voorkomt dat de compressor na een start te snel stopt, zodat hij in minder, rustigere draaiperiodes werkt.',
  featureHelp_pump_duty:
    'Stelt het toerental van de waterpomp in: sneller tijdens het verwarmen, trager als het rustig is.',
  featureHelp_quiet:
    'Laat de warmtepomp stil draaien in vaste tijdvakken en een paar minuten na elke start van de compressor.',
  featureHelp_stove:
    'Zet de verwarming terug zolang een houtkachel de kamer opwarmt en gaat weer verder als de kachel uit is.',
  featureHelp_dayshift:
    'Op zonnige, zachte dagen wordt het overdag iets warmer en ’s nachts iets koeler, zodat de pomp ’s nachts minder draait.',
  featureHelp_summer:
    'Zet de ruimteverwarming uit als het buiten een tijd warm is geweest, en weer aan als het afkoelt.',
  featureHelp_away:
    'Laat je een lager kamerdoel instellen terwijl je weg bent, zodat het huis weer warm is als je terugkomt.',
  featureHelp_boost: 'Maak de kamer een paar uur warmer of koeler, vanaf de startpagina.',
  featureHelp_starts_alarm:
    'Geeft een melding als de compressor te vaak start. Het kijkt alleen mee en verandert niets aan de verwarming.',
  featureHelp_house_basics:
    'Schat hoeveel warmte je huis verliest, uit de gegevens die ovenbird vastlegt. Het kijkt alleen mee en verandert niets aan de verwarming.',
  featureState_off: 'Uit',
  featureState_shadow: 'Schaduw',
  featureState_on: 'Aan',
  featureState_active_now: 'Nu actief',
  featureMore: 'Meer opties',
  featureFixed: 'Vastgelegd door de installatie',
  featureFixedHint:
    'Deze waarden worden bij de installatie van ovenbird ingesteld. Ze staan hier ter informatie en zijn niet te wijzigen.',
  featureNotWorking:
    'Aan, maar werkt nu niet, bijvoorbeeld omdat er geen kamersensor is om op te sturen.',
  featureEditor: 'Alle instellingen: {section}',
  featureExperimental: 'Experimenteel',
  featureAck_dayshift:
    'Experimenteel. In de simulator werden huizen met grote ramen aan de zonkant hierdoor te warm. Ik wil het in mijn huis proberen.',
  featureAckWhy: 'Vink het vakje hierboven aan om Aan te kunnen kiezen.',

  homeBoostTitle: 'Even warmer',
  homeBoostHow: 'Kamerdoel aanpassen met',
  homeBoostFor: 'Duur',
  homeBoostHours: '{n} u',
  homeBoostStart: 'Start',
  homeBoostActive: 'Kamerdoel {offset} K tot {until}',
  homeBoostLeft: 'nog {left}',
  homeBoostStop: 'Boost stoppen',
  homeBoostPaused_stove: 'Gepauzeerd zolang de houtkachelmodus actief is. De tijd loopt door.',
  homeBoostPaused_summer: 'Gepauzeerd door de zomerstand. De tijd loopt door.',
  homeBoostAway: 'Afwezig is ingesteld. Beëindig dat eerst om een boost te gebruiken.',
  homeAwayTitle: 'Afwezig',
  homeAwayTarget: 'Kamerdoel tijdens afwezigheid',
  homeAwayDate: 'Terug op',
  homeAwayTime: 'om',
  homeAwaySet: 'Afwezig instellen',
  homeAwayNote: 'Afwezig instellen beëindigt een lopende boost.',
  homeAwayActive: 'Afwezig tot {until}',
  homeAwayReturning: 'Het huis warmt op voor je thuiskomst',
  homeAwayTargetLine: 'Kamerdoel {target} °C',
  homeAwayComfortFrom: 'Weer op comfort vanaf {time}',
  homeAwayEnd: 'Ik ben terug',
  homeAwayTooSoon: 'Kies een moment minstens {hours} u vanaf nu, zodat het huis kan opwarmen.',
  homeAwayTooFar: 'Kies een moment binnen 60 dagen.',
  homeAwayPaused_stove:
    'Het kamerdoel voor afwezigheid is gepauzeerd zolang de houtkachelmodus actief is.',
  homeAwayPaused_summer: 'Het kamerdoel voor afwezigheid is gepauzeerd door de zomerstand.',
  homeSummerActive: 'Zomerstand: geen ruimteverwarming (gemiddelde buitentemperatuur {mean} °C)',
  homeSummerWarming: 'Zomerstand: de gemiddelde buitentemperatuur wordt nog opgebouwd',

  dayshiftTitle: 'Zonnige dagverschuiving',
  dayshiftMode_off: 'Uit',
  dayshiftMode_shadow: 'Schaduw: alleen vastleggen',
  dayshiftMode_on: 'Aan',
  dayshiftPhase_idle: 'Geen verschuiving',
  dayshiftPhase_boost: 'Overdag warmer',
  dayshiftPhase_setback: '’s Nachts koeler',
  dayshiftPhase_recovery: 'Weer opwarmen',
  dayshiftPhase_blocked: 'Geblokkeerd',
  dayshiftOffset: 'Verschuiving',
  dayshiftOffsetApplied: '{offset} K toegepast',
  dayshiftOffsetShadow: '{offset} K berekend, niet toegepast',
  dayshiftGuards: 'Tegengehouden door',
  dayshiftNext: 'Hierna: {phase} om {time}',
  dayshiftNextNone: 'Geen wijziging gepland.',
  dayshiftShadow_up:
    'In schaduw: het kamerdoel zou nu {k} K hoger worden. Er wordt niets verstuurd.',
  dayshiftShadow_down:
    'In schaduw: het kamerdoel zou nu {k} K lager worden. Er wordt niets verstuurd.',
  dayshiftShadow_none: 'In schaduw: het zou nu niets veranderen.',
  dayshiftForecast: 'Vandaag',
  dayshiftForecastLine:
    'Zon {sun} W/m² (nodig {sunLimit}), buiten nu {outside} °C, verwacht minimum {min} °C (nodig {limit}), vannacht {night} °C',
  dayshiftForecastNone: 'Er is nog geen voorspelling gelezen.',
  dayshiftForecastIssued: 'Voorspelling van {time}',
  dayshiftWindows:
    'Dag {dayStart}–{dayEnd}, nacht {nightStart}–{nightEnd}, weer warm om {comfortAt}',
  dayshiftSeeNow: 'Bekijk wat het nu doet',
  dayshiftReason_off: 'De dagverschuiving staat uit.',
  dayshiftReason_outside_windows: 'Buiten de tijden van dag en nacht.',
  dayshiftReason_sun_forecast: 'Er is genoeg zon voorspeld.',
  dayshiftReason_sun_low: 'Te weinig zon voor de rest van de dag.',
  dayshiftReason_outside_mild: 'Het is buiten zacht genoeg.',
  dayshiftReason_outside_cold: 'Het is buiten te koud.',
  dayshiftReason_outside_unknown: 'Nog geen buitentemperatuur.',
  dayshiftReason_forecast_missing: 'Geen voorspelling voor deze periode.',
  dayshiftReason_night_after_boost: 'Een nacht na een zonnige dag: de kamer mag koeler.',
  dayshiftReason_no_boost_today: 'De dag was niet lang genoeg zonnig, dus geen koelere nacht.',
  dayshiftReason_night_cold: 'De nacht wordt te koud voor een koelere kamer.',
  dayshiftReason_recovery_lead: 'De kamer wordt op tijd weer opgewarmd.',
  dayshiftReason_room_below_target: 'De kamer werd te koud, dus vannacht niet verder afkoelen.',
  dayshiftReason_room_warm: 'De kamer is warm genoeg, dus vandaag geen extra warmte meer.',
  dayshiftReason_forecast_stale: 'De weersvoorspelling is te oud.',
  dayshiftReason_room_untrusted: 'De kamertemperatuur wordt nu niet vertrouwd.',
  dayshiftReason_stove_active: 'De houtkachelmodus is actief.',
  dayshiftReason_stove_tail: 'De houtkachelmodus eindigde minder dan 12 u geleden.',
  dayshiftReason_away: 'Afwezig is ingesteld.',

  group_dayshift: 'Zonnige dagverschuiving',
  group_summer: 'Zomerstand',
  group_manual: 'Boost en afwezig',
  check_dayshift_windows:
    'De tijden kloppen niet: de dag moet beginnen voordat hij eindigt, en de nacht moet eindigen voordat de kamer weer warm moet zijn, met genoeg tijd om op te warmen.',
  check_dayshift_on_needs_ack:
    'De zonnige dagverschuiving is experimenteel. Vink eerst aan dat je hem wilt proberen voordat je hem aanzet, of gebruik schaduw.',
  houseExcluded_away: 'Afwezig: {n}',

  reason_quiet_start: 'Stil na een start',
  reason_room_target: 'Boost',
  reason_away: 'Afwezig',
  reason_summer: 'Zomerstand',
  explain_reason_quiet_start:
    'De compressor is net gestart, dus de pomp draait een paar minuten stil.',
  explain_reason_room_target: 'Je hebt tijdelijk een ander kamerdoel gevraagd (boost).',
  explain_reason_away: 'Je bent weg, dus het kamerdoel staat lager tot kort voor je terugkomt.',
  explain_reason_summer:
    'De zomerstand houdt het water op het minimum omdat het al een tijd warm is buiten.',
  term_room_target: 'Boost of afwezig',
  term_summer: 'Zomerstand',
  alarm_compressor_starts: 'Veel compressorstarts',
  alarmText_compressor_starts: 'De compressor startte vaker dan de grens toestaat.',
  alarmWhy_compressor_starts:
    'Veel korte draaiperiodes slijten de compressor en betekenen meestal dat de verwarming niet bij de belasting past.',
  alarmNow_compressor_starts: 'Er verandert niets; het alarm geeft alleen een melding.',
  alarmYou_compressor_starts:
    'Controleer of de stooklijn niet te laag staat en of de pendelbeveiliging aan staat. Blijft het gebeuren, vraag je installateur om advies.',
  mon_compressor_starts: '{value} in het laatste uur, grens {limit}',
  alarm_dayshift: 'Zonnige dagverschuiving',
  alarmText_dayshift:
    'De zonnige dagverschuiving begon of eindigde een warmere of koelere periode.',

  'cfg.control_dayshift_use.label': 'Zonnige dagverschuiving',
  'cfg.control_dayshift_use.help':
    'Op een zonnige, zachte dag zet ovenbird het kamerdoel overdag iets hoger en de nacht erna iets lager, zodat het huis de zonnewarmte vasthoudt. Schaduw legt alleen vast wat het zou doen.',
  'cfg.control_dayshift_use.opt.off': 'Uit',
  'cfg.control_dayshift_use.opt.shadow': 'Schaduw',
  'cfg.control_dayshift_use.opt.on': 'Aan',
  'cfg.control_dayshift_experimental_ok.label': 'Experimentele dagverschuiving proberen',
  'cfg.control_dayshift_experimental_ok.help':
    'Je accepteert dat de zonnige dagverschuiving experimenteel is: in de simulator werden huizen met grote ramen aan de zonkant er te warm door. Nodig om hem aan te zetten.',
  'cfg.control_dayshift_day_start.label': 'Dag begint',
  'cfg.control_dayshift_day_start.help':
    'Wanneer de dag begint, in de tijdzone van de service. Op een zonnige dag gaat het kamerdoel vanaf dan omhoog.',
  'cfg.control_dayshift_day_end.label': 'Dag eindigt',
  'cfg.control_dayshift_day_end.help':
    'Wanneer de dag eindigt. Daarna is het kamerdoel weer normaal.',
  'cfg.control_dayshift_boost_k.label': 'Overdag warmer',
  'cfg.control_dayshift_boost_k.help':
    'Hoeveel warmer de kamer op een zonnige, zachte dag mag worden, in K.',
  'cfg.control_dayshift_setback_k.label': '’s Nachts koeler',
  'cfg.control_dayshift_setback_k.help':
    'Hoeveel koeler de kamer in de nacht na zo’n dag mag worden, in K.',
  'cfg.control_dayshift_min_outside_c.label': 'Buiten minstens',
  'cfg.control_dayshift_min_outside_c.help':
    'De verschuiving start alleen als de buitentemperatuur, nu en verwacht, minstens dit is. Is hij eenmaal bezig, dan gaat hij door tot 1 °C lager.',
  'cfg.control_dayshift_min_sun_wm2.label': 'Genoeg zon',
  'cfg.control_dayshift_min_sun_wm2.help':
    'Vanaf welke verwachte gemiddelde zonnestraling voor de rest van de dag (in W/m²) het een zonnige dag is. Is hij eenmaal bezig, dan gaat hij door tot de helft.',
  'cfg.control_dayshift_night_start.label': 'Nacht begint',
  'cfg.control_dayshift_night_start.help':
    'Wanneer de nacht begint, waarin de kamer koeler mag zijn.',
  'cfg.control_dayshift_night_end.label': 'Nacht eindigt',
  'cfg.control_dayshift_night_end.help': 'Uiterlijk wanneer de koelere nacht eindigt.',
  'cfg.control_dayshift_comfort_at.label': 'Weer warm om',
  'cfg.control_dayshift_comfort_at.help':
    'Wanneer de kamer na een koelere nacht weer op de normale temperatuur moet zijn.',
  'cfg.control_dayshift_recovery_s.label': 'Opwarmtijd',
  'cfg.control_dayshift_recovery_s.help':
    'Hoeveel eerder de koelere nacht stopt, zodat de kamer op tijd warm is. Vloerverwarming heeft zo’n 4 tot 5 uur nodig.',
  'cfg.control_plan_rule_max_k.label': 'Grootste geplande verschuiving',
  'cfg.control_plan_rule_max_k.help':
    'Hoeveel een geplande regel zoals de dagverschuiving het kamerdoel hoogstens mag verzetten, in K. Het begrenst ook hoeveel een koelere nacht de drempel van de melding ‘kamer te koud’ verlaagt.',
  'cfg.control_summer_enabled.label': 'Zomerstand',
  'cfg.control_summer_enabled.help':
    'Zet de ruimteverwarming uit zolang het buiten warm is. De pomp zelf blijft aan.',
  'cfg.control_summer_off_c.label': 'Verwarming uit boven',
  'cfg.control_summer_off_c.help':
    'Geen ruimteverwarming zolang het trage gemiddelde van de buitentemperatuur hierboven ligt.',
  'cfg.control_summer_hysteresis_k.label': 'Weer aan onder de grens met',
  'cfg.control_summer_hysteresis_k.help':
    'De verwarming komt terug als het trage gemiddelde zoveel K onder de grens ligt. Zo schakelt hij niet heen en weer.',
  'cfg.control_summer_mean_s.label': 'Middelingstijd',
  'cfg.control_summer_mean_s.help':
    'Over hoeveel tijd de buitentemperatuur wordt gemiddeld. Een dag of langer zorgt ervoor dat één warme middag de verwarming niet stopt.',
  'cfg.control_boost_enabled.label': 'Boost toestaan',
  'cfg.control_boost_enabled.help': 'Toont de boost op de startpagina. Uit verbergt hem.',
  'cfg.control_boost_default_k.label': 'Standaard boost',
  'cfg.control_boost_default_k.help':
    'Hoeveel warmer het kamerdoel wordt als een boost zonder keuze start, in K.',
  'cfg.control_boost_default_s.label': 'Standaardduur boost',
  'cfg.control_boost_default_s.help': 'Hoe lang een boost duurt als er geen duur is gekozen.',
  'cfg.control_away_enabled.label': 'Afwezig toestaan',
  'cfg.control_away_enabled.help': 'Toont de afwezigheid op de startpagina. Uit verbergt hem.',
  'cfg.control_away_target_c.label': 'Kamerdoel tijdens afwezigheid',
  'cfg.control_away_target_c.help':
    'De kamertemperatuur die wordt aangehouden terwijl je weg bent, tussen 10 en 20 °C.',
  'cfg.control_away_comfort_lead_s.label': 'Weer warm voor je terugkomt',
  'cfg.control_away_comfort_lead_s.help':
    'Hoe lang voor je terugkomst het huis weer op comforttemperatuur komt. Vloerverwarming is traag, dus reken op uren.',
  'cfg.control_quiet_enabled.label': 'Stille tijdvakken gebruiken',
  'cfg.control_quiet_enabled.help':
    'Uit negeert de tijdvakken van de stille modus. Stil na een start heeft een eigen schakelaar.',
  'cfg.control_quiet_start_enabled.label': 'Stil na een start',
  'cfg.control_quiet_start_enabled.help':
    'Laat de warmtepomp de eerste minuten na de start van de compressor, het luidste moment, stil draaien.',
  'cfg.control_quiet_start_minutes.label': 'Stille minuten na een start',
  'cfg.control_quiet_start_minutes.help': 'Hoe lang de warmtepomp na een start stil blijft.',
  'cfg.control_quiet_start_level.label': 'Stilteniveau na een start',
  'cfg.control_quiet_start_level.help':
    'Van 1 tot 3. Een hoger niveau is stiller. Tijdens ontdooien blijft het ook stil.',
  'cfg.control_cycling_max_raise_k.label': 'Grootste verhoging tegen pendelen',
  'cfg.control_cycling_max_raise_k.help':
    'Hoeveel K boven de stooklijn de watertemperatuur mag komen om te voorkomen dat de compressor te vroeg stopt.',
  'cfg.safety_starts_alarm_enabled.label': 'Startenalarm',
  'cfg.safety_starts_alarm_enabled.help': 'Geeft een melding als de compressor te vaak start.',
  'cfg.safety_starts_per_hour_max.label': 'Meeste starts per uur',
  'cfg.safety_starts_per_hour_max.help': 'Meer starts dan dit in een uur geeft de melding.',
  'cfg.safety_starts_per_day_max.label': 'Meeste starts per dag',
  'cfg.safety_starts_per_day_max.help': 'Meer starts dan dit op een dag geeft de melding.',
};
