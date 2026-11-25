import type { HelpTopic } from '$lib/help/types';

export const topic: HelpTopic = {
  id: 'activity/audit',
  title: 'Activiteit: logboek',
  lead: 'Het logboek houdt bij wie wat deed: instellingen toegepast of teruggedraaid, pauzeren en hervatten, opgeheven blokkades en geschreven pompinstellingen.',
  art: 'activity',
  sections: [
    {
      id: 'trail',
      kind: 'see',
      title: 'Logboek van wijzigingen',
      body: 'De gekozen periode, nieuwste eerst. Elke regel toont de tijd, wie het deed (gebruiker en adres), de actie en de details, zoals de versie met de veranderde waarden of de opgegeven reden.',
      target: 'activity/audit.trail',
    },
    {
      id: 'actions',
      kind: 'know',
      title: 'Wat wordt vastgelegd',
      body: 'Instellingen toegepast, teruggedraaid of gereset, en een bevestigde reset; **Gepauzeerd** en **Hervat (Automatisch)**; **Blokkade opgeheven**; **Pompinstelling geschreven**; en **Verzoek geweigerd**, bijvoorbeeld na een verkeerd wachtwoord. Alleen pagina’s bekijken wordt niet vastgelegd.',
    },
    {
      id: 'kept',
      kind: 'know',
      title: 'Regels veranderen nooit',
      body: 'Er komen alleen regels bij; ze worden nooit bewerkt of gewist. Alleen een beheerder kan het [[audit|logboek]] lezen. Versies van de instellingen met hun opmerkingen staan bij [Versies en back-up](#/settings/versions).',
    },
  ],
  questions: [
    {
      id: 'refused',
      q: 'Wat betekent “Verzoek geweigerd”?',
      a: 'Iemand of iets sprak de service aan met een verkeerd wachtwoord of zonder toestemming. Eén keer is meestal een tikfout; veel achter elkaar is het nakijken waard.',
    },
    {
      id: 'how-far',
      q: 'Hoe ver gaat het terug?',
      a: 'Zo ver als de periode boven de tijdlijn: de laatste 24 uur, tenzij je **7 d** of **Aangepast** kiest. Het toont tot 200 gebeurtenissen.',
    },
  ],
  related: ['settings/versions', 'activity'],
};
