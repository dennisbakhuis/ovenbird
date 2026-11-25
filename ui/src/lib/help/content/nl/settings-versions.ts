import type { HelpTopic } from '$lib/help/types';

export const topic: HelpTopic = {
  id: 'settings/versions',
  title: 'Versies en back-up',
  lead: 'Elke toegepaste wijziging wordt een genummerde versie. Hier zie je wie wat veranderde, ga je terug naar een eerdere versie en bewaar of laad je je instellingen als bestand.',
  art: 'settings',
  sections: [
    {
      id: 'list',
      kind: 'see',
      title: 'Versies',
      body: 'Nieuwste eerst. Elke [[config-version|versie]] toont haar nummer, wanneer en door wie, waar ze vandaan komt (webinterface, terugdraaien of seed-bestand) en de opmerking. Open de regel eronder om te zien wat er veranderde, van oud naar nieuw. **huidig** markeert de versie die in gebruik is.',
      target: 'settings/versions.list',
    },
    {
      id: 'rollback',
      kind: 'do',
      title: 'Terug naar een versie',
      body: '**Deze versie herstellen** bewaart een nieuwe versie met de instellingen van die versie, na dezelfde controles als elke wijziging. Instellingen die door de installatie vastliggen blijven zoals ze zijn.\n\n**Laden als concept** zet die instellingen in plaats daarvan in je [[draft|concept]], zodat je ze kunt aanpassen voordat je bekijkt en toepast.',
    },
    {
      id: 'export',
      kind: 'do',
      title: 'Exporteren en importeren',
      body: '**Instellingen exporteren** downloadt je opgeslagen instellingen als bestand: een back-up, of een manier om ze naar een andere installatie te brengen. **Importeren uit bestand…** vult alleen je concept; er verandert niets totdat je bekijkt en toepast. Vergrendelde en onbekende instellingen uit het bestand worden overgeslagen.',
      target: 'settings/versions.export',
    },
    {
      id: 'locked',
      kind: 'see',
      title: 'Instellingen uit de installatie',
      body: '**Vastgelegd door omgeving of opties-bestand** noemt instellingen die je hier zou kunnen wijzigen, maar die de installatie overschrijft; verander ze waar de kolom **Variabele** zegt. **Vast door de installatie** bevat de rest: verbindingen, veiligheidsdrempels en andere waarden die deze pagina nooit verandert.',
      target: 'settings/versions.locked',
    },
    {
      id: 'kept',
      kind: 'know',
      title: 'De geschiedenis blijft bewaard',
      body: 'Versies worden nooit bewerkt of gewist; terugdraaien voegt er een toe. Het tabblad [Logboek](#/activity/audit) houdt bij wie wat toepaste, terugdraaide of bevestigde.',
    },
  ],
  questions: [
    {
      id: 'when',
      q: 'Gaat terugdraaien meteen in?',
      a: 'Bij de volgende beslissing, binnen ongeveer een minuut. Vanaf dan verandert de watertemperatuur in haar gewone stappen.',
    },
    {
      id: 'file',
      q: 'Wat staat er in het exportbestand?',
      a: 'Je opgeslagen waarden, plus ter informatie de geldende waarde van elke instelling. Geen wachtwoorden of tokens.',
    },
    {
      id: 'no-button',
      q: 'Waarom kan ik niet terugdraaien?',
      a: 'Alleen een beheerder kan dat, en bij de huidige versie staan geen knoppen. Zijn de instellingen al gelijk, dan meldt het venster dat.',
    },
  ],
  related: ['settings', 'activity/audit'],
};
