import type { HelpTopic } from '$lib/help/types';

export const topic: HelpTopic = {
  id: 'setpoint',
  title: 'Aanvoertemperatuur',
  lead: 'Elke minuut rekent ovenbird één getal uit: de watertemperatuur voor de pomp. Deze pagina laat zien hoe dat getal tot stand kwam, en wat het zou veranderen.',
  art: 'setpoint',
  sections: [
    {
      id: 'now',
      kind: 'see',
      title: 'Nu',
      body: 'Het grote getal is de [[setpoint|aanvoertemperatuur]] van de laatste [[decision|beslissing]], met de reden in één woord en in één gewone zin. Gekleurde regels eronder noemen bijzonderheden: [[defrost|ontdooien]], een [[dhw|warmwaterrun]] of de [[wood-stove|houtkachelmodus]]. In houtkachelmodus is de reden **Houtkachel**, pauzeert de ruimtecorrectie terwijl haar integrator voor daarna bewaard blijft, en zegt een regel in gewone woorden wanneer de herkenning wacht.\n\nDe labels bovenaan tonen de [[config-version|configuratieversie]] en het tijdstip van de beslissing.',
      without: {
        hotWater: {
          body: 'Het grote getal is de [[setpoint|aanvoertemperatuur]] van de laatste [[decision|beslissing]], met de reden in één woord en in één gewone zin. Gekleurde regels eronder noemen bijzonderheden: [[defrost|ontdooien]], een pomp die elders bezig is of de [[wood-stove|houtkachelmodus]]. In houtkachelmodus is de reden **Houtkachel**, pauzeert de ruimtecorrectie terwijl haar integrator voor daarna bewaard blijft, en zegt een regel in gewone woorden wanneer de herkenning wacht.\n\nDe labels bovenaan tonen de [[config-version|configuratieversie]] en het tijdstip van de beslissing.',
        },
      },
      target: 'setpoint.now',
    },
    {
      id: 'waterfall',
      kind: 'see',
      title: 'Zo ontstaat de aanvoertemperatuur',
      body: 'Lees van boven naar beneden, op één °C-schaal:\n\n- **Stooklijn**: het startpunt, uit de buitentemperatuur.\n- Elke correctie, zoals [[room-feedback|Ruimtecorrectie]], [[start-ramp|Zachte start]] of **Houtkachel**, omhoog of omlaag.\n- **Veiligheidsgrenzen**: het toegestane bereik, zodat het water nooit te heet of te koud wordt.\n- **Afronden, dode band, wachttijd**: of de wijziging het versturen al waard is.\n- **Aanvoertemperatuur**: de hele graad die is verstuurd, en **Pomp heeft**: wat de pomp terugmeldt. Ging er niets weg (Schaduw, een pauze of een blokkade), dan staat er **Zou sturen**.',
      target: 'setpoint.waterfall',
    },
    {
      id: 'change',
      kind: 'see',
      title: 'Wat zou het veranderen',
      body: 'De schaal laat zien hoe ver de kamer (of de buitentemperatuur) moet bewegen voordat de aanvoertemperatuur verandert, en naar welke waarde. In de groene zone blijft ze gelijk; het gestippelde streepje is het kamerdoel.\n\n**Kamersensor** toont de waarde die ovenbird gebruikt, hoe oud die is, en of een tweede sensor het ermee eens is. Is de sensor niet te vertrouwen, dan valt ovenbird terug op alleen de stooklijn.',
      target: 'setpoint.change',
    },
    {
      id: 'details',
      kind: 'see',
      title: 'Toestand, invoer en opdrachten',
      body: 'Drie ingeklapte blokken voor als je het hele plaatje wilt:\n\n- **Toestand van de regelaar**: elke stap van de berekening, de integrator van de ruimtecorrectie, de zachte start en de resterende wachttijd.\n- **Gebruikte invoer**: elke meting met waarde en leeftijd.\n- **Wat naar de pomp ging**: wat de beslissing wilde, wat de pomp had, en wat er echt is verstuurd.',
      target: 'setpoint.details',
    },
    {
      id: 'history',
      kind: 'do',
      title: 'Terugkijken',
      body: 'Het waterpaneel stapelt elke correctie op de stooklijn; de dikke lijn is de verstuurde aanvoertemperatuur, de groene band het toegestane bereik. Daaronder de kamer, en een baan met de reden per moment.',
      steps: [
        'Kies **6 u**, **24 u** of **7 d**.',
        'Klik of tik op de grafiek: de kaarten erboven tonen nu dat moment.',
        'Kies **Terug naar nu** om terug te gaan.',
      ],
      target: 'setpoint.history',
    },
    {
      id: 'episodes',
      kind: 'do',
      title: 'Wat er gebeurde',
      body: 'Een tabel van wat ovenbird deed, nieuwste eerst. **Episodes** voegt minuten met dezelfde reden samen tot één regel, dus een compressorstart of een [[hold|blokkade]] is één regel. **Elke beslissing** toont de minuten één voor één.\n\nOpen een regel om dat moment in de kaarten erboven te zien.',
      target: 'setpoint.episodes',
    },
    {
      id: 'calm',
      kind: 'know',
      title: 'Waarom de aanvoertemperatuur zo weinig beweegt',
      body: 'ovenbird wijzigt de aanvoertemperatuur bewust zelden en in hele graden. Een wijziging gaat pas de deur uit als de berekende waarde minstens de [[dead-band|dode band]] verschilt (1 K of meer), en niet eerder dan de [[dwell|wachttijd]] na de vorige wijziging.\n\nZo blijft de pomp rustig: minder starts en stops, en minder schrijfacties naar haar geheugen. Een vloer of radiatoren reageren toch traag, dus een paar minuten wachten kost niets.',
    },
  ],
  questions: [
    {
      id: 'below-curve',
      q: 'Waarom ligt de aanvoertemperatuur vlak na een start onder de stooklijn?',
      a: 'Dat is de [[start-ramp|zachte start]]. Na een compressorstart houdt ovenbird het water iets onder de stooklijn en laat het langzaam oplopen. De pomp warmt zo rustig op, in plaats van door te schieten en weer te stoppen.',
    },
    {
      id: 'defrost',
      q: 'Wat gebeurt er tijdens ontdooien of warm water maken?',
      without: {
        hotWater: { q: 'Wat gebeurt er tijdens ontdooien, of als de pomp elders bezig is?' },
      },
      a: 'De pomp is dan met iets anders bezig, dus de kamer reageert niet zoals normaal. ovenbird zet de ruimtecorrectie stil en verlaagt de aanvoertemperatuur in die tijd nooit, zodat de dip geen overreactie geeft. Daarna gaat het verder waar het was.',
    },
    {
      id: 'room-cold',
      q: 'De kamer werd kouder, maar de aanvoertemperatuur bleef gelijk. Waarom?',
      a: 'Kijk bij **Wat zou het veranderen**: misschien zit de kamer nog in de zone waarin de aanvoertemperatuur gelijk blijft, of is er een wijziging nodig maar houdt de wachttijd die tegen. De ruimtecorrectie bouwt ook bewust langzaam op, omdat een huis uren nodig heeft om op te warmen.',
    },
    {
      id: 'plan',
      q: 'Wat is "Plan" in de lijst met bijdragen?',
      a: 'Een plek voor een toekomstige planner die bijvoorbeeld kan voorverwarmen voor een koude nacht of goedkope uren. Die is nog niet actief, dus het draagt altijd niets bij.',
    },
    {
      id: 'nothing-sent',
      q: 'Waarom staat er bij een regel "niets verstuurd"?',
      a: 'ovenbird besliste wel, maar schreef niet naar de pomp, bijvoorbeeld omdat [[heishamon|HeishaMon]] niet antwoordde, er een [[hold|blokkade]] actief was of ovenbird in [[shadow|Schaduw]] staat. De pomp houdt dan de laatste waarde die ze had.',
    },
  ],
  related: ['home', 'settings/curve', 'settings/room', 'settings/behaviour', 'activity'],
};
