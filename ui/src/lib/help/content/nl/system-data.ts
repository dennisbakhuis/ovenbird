import type { HelpTopic } from '$lib/help/types';

export const topic: HelpTopic = {
  id: 'system/data',
  title: 'Systeem: data',
  lead: 'Hoe groot de historie is, hoe lang die bewaard blijft en hoe je hem downloadt: een paar signalen als spreadsheet, de logboeken, alles als één archief, of het jaararchief met bevroren maanden.',
  art: 'system',
  sections: [
    {
      id: 'storage',
      kind: 'see',
      title: 'Opslag',
      body: 'De grootte van de historiedatabase en van de back-upkopie, de vrije schijfruimte en de grootte die je mag verwachten zodra elke begrensde resolutie vol is bij de huidige instellingen. Data die altijd blijft, groeit door; de regel eronder zegt hoeveel per jaar.\n\nDe tabel toont elke resolutie: ruwe metingen zoals ze binnenkwamen, de minuut-, kwartier- en uurgemiddelden, en het logboek van beslissingen, commando’s en alarmen. **Per dag** is wat een dag ervan op schijf kost.',
      target: 'system/data.storage',
    },
    {
      id: 'retention',
      kind: 'do',
      title: 'Hoe lang data blijft',
      body: 'Elke resolutie heeft een eigen bewaartermijn, in Instellingen onder **Data**. Oudere ruwe metingen gaan niet verloren: de gemiddelden bewaren het verloop van elk signaal veel langer. **Altijd bewaren** haalt de grens weg; elke andere bewaartermijn is minstens één dag. Een wijziging werkt binnen een minuut, zonder herstart.',
      target: 'system/data.retention',
    },
    {
      id: 'presets',
      kind: 'do',
      title: 'Kort, Standaard, Lang of Onbeperkt',
      body: 'Instellingen → Data biedt vier keuzes, elk met de grootte die de database ermee bereikt. **Kort** bewaart ongeveer een maand detail, **Standaard** (de standaard) 90 dagen minuutdata, **Lang** een jaar detail, **Onbeperkt** alles. De kwartier- en uurgemiddelden blijven altijd, behalve bij Kort. Waarden die bij geen ervan passen heten **Eigen keuze**; de vijf velden onder **Geavanceerd** stellen elke resolutie apart in.',
    },
    {
      id: 'compact',
      kind: 'do',
      title: 'Ruimte nu vrijmaken',
      body: 'Na een kortere bewaartermijn blijft het databasebestand even groot tot het opnieuw is opgebouwd. **Ruimte nu vrijmaken** bouwt het op tussen twee schrijfbeurten; het schrijven van historie wacht intussen een paar seconden. Er is vrije schijfruimte nodig van ongeveer twee keer de database. Alleen een beheerder kan het starten.',
      target: 'system/data.compact',
    },
    {
      id: 'export',
      kind: 'do',
      title: 'Reeksen downloaden',
      body: 'Kies een periode, de signalen en een resolutie. **Lang** geeft een rij per waarde (met minimum en maximum bij gemiddelden); **Breed** geeft een rij per tijdstip met een kolom per signaal, handig in een spreadsheet. NDJSON past bij scripts. De schatting toont de grootte vóór je downloadt; er is geen grens aan het aantal rijen.',
      steps: [
        'Kies een periode, of **Zelf kiezen** voor eigen dagen.',
        'Vink de signalen aan die je nodig hebt; het filter maakt de lijst korter.',
        'Kies resolutie, indeling en formaat, bekijk de schatting en druk op **Reeksen downloaden**.',
      ],
      target: 'system/data.export',
    },
    {
      id: 'journals',
      kind: 'see',
      title: 'Logboeken',
      body: 'Elke beslissing, elk commando, alarm of elke weersverwachting in de gekozen periode, in het gekozen formaat. Anders dan op de Activiteit-pagina’s is er geen grens van 5.000 rijen.',
      target: 'system/data.journals',
    },
    {
      id: 'archive',
      kind: 'do',
      title: 'Volledig archief',
      body: 'Een zip met een verse kopie van de hele historiedatabase, de configuratie en een manifest dat ze beschrijft. Open de database met elk SQLite-programma. Wachtwoorden en tokens zitten er nooit in. Alleen een beheerder kan het downloaden.',
      target: 'system/data.archive',
    },
    {
      id: 'yearly',
      kind: 'see',
      title: 'Jaararchief',
      body: 'Naast de actuele historie wordt elke afgelopen maand bevroren in een eigen zip in de datamap, in de tijdzone van de installatie: de minuut-, kwartier- en uurgemiddelden, de beslissingen, commando’s, alarmen, de weersverwachtingen en de configuratieversies van die maand. Het staat los van de bewaartermijn, dus ook bij een korte bewaartermijn blijft elke maand in het archief. De maand wordt elk kwartier bijgewerkt en zes uur na het einde bevroren; een maand die de historie niet meer helemaal had, toont de ontbrekende dagen. Een volle maand kost ongeveer 30 MB.',
      target: 'system/data.yearly',
    },
    {
      id: 'yearly-switch',
      kind: 'do',
      title: 'Archief aan of uit',
      body: 'De schakelaar op de kaart (of **Jaararchief** in Instellingen → Data) start of stopt het bevriezen van nieuwe maanden. Bewaarde maanden blijven tot je ze verwijdert. Schakelen vraagt de beheerderslogin. Weer aangezet haalt het archief eerst de maanden in die de historie nog heeft.',
      target: 'system/data.yearly-switch',
    },
    {
      id: 'yearly-download',
      kind: 'do',
      title: 'Een jaar of stookseizoen downloaden',
      body: 'Kies **Kalenderjaar** of **Stookseizoen** (augustus tot en met juli) en download: één zip met de bevroren maanden en een manifest dat zegt welke maanden erin zitten. Een jaar dat nog loopt, of waarin het archief begon, heet deels, met zijn maanden. De huidige maand komt erbij zodra hij bevroren is; download hem los uit de lijst met maanden. Downloaden vraagt de beheerderslogin.',
      target: 'system/data.yearly-download',
    },
    {
      id: 'yearly-months',
      kind: 'do',
      title: 'Losse maanden en verwijderen',
      body: 'Elke maand toont op hoeveel dagen hij data heeft en hoe groot hij is. **Verwijderen** haalt een bevroren maand na bevestiging definitief weg, en die maand wordt niet opnieuw gearchiveerd; bij een kalenderjaar gaan alle bevroren maanden ervan weg. De actuele historie blijft zoals hij is. Verwijderen vraagt de beheerderslogin.',
      target: 'system/data.yearly-months',
    },
    {
      id: 'privacy',
      kind: 'know',
      title: 'Je data verraadt wanneer je thuis bent',
      body: 'Kamertemperaturen, warm water en de pomp laten zien wanneer het huis bewoond, verwarmd of leeg is, en de signaalnamen bevatten je Home Assistant-entiteiten. Deel exports alleen met mensen die je vertrouwt.',
      without: {
        hotWater: {
          body: 'Kamertemperaturen en de pomp laten zien wanneer het huis bewoond, verwarmd of leeg is, en de signaalnamen bevatten je Home Assistant-entiteiten. Deel exports alleen met mensen die je vertrouwt.',
        },
      },
    },
  ],
  related: ['system', 'settings'],
};
