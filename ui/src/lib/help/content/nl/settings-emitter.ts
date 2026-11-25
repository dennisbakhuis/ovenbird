import type { HelpTopic } from '$lib/help/types';

export const topic: HelpTopic = {
  id: 'settings/emitter',
  title: 'Afgifte',
  lead: 'Vertel ovenbird hoe je huis de warmte afgeeft: vloerverwarming, radiatoren of allebei. Die keuze bepaalt de stooklijn van de voorinstelling, de veiligheidsgrenzen en de afstelling.',
  art: 'settings',
  sections: [
    {
      id: 'choose',
      kind: 'do',
      title: 'De afgifte kiezen',
      body: 'Elke kaart toont de stooklijn van de voorinstelling en de maximale aanvoertemperatuur; **in gebruik** markeert de huidige [[emitter|afgifte]].\n\nKies wat er echt in huis zit. **Vloerverwarming in dekvloer** en **Gemengd** staan hooguit 40 °C toe, **Radiatoren** 55 °C. Radiatoren kiezen bij een vloer zou water toestaan dat heter is dan een dekvloer hoort te krijgen.',
      target: 'settings/emitter.choose',
    },
    {
      id: 'diff',
      kind: 'see',
      title: 'Wat overschakelen verandert',
      body: 'Onder de kaarten zet ovenbird op een rij wat een wissel zou doen: hoeveel waarden de [[preset|voorinstelling]] volgen en zouden veranderen, en onder **Behouden: zelf ingestelde waarden** welke blijven. **Alles wat deze voorinstelling bepaalt** toont de hele lijst.',
      target: 'settings/emitter.diff',
    },
    {
      id: 'envelope',
      kind: 'know',
      title: 'De veiligheidsgrenzen gaan mee',
      body: 'De afgifte bepaalt ook de [[envelope|veiligheidsband]], de band rond haar stooklijn waarin jouw stooklijn moet blijven, en de minimale en maximale watertemperatuur. Heb je een eigen stooklijn, dan kan die na een wissel buiten de nieuwe band vallen; bij het bekijken zie je dan wat je moet aanpassen.',
    },
    {
      id: 'apply',
      kind: 'know',
      title: 'Een wissel bevestig je',
      body: 'Een andere afgifte verandert veel tegelijk, dus bij het bekijken moet je het bevestigen. Het gaat in tussen twee beslissingen, zoals elke instelling, en je kunt het terugdraaien bij [Versies en back-up](#/settings/versions).',
    },
  ],
  questions: [
    {
      id: 'both',
      q: 'Ik heb beneden vloerverwarming en boven radiatoren. Wat kies ik?',
      a: '**Gemengd** is daarvoor bedoeld: vloerverwarming samen met lagetemperatuurradiatoren.',
    },
    {
      id: 'kept',
      q: 'Worden mijn eigen waarden vervangen?',
      a: 'Nee. Alleen waarden die de voorinstelling nog volgen veranderen. Zelf ingestelde waarden blijven; de lijst onder **Behouden: zelf ingestelde waarden** toont ze.',
    },
  ],
  related: ['settings/curve', 'settings/behaviour'],
};
