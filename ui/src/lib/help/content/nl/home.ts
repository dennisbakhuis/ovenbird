import type { HelpTopic } from '$lib/help/types';

export const topic: HelpTopic = {
  id: 'home',
  title: 'Thuis',
  lead: 'Hoe warm het huis is, wat de warmtepomp nu doet, en waarom ovenbird om deze watertemperatuur vraagt.',
  art: 'home',
  sections: [
    {
      id: 'verdict',
      kind: 'see',
      title: 'In één oogopslag',
      body: 'Eén regel vat het huis samen: **Het huis is op temperatuur**, **Aan het opwarmen**, **Warmer dan het doel**, **Aandacht nodig: …**, **Houtkachel brandt, verwarming teruggeschakeld** of **Geen kamertemperatuur**. Hij volgt de [[alarm|alarmen]] (waarschuwing of kritiek), een [[hold|blokkade]], of ovenbird stuurt, het vertrouwen in de kamerwaarde en de [[wood-stove|houtkachelmodus]]. [Activiteit](#/activity) toont de alarmen en blokkades.\n\nDaaronder, uit de [[forecast|weersverwachting]]: "Vannacht: buiten tot −1 °C. De verwarming gaat door." Zonder weersverwachting valt die regel weg.',
      target: 'home.verdict',
    },
    {
      id: 'room',
      kind: 'see',
      title: 'Kamertemperatuur',
      body: 'Het grote getal is de kamer zoals je [[room-sensor|kamersensor]] die meet, met een pijl voor de trend; de balk toont de [[comfort-band|comfortband]]. De regel eronder zegt hoeveel ovenbird de waarde vertrouwt ([[cooling-authority|vertrouwen in de kamerwaarde]]).\n\n**Doel 21,0 °C** is een knop: die opent **Comforttemperatuur**, met − en + in stappen van 0,1 °C. **Opslaan** toont een controle van één zin (meer onder **Details**), daarna **Toepassen**. Met de houtkachelmodus aan biedt **Kachel aan…** 2, 4 of 8 uur.',
      target: 'home.room',
    },
    {
      id: 'pump',
      kind: 'see',
      title: 'Warmtepomp',
      body: 'Rechtsboven staat wat de pomp doet: Verwarmen, Stand-by, Ontdooien, Warm water, Uit of HeishaMon offline, met het toerental van de [[compressor]] in Hz en een maantje als de [[quiet-mode|fluistermodus]] aan staat.\n\nDaaronder: stroom erin, warmte eruit en de [[cop|COP]], dan het water: [[inlet|retour]] → [[outlet|aanvoer]], [[delta-t|ΔT]] en [[flow|debiet]]. **Aanvoertemperatuur** is wat ovenbird stuurde. Stuurt ovenbird niet ([[control-state|wie stuurt de pomp]]), dan staat er **Zou sturen** naast **Pomp heeft**. Tik op **waarom?** voor de opbouw.',
      without: {
        hotWater: {
          body: 'Rechtsboven staat wat de pomp doet: Verwarmen, Stand-by, Ontdooien, Pomp elders bezig, Uit of HeishaMon offline, met het toerental van de [[compressor]] in Hz en een maantje als de [[quiet-mode|fluistermodus]] aan staat.\n\nDaaronder: stroom erin, warmte eruit en de [[cop|COP]], dan het water: [[inlet|retour]] → [[outlet|aanvoer]], [[delta-t|ΔT]] en [[flow|debiet]]. **Aanvoertemperatuur** is wat ovenbird stuurde. Stuurt ovenbird niet ([[control-state|wie stuurt de pomp]]), dan staat er **Zou sturen** naast **Pomp heeft**. Tik op **waarom?** voor de opbouw.',
        },
      },
      target: 'home.pump',
    },
    {
      id: 'why',
      kind: 'see',
      title: 'Waarom deze aanvoertemperatuur',
      body: 'Een korte versie van de berekening van de [[setpoint|aanvoertemperatuur]]: de [[heating-curve|stooklijn]] bij de huidige buitentemperatuur, elke correctie daarbovenop, en de hele graad die is verstuurd. Regels die niets bijdragen vallen weg.\n\nDit zit ingeklapt in de kaart Warmtepomp, op een telefoon en op een breed scherm; klap het open om de regels te zien. **Details van de aanvoertemperatuur** opent het hele verhaal op de pagina [Aanvoer](#/setpoint).',
      target: 'home.why',
    },
    {
      id: 'day',
      kind: 'see',
      title: 'Pomp, afgelopen 24 uur',
      body: 'Vier banen laten zien wanneer de compressor draaide (donkerder is sneller), wanneer de pomp [[defrost|ontdooide]], [[dhw|warm water]] maakte en in de stille modus stond.\n\nEen goede dag heeft een paar lange runs in plaats van veel korte: elke start kost rendement en slijtage (zie [[short-cycling|pendelen]]). **Toon als lijst** geeft hetzelfde als tekst.',
      without: {
        hotWater: {
          body: 'Drie banen laten zien wanneer de compressor draaide (donkerder is sneller), wanneer de pomp [[defrost|ontdooide]] en wanneer ze in de stille modus stond. Was de pomp elders bezig, dan staat daar ook een baan voor.\n\nEen goede dag heeft een paar lange runs in plaats van veel korte: elke start kost rendement en slijtage (zie [[short-cycling|pendelen]]). **Toon als lijst** geeft hetzelfde als tekst.',
        },
      },
      target: 'home.day',
    },
    {
      id: 'chart',
      kind: 'see',
      title: 'Temperaturen',
      body: 'Drie panelen op één tijdlijn: de kamer tegen de comfortband, het water (aanvoertemperatuur, aanvoer en retour) en de buitentemperatuur. Elk paneel heeft een eigen schaal, zodat kleine veranderingen in de kamer zichtbaar blijven naast grote sprongen in het water.\n\nKies bovenaan **6 u**, **24 u** of **7 d**. Ga over de grafiek om een moment af te lezen, of gebruik **Toon als tabel**.',
      target: 'home.chart',
    },
    {
      id: 'tiles',
      kind: 'see',
      title: 'Vandaag en deze week',
      body: '**Energie vandaag** is de stroom sinds middernacht, met de geleverde warmte eronder. **COP vandaag** is warmte gedeeld door stroom. **Starts vandaag** telt de compressorstarts, met ontdooiingen en de gemiddelde looptijd. **Komende 24 u** toont de verwachting en opent [Weer](#/weather).\n\n"Vandaag" begint om middernacht in de tijdzone van de service, dezelfde dag als de dagcijfers op [Pomp](#/pump); staat de service in een andere zone dan jij, dan noemt een regel onder de tegels die. **Deze week** telt de laatste 7 dagen op.',
      target: 'home.tiles',
    },
  ],
  questions: [
    {
      id: 'reports-differ',
      q: 'Waarom heeft "Pomp heeft" een ander getal dan de waarde van ovenbird?',
      a: 'ovenbird stuurt een hele graad en controleert daarna wat de pomp terugmeldt. Een minuut of twee na een wijziging kunnen die verschillen, terwijl de opdracht via [[heishamon|HeishaMon]] onderweg is. Zolang ovenbird niet stuurt (Schaduw, een pauze of een blokkade) kan het langer verschillen: de pomp houdt haar eigen waarde.',
    },
    {
      id: 'idle-cold',
      q: 'De kamer is onder het doel. Waarom staat de pomp dan stand-by?',
      a: 'ovenbird bepaalt de watertemperatuur; de pomp beslist zelf wanneer ze start en stopt, op basis van hoe ver het water van die waarde af zit. Een vloer of radiatoren vol warm water blijven nog een tijd verwarmen, dus even stand-by is normaal en spaart starts. Blijft de kamer te koud, dan verhoogt de [[room-feedback|ruimtecorrectie]] de aanvoertemperatuur stap voor stap.',
    },
    {
      id: 'incomplete',
      q: 'Wat betekent "Onvolledige gegevens" onder Energie vandaag?',
      a: 'Voor minder dan 80 % van vandaag zijn er metingen, bijvoorbeeld na een herstart of een gat bij HeishaMon. De cijfers zijn wat er gemeten is, dus energie en COP kunnen te laag of scheef zijn.',
    },
    {
      id: 'no-forecast',
      q: 'Waarom zie ik geen tegel Komende 24 u?',
      a: 'De weersverwachting staat uit. Die is opt-in, omdat ze je afgeronde locatie naar een weerdienst stuurt. Je zet haar aan bij [Instellingen → Weer](#/settings/weather).',
    },
    {
      id: 'stove-banner',
      q: 'Wat betekent "Houtkachel: verwarming 3 K teruggeschakeld"?',
      a: 'De [[wood-stove|houtkachelmodus]] staat aan: een kachel verwarmt de kamer met de sensor, dus verlaagt ovenbird de stooklijn met 3 K in plaats van elke kamer af te koelen. De tweede regel zegt of een referentieruimte de rest van het huis bewaakt. Kijkt ovenbird alleen mee, is hij gepauzeerd of wacht hij, dan zegt de balk wat hij zou doen en dat er niets naar de pomp gaat. **Stoppen** beëindigt hem; de automatische herkenning wacht dan tot de kamer is afgekoeld. Zie [Houtkachel](#/settings/stove).',
    },
  ],
  related: ['setpoint', 'pump', 'weather', 'activity'],
};
