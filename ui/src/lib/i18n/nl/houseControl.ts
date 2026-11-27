export const houseControl = {
  houseTab_control: 'Regeling',
  houseCtlAbsent: 'Deze service biedt het gebruik van het model door de regelaar nog niet aan.',
  wfModelPlan_down:
    'Het huismodel verlaagde het kamerdoel met {k}; de ruimtecorrectie werkt op het verlaagde doel.',
  wfModelPlan_up:
    'Het huismodel verhoogde het kamerdoel met {k}; de ruimtecorrectie werkt op het verhoogde doel.',
  houseCtlTitle: 'Hoe de regelaar het model gebruikt',
  houseCtlSubtitle: 'Verschuift het kamerdoel een beetje vóór zon of een koude omslag.',
  houseCtlSwitchLabel: 'Gebruik van het model door de regelaar',
  houseCtlUse_off: 'Uit',
  houseCtlUse_shadow: 'Schaduw: rekent alleen mee',
  houseCtlUse_on: 'Aan',
  houseCtlUseShort_off: 'Uit',
  houseCtlUseShort_shadow: 'Schaduw',
  houseCtlUseShort_on: 'Aan',
  houseCtlMeaning_off: 'De regelaar negeert het model en verwarmt naar je kamerdoel, zoals altijd.',
  houseCtlMeaning_shadow:
    'Elke 15 minuten rekent de planner uit wat hij zou doen en legt dat hier vast. Hij verandert niets: het kamerdoel blijft zoals jij het instelde.',
  houseCtlMeaning_on:
    'Elke 15 minuten verschuift de planner het kamerdoel binnen de grenzen hieronder: omlaag voordat gratis warmte binnenkomt, omhoog voor een koude omslag.',
  houseCtlLocked:
    'Aan is voorlopig vergrendeld: het opent na een beoordeling en een schaduwperiode. Tot die tijd wordt kiezen geweigerd.',
  houseCtlDraftHint: 'Een wijziging gaat via de balk onderaan, net als elke instelling.',
  houseCtlChangeLink: 'Wijzigen',

  houseCtlNowTitle: 'Nu',
  houseCtlNowOff: 'De planner draait niet zolang de schakelaar uit staat.',
  houseCtlNowNever:
    'De planner heeft nog niet gerekend. De eerste berekening komt binnen 15 minuten.',
  houseCtlEvaluated: 'Laatst berekend {when}',
  houseCtlUntilNext: 'de volgende berekening',
  houseCtlShift_would_down: 'Zou het kamerdoel met {k} K verlagen tot {until}.',
  houseCtlShift_would_up: 'Zou het kamerdoel met {k} K verhogen tot {until}.',
  houseCtlShift_is_down: 'Verlaagt het kamerdoel met {k} K tot {until}.',
  houseCtlShift_is_up: 'Verhoogt het kamerdoel met {k} K tot {until}.',
  houseCtlHeld_down:
    'Het plan wil het kamerdoel met {k} K verlagen, maar de regelaar past dat nu niet toe.',
  houseCtlHeld_up:
    'Het plan wil het kamerdoel met {k} K verhogen, maar de regelaar past dat nu niet toe.',
  houseCtlStatus_blocked: 'Nu geen verschuiving: de planner mag niet ingrijpen, zie hieronder.',
  houseCtlStatus_issued: 'Er is een verschuiving afgegeven.',
  houseCtlStatus_inside_dead_zone:
    'Nu geen verschuiving: de verwachte verandering blijft binnen de dode band.',
  houseCtlStatus_crossing_zero:
    'Nu geen verschuiving: de verschuiving zou van richting moeten wisselen, dus ze blijft voorlopig op nul.',
  houseCtlStatus_forecast_gap:
    'Nu geen verschuiving: de weersverwachting heeft een gat in de komende uren.',
  houseCtlStatus_forecast_mismatch:
    'Nu geen verschuiving: de verwachting past niet bij de gemeten buitentemperatuur.',
  houseCtlStatus_model_invalid: 'Nu geen verschuiving: het model gaf geen bruikbare voorspelling.',
  houseCtlStatus_planner_error: 'Nu geen verschuiving: de planner kreeg een fout.',
  houseCtlRise:
    'In de komende {h} uur zal {cause} de kamer naar verwachting ongeveer {k} °C opwarmen, rond {at}.',
  houseCtlFall:
    'In de komende {h} uur zal {cause} de kamer naar verwachting ongeveer {k} °C afkoelen, rond {at}.',
  houseCtlFallThen: 'Later zal {cause} haar naar verwachting ongeveer {k} °C afkoelen, rond {at}.',
  houseCtlCause_sun: 'de zon',
  houseCtlCause_mild: 'de mildere buitenlucht',
  houseCtlCause_cold: 'de koudere buitenlucht',
  houseCtlCause_lessSun: 'minder zon',
  houseCtlEffectNone:
    'In de komende {h} uur wordt geen opvallende opwarming of afkoeling van de kamer verwacht.',

  houseCtlBlocksTitle: 'Mag de planner ingrijpen?',
  houseCtlReady: 'Er houdt nu niets de planner tegen.',
  houseCtlBlock_weather_off: 'De weersverwachting staat uit.',
  houseCtlBlock_model_missing: 'Er is nog geen geleerd huismodel.',
  houseCtlBlock_model_not_credible: 'Het model wordt nog niet vertrouwd.',
  houseCtlBlock_model_error_high:
    'De kamerfout van het model ({rmse} K) ligt boven de grens van {max} K.',
  houseCtlBlock_model_stale: 'Het model is verouderd.',
  houseCtlBlock_forecast_stale: 'De weersverwachting is ouder dan 3 uur.',
  houseCtlBlock_room_untrusted: 'De kamertemperatuur wordt nu niet vertrouwd.',
  houseCtlBlock_stove_active: 'Een houtkachel brandt.',
  houseCtlBlock_stove_tail: 'Een houtkachel brandde de afgelopen 12 uur.',
  houseCtlBlockUnknown: 'Reden: {code}',

  houseCtlChartTitle: 'Berekende verschuiving van het kamerdoel, laatste 7 dagen',
  houseCtlComputed: 'Berekende verschuiving',
  houseCtlApplied: 'Toegepast',
  houseCtlBand: 'Toegestaan bereik',
  houseCtlChartNote:
    'Gestippeld: wat de planner berekende. Doorgetrokken: wat de regelaar toepaste. Een onderbreking: niet berekend.',
  houseCtlDay_one: '{n} dag',
  houseCtlDay_other: '{n} dagen',
  houseCtlSumNone: 'In de afgelopen {n} dagen heeft de planner niet gerekend.',
  houseCtlSumFlat_would:
    'In de afgelopen {n} dagen zou het model het kamerdoel niet hebben verschoven.',
  houseCtlSumFlat_did: 'In de afgelopen {n} dagen heeft het model het kamerdoel niet verschoven.',
  houseCtlSumDown_would_first:
    'In de afgelopen {n} dagen zou het model het kamerdoel op {days} hebben verlaagd, met hooguit {k} K.',
  houseCtlSumDown_would_next: 'Het zou het kamerdoel op {days} hebben verlaagd, met hooguit {k} K.',
  houseCtlSumDown_did_first:
    'In de afgelopen {n} dagen heeft het model het kamerdoel op {days} verlaagd, met hooguit {k} K.',
  houseCtlSumDown_did_next: 'Het heeft het kamerdoel op {days} verlaagd, met hooguit {k} K.',
  houseCtlSumUp_would_first:
    'In de afgelopen {n} dagen zou het model het kamerdoel op {days} hebben verhoogd, met hooguit {k} K.',
  houseCtlSumUp_would_next: 'Het zou het op {days} hebben verhoogd, met hooguit {k} K.',
  houseCtlSumUp_did_first:
    'In de afgelopen {n} dagen heeft het model het kamerdoel op {days} verhoogd, met hooguit {k} K.',
  houseCtlSumUp_did_next: 'Het heeft het op {days} verhoogd, met hooguit {k} K.',
  houseCtlSumApplied: 'Ongeveer {h} uur van de verschuivingen is toegepast.',

  houseCtlBounds: 'Hooguit {down} K omlaag en {up} K omhoog, {h} uur vooruit kijkend.',
  houseCtlAdvanced: 'Grenzen en limieten',
  houseCtlNoteTitle: 'Wat er mis kan gaan',
  houseCtlNote:
    'Het model is een vereenvoudiging van je huis en een verwachting kan ernaast zitten, dus een verschuiving kan een beetje afwijken. Wat je beschermt: de grenzen hierboven begrenzen elke verschuiving, de kamersensor beslist nog steeds (de ruimtecorrectie blijft werken op het verschoven doel) en de veiligheidsgrenzen blijven zoals ze zijn.',
  houseCtlFailed: 'Het modelgebruik kon niet worden geladen.',
  houseStatusUse: 'Gebruik door de regelaar: {use}',
  houseStatusUseLink: 'Details',
  houseCtlModelLine: 'Model {model}, typische kamerfout {rmse} K.',

  explain_reason_plan_setback_model:
    'Kamerdoel {planApplied} verlaagd: het huismodel verwacht dat de kamer de komende uren vanzelf opwarmt (zon of milder weer), dus er is nu minder verwarming nodig. Aanvoertemperatuur {setpoint} °C.',
  explain_reason_plan_preheat_model:
    'Kamerdoel {planApplied} verhoogd: het huismodel verwacht dat de kamer de komende uren afkoelt (een koude omslag of minder zon), dus de verwarming start iets eerder. Aanvoertemperatuur {setpoint} °C.',
  explain_plan_requested: 'Het plan vroeg {planRequested}; de grenzen beperkten dat.',
  explain_plan_ignored: 'Het plan van het huismodel is niet gebruikt: {why}.',
  houseCtlIgnored_room_untrusted: 'de kamertemperatuur wordt niet vertrouwd',
  houseCtlIgnored_stove_active: 'een houtkachel brandt',
  houseCtlIgnored_stove_recovery: 'de houtkacheldetectie is nog aan het herstellen',
  houseCtlIgnored_slice_too_long: 'het plan beslaat een te lange periode',
} as const;
