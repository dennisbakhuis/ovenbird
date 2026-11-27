import type { fields as en } from '$lib/i18n/en/fields';

export const fields: Record<keyof typeof en, string> = {
  'cfg.control_curve.label': 'Stooklijn',
  'cfg.control_curve.help':
    'De aanvoertemperatuur bij elke buitentemperatuur. Tussen 2 en 6 punten; de aanvoertemperatuur stijgt nooit als het buiten warmer wordt.',
  'cfg.control_outside_filter_s.label': 'Afvlakking buitentemperatuur',
  'cfg.control_outside_filter_s.help':
    'Tijdconstante van het filter op de buitentemperatuur. De pomp meldt hele graden; dit vlakt de sprongen af. Onder 30 minuten wordt afgeraden.',
  'cfg.control_room_signal.label': 'Kamersensor',
  'cfg.control_room_signal.help':
    'De temperatuursensor die de regelaar vertelt hoe warm de kamer is. Laat leeg om alleen op de stooklijn te regelen.',
  'cfg.control_room_profile.label': 'Type sensor',
  'cfg.control_room_profile.help':
    'Periodieke sensoren melden op een vast interval. Sensoren die bij verandering melden doen dat alleen als de waarde beweegt, dus stilte is normaal.',
  'cfg.control_room_profile.opt.periodic': 'Periodiek',
  'cfg.control_room_profile.opt.on_change': 'Bij verandering',
  'cfg.control_room_step_k.label': 'Stapgrootte van de sensor',
  'cfg.control_room_step_k.help':
    'De kleinste verandering die de sensor meldt. Wordt gebruikt om te beoordelen of een vastgehouden waarde nog aannemelijk is.',
  'cfg.control_room_report_interval_s.label': 'Meldinterval',
  'cfg.control_room_report_interval_s.help':
    'Hoe vaak een periodieke sensor meldt. Een waarde die ouder is dan een paar intervallen geldt als verouderd.',
  'cfg.control_room_silence_limit_s.label': 'Stiltegrens',
  'cfg.control_room_silence_limit_s.help':
    'Hoe lang een sensor die bij verandering meldt stil mag zijn voordat zijn waarde niet meer wordt vertrouwd.',
  'cfg.control_room_liveness_signals.label': 'Levenssignalen',
  'cfg.control_room_liveness_signals.help':
    'Andere signalen van hetzelfde apparaat (luchtvochtigheid, batterij). Zolang die binnenkomen wordt een stille temperatuur nog vertrouwd.',
  'cfg.control_room_crosscheck_signal.label': 'Controlesensor',
  'cfg.control_room_crosscheck_signal.help':
    'Een tweede temperatuur die ongeveer met de kamersensor moet overeenkomen. Zo niet, dan wordt de ruimtecorrectie gepauzeerd.',
  'cfg.control_comfort_c.label': 'Comfortdoel',
  'cfg.control_comfort_c.help': 'De kamertemperatuur waar de regelaar naartoe werkt.',
  'cfg.control_weather_compensation.label': 'Weersafhankelijke regeling (WAR)',
  'cfg.control_weather_compensation.help':
    'Aan: de watertemperatuur volgt de stooklijn, warmer als het buiten kouder is. Uit: één vaste watertemperatuur, ongeacht de buitentemperatuur. Ruimtecorrectie is een aparte schakelaar en werkt in beide gevallen.',
  'cfg.control_fixed_water_c.label': 'Vaste watertemperatuur',
  'cfg.control_fixed_water_c.help':
    'Watertemperatuur zolang de weersafhankelijke regeling uit staat. Ruimtecorrectie kan hem nog iets verhogen of verlagen, en de veiligheidsband tilt hem op als het buiten erg koud is.',
  'cfg.control_feedback_enabled.label': 'Ruimtecorrectie',
  'cfg.control_feedback_enabled.help':
    'Uit: alleen de stooklijn (of de vaste watertemperatuur) wordt gebruikt, zonder proportionele of integrerende correctie vanuit de kamer. Los van de weersafhankelijke regeling.',
  'cfg.control_feedback_kp.label': 'Proportionele versterking',
  'cfg.control_feedback_kp.help':
    'Hoeveel K de aanvoertemperatuur verandert per K kamerafwijking. Hoger reageert sneller maar kan doorschieten.',
  'cfg.control_feedback_ti_s.label': 'Integratietijd',
  'cfg.control_feedback_ti_s.help':
    'Hoe langzaam de correctie opbouwt om een blijvende kamerafwijking weg te werken. 0 schakelt het integrerende deel uit.',
  'cfg.control_feedback_output_limit_k.label': 'Correctiegrens',
  'cfg.control_feedback_output_limit_k.help':
    'Het meeste dat de ruimtecorrectie bij de stooklijn mag optellen of aftrekken, in K.',
  'cfg.control_feedback_integral_limit_k.label': 'Integratiegrens',
  'cfg.control_feedback_integral_limit_k.help':
    'Het meeste dat het integrerende deel mag bijdragen, in K. Het kan niet boven de correctiegrens uitkomen.',
  'cfg.safety_room_floor_k.label': 'Marge voor te koude kamer',
  'cfg.safety_room_floor_k.help':
    'Geef een waarschuwing als de kamer zoveel K onder het comfortdoel blijft. Leeg schakelt de bewaking uit.',
  'cfg.safety_room_floor_sustain_s.label': 'Duur voor te koude kamer',
  'cfg.safety_room_floor_sustain_s.help':
    'Hoe lang de kamer te koud moet blijven voordat de waarschuwing komt.',
  'cfg.safety_defrost_low_flow.label': 'Geen doorstroming tijdens ontdooien',
  'cfg.safety_defrost_low_flow.help':
    'Sommige warmtepompen zetten tijdens het ontdooien hun waterpomp stil. Bij een pompmodel dat ovenbird uit de servicehandleiding kent, weet ovenbird wanneer dat zo hoort: de WH-MXC12J9E8 ontdooit onder 27 °C retourwater met heet gas en zet dan haar waterpomp stil (ontdooimodus 2). Automatisch legt dat geval alleen vast en geeft anders een alarm; Alleen vastleggen doet dat ook bij een pompmodel dat ovenbird niet kent; Alarm geeft altijd de waarschuwing. Vastleggen betekent bij Activiteit → Alarmen, zonder actief alarm of melding. Hoort de waterpomp volgens het model te draaien, dan is lage doorstroming altijd een alarm.',
  'cfg.safety_defrost_low_flow.opt.auto':
    'Automatisch (alleen vastleggen als het pompmodel dit zo hoort te doen)',
  'cfg.safety_defrost_low_flow.opt.alarm': 'Alarm',
  'cfg.safety_defrost_low_flow.opt.log': 'Alleen vastleggen (Activiteit → Alarmen)',
  'cfg.control_min_setpoint_c.label': 'Minimale aanvoertemperatuur',
  'cfg.control_min_setpoint_c.help':
    'De regelaar vraagt nooit koeler water dan dit. Leeg volgt de voorinstelling van de afgifte.',
  'cfg.control_max_supply_c.label': 'Maximale aanvoertemperatuur',
  'cfg.control_max_supply_c.help':
    'De regelaar vraagt nooit heter water dan dit. Hier kan het alleen omlaag; omhoog kan alleen via de omgeving of het opties-bestand.',
  'cfg.control_deadband_k.label': 'Dode band',
  'cfg.control_deadband_k.help':
    'De aanvoertemperatuur verandert pas als de berekende waarde minstens zoveel afwijkt. Groter betekent minder wijzigingen.',
  'cfg.control_dwell_s.label': 'Wachttijd tussen wijzigingen',
  'cfg.control_dwell_s.help':
    'Minimale tijd tussen twee wijzigingen van de aanvoertemperatuur. Beschermt het dagelijkse schrijfbudget; onder 10 minuten wordt afgeraden.',
  'cfg.control_ramp_enabled.label': 'Zachte start',
  'cfg.control_ramp_enabled.help':
    'Houd de aanvoertemperatuur na een compressorstart onder de stooklijn en geef haar langzaam vrij.',
  'cfg.control_ramp_hold_s.label': 'Aanhoudtijd zachte start',
  'cfg.control_ramp_hold_s.help':
    'Hoe lang de aanvoertemperatuur laag blijft na een compressorstart.',
  'cfg.control_ramp_max_below_curve_k.label': 'Diepte zachte start',
  'cfg.control_ramp_max_below_curve_k.help':
    'Hoever onder de stooklijn de aanvoertemperatuur mag beginnen, in K.',
  'cfg.control_ramp_release_k_per_h.label': 'Vrijgavesnelheid zachte start',
  'cfg.control_ramp_release_k_per_h.help':
    'Hoe snel de aanvoertemperatuur terugklimt naar de stooklijn, in K per uur.',
  'cfg.control_cycling_enabled.label': 'Pendelbeveiliging',
  'cfg.control_cycling_enabled.help':
    'Houdt de aanvoertemperatuur vroeg in een run hoog genoeg zodat de pomp niet stopt en herstart. Uitzetten geeft een waarschuwing.',
  'cfg.control_cycling_min_run_s.label': 'Venster van de pendelbeveiliging',
  'cfg.control_cycling_min_run_s.help':
    'De minimale looptijd die de beveiliging probeert veilig te stellen.',
  'cfg.control_pump_duty.label': 'Pompvermogen regelen',
  'cfg.control_pump_duty.help':
    'Laat de regelaar het maximale pompvermogen instellen: hoger tijdens verwarmen, lager in rust. Standaard uit: dit vervangt de eigen instelling van de pomp, dus vul eerst waarden in die bij je installatie passen (vraag je installateur) voordat je het aanzet.',
  'cfg.control_pump_duty_heat.label': 'Vermogen tijdens verwarmen',
  'cfg.control_pump_duty_heat.help': 'Maximaal pompvermogen terwijl de compressor draait (64–254).',
  'cfg.control_pump_duty_idle.label': 'Vermogen in rust',
  'cfg.control_pump_duty_idle.help': 'Maximaal pompvermogen terwijl de compressor uit is (64–254).',
  'cfg.control_pump_duty_idle_delay_s.label': 'Vertraging voor rustvermogen',
  'cfg.control_pump_duty_idle_delay_s.help':
    'Hoe lang na het stoppen van de compressor het rustvermogen wordt ingesteld.',
  'cfg.control_quiet_windows.label': 'Tijdvakken stille modus',
  'cfg.control_quiet_windows.help':
    'Dagelijkse tijdvakken waarin de pomp op het gekozen niveau in stille modus gaat. Een tijdvak dat eindigt voordat het begint loopt over middernacht.',
  'cfg.control_timezone.label': 'Tijdzone',
  'cfg.control_timezone.help':
    'De tijdzone van de stille tijdvakken, bijvoorbeeld Europe/Amsterdam.',
  'cfg.control_emitter.label': 'Afgifte',
  'cfg.control_emitter.help':
    'Het soort warmteafgifte. Het bepaalt de voorgestelde stooklijn, veiligheidsband en afstelling waar alle andere instellingen van uitgaan.',
  'cfg.control_emitter.opt.screed_floor': 'Vloerverwarming in dekvloer',
  'cfg.control_emitter.opt.mixed': 'Gemengd (vloer en lagetemperatuurradiatoren)',
  'cfg.control_emitter.opt.radiators': 'Radiatoren',
  'cfg.weather_enabled.label': 'Weersverwachting',
  'cfg.weather_enabled.help':
    'Haal een verwachting van de buitentemperatuur op voor de weerpagina. Alleen ter weergave: de regelaar gebruikt haar niet.',
  'cfg.weather_latitude.label': 'Breedtegraad',
  'cfg.weather_latitude.help': 'Graden noord, afgerond op 0,01°.',
  'cfg.weather_longitude.label': 'Lengtegraad',
  'cfg.weather_longitude.help': 'Graden oost, afgerond op 0,01°.',
  'cfg.weather_location_source.label': 'Bron van de locatie',
  'cfg.weather_location_source.help': 'Waar de locatie voor de verwachting vandaan komt.',
  'cfg.weather_location_source.opt.ha_zone_home': 'Thuiszone van Home Assistant',
  'cfg.weather_location_source.opt.manual': 'Handmatig ingevuld',
  'cfg.weather_location_source.opt.browser': 'Deze browser',
  'cfg.control_cycling_stop_delta_k.label': 'Pendelmodel: stopdelta',
  'cfg.control_cycling_stop_delta_k.help':
    'Onderdeel van het model van de eigen stopregel van de pomp.',
  'cfg.control_cycling_margin_k.label': 'Pendelmodel: marge',
  'cfg.control_cycling_margin_k.help':
    'Veiligheidsmarge bovenop het model van de stopregel van de pomp.',
  'cfg.control_rounding_hysteresis_k.label': 'Afrondingshysterese',
  'cfg.control_rounding_hysteresis_k.help':
    'Hysterese bij het afronden van de aanvoertemperatuur op hele graden.',
  'cfg.control_ramp_dwell_s.label': 'Staptijd zachte start',
  'cfg.control_ramp_dwell_s.help': 'Tijd per stap tijdens het vrijgeven van de zachte start.',
  'cfg.control_interval_s.label': 'Beslisinterval',
  'cfg.control_interval_s.help': 'Hoe vaak de regelaar een beslissing neemt.',
  'cfg.control_envelope_curve.label': 'Stooklijn van de veiligheidsband',
  'cfg.control_envelope_curve.help':
    'De stooklijn van de voorinstelling waaraan de veiligheidsband verankerd is. Een stooklijn die je aanpast moet binnen de band eromheen blijven.',
  'cfg.command_pump_duty_min.label': 'Laagst toegestane pompvermogen',
  'cfg.command_pump_duty_min.help': 'Harde ondergrens voor het opgedragen pompvermogen.',
  'cfg.command_pump_duty_max.label': 'Hoogst toegestane pompvermogen',
  'cfg.command_pump_duty_max.help': 'Harde bovengrens voor het opgedragen pompvermogen.',
  'cfg.hot_water.label': 'Tapwater',
  'cfg.hot_water.help':
    'Of de app tapwater toont: de pomp die een boiler opwarmt. Automatisch volgt wat de pomp meldt. Verborgen blijft een tapwaterrun zichtbaar, als “Pomp elders bezig”. Het verandert niets aan hoe ovenbird de pomp regelt.',
  'cfg.hot_water.opt.auto': 'Automatisch (zoals de pomp meldt)',
  'cfg.hot_water.opt.on': 'Tonen',
  'cfg.hot_water.opt.off': 'Verbergen',
  'cfg.history_retention_days.label': 'Bewaartijd geschiedenis',
  'cfg.history_retention_days.help': 'Hoeveel dagen geschiedenis worden bewaard.',
  'cfg.admin_password.label': 'Beheerderswachtwoord',
  'cfg.admin_username.label': 'Gebruikersnaam beheerder',
  'cfg.allow_commands.label': 'Opdrachten naar de warmtepomp sturen',
  'cfg.clock_speed.label': 'Snelheid simulatieklok',
  'cfg.clock_start.label': 'Start simulatieklok',
  'cfg.command_brokers.label': 'Brokers voor opdrachten',
  'cfg.command_daily_budget.label': 'Dagbudget voor schrijfacties',
  'cfg.command_escalation_factor.label': 'Escalatiefactor bij herhalen',
  'cfg.command_escalation_hours.label': 'Escalatieperiode bij herhalen',
  'cfg.command_hold_s.label': 'Pauze na een externe schrijfactie',
  'cfg.command_latch_after.label': 'Vergrendelen na mislukkingen',
  'cfg.command_max_retries.label': 'Maximaal aantal herhalingen',
  'cfg.command_min_spacing_s.label': 'Minimale tijd tussen opdrachten',
  'cfg.command_setpoint_register.label': 'Register voor de aanvoertemperatuur',
  'cfg.command_verify_timeout_s.label': 'Wachttijd voor verificatie',
  'cfg.config_seed.label': 'Startbestand voor de configuratie',
  'cfg.control_cycling_decrease_headroom_k.label': 'Pendelmodel: ruimte bij verlagen',
  'cfg.control_cycling_max_raise_k.label': 'Pendelmodel: grootste verhoging',
  'cfg.control_envelope_above_k.label': 'Veiligheidsband boven de stooklijn',
  'cfg.control_envelope_below_k.label': 'Veiligheidsband onder de stooklijn',
  'cfg.control_feedback_max_integration_step_s.label': 'Langste integratiestap',
  'cfg.control_mode.label': 'Hoogste regelmodus',
  'cfg.control_ramp_below_outlet_k.label': 'Startrem: onder aanvoer',
  'cfg.control_room_alive_decay_end_s.label': 'Vertrouwen in kamer eindigt (in leven)',
  'cfg.control_room_alive_decay_start_s.label': 'Vertrouwen in kamer neemt af vanaf (in leven)',
  'cfg.control_room_crosscheck_sustain_s.label': 'Duur van de kruiscontrole',
  'cfg.control_room_crosscheck_tau_s.label': 'Afvlakking van de kruiscontrole',
  'cfg.control_room_crosscheck_threshold_k.label': 'Drempel van de kruiscontrole',
  'cfg.control_room_decay_start_s.label': 'Vertrouwen in kamer neemt af vanaf',
  'cfg.control_state_max_age_s.label': 'Oudste regelaarstatus om te herstellen',
  'cfg.data_dir.label': 'Gegevensmap',
  'cfg.ha_entities.label': 'Home Assistant-entiteiten',
  'cfg.ha_token.label': 'Home Assistant-token',
  'cfg.ha_url.label': 'Adres van Home Assistant',
  'cfg.ha_url.help':
    'Waar ovenbird Home Assistant leest: http://<host>:8123 in je netwerk of je https-adres. Stel het in bij het onderdeel Home Assistant.',
  'cfg.ha_token.help':
    'Langlevende toegangstoken om Home Assistant te lezen. Hij wordt bewaard maar nooit meer getoond.',
  'cfg.heishamon_base.label': 'Basis van de HeishaMon-topics',
  'cfg.history_15m_days.label': '15-minutengeschiedenis bewaren',
  'cfg.history_15m_days.help':
    'Hoe lang de kwartiergemiddelden blijven. Ze vullen de grafieken over lange perioden. 0 bewaart ze altijd.',
  'cfg.history_1h_days.label': 'Uurgeschiedenis bewaren',
  'cfg.history_1h_days.help':
    'Hoe lang de uurgemiddelden blijven. Ze zijn klein; 0 bewaart ze altijd.',
  'cfg.history_1m_days.label': '1-minuutgeschiedenis bewaren',
  'cfg.history_1m_days.help':
    'Hoe lang de minuutgemiddelden blijven. Ze zijn het grootste deel van de database.',
  'cfg.history_archive_enabled.label': 'Jaararchief',
  'cfg.history_archive_enabled.help':
    'Bevries elke afgelopen maand in een zip in de datamap, bewaard hoe kort de historie ook blijft. Maanden downloaden of verwijderen onder Systeem → Data.',
  'cfg.history_decision_days.label': 'Beslissingen bewaren',
  'cfg.history_decision_days.help':
    'Hoe lang beslissingen, commando’s, alarmen en verwachtingen blijven.',
  'cfg.history_min_free_mb.label': 'Minimale vrije schijfruimte',
  'cfg.history_queue_size.label': 'Schrijfwachtrij geschiedenis',
  'cfg.history_raw_days.label': 'Ruwe geschiedenis bewaren',
  'cfg.history_raw_days.help':
    'Hoe lang elke ruwe meting blijft, zoals hij binnenkwam. Oudere data blijft als gemiddelden.',
  'cfg.history_snapshot_hours.label': 'Interval voor geschiedenis-snapshot',
  'cfg.http_allowed_origins.label': 'Toegestane web-origins',
  'cfg.http_host.label': 'Adres van de webserver',
  'cfg.http_port.label': 'Poort van de webserver',
  'cfg.ingress.label': 'Home Assistant-ingress',
  'cfg.log_level.label': 'Logniveau',
  'cfg.mqtt_ca_file.label': 'MQTT CA-certificaat',
  'cfg.mqtt_client_id.label': 'MQTT-client-id',
  'cfg.mqtt_host.label': 'MQTT-broker',
  'cfg.mqtt_inputs.label': 'Extra MQTT-invoer',
  'cfg.mqtt_password.label': 'MQTT-wachtwoord',
  'cfg.mqtt_port.label': 'MQTT-poort',
  'cfg.mqtt_tls.label': 'MQTT via TLS',
  'cfg.mqtt_username.label': 'MQTT-gebruikersnaam',
  'cfg.operate_token.label': 'Bedieningstoken',
  'cfg.safety_defrost_max_s.label': 'Langste ontdooiing',
  'cfg.safety_flow_sustain_s.label': 'Duur van te lage doorstroming',
  'cfg.safety_interval_s.label': 'Interval van de veiligheidscontrole',
  'cfg.safety_min_flow_lpm.label': 'Minimale doorstroming',
  'cfg.safety_outlet_margin_k.label': 'Marge op de aanvoer',
  'cfg.safety_outlet_sustain_s.label': 'Duur van te hete aanvoer',
  'cfg.simulation.label': 'Simulatie',
  'cfg.ui_dir.label': 'Map van de webinterface',
  'cfg.weather_sim_file.label': 'Bestand met gesimuleerd weer',
  'cfg.control_stove_enabled.label': 'Houtkachelmodus',
  'cfg.control_stove_enabled.help':
    'Als een houtkachel de kamer met de sensor verwarmt, schakelt ovenbird de verwarming terug in plaats van het hele huis af te laten koelen door de ruimtecorrectie.',
  'cfg.control_stove_auto.label': 'Kachel automatisch herkennen',
  'cfg.control_stove_auto.help':
    'Start de houtkachelmodus vanzelf als de kamer duidelijk warmer wordt dan de comforttemperatuur. Uit: alleen met de hand (Kachel aan… op Home).',
  'cfg.control_stove_enter_above_k.label': 'Starten boven comfort',
  'cfg.control_stove_enter_above_k.help':
    'De houtkachelmodus start als de kamer zoveel boven de comforttemperatuur komt, in K.',
  'cfg.control_stove_exit_hysteresis_k.label': 'Zoveel lager stoppen',
  'cfg.control_stove_exit_hysteresis_k.help':
    'Hij stopt pas als de kamer zoveel onder de startdrempel zit, in K, zodat hij niet aan en uit springt.',
  'cfg.control_stove_rise_enabled.label': 'Ook starten bij snelle stijging',
  'cfg.control_stove_rise_enabled.help':
    'Start eerder als de kamer snel warmer wordt terwijl hij al boven de comforttemperatuur zit.',
  'cfg.control_stove_rise_k.label': 'Snelle stijging',
  'cfg.control_stove_rise_k.help':
    'Zoveel moet de kamer binnen de periode stijgen om als snelle stijging te tellen, in K.',
  'cfg.control_stove_rise_window_s.label': 'Periode snelle stijging',
  'cfg.control_stove_rise_window_s.help': 'De tijd waarin die stijging moet gebeuren.',
  'cfg.control_stove_backoff_k.label': 'Terugschakelen',
  'cfg.control_stove_backoff_k.help':
    'Zoveel gaat de stooklijn omlaag terwijl de kachel brandt, in K. De pomp blijft draaien, dus de rest van het huis wordt nog verwarmd; een referentieruimte zorgt dat het daar warm blijft.',
  'cfg.control_stove_to_minimum.label': 'Terug tot het minimum',
  'cfg.control_stove_to_minimum.help':
    'Verlaag de aanvoertemperatuur helemaal tot het veiligheidsminimum in plaats van met de vaste stap.',
  'cfg.control_stove_min_active_s.label': 'Kortste periode',
  'cfg.control_stove_min_active_s.help':
    'Na een automatische start blijft de houtkachelmodus minstens zo lang aan.',
  'cfg.control_stove_max_active_s.label': 'Langste periode',
  'cfg.control_stove_max_active_s.help':
    'Na zo lang stopt hij uiterlijk, ook als de kamer nog warm is.',
  'cfg.control_stove_reentry_hold_s.label': 'Wachten na onbetrouwbare kamerwaarde',
  'cfg.control_stove_reentry_hold_s.help':
    'Na een onbetrouwbare kamerwaarde moet de waarde weer zo lang te vertrouwen zijn voordat de kachel herkend kan worden.',
  'cfg.control_stove_reference_signal.label': 'Referentieruimte',
  'cfg.control_stove_reference_signal.help':
    'Optioneel: een sensor in een andere ruimte, zoals de hal. Wordt het daar te koud, dan schakelt ovenbird minder terug.',
  'cfg.control_stove_reference_floor_c.label': 'Referentieruimte minstens',
  'cfg.control_stove_reference_floor_c.help':
    'Onder deze temperatuur in de referentieruimte wordt het terugschakelen kleiner.',
  'cfg.control_stove_reference_band_k.label': 'Referentieband',
  'cfg.control_stove_reference_band_k.help':
    'Over zoveel K onder de ondergrens zakt het terugschakelen naar nul.',
  'cfg.house_floor_area_m2.label': 'Verwarmd vloeroppervlak',
  'cfg.house_floor_area_m2.help':
    'Het verwarmde vloeroppervlak van het huis in m², voor de indicatieve isolatiescore op de pagina Huis (warmteverlies per m²). Laat leeg om alleen het warmteverlies in W/K te zien.',
  'cfg.house_learn_enabled.label': 'Huismodel leren',
  'cfg.house_learn_enabled.help':
    'Laat ovenbird het huismodel zelf leren uit zijn eigen geschiedenis. Zet het uit om nieuwe runs te stoppen; het model dat in gebruik is blijft.',
  'cfg.house_learn_interval_h.label': 'Leerinterval',
  'cfg.house_learn_interval_h.help':
    'Uren tussen twee leerrondes, van 24 (dagelijks) tot 720 (maandelijks). Standaard 168, eens per week.',
  'cfg.mqtt_host.help':
    'Hostnaam of IP-adres van de MQTT-broker waarop HeishaMon publiceert, zoals 192.0.2.20 of mosquitto.',
  'cfg.mqtt_port.help': 'De poort van de broker: meestal 1883, of 8883 met TLS.',
  'cfg.mqtt_username.help':
    'Gebruikersnaam voor de broker. Laat leeg als de broker anonieme clients toelaat.',
  'cfg.mqtt_password.help':
    'Wachtwoord voor de broker. Het wordt opgeslagen, maar nooit meer getoond.',
  'cfg.mqtt_tls.help':
    'Versleuteld verbinden (TLS). Het certificaat van de broker wordt gecontroleerd.',
  'cfg.mqtt_ca_file.help':
    'Pad op de ovenbird-server naar een CA-certificaat, voor een broker met een eigen certificaatautoriteit. Leeg gebruikt de vertrouwde certificaten van het systeem.',
  'cfg.mqtt_client_id.help':
    'De naam waarmee ovenbird verbinding maakt. Leeg kiest er zelf een; vul hem in als de broker alleen bekende clients toelaat.',
  'cfg.heishamon_base.help':
    'Het basistopic waaronder HeishaMon publiceert (de MQTT topic base), meestal panasonic_heat_pump.',
  'cfg.mqtt_inputs.help':
    'Extra MQTT-topics die ovenbird als sensor leest, zoals een thermometer die via MQTT publiceert. Ze staan in de sensorlijsten naast de sensoren uit Home Assistant.',
  'cfg.control_outside_signal.label': 'Buitensensor voor de stooklijn',
  'cfg.control_outside_signal.help':
    'Optioneel: een thermometer buiten (een sensor uit Home Assistant of een MQTT-invoer, in °C) voor de stooklijn in plaats van de eigen sensor van de pomp. De veiligheidsband blijft de sensor van de pomp gebruiken. Zonder verse, aannemelijke waarde valt de stooklijn terug op de sensor van de pomp.',
  'cfg.control_outside_max_age_s.label': 'Buitensensor geldt als vers tot',
  'cfg.control_outside_max_age_s.help':
    'Hoe oud de waarde van de gekozen buitensensor mag zijn. Is hij ouder, dan gebruikt de stooklijn de sensor van de pomp tot de gekozen sensor weer meldt.',
  'cfg.control_outside_plausible_min_c.label': 'Buitensensor aannemelijk vanaf',
  'cfg.control_outside_plausible_min_c.help':
    'De laagste buitentemperatuur die de gekozen sensor mag melden. Een koudere waarde geldt als storing: de stooklijn gebruikt de sensor van de pomp tot de gekozen sensor weer een aannemelijke waarde meldt.',
  'cfg.control_outside_plausible_max_c.label': 'Buitensensor aannemelijk tot',
  'cfg.control_outside_plausible_max_c.help':
    'De hoogste buitentemperatuur die de gekozen sensor mag melden. Een warmere waarde geldt als storing: de stooklijn gebruikt de sensor van de pomp tot de gekozen sensor weer een aannemelijke waarde meldt.',
  'cfg.control_outside_max_deviation_k.label': 'Buitensensor mag van de pomp afwijken met',
  'cfg.control_outside_max_deviation_k.help':
    'Hoe ver de gekozen sensor van de eigen buitensensor van de pomp mag liggen. Liggen ze verder uit elkaar, dan klopt een van beide niet en gebruikt de stooklijn de sensor van de pomp tot ze weer overeenkomen.',
};
