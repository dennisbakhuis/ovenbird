export const houseControl = {
  houseTab_control: 'Regeling',
  houseCtlAbsent: 'Deze service biedt het gebruik van het model door de regelaar nog niet aan.',
  wfModelPlan_down:
    'Het huismodel verlaagde het kamerdoel met {k}; de ruimtecorrectie werkt met dat lagere doel.',
  wfModelPlan_up:
    'Het huismodel verhoogde het kamerdoel met {k}; de ruimtecorrectie werkt met dat hogere doel.',
  houseCtlTitle: 'Hoe de regelaar het model gebruikt',
  houseCtlSubtitle:
    'Kan het kamerdoel een beetje verschuiven, vooruitlopend op zon of kouder weer.',
  houseCtlSwitchLabel: 'Gebruik van het model door de regelaar',
  houseCtlUse_off: 'Uit',
  houseCtlUse_shadow: 'Schaduw (rekent alleen mee)',
  houseCtlUse_on: 'Aan',
  houseCtlUseShort_off: 'Uit',
  houseCtlUseShort_shadow: 'Schaduw',
  houseCtlUseShort_on: 'Aan',
  houseCtlMeaning_off: 'De regelaar negeert het model en verwarmt naar je kamerdoel, zoals altijd.',
  houseCtlMeaning_shadow:
    'Elke 15 minuten rekent de planner uit wat hij zou doen en legt dat hier vast. Hij verandert niets: het kamerdoel blijft zoals je het hebt ingesteld.',
  houseCtlMeaning_on:
    'Elke 15 minuten verschuift de planner het kamerdoel binnen de grenzen hieronder: omlaag voordat er vrije warmte binnenkomt, omhoog voordat het kouder wordt.',
  houseCtlLocked:
    'Aan is voorlopig vergrendeld: die stand gaat pas open na een beoordeling en een periode in Schaduw. Tot dan wordt Aan geweigerd.',
  houseCtlDraftHint: 'Een wijziging gaat via de balk onderaan, net als bij elke andere instelling.',
  houseCtlChangeLink: 'Wijzigen',

  houseCtlNowTitle: 'Nu',
  houseCtlNowOff: 'De planner draait niet zolang de schakelaar op Uit staat.',
  houseCtlNowNever:
    'De planner heeft nog niet gerekend. De eerste berekening volgt binnen 15 minuten.',
  houseCtlEvaluated: 'Laatst berekend {when}',
  houseCtlUntilNext: 'de volgende berekening',
  houseCtlShift_would_down: 'De planner zou het kamerdoel tot {until} met {k} K verlagen.',
  houseCtlShift_would_up: 'De planner zou het kamerdoel tot {until} met {k} K verhogen.',
  houseCtlShift_is_down: 'De planner verlaagt het kamerdoel tot {until} met {k} K.',
  houseCtlShift_is_up: 'De planner verhoogt het kamerdoel tot {until} met {k} K.',
  houseCtlHeld_down:
    'Het plan wil het kamerdoel met {k} K verlagen, maar de regelaar past dat nu niet toe.',
  houseCtlHeld_up:
    'Het plan wil het kamerdoel met {k} K verhogen, maar de regelaar past dat nu niet toe.',
  houseCtlStatus_blocked: 'Nu geen verschuiving: de planner mag niet ingrijpen, zie hieronder.',
  houseCtlStatus_issued: 'Er is een verschuiving doorgegeven.',
  houseCtlStatus_inside_dead_zone:
    'Nu geen verschuiving: de verwachte verandering blijft binnen de dode band.',
  houseCtlStatus_crossing_zero:
    'Nu geen verschuiving: de verschuiving zou van richting moeten wisselen, dus ze blijft voorlopig op nul.',
  houseCtlStatus_forecast_gap:
    'Nu geen verschuiving: de weersverwachting heeft een gat in de komende uren.',
  houseCtlStatus_forecast_mismatch:
    'Nu geen verschuiving: de verwachting klopt niet met de gemeten buitentemperatuur.',
  houseCtlStatus_model_invalid: 'Nu geen verschuiving: het model gaf geen bruikbare voorspelling.',
  houseCtlStatus_planner_error: 'Nu geen verschuiving: de planner liep tegen een fout aan.',
  houseCtlRise:
    'Naar verwachting warmt {cause} de kamer de komende {h} uur ongeveer {k} °C op (rond {at}).',
  houseCtlFall:
    'Naar verwachting koelt {cause} de kamer de komende {h} uur ongeveer {k} °C af (rond {at}).',
  houseCtlFallThen:
    'Daarna koelt {cause} de kamer naar verwachting ongeveer {k} °C af (rond {at}).',
  houseCtlCause_sun: 'de zon',
  houseCtlCause_mild: 'de zachtere buitenlucht',
  houseCtlCause_cold: 'de koudere buitenlucht',
  houseCtlCause_lessSun: 'minder zon',
  houseCtlEffectNone:
    'In de komende {h} uur wordt geen merkbare opwarming of afkoeling van de kamer verwacht.',

  houseCtlBlocksTitle: 'Mag de planner ingrijpen?',
  houseCtlReady: 'Niets houdt de planner nu tegen.',
  houseCtlBlock_weather_off: 'De weersverwachting staat uit.',
  houseCtlBlock_model_missing: 'Er is nog geen geleerd huismodel.',
  houseCtlBlock_model_not_credible: 'Het model wordt nog niet vertrouwd.',
  houseCtlBlock_model_error_high:
    'De kamerfout van het model ({rmse} K) ligt boven de grens van {max} K.',
  houseCtlBlock_model_stale: 'Het model is verouderd.',
  houseCtlBlock_forecast_stale: 'De weersverwachting is ouder dan 3 uur.',
  houseCtlBlock_room_untrusted: 'De kamertemperatuur wordt nu niet vertrouwd.',
  houseCtlBlock_stove_active: 'De houtkachel brandt.',
  houseCtlBlock_stove_tail: 'De houtkachel heeft de afgelopen 12 uur gebrand.',
  houseCtlBlockUnknown: 'Reden: {code}',

  houseCtlChartTitle: 'Berekende verschuiving van het kamerdoel, laatste 7 dagen',
  houseCtlComputed: 'Berekende verschuiving',
  houseCtlApplied: 'Toegepast',
  houseCtlBand: 'Toegestaan bereik',
  houseCtlChartNote:
    'Gestippeld: wat de planner berekende. Doorgetrokken: wat de regelaar toepaste. Een onderbreking: niet berekend.',
  houseCtlDay_one: '{n} dag',
  houseCtlDay_other: '{n} dagen',
  houseCtlSumNone: 'De planner heeft de afgelopen {n} dagen niet gerekend.',
  houseCtlSumFlat_would:
    'In de afgelopen {n} dagen zou het model het kamerdoel niet hebben verschoven.',
  houseCtlSumFlat_did: 'In de afgelopen {n} dagen heeft het model het kamerdoel niet verschoven.',
  houseCtlSumDown_would_first:
    'In de afgelopen {n} dagen zou het model het kamerdoel op {days} hebben verlaagd, met hooguit {k} K.',
  houseCtlSumDown_would_next: 'Op {days} zou het kamerdoel zijn verlaagd, met hooguit {k} K.',
  houseCtlSumDown_did_first:
    'In de afgelopen {n} dagen heeft het model het kamerdoel op {days} verlaagd, met hooguit {k} K.',
  houseCtlSumDown_did_next: 'Op {days} is het kamerdoel verlaagd, met hooguit {k} K.',
  houseCtlSumUp_would_first:
    'In de afgelopen {n} dagen zou het model het kamerdoel op {days} hebben verhoogd, met hooguit {k} K.',
  houseCtlSumUp_would_next: 'Op {days} zou het juist zijn verhoogd, met hooguit {k} K.',
  houseCtlSumUp_did_first:
    'In de afgelopen {n} dagen heeft het model het kamerdoel op {days} verhoogd, met hooguit {k} K.',
  houseCtlSumUp_did_next: 'Op {days} is het juist verhoogd, met hooguit {k} K.',
  houseCtlSumApplied: 'Ongeveer {h} uur van de verschuivingen is toegepast.',

  houseCtlBounds: 'Hooguit {down} K omlaag en {up} K omhoog; de planner kijkt {h} uur vooruit.',
  houseCtlAdvanced: 'Grenzen',
  houseCtlNoteTitle: 'Wat er mis kan gaan',
  houseCtlNote:
    'Het model is een vereenvoudiging van je huis en een verwachting kan ernaast zitten, dus een verschuiving kan net verkeerd uitvallen. Wat je beschermt: de grenzen hierboven beperken elke verschuiving, de kamersensor heeft nog steeds het laatste woord (de ruimtecorrectie blijft werken met het verschoven doel) en de veiligheidsgrenzen blijven zoals ze zijn.',
  houseCtlFailed: 'Het gebruik van het model kon niet worden geladen.',
  houseStatusUse: 'Gebruik door de regelaar: {use}',
  houseStatusUseLink: 'Details',
  houseCtlModelLine: 'Model {model}, typische kamerfout {rmse} K.',

  explain_reason_plan_setback_model:
    'Kamerdoel {planApplied} verlaagd: het huismodel verwacht dat de kamer de komende uren vanzelf warmer wordt (zon of zachter weer), dus nu is er minder verwarming nodig. Aanvoertemperatuur {setpoint} °C.',
  explain_reason_plan_preheat_model:
    'Kamerdoel {planApplied} verhoogd: het huismodel verwacht dat de kamer de komende uren afkoelt (kouder weer of minder zon), dus de verwarming begint iets eerder. Aanvoertemperatuur {setpoint} °C.',
  explain_plan_requested: 'Het plan vroeg {planRequested}; de grenzen hebben dat beperkt.',
  explain_plan_ignored: 'Het plan van het huismodel is niet gebruikt: {why}.',
  houseCtlIgnored_room_untrusted: 'de kamertemperatuur wordt niet vertrouwd',
  houseCtlIgnored_stove_active: 'de houtkachel brandt',
  houseCtlIgnored_stove_recovery:
    'de houtkacheldetectie wacht nog na een vuur of een sensorstoring',
  houseCtlIgnored_slice_too_long: 'het plan gold langer dan toegestaan',
} as const;
