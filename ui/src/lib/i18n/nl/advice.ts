export const advice = {
  alarmNow_mode_mismatch:
    'Stuurt niets tot de pomp weer verwarmt in de stand Direct; de pomp houdt haar huidige aanvoertemperatuur.',
  alarmYou_mode_mismatch:
    'Kijk op de afstandsbediening van Panasonic of de pomp verwarmt en de watertemperatuur op Direct staat, niet op de stooklijn.',
  alarmNow_verification_failed:
    'Houdt zijn opdrachten een tijd tegen; de pomp houdt de waarde die ze meldt. Een mislukte pompinstelling van jou stopt de regeling niet.',
  alarmYou_verification_failed:
    'Kijk of HeishaMon online is en de pomp aan staat. Was het een instelling die jij wijzigde, dan kent je pompmodel die misschien niet.',
  alarmNow_write_budget:
    'Stuurt vandaag niets meer behalve veiligheidscorrecties; de pomp houdt haar laatste waarden. Om middernacht UTC begint het budget opnieuw.',
  alarmYou_write_budget:
    'Niet dringend. Gebeurt het vaak, zoek dan bij Activiteit → Opdrachten naar een waarde die steeds verandert.',
  alarmNow_foreign_writer:
    'Houdt zijn opdrachten tegen zolang de blokkade duurt, eerst 1 uur; de pomp houdt de waarde van de andere schrijver.',
  alarmYou_foreign_writer:
    'Zoek uit wie de pomp wijzigde (afstandsbediening, Node-RED, een app) en stop dat. Wacht daarna, of geef vrij bij Activiteit → Blokkades.',
  alarmNow_hold_latched:
    'Stuurt niets tot een beheerder de blokkade vrijgeeft; de pomp houdt haar huidige waarden.',
  alarmYou_hold_latched:
    'Zoek uit wat de pomp steeds wijzigt en stop dat, en geef de blokkade dan vrij bij Activiteit → Blokkades.',
  alarmNow_heishamon_restarted:
    'Stuurt zijn eigen waarden opnieuw; waarden die door de herstart veranderden, tellen niet als een andere schrijver.',
  alarmYou_heishamon_restarted:
    'Je hoeft niets te doen. Herstart HeishaMon vaak, kijk dan naar de voeding en de wifi.',
  alarmNow_correction_failed:
    'Kreeg de aanvoertemperatuur niet onder het maximum; probeert het later opnieuw en laat intussen alleen lagere waarden door.',
  alarmYou_correction_failed:
    'Zet een lagere watertemperatuur op de afstandsbediening, zoek uit wat hem steeds verhoogt en stop dat. Twijfel je, bel je installateur.',
  alarmNow_setpoint_above_max:
    'Stuurt meteen zijn eigen veilige aanvoertemperatuur om de pomp onder het maximum te krijgen, hooguit 3 keer per uur.',
  alarmYou_setpoint_above_max:
    'Zoek uit wie de hoge waarde instelde (afstandsbediening, Node-RED, een app) en stop dat.',
  alarmNow_outlet_overshoot:
    'Laat alleen lagere watertemperaturen door tot het aanvoerwater is afgekoeld.',
  alarmYou_outlet_overshoot:
    'Kijk op de afstandsbediening naar een foutcode en of de kranen van vloer en radiatoren open zijn. Blijft het, bel je installateur.',
  alarmNow_low_flow:
    'Laat alleen lagere watertemperaturen door tot het debiet weer boven het minimum zit.',
  alarmYou_low_flow:
    'Zet dichte kranen van radiatoren of vloergroepen open, controleer de waterdruk en het filter. Blijft het, bel je installateur.',
  alarmNow_pump_error: 'Laat alleen lagere watertemperaturen door zolang de pomp een fout meldt.',
  alarmYou_pump_error:
    'Lees de foutcode af op de afstandsbediening van Panasonic en zoek hem op in de handleiding, of bel je installateur.',
  alarmNow_backup_heater:
    'Er verandert niets: hij regelt gewoon door. Het elektrische bijverwarmingselement gebruikt wel veel stroom.',
  alarmYou_backup_heater:
    'Kijk waarom het aan staat: strenge kou, een ontdooiprobleem of de instelling op de afstandsbediening. Twijfel je, vraag je installateur.',
  alarmNow_backup_heater_allowed:
    'Er verandert niets; het meldt alleen dat de pomp haar elektrische bijverwarming mag inschakelen.',
  alarmYou_backup_heater_allowed:
    'Je hoeft niets te doen. Wil je de bijverwarming nooit, vraag dan je installateur of die geblokkeerd kan worden.',
  alarmNow_heating_off_outdoor:
    'Beslist en stuurt gewoon door, maar boven deze buitentemperatuur verwarmt de pomp zelf niet.',
  alarmYou_heating_off_outdoor:
    'Bij zacht weer hoef je niets te doen. Wordt het huis koud, verhoog dan Verwarming uit boven buitentemperatuur op de pagina Pomp.',
  alarmNow_defrost_stuck:
    'Zoals bij elke ontdooiing: de ruimtecorrectie staat stil en de aanvoertemperatuur gaat niet omlaag tot het ontdooien klaar is.',
  alarmYou_defrost_stuck:
    'Kijk bij de buitenunit naar ijs, sneeuw of een geblokkeerde ventilator. Gebeurt het vaker, bel je installateur.',
  alarmNow_room_below_floor:
    'De ruimtecorrectie, als die aan staat, verhoogt de watertemperatuur binnen haar grens; het alarm zelf verandert niets.',
  alarmYou_room_below_floor:
    'Kijk of er ramen openstaan of kranen dicht zijn. Is het huis bij elk weer te koud, zet de stooklijn dan hoger.',
  alarmNow_room_sensor_silent:
    'De ruimtecorrectie pauzeert: hij regelt op de stooklijn, en een correctie die verwarmt zwakt in 24 uur af.',
  alarmYou_room_sensor_silent:
    'Controleer de batterij van de kamersensor en zijn verbinding in Home Assistant.',
  alarmNow_room_sensor_quiet:
    'De kamer mag de watertemperatuur niet meer verlagen; wat er sinds de stilte aan koeling is geleerd, wordt teruggedraaid.',
  alarmYou_room_sensor_quiet:
    'Controleer de batterij en de verbinding van de sensor. Het alarm verdwijnt bij zijn volgende melding.',
  alarmNow_room_report_overdue:
    'De ruimtecorrectie pauzeert zodra de waarde te oud is: hij regelt op de stooklijn tot de sensor weer meldt.',
  alarmYou_room_report_overdue:
    'Controleer de batterij en de verbinding van de sensor. Meldt hij alleen bij verandering, zet Type sensor dan op Bij verandering.',
  alarmNow_room_implausible:
    'De ruimtecorrectie pauzeert: hij regelt op de stooklijn tot de kamersensor en de controlesensor het weer eens zijn.',
  alarmYou_room_implausible:
    'Vergelijk beide sensoren en verplaats of vervang de verkeerde, of haal de Controlesensor weg bij Instellingen.',
  alarmNow_ha_link_down:
    'Regelt door; kamerwaarden uit Home Assistant worden korter vertrouwd, daarna regelt hij op de stooklijn.',
  alarmYou_ha_link_down:
    'Kijk of Home Assistant draait en of het adres en het token die ovenbird gebruikt nog werken.',
  alarmNow_config_reset:
    'Draait in Schaduw op de standaardwaarden van de installatie: hij beslist elke minuut maar stuurt niets.',
  alarmYou_config_reset:
    'Controleer de instellingen, gebruik Importeren uit bestand… bij Versies en back-up als je een export hebt, en klik dan op Bevestigen.',
  alarmNow_pump_setting_changed:
    'Er verandert niets; het noteert dat een pompinstelling zonder ovenbird veranderde. Het alarm verdwijnt na 24 uur.',
  alarmYou_pump_setting_changed:
    'Je hoeft niets te doen als jij het op de afstandsbediening deed. Zo niet, zoek dan uit wie.',
  alarmNow_envelope_mismatch:
    'Houdt de waarde die de veiligheidsregel schreef, in plaats van die als een wijziging door een ander te zien, en houdt zijn volgende waarden binnen de band van de regel. Het alarm verdwijnt zodra zijn eigen waarde weer binnen de band ligt.',
  alarmYou_envelope_mismatch:
    'Meestal niets. Komt het terug, controleer dan of de instellingen van de veilige lijn in ovenbird overeenkomen met de regel op de HeishaMon.',
  alarmNow_notify_failing:
    'Houdt elk alarm op het scherm en probeert de wachtende meldingen opnieuw te versturen; dit alarm zelf wordt niet verstuurd.',
  alarmYou_notify_failing:
    'Controleer de ntfy-server, het topic en de internetverbinding en gebruik daarna Test sturen bij Systeem.',
  alarmNow_release_interrupted:
    'Blijft gepauzeerd en stuurt niets; de pomp houdt de waarden die ze nu heeft.',
  alarmYou_release_interrupted:
    'Open Proef, kijk welke waarden terug zijn en gebruik Regeling nu teruggeven opnieuw, of zet de rest met de hand.',
  alarmNow_stove_reference_missing:
    'Houdt maar een deel van de terugschakeling aan tot de referentieruimte weer meet, zodat de rest van het huis minder afkoelt.',
  alarmYou_stove_reference_missing:
    'Controleer de sensor van de referentieruimte (batterij, Home Assistant) of kies een andere bij Houtkachel.',
  alarmNow_archive_failing:
    'Regelt en registreert door. Het opschonen wacht tot 3 dagen op het archief en verwijdert daarna oude historie, ook als die niet gearchiveerd is.',
  alarmYou_archive_failing:
    'Controleer de vrije ruimte van de datamap en de archieffout onder Systeem → Data. Het alarm verdwijnt bij de volgende geslaagde kopie.',
  alarmNow_archive_rebuilt:
    'Zette de beschadigde werkkopie opzij (.corrupt-bestand in de archiefmap) en bouwde de maand opnieuw op uit de historie die nog bewaard is. Het alarm verdwijnt na 24 uur.',
  alarmYou_archive_rebuilt:
    'Je hoeft niets te doen. Dagen die de historie niet meer had, ontbreken in die maand; bewaar het .corrupt-bestand als je ze wilt proberen te redden.',
  alarmNow_room_unit_refused:
    'Ruimtecorrectie staat uit: zonder eenheid is de waarde niet veilig te lezen, dus het regelt op de stooklijn.',
  alarmYou_room_unit_refused:
    'Geef de sensor een temperatuureenheid in Home Assistant (°C of °F), of zet Home Assistant op het metrische stelsel.',
  alarmNow_outside_sensor_stale:
    'Regelt door; de stooklijn gebruikt de eigen buitensensor van de pomp tot de gekozen sensor weer meldt.',
  alarmYou_outside_sensor_stale:
    'Controleer de buitensensor (batterij, Home Assistant of MQTT) of kies een andere bij Stooklijn.',
  alarmNow_mqtt_revert_failed:
    'Blijft op de nieuwe broker, die geen pompgegevens levert: de regeling valt terug zoals bij elk verlies van pompgegevens.',
  alarmYou_mqtt_revert_failed:
    'Stel een werkende broker in bij MQTT (testen, dan opslaan) of in de installatie en herstart.',
  alarmNow_outside_sensor_implausible:
    'Regelt door; de stooklijn gebruikt de eigen buitensensor van de pomp tot de gekozen sensor weer een aannemelijke waarde meldt.',
  alarmYou_outside_sensor_implausible:
    'Controleer waar de buitensensor hangt (volle zon, een warme muur) en wat hij meldt, of pas zijn grenzen aan bij Stooklijn.',
  alarmNow_mqtt_connection_reverted: 'Draait door op de vorige broker, zoals voor de wijziging.',
  alarmYou_mqtt_connection_reverted:
    'Controleer adres, poort, gebruikersnaam en HeishaMon-basis van de nieuwe broker, test opnieuw bij MQTT en sla op zodra de test HeishaMon-gegevens vindt.',
};
