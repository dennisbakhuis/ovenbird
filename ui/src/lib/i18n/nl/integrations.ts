import type { integrations as en } from '$lib/i18n/en/integrations';

export const integrations: Record<keyof typeof en, string> = {
  section_mqtt: 'MQTT',
  group_mqtt: 'MQTT-broker',
  mqttTitle: 'MQTT-broker',
  mqttIntro:
    'ovenbird leest de warmtepomp via HeishaMon op deze MQTT-broker. Test nieuwe instellingen eerst: opslaan kan na een geslaagde test, en ovenbird gaat terug naar de vorige broker als de nieuwe binnen 60 s geen HeishaMon-gegevens levert.',
  mqttStatusConnected: 'Verbonden',
  mqttStatusDown: 'Niet verbonden',
  mqttNow: 'Nu {broker} · basis {base} · {n} HeishaMon-berichten in deze sessie',
  mqttStatusMissing:
    'Deze service heeft geen MQTT-verbinding die je hier kunt wijzigen. Stel de broker in bij de installatie.',
  mqttLocked: 'Ingesteld door de installatie ({env}). Wijzig het daar; hier kan het niet.',
  mqttPasswordStored: 'Er is een wachtwoord opgeslagen. Laat dit leeg om het te houden.',
  mqttPasswordNone: 'Er is geen wachtwoord opgeslagen.',
  mqttPasswordPlaceholder: 'Optioneel',
  mqttPasswordDrops:
    'Een nieuwe broker of poort, TLS uitzetten of een ander CA-bestand zonder wachtwoord laat het opgeslagen wachtwoord vallen, zodat het nooit naar een andere broker gaat.',
  mqttCaPlaceholder: 'De certificaten van het systeem',
  mqttClientPlaceholder: 'Kiest ovenbird zelf',
  mqttMore: 'Versleuteling en client',
  mqttProblem_host: 'Vul de hostnaam of het IP-adres van de broker in.',
  mqttProblem_port: 'Een poort is een heel getal van 1 tot en met 65535.',
  mqttProblem_base: 'Laat de jokertekens # en + weg uit het basistopic.',
  mqttProblem_spaces: 'Laat spaties weg.',
  mqttTest: 'Verbinding testen',
  mqttTesting: 'Bezig met testen… (tot 30 s)',
  mqttSave: 'Verbinding opslaan',
  mqttSaving: 'Bezig met opslaan…',
  mqttSaveBlock_commands:
    'Opdrachten aan de pomp staan aan, dus de broker kan hier niet worden gewijzigd: wijzig hem in de installatie en herstart.',
  mqttSaveBlock_applying: 'De laatste wijziging wordt nog gecontroleerd.',
  mqttSaveBlock_locked: 'De installatie bepaalt de broker; hier kan hij niet worden gewijzigd.',
  mqttSaveBlock_unchanged: 'Wijzig eerst een instelling. Testen wat nu draait kan altijd.',
  mqttSaveBlock_untested: 'Test deze instellingen eerst; na een geslaagde test kun je ze opslaan.',
  mqttSaveBlock_failed: 'De test van deze instellingen mislukte. Pas ze aan en test opnieuw.',
  mqttSaveBlock_changed:
    'De instellingen zijn gewijzigd sinds de test. Test opnieuw om ze op te slaan.',
  mqttVerdict_ok: 'De broker werkt en er komen HeishaMon-gegevens binnen',
  mqttVerdict_no_heishamon: 'Verbonden, maar geen HeishaMon-gegevens onder deze basis',
  mqttVerdict_failed: 'Geen werkende verbinding',
  mqttTest_invalid: 'Deze instellingen zijn niet geldig.',
  mqttTest_unreachable: 'De broker is op dit adres en deze poort niet bereikbaar.',
  mqttTest_tls:
    'De versleutelde verbinding mislukte. Controleer TLS, de poort en het CA-certificaat.',
  mqttTest_auth_failed: 'De broker weigerde de gebruikersnaam of het wachtwoord.',
  mqttTest_refused: 'De broker weigerde de verbinding.',
  mqttTest_timeout: 'De broker antwoordde niet op tijd.',
  mqttTest_no_heishamon:
    'Onder dit basistopic kwam geen HeishaMon-waarde binnen. Vergelijk het met de basis in de MQTT-instellingen van HeishaMon.',
  mqttResultBroker: 'Broker',
  mqttResultConnected: 'Verbonden',
  mqttResultHeishamon: 'HeishaMon-gegevens',
  mqttResultTopic: 'Eerste waarde op',
  mqttRefused_test_required:
    'Test eerst precies deze instellingen met succes. Een test geldt 10 minuten.',
  mqttRefused_commands_enabled:
    'Opdrachten aan de pomp staan aan, dus de broker kan hier niet worden gewijzigd: wijzig hem in de installatie en herstart.',
  mqttRefused_apply_pending:
    'De laatste wijziging van de broker wordt nog gecontroleerd. Wacht de uitkomst af.',
  mqttApplying:
    'Bezig met overschakelen naar de nieuwe broker… ovenbird wacht tot 60 s op HeishaMon-gegevens en gaat anders terug naar de vorige broker.',
  mqttApplied: 'Toegepast om {time}: verbonden, en er komen HeishaMon-gegevens binnen.',
  mqttReverted:
    'Teruggedraaid om {time}: de nieuwe broker leverde niet op tijd HeishaMon-gegevens, dus ovenbird zit weer op de vorige broker.',
  mqttRevertFailed:
    'Om {time} leverde de nieuwe broker geen HeishaMon-gegevens en lukte teruggaan naar de vorige broker niet. Stel hier of in de installatie een werkende broker in.',
  mqttCommandsNotice:
    'Opdrachten aan de pomp staan aan. De opdrachtverbinding houdt de broker waarmee ze startte, dus de broker kan hier niet worden gewijzigd. Testen kan wel.',
  overviewMqttInputs: 'Extra MQTT-sensoren: {n}',
  mqttInputsTitle: 'Extra MQTT-sensoren',
  mqttInputsIntro:
    'Topics die ovenbird als sensor leest. Nadat je ze hebt toegepast staan ze in de sensorlijsten, bijvoorbeeld als buitensensor van de stooklijn.',
  mqttInputTopic: 'Topic',
  mqttInputSignal: 'Signaalnaam',
  mqttInputUnit: 'Eenheid',
  mqttInputMin: 'Minimum',
  mqttInputMax: 'Maximum',
  mqttInputAdd: 'MQTT-sensor toevoegen',
  mqttInputRemove: '{topic} verwijderen',
  mqttInputNone: 'Nog geen extra MQTT-sensoren.',
  mqttInputSignalHint: 'Verschijnt als {signal}',
  mqttInputRow: 'MQTT-sensor {n}',
  mqttInputRangeHint: 'Waarden buiten minimum en maximum worden genegeerd.',
  check_mqtt_topic_missing: 'Elke MQTT-sensor heeft een topic nodig.',
  check_mqtt_topic_wildcard: 'Een topic kan de jokertekens # of + niet bevatten.',
  check_mqtt_topic_duplicate: 'Elk topic kan maar één keer in de lijst staan.',
  check_mqtt_range: 'Het minimum mag niet boven het maximum liggen.',
  check_mqtt_topic_too_long: 'Een topic kan hoogstens 256 tekens lang zijn.',
  check_mqtt_topic_reserved:
    'Dit topic hoort bij het HeishaMon-board zelf (main, commands, stats, LWT); het kan geen extra sensor zijn.',
  check_mqtt_signal_too_long: 'Een signaalnaam kan hoogstens 256 tekens lang zijn.',
  check_mqtt_signal_reserved:
    'Deze signaalnaam is gereserveerd voor de warmtepomp, Home Assistant of ovenbird zelf (main/, ha/, commands/, derived/, stats, LWT).',
  check_mqtt_signal_duplicate: 'Elke signaalnaam kan maar één keer gebruikt worden.',
  check_mqtt_inputs_invalid: 'Herstel eerst de gemarkeerde MQTT-sensoren.',
  check_not_mqtt_inputs: 'MQTT-sensoren moeten een lijst van topics zijn.',
  check_ca_file_missing: 'Het CA-certificaatbestand bestaat niet op de ovenbird-server.',
  curveOutsideTitle: 'Buitentemperatuur',
  curveOutsideOnly:
    'Alleen de stooklijn gebruikt deze sensor. De veiligheidsband, de veiligheidsbewaking en het huismodel blijven de eigen sensor van de pomp gebruiken.',
  curveOutsidePump: 'Geen sensor gekozen: de stooklijn gebruikt de eigen buitensensor van de pomp.',
  curveOutsideFallback:
    'De gekozen sensor heeft geen verse, aannemelijke waarde, dus de stooklijn gebruikt nu de sensor van de pomp.',
  curveOutsideUsing: 'De stooklijn gebruikt nu {name}.',
  fact_outside_source: 'De stooklijn gebruikt de buitentemperatuur van {name} ({raw} °C).',
  fact_outside_fallback:
    'De buitensensor {name} {why}, dus de stooklijn gebruikt de sensor van de pomp ({raw} °C).',
  outsideWhy_stale: 'is {min} min oud',
  outsideWhy_missing: 'heeft geen waarde',
  outsideWhy_implausible: 'meldt een onwaarschijnlijke waarde',
  outsideWhy_deviates: 'wijkt te veel af van de eigen sensor van de pomp',
  outsideWhy_unknown: 'is niet vers',
  stateOutsideFrom: 'van {name}',
  stateOutsideFallback: 'sensor van de pomp (terugval)',
};
