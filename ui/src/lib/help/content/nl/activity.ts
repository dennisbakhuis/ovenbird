import type { HelpTopic } from '$lib/help/types';

export const topic: HelpTopic = {
  id: 'activity',
  title: 'Activiteit: alarmen',
  lead: 'Wat je aandacht vraagt en wat er gebeurde, de afgelopen 24 uur of een periode die je kiest. Alarmen verschijnen als er iets mis of ongewoon is, en verdwijnen vanzelf.',
  art: 'activity',
  sections: [
    {
      id: 'timeline',
      kind: 'see',
      title: 'Tijdlijn',
      body: 'Eén baan per soort gebeurtenis: alarmen en blokkades als balken zolang ze duurden, wijzigingen van de instellingen en opdrachten als streepjes. De tijdlijn is op elk tabblad hetzelfde. **Toon als lijst** zet de gebeurtenissen onder elkaar als tekst.',
      target: 'activity.timeline',
    },
    {
      id: 'range',
      kind: 'do',
      title: 'Periode',
      body: 'Kies boven de tijdlijn **24 u**, **7 d** of **Aangepast** met **Van** en **Tot**. De periode bepaalt wat de tijdlijn en alle vier de tabbladen tonen: alarmen, blokkades, opdrachten en logboek. Zo staat een alarm van zaterdag op maandag nog gewoon in de lijst.',
      target: 'activity.range',
    },
    {
      id: 'active',
      kind: 'see',
      title: 'Actieve alarmen',
      body: 'Elk [[alarm]] dat nu speelt, het ernstigste eerst, met sinds wanneer en wat de service mat. Twee regels zeggen wat er nu gebeurt: **ovenbird nu:** wat ovenbird eraan doet, en **Jij:** wat jij kunt doen. De link eronder brengt je verder, zoals **Toon blokkades** of **Open Systeem**.',
      target: 'activity.active',
    },
    {
      id: 'severity',
      kind: 'know',
      title: 'Kritiek, waarschuwing, info',
      body: '- **Kritiek**: een veiligheidsgrens, zoals te heet water, te weinig debiet of een pompfout. Totdat het opgelost is, laat ovenbird de watertemperatuur alleen nog dalen.\n- **Waarschuwing**: iets om naar te kijken, zoals een stille kamersensor of iemand anders die de pomp wijzigde.\n- **Info**: goed om te weten, je hoeft niets te doen, zoals een herstart van HeishaMon.',
    },
    {
      id: 'monitors',
      kind: 'see',
      title: 'Veiligheidsbewakers',
      body: 'De controles die om de paar seconden lopen, in elke modus. Elke bewaker toont de waarde nu tegenover zijn grens (het rode streepje) en een status: **ok**, **in afwachting** (gezien, wacht af of het aanhoudt), **actief**, of **onbekend** als er geen recente gegevens zijn. **Waarom?** toont de eigen melding van de service.',
      target: 'activity.monitors',
    },
    {
      id: 'journal',
      kind: 'see',
      title: 'Alarmjournaal',
      body: 'Elk alarm in de gekozen periode, met wanneer het begon en hoelang het duurde. **actief** betekent dat het nog speelt; **opgelost** dat de oorzaak weg is. Je kunt een alarm niet wegklikken: het verdwijnt pas als de oorzaak weg is.',
      target: 'activity.journal',
    },
    {
      id: 'room',
      kind: 'know',
      title: 'Alarmen over de kamersensor en Home Assistant',
      body: '- **Kamersensor laat niets horen**: een sensor die bij verandering meldt, gaf 8 uur geen teken van leven.\n- **Kamersensor stil**: geen teken van leven voorbij de stiltegrens.\n- **Kamermelding te laat**: een periodieke sensor miste drie meldingen.\n- **Kamerwaarde onwaarschijnlijk**: de controlesensor is het er niet mee eens.\n- **Verbinding met Home Assistant verbroken**: 5 minuten geen contact.\n\novenbird vertrouwt de kamerwaarde dan minder of niet en leunt op de stooklijn.',
    },
  ],
  questions: [
    {
      id: 'ack',
      q: 'Moet ik alarmen bevestigen?',
      a: 'Nee. Alarmen verdwijnen vanzelf zodra de oorzaak weg is. Alleen kwijtgeraakte instellingen vragen om je **Bevestigen**, op de pagina [Instellingen](#/settings).',
    },
    {
      id: 'foreign',
      q: '“Iemand anders wijzigde de pomp”: wat nu?',
      a: 'Iets anders dan ovenbird schreef een pompinstelling: de afstandsbediening van Panasonic, Node-RED of een andere app. ovenbird stopt een tijdje met opdrachten sturen (een [[hold|blokkade]]). Zoek uit wie het was; zie [Blokkades](#/activity/holds).',
    },
    {
      id: 'critical',
      q: 'Een kritiek alarm blijft staan. Wat kan ik nakijken?',
      a: 'Kijk bij de warmtepomp zelf: een foutcode op de afstandsbediening, dichte kranen van radiatoren of vloergroepen, de waterdruk. Intussen stuurt ovenbird alleen lagere watertemperaturen.',
    },
    {
      id: 'csv',
      q: 'Kan ik het logboek als spreadsheet downloaden?',
      a: 'Ja. **CSV** naast het alarmlogboek, de blokkadehistorie, het opdrachtenlogboek en het auditlogboek downloadt de periode die je ziet. Elke grafiek heeft **Toon als tabel**, en die tabel heeft een eigen CSV-knop.',
    },
  ],
  related: ['activity/holds', 'settings/room', 'system'],
  aliases: ['csv', 'exporteren', 'downloaden', 'spreadsheet', 'logboek'],
};
