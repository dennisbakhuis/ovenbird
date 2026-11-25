import type { HelpTopic } from '$lib/help/types';

export const topic: HelpTopic = {
  id: 'system',
  title: 'Systeem',
  lead: 'Of ovenbird de regie heeft en of zijn verbindingen gezond zijn. Hier pauzeer en hervat je de automatische regeling.',
  art: 'system',
  sections: [
    {
      id: 'mode',
      kind: 'see',
      title: 'Regelmodus',
      body: 'Drie stappen: **Uit**, **Schaduw** en **Automatisch**; de gevulde stip is de modus van nu. Het slotje markeert de hoogste modus die de installatie toestaat.\n\nIn [[auto-mode|Automatisch]] stuurt ovenbird de aanvoertemperatuur naar de pomp. In [[shadow|Schaduw]] leest en beslist hij elke minuut, maar stuurt hij niets. De zin onder de modus zegt [[control-state|wie de pomp nu stuurt]], bijvoorbeeld "ovenbird wacht tot 18:25" tijdens een blokkade op Automatisch.',
      target: 'system.mode',
    },
    {
      id: 'pause',
      kind: 'do',
      title: 'Pauzeren en hervatten',
      body: '**Pauzeren** stopt meteen met sturen, bijvoorbeeld als je aan de installatie werkt. Ook na een herstart blijft hij gepauzeerd. **Hervatten** gaat na een bevestiging terug naar Automatisch; alleen een beheerder kan hervatten.',
    },
    {
      id: 'health',
      kind: 'see',
      title: 'Status',
      body: 'Eén tegel per onderdeel: [[mqtt|MQTT]], de berichtenserver; [[heishamon|HeishaMon]], het printje op de pomp, met zijn laatste hartslag; Home Assistant ([[ha-link|koppeling met Home Assistant]]); de opslag van de geschiedenis; de alarmen, met het ernstigste; en de weersverwachting. Groen is goed; **uitgeschakeld** betekent niet ingesteld.\n\nDaaronder: de versie van de service, de API-versie, en of hij live en gereed is.',
      target: 'system.health',
    },
    {
      id: 'notifications',
      kind: 'see',
      title: 'Meldingen',
      body: 'Of waarschuwingen op je telefoon aankomen als er geen pagina openstaat. **Waarschuwingen (ntfy)** stuurt een pushbericht bij waarschuwingen en kritieke alarmen. De **waakhond-ping** belt elke paar minuten een dienst buiten je huis; stoppen de pings, dan waarschuwt die dienst je dat ovenbird zelf gestopt is.\n\nMet **Test sturen** controleer je of een bericht aankomt. Beide stel je in bij de add-on-opties of de omgeving, niet bij Instellingen.',
      target: 'system.notifications',
    },
    {
      id: 'safety',
      kind: 'know',
      title: 'Vangnet',
      body: 'Als ovenbird stopt, houdt een kleine [[envelope|veiligheidsregel]] op de HeishaMon de watertemperatuur binnen een veilige band. ovenbird kan die regel niet zien en toont wat hij weet: **Niet opgegeven**, **Opgegeven** (de installateur zegt dat hij er is) of **Bewezen** (de pomp werd zonder ovenbird terug de band in gezet). Daaronder: de band van nu en de eigen grenzen van ovenbird.',
      target: 'system.safety',
    },
    {
      id: 'about',
      kind: 'know',
      title: 'Over deze installatie',
      body: 'Versie, de klok en tijdzone van de service, hoe lang hij draait en hoe vaak hij startte. **Meer over deze installatie** toont de regellus, de verbindingen en het setpointregister. **Diagnose downloaden** bewaart een bundel voor een probleemmelding, zonder wachtwoorden of tokens; alleen een beheerder kan hem downloaden.',
      target: 'system.about',
    },
    {
      id: 'live',
      kind: 'know',
      title: 'Live gaan',
      body: 'Automatisch kan alleen als de installatie het toestaat. De hoogste modus en de toestemming om opdrachten te sturen zijn instellingen van de installatie; deze pagina kan ze niet aanzetten. Een nieuwe installatie begint in Schaduw, zodat je eerst zijn beslissingen kunt volgen.',
    },
  ],
  questions: [
    {
      id: 'shadow-heat',
      q: 'Staat de verwarming uit in Schaduw?',
      a: 'Nee. De pomp verwarmt verder op zijn eigen instellingen, of op die van een andere regelaar. ovenbird stuurt alleen niets.',
    },
    {
      id: 'offline',
      q: 'HeishaMon is offline. Wat nu?',
      a: 'ovenbird krijgt geen verse gegevens van de pomp en stuurt niets. Kijk of HeishaMon stroom en wifi heeft. De pomp draait door op zijn laatste instellingen.',
    },
    {
      id: 'ready',
      q: 'Bij Gereed staat nee. Is er iets kapot?',
      a: 'De service draait, maar niet alles is in orde: meestal speelt er een kritiek alarm of ligt een nodige verbinding eruit. Zie [Activiteit](#/activity) en de tegels hierboven.',
    },
    {
      id: 'alerts',
      q: "Hoe weet ik dat een alarm 's nachts bij mij aankomt?",
      a: "Kijk bij **Meldingen**: daar hoort te staan dat de waarschuwingen werken en de waakhond-ping gezond is. Stuur na elke wijziging een test. Zonder meldingen staat een alarm alleen op deze pagina's.",
    },
  ],
  related: ['system/signals', 'system/shadow', 'system/trial', 'activity'],
};
