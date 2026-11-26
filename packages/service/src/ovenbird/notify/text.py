"""Words of the ntfy messages in English and Dutch.

Every alarm has a display name, what ovenbird does now and what the person can do,
the same words the UI shows on the alarm card; the journal codes (hold, wood stove,
envelope rule), the operator events and the test message have a title. Unknown codes
fall back to the code itself, so a new alarm is still sent, only less readable.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final, Literal

type Language = Literal["en", "nl"]


@dataclass(frozen=True, slots=True)
class AlarmText:
    """How one alarm reads on the phone.

    Parameters
    ----------
    name
        Display name.
    now
        What ovenbird does while it is active.
    you
        What the person can do.
    """

    name: str
    now: str
    you: str


EN: Final[dict[str, AlarmText]] = {
    "mode_mismatch": AlarmText(
        "Pump mode mismatch",
        "Sends nothing until the pump is back in Direct mode and heating; the pump keeps its "
        "current setpoint.",
        "Check on the Panasonic remote that the pump heats and its water temperature is set to "
        "Direct, not to the curve.",
    ),
    "verification_failed": AlarmText(
        "Command not confirmed",
        "Holds its commands for a while; the pump keeps the value it reports.",
        "Check that HeishaMon is online and the pump is on.",
    ),
    "write_budget": AlarmText(
        "Write budget used up",
        "Sends nothing more today except safety corrections; the pump keeps its last values.",
        "Nothing urgent. If it happens often, look in Activity for a value that keeps changing.",
    ),
    "foreign_writer": AlarmText(
        "Someone else changed the pump",
        "Holds its writes for the hold time, 1 hour at first; the pump keeps the value the other "
        "writer set.",
        "Find out who changed the pump (remote, Node-RED, an app) and stop it. Then wait, or "
        "release the hold in Activity → Holds.",
    ),
    "hold_latched": AlarmText(
        "ovenbird waits for a release",
        "Sends nothing until an administrator releases the hold; the pump keeps its current "
        "values.",
        "Find out what keeps changing the pump and stop it, then release the hold in Activity → "
        "Holds.",
    ),
    "heishamon_restarted": AlarmText(
        "HeishaMon restarted",
        "Sends its own values again.",
        "Nothing to do. If HeishaMon restarts often, check its power supply and WiFi.",
    ),
    "correction_failed": AlarmText(
        "Safety correction failed",
        "Could not bring the setpoint back under the maximum; it tries again later and meanwhile "
        "releases only lower values.",
        "Set a lower water temperature on the remote, find out what keeps raising it and stop "
        "it. Call your installer if unsure.",
    ),
    "setpoint_above_max": AlarmText(
        "Setpoint above maximum",
        "Sends its own safe setpoint right away to bring the pump back under the maximum.",
        "Find out who set the high value (remote, Node-RED, an app) and stop it.",
    ),
    "outlet_overshoot": AlarmText(
        "Outlet too hot",
        "Releases only lower water temperatures until the water leaving the pump has cooled down.",
        "Check the remote for an error code and that floor and radiator valves are open. If it "
        "stays, call your installer.",
    ),
    "low_flow": AlarmText(
        "Low flow",
        "Releases only lower water temperatures until the flow is back above the minimum.",
        "Open closed radiator or floor valves, check the water pressure and the filter. If it "
        "stays, call your installer.",
    ),
    "low_flow_defrost": AlarmText(
        "No flow during defrost",
        "Nothing to correct: the pump runs its own defrost and ovenbird never writes during a "
        "defrost. The normal low-flow protection resumes when the defrost ends.",
        "If the message names deice mode 2, the pump stops its water pump by design (return "
        "water below 27 °C) and the defrost lasts longer; if that happens often, a slightly "
        "higher minimum water temperature in frosty weather avoids it. Otherwise the pump "
        "should keep running: have the water pump, flow sensor and filter checked.",
    ),
    "pump_error": AlarmText(
        "Pump error",
        "Releases only lower water temperatures while the pump reports an error.",
        "Read the error code on the Panasonic remote and look it up in the manual, or call your "
        "installer.",
    ),
    "backup_heater": AlarmText(
        "Backup heater on",
        "Keeps controlling as usual. The electric backup heater uses a lot of electricity.",
        "Check why it runs: very cold weather, a defrost problem or its setting on the remote.",
    ),
    "backup_heater_allowed": AlarmText(
        "Backup heater allowed",
        "Nothing changes; the pump may switch on its electric backup heater.",
        "Nothing to do.",
    ),
    "heating_off_outdoor": AlarmText(
        "Above heating-off temperature",
        "Keeps deciding and sending, but the pump itself does not heat above this outdoor "
        "temperature.",
        "Nothing to do in mild weather.",
    ),
    "defrost_stuck": AlarmText(
        "Defrost taking too long",
        "Room correction is frozen and the setpoint is not lowered until the defrost ends.",
        "Look at the outdoor unit for ice, snow or a blocked fan. If it keeps happening, call "
        "your installer.",
    ),
    "room_below_floor": AlarmText(
        "Room too cold",
        "Room correction, if on, keeps raising the water temperature within its limit.",
        "Check for open windows or closed valves.",
    ),
    "room_sensor_silent": AlarmText(
        "Room sensor silent",
        "Room correction is paused: it runs on the heating curve.",
        "Check the room sensor's battery and its connection in Home Assistant.",
    ),
    "mqtt_connection_reverted": AlarmText(
        "Broker change undone",
        "Back on the previous broker: the new one gave no HeishaMon data in time.",
        "Check the broker settings and test them again under Settings, MQTT.",
    ),
    "mqtt_revert_failed": AlarmText(
        "Broker change stuck",
        "The new broker gave no HeishaMon data and the previous one could not be put back.",
        "Set a working broker under Settings, MQTT, or in the deployment.",
    ),
    "outside_sensor_stale": AlarmText(
        "Outside sensor stale",
        "The heating curve uses the pump's own outside sensor.",
        "Check the outside sensor's battery and its connection.",
    ),
    "outside_sensor_implausible": AlarmText(
        "Outside sensor implausible",
        "The heating curve uses the pump's own outside sensor.",
        "Check where the outside sensor hangs (sun, wall, heat) and what it reports.",
    ),
    "room_sensor_quiet": AlarmText(
        "Room sensor quiet",
        "No longer lets the room lower the water temperature.",
        "Check the sensor's battery and connection.",
    ),
    "room_report_overdue": AlarmText(
        "Room report overdue",
        "Room correction pauses once the value is too old: it runs on the heating curve.",
        "Check the sensor's battery and connection.",
    ),
    "room_implausible": AlarmText(
        "Room value implausible",
        "Room correction is paused: it runs on the heating curve until both room sensors agree "
        "again.",
        "Compare both sensors and move or replace the wrong one.",
    ),
    "room_unit_refused": AlarmText(
        "Room value has no usable unit",
        "Room correction pauses: it runs on the heating curve as if the room value were missing.",
        "Give the sensor a temperature unit in Home Assistant, or pick another room sensor.",
    ),
    "ha_link_down": AlarmText(
        "Home Assistant link down",
        "Keeps controlling; room values from Home Assistant are trusted for a shorter time.",
        "Check that Home Assistant is running and that the address and token ovenbird uses "
        "still work.",
    ),
    "config_reset": AlarmText(
        "Configuration reset",
        "Runs in Shadow on the installation defaults: it decides every minute but sends "
        "nothing to the pump.",
        "Open ovenbird, check the settings, import an export if you have one, then click "
        "Acknowledge.",
    ),
    "pump_setting_changed": AlarmText(
        "Pump setting changed",
        "Nothing changes; it notes that a pump setting changed without ovenbird.",
        "Nothing to do if you changed it on the remote. If not, find out who did.",
    ),
    "envelope_mismatch": AlarmText(
        "Value outside the safety rule",
        "Keeps the value the safety rule wrote and keeps its next values inside the rule's band.",
        "Usually nothing. If it comes back, check that the envelope settings match the rule on "
        "the HeishaMon.",
    ),
    "release_interrupted": AlarmText(
        "Hand-back interrupted",
        "Control stays paused; the pump may be only partly back on the values it had before "
        "ovenbird took over.",
        "Open ovenbird, System → Trial, and release control again to finish the hand-back.",
    ),
    "notify_failing": AlarmText(
        "Notifications not delivered",
        "Keeps trying to send its messages.",
        "Check the ntfy server and the internet connection.",
    ),
    "archive_failing": AlarmText(
        "Yearly archive failing",
        "Keeps controlling and recording; old history is kept up to 3 days longer while the "
        "archive cannot copy it.",
        "Check the free space of the data directory and the archive error under System → Data.",
    ),
    "archive_rebuilt": AlarmText(
        "Archive month rebuilt",
        "Moved the damaged working copy of the month aside and rebuilt it from the history "
        "ovenbird still keeps.",
        "Nothing to do. Days the history no longer held are missing from that month; the "
        "damaged file stays in the archive folder.",
    ),
}

NL: Final[dict[str, AlarmText]] = {
    "mode_mismatch": AlarmText(
        "Pompmodus klopt niet",
        "Stuurt niets tot de pomp weer verwarmt in de stand Direct; de pomp houdt haar huidige "
        "aanvoertemperatuur.",
        "Kijk op de afstandsbediening van Panasonic of de pomp verwarmt en de watertemperatuur "
        "op Direct staat, niet op de stooklijn.",
    ),
    "verification_failed": AlarmText(
        "Opdracht niet bevestigd",
        "Houdt zijn opdrachten een tijd tegen; de pomp houdt de waarde die ze meldt.",
        "Kijk of HeishaMon online is en de pomp aan staat.",
    ),
    "write_budget": AlarmText(
        "Schrijfbudget op",
        "Stuurt vandaag niets meer behalve veiligheidscorrecties; de pomp houdt haar laatste "
        "waarden.",
        "Niet dringend. Gebeurt het vaak, zoek dan bij Activiteit naar een waarde die steeds "
        "verandert.",
    ),
    "foreign_writer": AlarmText(
        "Iemand anders wijzigde de pomp",
        "Houdt zijn opdrachten tegen zolang de blokkade duurt, eerst 1 uur; de pomp houdt de "
        "waarde van de andere schrijver.",
        "Zoek uit wie de pomp wijzigde (afstandsbediening, Node-RED, een app) en stop dat. Wacht "
        "daarna, of geef vrij bij Activiteit → Blokkades.",
    ),
    "hold_latched": AlarmText(
        "ovenbird wacht op vrijgave",
        "Stuurt niets tot een beheerder de blokkade vrijgeeft; de pomp houdt haar huidige waarden.",
        "Zoek uit wat de pomp steeds wijzigt en stop dat, en geef de blokkade dan vrij bij "
        "Activiteit → Blokkades.",
    ),
    "heishamon_restarted": AlarmText(
        "HeishaMon herstart",
        "Stuurt zijn eigen waarden opnieuw.",
        "Je hoeft niets te doen. Herstart HeishaMon vaak, kijk dan naar de voeding en de wifi.",
    ),
    "correction_failed": AlarmText(
        "Veiligheidscorrectie mislukt",
        "Kreeg de aanvoertemperatuur niet onder het maximum; probeert het later opnieuw en laat "
        "intussen alleen lagere waarden door.",
        "Zet een lagere watertemperatuur op de afstandsbediening, zoek uit wat hem steeds "
        "verhoogt en stop dat. Twijfel je, bel je installateur.",
    ),
    "setpoint_above_max": AlarmText(
        "Aanvoertemperatuur boven maximum",
        "Stuurt meteen zijn eigen veilige aanvoertemperatuur om de pomp onder het maximum te "
        "krijgen.",
        "Zoek uit wie de hoge waarde instelde (afstandsbediening, Node-RED, een app) en stop dat.",
    ),
    "outlet_overshoot": AlarmText(
        "Aanvoer te heet",
        "Laat alleen lagere watertemperaturen door tot het aanvoerwater is afgekoeld.",
        "Kijk op de afstandsbediening naar een foutcode en of de kranen van vloer en radiatoren "
        "open zijn. Blijft het, bel je installateur.",
    ),
    "low_flow": AlarmText(
        "Laag debiet",
        "Laat alleen lagere watertemperaturen door tot het debiet weer boven het minimum zit.",
        "Zet dichte kranen van radiatoren of vloergroepen open, controleer de waterdruk en het "
        "filter. Blijft het, bel je installateur.",
    ),
    "low_flow_defrost": AlarmText(
        "Geen doorstroming tijdens ontdooien",
        "Er valt niets te corrigeren: de pomp ontdooit zelf en ovenbird schrijft nooit tijdens "
        "het ontdooien. De gewone bewaking op laag debiet werkt weer zodra het ontdooien klaar "
        "is.",
        "Noemt het bericht ontdooimodus 2, dan zet de pomp haar waterpomp bewust stil "
        "(retourwater onder 27 °C) en duurt het ontdooien langer; gebeurt dat vaak, dan "
        "voorkomt een iets hogere minimale watertemperatuur bij vorst het. Anders hoort de "
        "waterpomp te blijven draaien: laat de waterpomp, de debietsensor en het filter "
        "nakijken.",
    ),
    "pump_error": AlarmText(
        "Pompfout",
        "Laat alleen lagere watertemperaturen door zolang de pomp een fout meldt.",
        "Lees de foutcode af op de afstandsbediening van Panasonic en zoek hem op in de "
        "handleiding, of bel je installateur.",
    ),
    "backup_heater": AlarmText(
        "Bijverwarming aan",
        "Regelt gewoon door. Het elektrische bijverwarmingselement gebruikt wel veel stroom.",
        "Kijk waarom het aan staat: strenge kou, een ontdooiprobleem of de instelling op de "
        "afstandsbediening.",
    ),
    "backup_heater_allowed": AlarmText(
        "Bijverwarming toegestaan",
        "Er verandert niets; de pomp mag haar elektrische bijverwarming inschakelen.",
        "Je hoeft niets te doen.",
    ),
    "heating_off_outdoor": AlarmText(
        "Boven uitschakeltemperatuur verwarming",
        "Beslist en stuurt gewoon door, maar boven deze buitentemperatuur verwarmt de pomp zelf "
        "niet.",
        "Bij zacht weer hoef je niets te doen.",
    ),
    "defrost_stuck": AlarmText(
        "Ontdooien duurt te lang",
        "De ruimtecorrectie staat stil en de aanvoertemperatuur gaat niet omlaag tot het "
        "ontdooien klaar is.",
        "Kijk bij de buitenunit naar ijs, sneeuw of een geblokkeerde ventilator. Gebeurt het "
        "vaker, bel je installateur.",
    ),
    "room_below_floor": AlarmText(
        "Kamer te koud",
        "De ruimtecorrectie, als die aan staat, verhoogt de watertemperatuur binnen haar grens.",
        "Kijk of er ramen openstaan of kranen dicht zijn.",
    ),
    "room_sensor_silent": AlarmText(
        "Kamersensor stil",
        "De ruimtecorrectie pauzeert: hij regelt op de stooklijn.",
        "Controleer de batterij van de kamersensor en zijn verbinding in Home Assistant.",
    ),
    "mqtt_connection_reverted": AlarmText(
        "Brokerwijziging teruggedraaid",
        "Terug op de vorige broker: de nieuwe gaf niet op tijd HeishaMon-gegevens.",
        "Controleer de brokerinstellingen en test ze opnieuw onder Instellingen, MQTT.",
    ),
    "mqtt_revert_failed": AlarmText(
        "Brokerwijziging vastgelopen",
        "De nieuwe broker gaf geen HeishaMon-gegevens en de vorige kon niet terug.",
        "Stel een werkende broker in onder Instellingen, MQTT, of in de installatie.",
    ),
    "outside_sensor_stale": AlarmText(
        "Buitensensor verouderd",
        "De stooklijn gebruikt de eigen buitensensor van de pomp.",
        "Controleer de batterij en de verbinding van de buitensensor.",
    ),
    "outside_sensor_implausible": AlarmText(
        "Buitensensor onwaarschijnlijk",
        "De stooklijn gebruikt de eigen buitensensor van de pomp.",
        "Controleer waar de buitensensor hangt (zon, muur, warmte) en wat hij meldt.",
    ),
    "room_sensor_quiet": AlarmText(
        "Kamersensor laat niets horen",
        "De kamer mag de watertemperatuur niet meer verlagen.",
        "Controleer de batterij en de verbinding van de sensor.",
    ),
    "room_report_overdue": AlarmText(
        "Kamermelding te laat",
        "De ruimtecorrectie pauzeert zodra de waarde te oud is: hij regelt op de stooklijn.",
        "Controleer de batterij en de verbinding van de sensor.",
    ),
    "room_implausible": AlarmText(
        "Kamerwaarde onwaarschijnlijk",
        "De ruimtecorrectie pauzeert: hij regelt op de stooklijn tot beide kamersensoren het "
        "weer eens zijn.",
        "Vergelijk beide sensoren en verplaats of vervang de verkeerde.",
    ),
    "room_unit_refused": AlarmText(
        "Kamerwaarde zonder bruikbare eenheid",
        "De ruimtecorrectie pauzeert: hij regelt op de stooklijn alsof de kamerwaarde ontbreekt.",
        "Geef de sensor een temperatuureenheid in Home Assistant, of kies een andere kamersensor.",
    ),
    "ha_link_down": AlarmText(
        "Verbinding met Home Assistant verbroken",
        "Regelt door; kamerwaarden uit Home Assistant worden korter vertrouwd.",
        "Kijk of Home Assistant draait en of het adres en het token die ovenbird gebruikt nog "
        "werken.",
    ),
    "config_reset": AlarmText(
        "Configuratie teruggezet",
        "Draait in Schaduw op de standaardwaarden van de installatie: hij beslist elke "
        "minuut maar stuurt niets naar de pomp.",
        "Open ovenbird, controleer de instellingen, importeer een export als je die hebt en "
        "klik dan op Bevestigen.",
    ),
    "pump_setting_changed": AlarmText(
        "Pompinstelling gewijzigd",
        "Er verandert niets; het noteert dat een pompinstelling zonder ovenbird veranderde.",
        "Je hoeft niets te doen als jij het op de afstandsbediening deed. Zo niet, zoek dan uit "
        "wie.",
    ),
    "envelope_mismatch": AlarmText(
        "Waarde buiten de veiligheidsregel",
        "Houdt de waarde die de veiligheidsregel schreef en houdt zijn volgende waarden binnen "
        "de band van de regel.",
        "Meestal niets. Komt het terug, controleer dan of de instellingen van de veilige lijn "
        "overeenkomen met de regel op de HeishaMon.",
    ),
    "release_interrupted": AlarmText(
        "Teruggeven onderbroken",
        "De regeling blijft gepauzeerd; de pomp staat misschien maar deels terug op de waarden "
        "van voor ovenbird.",
        "Open ovenbird, Systeem → Proef, en geef de regeling opnieuw terug om het af te maken.",
    ),
    "notify_failing": AlarmText(
        "Meldingen komen niet aan",
        "Blijft proberen zijn berichten te versturen.",
        "Controleer de ntfy-server en de internetverbinding.",
    ),
    "archive_failing": AlarmText(
        "Jaararchief faalt",
        "Regelt en registreert door; oude historie blijft tot 3 dagen langer bewaard zolang het "
        "archief haar niet kan kopiëren.",
        "Controleer de vrije ruimte van de datamap en de archieffout onder Systeem → Data.",
    ),
    "archive_rebuilt": AlarmText(
        "Archiefmaand opnieuw opgebouwd",
        "Zette de beschadigde werkkopie van de maand opzij en bouwde haar opnieuw op uit de "
        "historie die ovenbird nog bewaart.",
        "Je hoeft niets te doen. Dagen die de historie niet meer had, ontbreken in die maand; "
        "het beschadigde bestand blijft in de archiefmap.",
    ),
}

WORDS: Final[dict[Language, dict[str, str]]] = {
    "en": {
        "critical": "Critical",
        "warning": "Warning",
        "info": "Notice",
        "you": "You:",
        "ovenbird": "ovenbird:",
        "details": "Details:",
        "resolved": "resolved",
        "brief": "came and went",
        "lasted": "It lasted {minutes} min and is over now.",
        "test_title": "test notification",
        "test_body": "Sent by {who}. Alarms will arrive like this.",
        "by": "by {who}",
        "mode_pause": "Control paused",
        "mode_resume": "Control resumed",
        "control_release": "Control handed back",
        "hold_release": "Command hold released",
        "command_hold": "Command hold",
        "stove_mode": "Wood-stove mode",
        "envelope_correction": "Safety rule correction",
        "started": "started",
        "expired": "ended",
        "released": "released",
        "recognised": "recognised",
        "raised": "raised",
        "cleared": "cleared",
        "outcome_ok": "everything restored",
        "outcome_incomplete": "not everything restored",
    },
    "nl": {
        "critical": "Kritiek",
        "warning": "Waarschuwing",
        "info": "Melding",
        "you": "Jij:",
        "ovenbird": "ovenbird:",
        "details": "Details:",
        "resolved": "opgelost",
        "brief": "kwam en ging",
        "lasted": "Het duurde {minutes} min en is nu voorbij.",
        "test_title": "testmelding",
        "test_body": "Verstuurd door {who}. Zo komen alarmen binnen.",
        "by": "door {who}",
        "mode_pause": "Regeling gepauzeerd",
        "mode_resume": "Regeling hervat",
        "control_release": "Regeling teruggegeven",
        "hold_release": "Blokkade vrijgegeven",
        "command_hold": "Blokkade van opdrachten",
        "stove_mode": "Houtkachelmodus",
        "envelope_correction": "Correctie door de veiligheidsregel",
        "started": "gestart",
        "expired": "afgelopen",
        "released": "vrijgegeven",
        "recognised": "herkend",
        "raised": "gemeld",
        "cleared": "opgeheven",
        "outcome_ok": "alles teruggezet",
        "outcome_incomplete": "niet alles teruggezet",
    },
}


def alarm_text(code: str, language: Language) -> AlarmText:
    """Return the display name and advice of ``code`` (the code itself when unknown)."""
    texts = NL if language == "nl" else EN
    found = texts.get(code)
    if found is not None:
        return found
    return AlarmText(code.replace("_", " "), "", "")


def word(key: str, language: Language) -> str:
    """Return the phrase ``key`` in ``language`` (the key itself when unknown)."""
    return WORDS[language].get(key, key)
