import type { HelpTopic } from '$lib/help/types';

export const topic: HelpTopic = {
  id: 'settings/ha',
  title: 'Home Assistant',
  lead: 'Waar ovenbird je kamersensoren leest: het adres van Home Assistant en een toegangstoken. ovenbird leest alleen uit Home Assistant; het verandert daar nooit iets.',
  art: 'settings',
  sections: [
    {
      id: 'connection',
      kind: 'do',
      title: 'Home Assistant koppelen',
      body: 'Gebruik het adres waarmee je Home Assistant opent: rechtstreeks in je netwerk, zoals `http://192.0.2.10:8123`, of je https-adres achter een reverse proxy. Gewoon http is prima in je eigen netwerk.',
      steps: [
        'Open in Home Assistant je profiel, dan **Beveiliging**, en maak een **Langlevende toegangstoken**.',
        'Vul het adres in en plak de token.',
        'Druk op **Verbinding testen**. Dat controleert of Home Assistant antwoordt, de token accepteert en of de gebruikte sensoren bestaan.',
        'Druk op **Verbinding opslaan**. ovenbird maakt meteen verbinding; herstarten is niet nodig.',
      ],
      target: 'settings/ha.connection',
    },
    {
      id: 'token',
      kind: 'know',
      title: 'De token blijft geheim',
      body: 'De token wordt op de ovenbird-server bewaard en nooit meer getoond: de pagina zegt alleen dat er een is opgeslagen. Exports, diagnose en het auditlog laten hem weg. Om hem te wijzigen plak je een nieuwe en sla je op.',
    },
    {
      id: 'sensors',
      kind: 'know',
      title: 'Sensoren kiezen',
      body: 'Kies de kamersensor bij [Comforttemperatuur](#/settings/room) en de referentieruimte bij [Houtkachel](#/settings/stove). ovenbird leest precies de sensoren die je daar kiest. Ook een thermostaat kan de kamersensor zijn: dan telt de gemeten kamertemperatuur.',
      target: 'settings/ha.sensors',
    },
    {
      id: 'units',
      kind: 'know',
      title: 'Eenheden',
      body: 'Temperaturen in °F of K worden bij binnenkomst omgerekend naar °C. Een kamersensor zonder eenheid wordt alleen vertrouwd als Home Assistant het metrische stelsel gebruikt; anders negeert ovenbird de waarde, geeft een alarm en regelt op de stooklijn.',
    },
    {
      id: 'locked',
      kind: 'know',
      title: 'Ingesteld door de installatie',
      body: 'Komt het adres of de token uit een omgevingsvariabele of het optiebestand, dan staat het hier op slot en gaat het boven een opgeslagen waarde. Testen kan nog steeds.',
    },
  ],
  questions: [
    {
      id: 'fails',
      q: 'De test zegt dat Home Assistant niet bereikbaar is. Wat nu?',
      a: 'Open hetzelfde adres in een browser in het netwerk van de ovenbird-machine. Controleer de poort (meestal 8123) en gebruik alleen https als Home Assistant of je proxy dat aanbiedt. Een doorverwijzing telt als fout: gebruik het uiteindelijke adres.',
    },
    {
      id: 'rejected',
      q: 'De token wordt geweigerd.',
      a: 'Maak een nieuwe langlevende toegangstoken in je profiel in Home Assistant en plak hem volledig; tokens zijn lang. Ook een verlopen of verwijderde token wordt geweigerd.',
    },
  ],
  related: ['settings', 'settings/room', 'system/signals'],
};
