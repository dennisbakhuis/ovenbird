import type { HelpTopic } from '$lib/help/types';

export const topic: HelpTopic = {
  id: 'settings/mqtt',
  title: 'MQTT',
  lead: 'Waar ovenbird de warmtepomp leest: de [[mqtt|MQTT]]-broker waarop [[heishamon|HeishaMon]] publiceert, en extra sensoren die via MQTT publiceren.',
  art: 'settings',
  sections: [
    {
      id: 'connection',
      kind: 'do',
      title: 'De broker wijzigen',
      body: 'De statusregel zegt of ovenbird verbonden is, met welke broker en welk basistopic, en hoeveel HeishaMon-berichten er sinds het verbinden binnenkwamen.',
      steps: [
        'Vul het adres en de poort van de broker in, en een gebruikersnaam en wachtwoord als de broker daarom vraagt.',
        'Controleer de **HeishaMon-basis**: de topic base uit de MQTT-instellingen van HeishaMon, meestal `panasonic_heat_pump`.',
        'Druk op **Verbinding testen**. ovenbird maakt een aparte verbinding die alleen leest en wacht tot 30 seconden op een actuele HeishaMon-waarde onder die basis (een bewaarde retained-waarde alleen telt niet: die kan van een board komen dat allang weg is). Er wordt niets verstuurd.',
        'Druk op **Verbinding opslaan**. Dat kan alleen voor precies de waarden van de laatste geslaagde test, binnen 10 minuten; verander je iets, dan test je opnieuw.',
      ],
      target: 'settings/mqtt.connection',
    },
    {
      id: 'revert',
      kind: 'know',
      title: 'Na 60 seconden terug naar de oude broker',
      body: 'Na het opslaan schakelt ovenbird meteen over en houdt de nieuwe broker 60 seconden in de gaten. Zodra die verbonden is en er actuele HeishaMon-gegevens binnenkomen, blijft de wijziging staan. Komt er in die tijd niets binnen, dan gaat ovenbird zelf terug naar de vorige broker en geeft de waarschuwing **Wijziging van de broker teruggedraaid**, zodat een tikfout de pomp nooit onbewaakt laat. Een herstart in die 60 seconden beëindigt de controle niet: die loopt na de start opnieuw. Mislukt het teruggaan, dan zegt de kaart dat en vraagt het kritieke alarm **Wijziging van de broker vastgelopen** om een werkende broker. De kaart toont de uitkomst; het auditlog legt beide stappen vast.',
    },
    {
      id: 'password',
      kind: 'know',
      title: 'Het wachtwoord blijft geheim',
      body: 'Het wachtwoord wordt op de ovenbird-server bewaard en nooit meer getoond: de kaart zegt alleen of er een is opgeslagen. Laat het veld leeg om het te houden. Een nieuwe broker of poort, TLS uitzetten of een ander CA-bestand zonder wachtwoord laat het opgeslagen wachtwoord vallen, zodat het nooit naar een andere broker gaat. Een wachtwoord uit de installatie kan zo’n wijziging helemaal niet volgen: wijzig de broker dan in de installatie.',
    },
    {
      id: 'locked',
      kind: 'know',
      title: 'Ingesteld door de installatie',
      body: 'Een veld dat uit een omgevingsvariabele of het optiesbestand komt, is hier vergrendeld en toont zijn variabele. Wijzig het in de installatie en herstart. De rest kun je wel testen.',
    },
    {
      id: 'commands',
      kind: 'know',
      title: 'Terwijl opdrachten aan staan',
      body: 'Zolang ovenbird opdrachten naar de pomp stuurt, houdt de opdrachtverbinding de broker waarmee ze startte. De broker kun je dan hier testen, maar niet wijzigen: wijzig hem in de installatie en herstart.',
    },
    {
      id: 'inputs',
      kind: 'do',
      title: 'Extra MQTT-sensoren',
      body: 'Een thermometer die via MQTT publiceert, kan ook een sensor zijn: voeg zijn topic toe onder **Extra MQTT-sensoren**. De signaalnaam is optioneel (anders `mqtt/<topic>`); geef de eenheid, zoals °C, en eventueel een bereik waarbuiten waarden worden genegeerd. Dit zijn gewone instellingen: bekijk en pas ze toe zoals elke andere wijziging. Daarna staan ze in de sensorlijsten, bijvoorbeeld als kamersensor of als buitensensor van de [stooklijn](#/settings/curve).',
      target: 'settings/mqtt.inputs',
    },
  ],
  questions: [
    {
      id: 'no-heishamon',
      q: 'De test maakt verbinding, maar vindt geen HeishaMon-gegevens.',
      a: 'De broker werkt, maar onder dat basistopic komt niets binnen. Vergelijk de basis met de MQTT topic base in de instellingen van HeishaMon, en controleer of HeishaMon naar deze broker publiceert.',
    },
    {
      id: 'reverted',
      q: 'Mijn wijziging is teruggedraaid. Wat nu?',
      a: 'De nieuwe broker leverde binnen 60 seconden geen HeishaMon-gegevens, dus ovenbird zit weer op de vorige en werkt gewoon door. Test de nieuwe instellingen opnieuw; de waarschuwing verdwijnt bij de volgende geslaagde test of wijziging.',
    },
  ],
  related: ['settings/ha', 'settings/curve', 'system/signals'],
};
