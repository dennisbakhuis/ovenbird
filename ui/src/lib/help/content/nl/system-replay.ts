import type { HelpTopic } from '$lib/help/types';

export const topic: HelpTopic = {
  id: 'system/replay',
  title: 'Systeem: naspelen',
  lead: 'Wat ovenbird over een voorbije periode had gestuurd met een andere instelling: de actieve, een opgeslagen versie of je huidige concept, naast wat het vastlegde en waar de pomp werkelijk op draaide.',
  art: 'system',
  sections: [
    {
      id: 'claims',
      kind: 'know',
      title: 'Geen uitspraak over comfort of energie',
      body: 'Naspelen gebeurt zonder terugkoppeling. Het huis volgde de regeling die toen werd vastgelegd, dus de kamers, het water en de pomp in het naspelen zijn de vastgelegde. Naspelen laat zien welke aanvoertemperaturen ovenbird had gestuurd en waarom; het kan niet zeggen hoe warm de kamers waren geweest of hoeveel energie een andere instelling had gekost.',
      target: 'system/replay.claims',
    },
    {
      id: 'period',
      kind: 'do',
      title: 'Kies een periode',
      body: 'Kies **24 u**, **7 dagen**, **30 dagen** of **Zelf kiezen**. De strook toont een vakje per dag: hoe voller het vakje, hoe meer beslissingen van die dag zijn opgeslagen. Tik op een dag om alleen die dag na te spelen. Beslissingen ouder dan hun bewaartermijn (Instellingen → Data) zijn weg en vallen niet na te spelen.',
      target: 'system/replay.period',
    },
    {
      id: 'config',
      kind: 'do',
      title: 'Kies een instelling',
      body: '**Actieve instelling** speelt de instelling na die nu draait. **Een opgeslagen versie** speelt een eerdere of latere versie uit Instellingen → Versies en back-up na. **Het huidige concept** speelt je niet-opgeslagen wijzigingen bovenop de actieve instelling na, voordat je ze toepast.',
      target: 'system/replay.config',
    },
    {
      id: 'run',
      kind: 'do',
      title: 'Speel het na',
      body: 'Druk op **Naspelen**. De service doorloopt elke opgeslagen beslissing opnieuw; 30 dagen duren een paar seconden tot een minuut. Je kunt de pagina intussen verlaten en terugkomen. Een nieuw naspelen stopt het lopende; naspelen vraagt de rol operate of admin.',
      target: 'system/replay.run',
    },
    {
      id: 'identity',
      kind: 'see',
      title: 'Exact of niet',
      body: 'Eerst wordt elke beslissing opnieuw doorlopen met de instelling waarmee hij draaide. **Exact** betekent dat elke vastgelegde aanvoertemperatuur terugkwam, zodat het naspelen van een andere instelling op dezelfde grond begint. **Niet exact** betekent dat een paar niet terugkwamen (bijvoorbeeld na een update van ovenbird): lees de uitkomst als een indicatie.',
    },
    {
      id: 'figures',
      kind: 'see',
      title: 'Cijfers, grafiek en episodes',
      body: 'De cijfers tellen hoe vaak de nagespeelde aanvoer wijzigt, hoeveel schrijfacties per dag dat kost tegen het dagbudget, hoe lang hij meer dan de drempel boven of onder het doel van de pomp ligt, en welke grens hem het vaakst tegenhield. De grafiek legt het naspelen (doorgetrokken), de vastgelegde aanvoer van ovenbird (gestippeld) en het doel van de pomp (gestreept) over elkaar. Een episode is een stuk waarin het naspelen en de pomp meer dan de drempel uit elkaar liggen, met de reden die het naspelen gaf.',
    },
  ],
  related: ['system/shadow', 'settings/versions', 'system/data'],
};
