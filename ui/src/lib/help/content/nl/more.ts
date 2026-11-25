import type { HelpTopic } from '$lib/help/types';

export const topic: HelpTopic = {
  id: 'more',
  title: 'Meer',
  lead: 'De pagina’s die niet in de onderbalk passen: instellingen, activiteit, systeem en signalen, elk met een regel status.',
  art: 'welcome',
  sections: [
    {
      id: 'links',
      kind: 'see',
      title: 'De pagina’s',
      body: '- **Instellingen**: de configuratieversie en eventuele niet-opgeslagen wijzigingen.\n- **Activiteit**: alarmen en een blokkade, met een bolletje dat de alarmen telt.\n- **Systeem**: de regelmodus en of HeishaMon online is.\n- **Signalen**: hoeveel live waarden er binnenkomen.',
      target: 'more.links',
    },
    {
      id: 'badge',
      kind: 'know',
      title: 'De kleur van het bolletje',
      body: 'Het bolletje krijgt de kleur van het ernstigste alarm: rood bij kritiek, oranje bij een waarschuwing, blauw bij alleen informatie. Geen bolletje: geen alarmen.',
    },
    {
      id: 'help',
      kind: 'know',
      title: 'Hulp op elke pagina',
      body: 'Het **?** bovenaan opent de hulp bij de pagina waar je bent; op een toetsenbord druk je op **?**. **Laat zien** wijst het deel van de pagina aan waar een onderdeel over gaat.',
    },
  ],
  questions: [
    {
      id: 'desktop',
      q: 'Waar staan deze pagina’s op een computer?',
      a: 'Op een breed scherm staat Instellingen in de bovenbalk, en zijn Activiteit en Systeem de pictogrammen rechtsboven. Signalen is een tabblad van Systeem.',
    },
    {
      id: 'badge-stays',
      q: 'Hoe krijg ik het bolletje weg?',
      a: 'Alarmen verdwijnen vanzelf als de oorzaak weg is. [Activiteit](#/activity) laat zien wat er nog speelt en waarom.',
    },
  ],
  related: ['activity', 'system', 'settings'],
};
